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


def _verify_running(settings, timeout: float = 8.0) -> bool:
    """Verifikasi xray benar-benar AKTIF & stabil setelah restart.

    `systemctl restart` pada service Type=simple langsung balik sukses begitu
    proses fork, padahal xray bisa crash sesaat kemudian (gagal bind port /
    sertifikat tak terbaca). Kita:
      - tunggu status mencapai 'active' (bukan gagal-vonis saat transisi
        'activating'/'inactive' sesaat), lalu
      - pastikan tetap 'active' setelah jeda pendek (menangkap crash-after-bind
        & crash-loop yang statusnya 'activating (auto-restart)').
    Hanya mengembalikan False bila jelas gagal ('failed') atau tak pernah
    mencapai 'active' dalam `timeout`."""
    if shutil.which("systemctl") is None:
        return True  # dev/non-systemd — anggap sehat
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = _run(["systemctl", "is-active", settings.xray_service],
                  timeout=10).stdout.strip()
        if st == "failed":
            return False
        if st == "active":
            time.sleep(1.0)  # pastikan tidak langsung crash setelah bind
            again = _run(["systemctl", "is-active", settings.xray_service],
                         timeout=10).stdout.strip()
            return again == "active"
        time.sleep(0.5)  # 'activating'/'deactivating'/'inactive' → tunggu
    return False  # tak pernah 'active' dalam batas waktu → anggap gagal


def _xray_error_tail(settings, lines: int = 25) -> str:
    """Ambil baris error terakhir dari xray untuk pesan yang actionable.
    Sumber: journalctl service xray, lalu file error log. Kembalikan '' bila
    tak ada info."""
    keys = ("error", "failed", "panic", "address already in use",
            "permission denied", "no such file", "cannot", "invalid")

    def _pick(text: str) -> str:
        hits = [ln.strip() for ln in text.splitlines()
                if any(k in ln.lower() for k in keys) and ln.strip()]
        if hits:
            return " | ".join(hits[-2:])
        tail = [ln.strip() for ln in text.splitlines() if ln.strip()]
        return tail[-1] if tail else ""

    if shutil.which("journalctl"):
        r = _run(["journalctl", "-u", settings.xray_service, "-n", str(lines),
                  "--no-pager", "-o", "cat"], timeout=10)
        got = _pick((r.stdout or "") + (r.stderr or ""))
        if got:
            return got
    try:
        with open(settings.xray_error_log) as f:
            return _pick("".join(f.readlines()[-lines:]))
    except OSError:
        return ""


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


def _ensure_certs_readable(settings, config: dict) -> None:
    """Pastikan file sertifikat yang dirujuk inbound TLS bisa DIBACA oleh proses
    xray (yang umumnya berjalan sebagai user 'nobody'), serta direktori induknya
    bisa ditembus. Mencegah error 'permission denied' saat memuat privkey padahal
    `xray -test` (dijalankan panel sebagai root) lolos.

    Hanya menyentuh sertifikat milik panel (di bawah `cert_dir`) agar tidak
    mengubah izin file di luar (mis. /etc/letsencrypt yang dikelola tool lain).
    Aman dipanggil non-root (chmod gagal → dilewati)."""
    cert_dir = os.path.abspath(str(getattr(settings, "cert_dir", "") or ""))
    if not cert_dir:
        return

    files = set()
    for ib in config.get("inbounds", []):
        tls = (ib.get("streamSettings") or {}).get("tlsSettings") or {}
        for cert in (tls.get("certificates") or []):
            for k in ("certificateFile", "keyFile"):
                p = cert.get(k)
                if p:
                    files.add(os.path.abspath(str(p)))

    domain_dirs = set()
    for path in files:
        if not path.startswith(cert_dir + os.sep):
            continue  # hanya sertifikat milik panel
        try:
            if os.path.isfile(path):
                os.chmod(path, 0o644)  # boleh dibaca service xray
                domain_dirs.add(os.path.dirname(path))
        except OSError:
            pass

    # Rantai direktori cert_dir → domain dir harus bisa ditembus (o+x).
    for d in domain_dirs | {cert_dir}:
        try:
            os.chmod(d, os.stat(d).st_mode | 0o011)
        except OSError:
            pass
    # Induk cert_dir (mis. /etc/xray-manager) juga perlu ditembus — cukup o+x,
    # tidak menambah hak baca sehingga config.json/DB tetap tersembunyi.
    try:
        parent = os.path.dirname(cert_dir)
        os.chmod(parent, os.stat(parent).st_mode | 0o011)
    except OSError:
        pass


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

    # 3. Tulis config baru, benahi izin sertifikat, lalu restart
    write_config(settings, config)
    _ensure_certs_readable(settings, config)
    ok, err = restart(settings)

    # 4. Verifikasi xray hidup; kalau tidak, rollback ke config sebelumnya
    if ok and _verify_running(settings):
        return True, "OK"

    # Ambil penyebab sebenarnya dari log xray (bind port / sertifikat / izin).
    detail = _xray_error_tail(settings)
    reason = detail or err or "xray tidak aktif setelah restart"
    if "permission denied" in reason.lower():
        reason += (" — pastikan file sertifikat bisa dibaca service xray "
                   "(chmod 644 pada cert/key, atau terbitkan ulang via ssl.sh)")

    if prev is not None:
        restored_ok = False
        try:
            with open(settings.xray_config, "w") as f:
                f.write(prev)
            rok, _ = restart(settings)  # pulihkan xray dengan config yang tadinya jalan
            restored_ok = rok and _verify_running(settings, timeout=6.0)
        except OSError:
            pass
        tail = ("Konfigurasi dikembalikan & xray berjalan lagi."
                if restored_ok else
                "Konfigurasi dikembalikan, tapi xray MASIH belum aktif — "
                "cek 'journalctl -u %s -n 50'." % settings.xray_service)
        return False, f"Xray gagal start dengan config baru: {reason}. {tail}"
    return False, f"Xray gagal start dengan config baru: {reason}."
