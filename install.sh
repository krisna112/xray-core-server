#!/usr/bin/env bash
#
# OceanShark Xray Manager — installer untuk Debian/Ubuntu
# Menginstal: Xray-core, aplikasi manager (Python), service systemd,
# CLI `xm`, dan (opsional) fail2ban untuk limit IP.
#
# Jalankan sebagai root:
#   bash install.sh
#
set -euo pipefail

# Versi Xray-core yang dipasang & didukung panel ini.
XRAY_VERSION="26.3.27"

APP_DIR="/opt/xray-manager"
CONF_DIR="/etc/xray-manager"
LOG_DIR="/var/log/xray-manager"
XRAY_LOG_DIR="/var/log/xray"
CONFIG_FILE="$CONF_DIR/config.json"
# Direktori source (lokasi script ini berada)
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'; BLU='\033[0;34m'; NC='\033[0m'
info() { echo -e "${BLU}[*]${NC} $*"; }
ok()   { echo -e "${GRN}[✔]${NC} $*"; }
warn() { echo -e "${YLW}[!]${NC} $*"; }
err()  { echo -e "${RED}[x]${NC} $*" >&2; }

[[ $EUID -eq 0 ]] || { err "Harus dijalankan sebagai root (gunakan sudo)."; exit 1; }

# ---------------------------------------------------------------------------
# 1. Deteksi OS
# ---------------------------------------------------------------------------
if [[ -f /etc/os-release ]]; then
  . /etc/os-release
  info "OS terdeteksi: ${PRETTY_NAME:-$ID}"
  case "$ID" in
    debian|ubuntu) ;;
    *) warn "OS '$ID' belum diuji. Installer dirancang untuk Debian/Ubuntu." ;;
  esac
else
  warn "Tidak bisa mendeteksi OS. Melanjutkan dengan asumsi Debian/Ubuntu."
fi

# ---------------------------------------------------------------------------
# 2. Dependensi sistem
# ---------------------------------------------------------------------------
info "Memasang dependensi sistem..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y -q
apt-get install -y -q python3 python3-venv python3-pip curl unzip ca-certificates
ok "Dependensi sistem terpasang."

# ---------------------------------------------------------------------------
# 3. Install Xray-core v$XRAY_VERSION (skrip resmi XTLS, versi dipin)
# ---------------------------------------------------------------------------
CUR_XRAY_VER="$(xray version 2>/dev/null | head -n1 | awk '{print $2}')"
if [[ "$CUR_XRAY_VER" == "$XRAY_VERSION" ]]; then
  ok "Xray-core v$XRAY_VERSION sudah terpasang."
