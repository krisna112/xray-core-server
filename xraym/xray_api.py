"""Interaksi dengan binary & service Xray: versi, test config, restart, stats."""

import json
import os
import shutil
import subprocess


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
    """Tulis config, validasi, lalu restart xray. (ok, pesan)."""
    import tempfile

    # Validasi dulu di file sementara agar config lama tidak rusak bila invalid
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

    write_config(settings, config)
    ok, err = restart(settings)
    if not ok:
        return False, f"Config tertulis tetapi restart gagal: {err}"
    return True, "OK"
