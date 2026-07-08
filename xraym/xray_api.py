"""Interaksi dengan binary & service Xray: versi, test config, restart, stats."""

import errno
import json
import os
import shutil
import socket
import subprocess
import time


class XrayError(Exception):
    pass


def _run(cmd, timeout=30):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise XrayError(f"Perintah tidak ditemukan: {cmd[0]}")
    except subprocess.TimeoutExpired:
        raise XrayError(f"Timeout menjalankan: {' '.join(cmd)}")


def version(settings) -> str:
    try:
        r = _run([settings.xray_binary, "version"], timeout=10)
        first = (r.stdout or r.stderr).strip().splitlines()
        return first[0] if first else "unknown"
    except XrayError:
        return "not-installed"


def test_config(settings, config_path=None) -> tuple:
    """(ok: bool, pesan error)."""
    path = config_path or settings.xray_config
    r = _run([settings.xray_binary, "run", "-test", "-config", path])
    if r.returncode == 0:
        return True, ""
    return False, (r.stdout + r.stderr).strip()


def _systemctl(action, service):
    if shutil.which("systemctl") is None:
        return False, "systemctl tidak tersedia (bukan lingkungan systemd)"
    r = _run(["systemctl", action, service], timeout=60)
    if r.returncode == 0:
        return True, ""
    return False, (r.stdout + r.stderr).strip()


def restart(settings) -> tuple:
    return _systemctl("restart", settings.xray_service)


def is_running(settings) -> bool:
    if shutil.which("systemctl") is None:
        return False
    r = _run(["systemctl", "is-active", settings.xray_service], timeout=10)
    return r.stdout.strip() == "active"


def installed(settings) -> bool:
    """True bila binary xray tersedia (bukan lingkungan dev tanpa xray)."""
    b = settings.xray_binary
    return bool(shutil.which(b)) or os.path.exists(b)


def port_available(port: int, udp: bool = False, listen: str = "0.0.0.0") -> bool:
    """Best-effort: True bila `port` masih bisa di-bind (belum dipakai proses
    lain di server). Hanya EADDRINUSE yang dianggap "dipakai" — kegagalan izin
    (EACCES, mis. panel non-root untuk port <1024) TIDAK memblokir karena xray
    yang berjalan sebagai root tetap bisa bind. Mencegah kasus port 443 sudah
    dipakai web server lalu xray mati saat gagal bind."""
    host = "0.0.0.0" if listen in ("", "0.0.0.0", "::", "::0") else listen
    kind = socket.SOCK_DGRAM if udp else socket.SOCK_STREAM
    try:
        s = socket.socket(socket.AF_INET, kind)
        try:
            if not udp:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, int(port)))
        finally:
            s.close()
    except OSError as e:
        if e.errno == errno.EADDRINUSE:
            return False
        # EACCES / error lain: jangan blokir — biar xray yang mencoba bind.
        return True
    return True


def _healthy(settings) -> bool:
    """Verifikasi xray benar-benar aktif setelah restart. `systemctl restart`
    pada service Type=simple langsung balik sukses begitu proses fork, padahal
    xray bisa crash sesaat kemudian karena gagal bind port. Kita polling status
    sebentar dan hanya menyimpulkan GAGAL bila jelas 'failed'/'inactive'."""
    if shutil.which("systemctl") is None:
        return True  # dev/non-systemd — anggap sehat
    for _ in range(5):
        time.sleep(0.6)
        st = _run(["systemctl", "is-active", settings.xray_service], timeout=10).stdout.strip()
        if st in ("failed", "inactive"):
            return False
        if st == "active":
            return True
    return True  # status ambigu (mis. 'activating') — jangan rollback


def stats_query(settings, reset=True) -> list:
    """Ambil semua counter stats dari Xray API.
    Return: list of {"name": "...", "value": int}."""
    cmd = [settings.xray_binary, "api", "statsquery",
           f"--server=127.0.0.1:{settings.xray_api_port}"]
    if reset:
        cmd.append("-reset")
    r = _run(cmd, timeout=20)
    if r.returncode != 0:
        raise XrayError((r.stdout + r.stderr).strip() or "statsquery gagal")
    try:
        data = json.loads(r.stdout or "{}")
    except ValueError:
        raise XrayError("Output statsquery bukan JSON")
    out = []
    for item in data.get("stat") or []:
        name = item.get("name", "")
        try:
            value = int(item.get("value", 0) or 0)
        except (TypeError, ValueError):
            value = 0
        if name and value:
            out.append({"name": name, "value": value})
    return out


def write_config(settings, config: dict) -> str:
    """Tulis config.json Xray secara atomik. Return path."""
    path = settings.xray_config
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(config, f, indent=2)
    os.replace(tmp, path)
    os.chmod(path, 0o644)
    return path


def apply_config(settings, config: dict) -> tuple:
    """Tulis config, validasi, restart xray, lalu verifikasi & rollback bila
    gagal. (ok, pesan).

    Alur aman (mirip 3x-ui):
      1. Validasi config baru di file sementara (`xray run -test`).
      2. Backup config live yang sedang berjalan.
      3. Tulis config baru & restart.
      4. Verifikasi xray benar-benar aktif. Jika tidak (mis. gagal bind port
         443 yang sudah dipakai web server), kembalikan config lama & restart
         lagi supaya xray TIDAK dibiarkan mati.
    """
    import tempfile

    # 1. Validasi dulu di file sementara agar config lama tidak rusak bila invalid
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(config, f, indent=2)
        tmp_path = f.name
    try:
        ok, err = test_config(settings, tmp_path)
        if not ok:
            return False, f"Config tidak valid: {err}"
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    # 2. Backup config live (untuk rollback)
    prev = None
    try:
        with open(settings.xray_config) as f:
            prev = f.read()
    except OSError:
        prev = None

    # 3. Tulis config baru & restart
    write_config(settings, config)
    ok, err = restart(settings)

    # 4. Verifikasi xray hidup; kalau tidak, rollback ke config sebelumnya
    if ok and _healthy(settings):
        return True, "OK"

    reason = err or "xray tidak aktif setelah restart (kemungkinan gagal bind port)"
    if prev is not None:
        try:
            with open(settings.xray_config, "w") as f:
                f.write(prev)
            restart(settings)  # pulihkan xray dengan config yang tadinya jalan
        except OSError:
            pass
        return False, (f"Xray gagal start dengan config baru: {reason}. "
                       "Konfigurasi dikembalikan ke versi sebelumnya (xray tetap berjalan).")
    return False, f"Xray gagal start dengan config baru: {reason}."
