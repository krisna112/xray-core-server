"""Konfigurasi aplikasi — dibaca dari /etc/xray-manager/config.json."""

import json
import os
import secrets

CONFIG_PATH = os.environ.get("XM_CONFIG", "/etc/xray-manager/config.json")

DEFAULTS = {
    # Web/API server
    "listen": "0.0.0.0",
    "port": 2053,
    "base_path": "",                # contoh: "/panelku" — prefix semua route
    "username": "admin",
    "password_hash": "",            # diisi installer / `xm user set-password`
    "secret": "",                   # kunci tanda-tangan session cookie
    "session_hours": 24,

    # Alamat publik server (domain / IP) — dipakai untuk share link & QR
    "domain": "",

    # Xray core
    "xray_binary": "/usr/local/bin/xray",
    "xray_config": "/usr/local/etc/xray/config.json",
    "xray_service": "xray",         # nama service systemd
    "xray_api_port": 10085,         # port API stats/handler xray (localhost)
    "xray_access_log": "/var/log/xray/access.log",
    "xray_error_log": "/var/log/xray/error.log",
    "xray_loglevel": "warning",

    # Profil "realtime": tuning policy agar ringan & latensi rendah untuk
    # panggilan video/suara (WhatsApp/Zoom/QUIC) di atas UDP maupun TCP.
    # true  → buffer kecil, connIdle pendek, UDP/QUIC lolos utuh.
    # false → default Xray (throughput maksimal, buffer besar).
    "realtime": True,

    # Database
    "db_path": "/etc/xray-manager/xray-manager.db",

    # Sertifikat TLS (diterbitkan ssl.sh via acme.sh / Cloudflare DNS).
    # Layout: <cert_dir>/<domain>/fullchain.pem & privkey.pem
    "cert_dir": "/etc/xray-manager/certs",

    # Background jobs
    "job_interval": 20,             # detik — polling stats + enforcement
    "ip_limit_window": 60,          # detik — jendela hitung IP unik per client
    "ip_limit_log": "/var/log/xray-manager/ip-limit.log",  # dibaca fail2ban

    # Push sinkronisasi ke web API (opsional). Kosongkan untuk menonaktifkan.
    "webhook_url": "",              # contoh: https://web-anda.com/api/panel_event.php
    "webhook_api_key": "",          # dikirim sebagai header X-API-KEY
    "sync_push_interval": 0,        # detik; 0 = nonaktif. Push snapshot penuh berkala.

    # Tanggal & waktu — zona waktu untuk menampilkan tanggal di panel
    "timezone": "",                 # mis. "Asia/Jakarta"; kosong = waktu lokal browser

    # Notifikasi Telegram (opsional) — dikirim saat client dinonaktifkan otomatis
    "tg_enable": False,
    "tg_bot_token": "",
    "tg_chat_id": "",
}


class Settings(dict):
    """Dict dengan akses atribut: settings.port, settings.domain, dst."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def save(self, path=None):
        path = path or CONFIG_PATH
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(dict(self), f, indent=2)
        os.replace(tmp, path)
        os.chmod(path, 0o600)


def load(path=None) -> Settings:
    path = path or CONFIG_PATH
    data = dict(DEFAULTS)
    if os.path.exists(path):
        with open(path) as f:
            data.update(json.load(f))
    s = Settings(data)
    # Pastikan secret selalu ada (untuk session cookie)
    if not s["secret"]:
        s["secret"] = secrets.token_hex(32)
        try:
            s.save(path)
        except OSError:
            pass  # read-only env (mis. saat testing) — pakai secret sementara
    return s