else
  if [[ -n "$CUR_XRAY_VER" ]]; then
    info "Xray-core v$CUR_XRAY_VER terpasang → mengunci ke v$XRAY_VERSION..."
  else
    info "Menginstal Xray-core v$XRAY_VERSION (skrip resmi XTLS)..."
  fi
  bash -c "$(curl -fsSL https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install --version "$XRAY_VERSION" \
    || bash -c "$(curl -fsSL https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install --version "v$XRAY_VERSION"
  ok "Xray-core terpasang: $(xray version 2>/dev/null | head -n1)"
fi
mkdir -p "$XRAY_LOG_DIR"
touch "$XRAY_LOG_DIR/access.log" "$XRAY_LOG_DIR/error.log"

# ---------------------------------------------------------------------------
# 4. Salin aplikasi & buat virtualenv
# ---------------------------------------------------------------------------
info "Menyalin aplikasi ke $APP_DIR ..."
mkdir -p "$APP_DIR" "$CONF_DIR" "$LOG_DIR"
cp -r "$SRC_DIR/xraym" "$APP_DIR/"
cp "$SRC_DIR/requirements.txt" "$APP_DIR/"
cp "$SRC_DIR/ssl.sh" "$APP_DIR/" 2>/dev/null || true
cp -r "$SRC_DIR/examples" "$APP_DIR/" 2>/dev/null || true
mkdir -p "$CONF_DIR/certs"

info "Membuat Python virtualenv & memasang paket..."
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip -q
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"
ok "Virtualenv siap."

# ---------------------------------------------------------------------------
# 5. CLI `xm`
# ---------------------------------------------------------------------------
install -m 0755 "$SRC_DIR/bin/xm" /usr/local/bin/xm
ok "CLI 'xm' terpasang di /usr/local/bin/xm"

# ---------------------------------------------------------------------------
# 6. Konfigurasi awal (interaktif bila belum ada)
# ---------------------------------------------------------------------------
if [[ -f "$CONFIG_FILE" ]]; then
  ok "Config sudah ada di $CONFIG_FILE — tidak ditimpa."
else
  info "Membuat konfigurasi awal..."
  read -rp "  Domain / IP publik server (untuk share link) : " XM_DOMAIN
  read -rp "  Port panel API [2053]                        : " XM_PORT
  XM_PORT="${XM_PORT:-2053}"
  read -rp "  Base path panel (opsional, mis. /rahasia)    : " XM_BASE
  read -rp "  Username admin panel [admin]                 : " XM_USER
  XM_USER="${XM_USER:-admin}"
  while true; do
    read -rsp "  Password admin panel                         : " XM_PASS; echo
    [[ -n "$XM_PASS" ]] && break
    warn "Password tidak boleh kosong."
  done

  SECRET="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  PW_HASH="$("$APP_DIR/venv/bin/python" -c \
    "import sys; sys.path.insert(0,'$APP_DIR'); from xraym import crypto; print(crypto.hash_password('$XM_PASS'))")"

  cat > "$CONFIG_FILE" <<EOF
{
  "listen": "0.0.0.0",
  "port": ${XM_PORT},
  "base_path": "${XM_BASE}",
  "username": "${XM_USER}",
  "password_hash": "${PW_HASH}",
  "secret": "${SECRET}",
  "session_hours": 24,
  "domain": "${XM_DOMAIN}",
  "xray_binary": "/usr/local/bin/xray",
  "xray_config": "/usr/local/etc/xray/config.json",
  "xray_service": "xray",
  "xray_api_port": 10085,
  "xray_access_log": "${XRAY_LOG_DIR}/access.log",
  "xray_error_log": "${XRAY_LOG_DIR}/error.log",
  "xray_loglevel": "warning",
  "db_path": "${CONF_DIR}/xray-manager.db",
  "job_interval": 20,
  "ip_limit_window": 60,
  "ip_limit_log": "${LOG_DIR}/ip-limit.log",
  "webhook_url": "",
  "webhook_api_key": "",
  "sync_push_interval": 0
}
EOF
  chmod 600 "$CONFIG_FILE"
  ok "Config tertulis di $CONFIG_FILE"
fi

# ---------------------------------------------------------------------------
# 7. Config Xray awal (kosong tapi valid) bila belum ada inbound
# ---------------------------------------------------------------------------
info "Menyiapkan config Xray awal dari database..."
PYTHONPATH="$APP_DIR" XM_CONFIG="$CONFIG_FILE" \
  "$APP_DIR/venv/bin/python" -c \
  "import sys; sys.path.insert(0,'$APP_DIR'); \
   from xraym import settings, db as dbmod, config_builder, xray_api; \
   st=settings.load('$CONFIG_FILE'); d=dbmod.DB(st.db_path); \
   xray_api.write_config(st, config_builder.build(d, st)); \
   print('config xray ditulis:', st.xray_config)"
systemctl restart xray || warn "Gagal restart xray — cek: journalctl -u xray"

# ---------------------------------------------------------------------------
# 8. Service systemd untuk manager
# ---------------------------------------------------------------------------
info "Memasang service systemd 'xray-manager'..."
cp "$SRC_DIR/systemd/xray-manager.service" /etc/systemd/system/xray-manager.service
systemctl daemon-reload
systemctl enable xray-manager >/dev/null 2>&1 || true
systemctl restart xray-manager
sleep 1
if systemctl is-active --quiet xray-manager; then
  ok "Service 'xray-manager' aktif."
else
  err "Service 'xray-manager' gagal start. Cek: journalctl -u xray-manager -n 50"
fi

# ---------------------------------------------------------------------------
# 9. Fail2ban (opsional)
# ---------------------------------------------------------------------------
read -rp "$(echo -e "${YLW}[?]${NC} Pasang integrasi fail2ban untuk limit IP? [y/N] ")" F2B
if [[ "${F2B,,}" == "y" ]]; then
  apt-get install -y -q fail2ban
  cp "$SRC_DIR/fail2ban/filter.d/xray-ip-limit.conf" /etc/fail2ban/filter.d/
  cp "$SRC_DIR/fail2ban/jail.d/xray-ip-limit.conf" /etc/fail2ban/jail.d/
  touch "$LOG_DIR/ip-limit.log"
  systemctl restart fail2ban
  ok "Fail2ban terpasang (jail: xray-ip-limit)."
fi

# ---------------------------------------------------------------------------
# 10. SSL via Cloudflare (opsional)
# ---------------------------------------------------------------------------
read -rp "$(echo -e "${YLW}[?]${NC} Terbitkan sertifikat TLS via Cloudflare sekarang? [y/N] ")" SSL
if [[ "${SSL,,}" == "y" ]]; then
  read -rp "  Domain (mis. vpn.domain.com)      : " SSL_DOMAIN
  read -rp "  Email akun Cloudflare             : " SSL_EMAIL
  read -rsp "  Cloudflare GLOBAL API KEY         : " SSL_KEY; echo
  if [[ -n "$SSL_DOMAIN" && -n "$SSL_EMAIL" && -n "$SSL_KEY" ]]; then
    bash "$SRC_DIR/ssl.sh" -d "$SSL_DOMAIN" -e "$SSL_EMAIL" -k "$SSL_KEY" \
      || warn "Penerbitan SSL gagal — bisa diulang nanti: bash $APP_DIR/ssl.sh -d $SSL_DOMAIN -e EMAIL -k KEY"
  else
    warn "Data tidak lengkap — lewati. Jalankan nanti: bash $APP_DIR/ssl.sh -d DOMAIN -e EMAIL -k KEY"
  fi
fi

# ---------------------------------------------------------------------------
# Selesai
# ---------------------------------------------------------------------------
PORT="$(PYTHONPATH="$APP_DIR" "$APP_DIR/venv/bin/python" -c \
  "import sys; sys.path.insert(0,'$APP_DIR'); from xraym import settings; print(settings.load('$CONFIG_FILE').port)")"
IP="$(curl -fsSL https://api.ipify.org 2>/dev/null || echo 'IP-SERVER')"

echo
ok "Instalasi selesai!"
echo -e "  Panel API : ${GRN}http://${IP}:${PORT}${NC}"
echo -e "  CLI       : ${GRN}xm status${NC}"
echo
echo "Langkah berikutnya:"
echo "  1) Buat inbound        : xm inbound add --protocol vless --port 8443 \\"
echo "                              --network tcp --security reality --dest yahoo.com:443"
echo "  2) Buat client 30 hari : xm client add --inbound 1 --email budi --days 30 --limit-ip 2 --qr"
echo "  3) Token sinkronisasi  : xm token create web-oceansharknet"
echo "  4) Lihat semua client  : xm client list"
echo
echo "Baca README.md untuk integrasi dengan web API Oceansharknet."
