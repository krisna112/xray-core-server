#!/usr/bin/env bash
#
# OceanShark Xray Manager — installer untuk Debian/Ubuntu
# Menginstal: Xray-core, aplikasi manager (Python), service systemd,
# CLI `xm`, menu interaktif, dan (opsional) SSL & fail2ban.
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
INSTALL_RESULT="$CONF_DIR/install-result.env"
# Direktori source (lokasi script ini berada)
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'; BLU='\033[0;34m'
CYN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
info() { echo -e "${BLU}[*]${NC} $*"; }
ok()   { echo -e "${GRN}[✔]${NC} $*"; }
warn() { echo -e "${YLW}[!]${NC} $*"; }
err()  { echo -e "${RED}[x]${NC} $*" >&2; }

[[ $EUID -eq 0 ]] || { err "Harus dijalankan sebagai root (gunakan sudo)."; exit 1; }

# ─── Helper ───────────────────────────────────────────────────────────────────

gen_random_string() {
    local length="${1:-12}"
    openssl rand -base64 $((length * 2)) 2>/dev/null | tr -dc 'a-zA-Z0-9' | head -c "$length"
}

# Deteksi IP publik server
get_server_ip() {
    local urls=(
        "https://api4.ipify.org"
        "https://ipv4.icanhazip.com"
        "https://4.ident.me"
        "https://check-host.net/ip"
    )
    local ip=""
    for url in "${urls[@]}"; do
        ip=$(curl -fsSL --max-time 3 "$url" 2>/dev/null | tr -d '[:space:]"')
        if [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            echo "$ip"
            return
        fi
    done
    echo ""
}

# Cek apakah port sedang dipakai
is_port_in_use() {
    local port="$1"
    if command -v ss >/dev/null 2>&1; then
        ss -ltn 2>/dev/null | awk -v p=":${port}$" '$4 ~ p {exit 0} END {exit 1}'
        return
    fi
    if command -v netstat >/dev/null 2>&1; then
        netstat -lnt 2>/dev/null | awk -v p=":${port} " '$4 ~ p {exit 0} END {exit 1}'
        return
    fi
    return 1
}

# Buka port di firewall (UFW / firewalld)
open_firewall_port() {
    local port="$1"
    local comment="${2:-xray-manager}"
    if command -v ufw >/dev/null 2>&1; then
        ufw allow "$port"/tcp comment "$comment" 2>/dev/null || true
    fi
    if command -v firewall-cmd >/dev/null 2>&1; then
        firewall-cmd --permanent --add-port="$port"/tcp 2>/dev/null || true
        firewall-cmd --reload 2>/dev/null || true
    fi
}

# Simpan hasil instalasi ke file (mode 600)
write_install_result() {
    local user="$1" pass="$2" port="$3" url="$4"
    mkdir -p "$(dirname "$INSTALL_RESULT")"
    local prev_umask
    prev_umask=$(umask)
    umask 077
    cat > "$INSTALL_RESULT" <<EOF
XM_USERNAME=${user}
XM_PASSWORD=${pass}
XM_PORT=${port}
XM_URL=${url}
XM_INSTALLED_AT=$(date -Iseconds)
EOF
    umask "$prev_umask"
    chmod 600 "$INSTALL_RESULT" 2>/dev/null
}

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
apt-get install -y -q python3 python3-venv python3-pip curl unzip ca-certificates openssl
ok "Dependensi sistem terpasang."

# ---------------------------------------------------------------------------
# 3. Install Xray-core v$XRAY_VERSION (skrip resmi XTLS, versi dipin)
# ---------------------------------------------------------------------------
CUR_XRAY_VER=""
if command -v xray >/dev/null 2>&1; then
  CUR_XRAY_VER="$(xray version 2>/dev/null | head -n1 | awk '{print $2}')" || true
fi
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
cp "$SRC_DIR/install.sh" "$APP_DIR/" 2>/dev/null || true
cp "$SRC_DIR/uninstall.sh" "$APP_DIR/" 2>/dev/null || true
cp -r "$SRC_DIR/examples" "$APP_DIR/" 2>/dev/null || true
cp -r "$SRC_DIR/fail2ban" "$APP_DIR/" 2>/dev/null || true
mkdir -p "$CONF_DIR/certs"

info "Membuat Python virtualenv & memasang paket..."
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip -q
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"
ok "Virtualenv siap."

# ---------------------------------------------------------------------------
# 5. CLI `xm` & menu interaktif
# ---------------------------------------------------------------------------
install -m 0755 "$SRC_DIR/bin/xm" /usr/local/bin/xm
install -m 0755 "$SRC_DIR/bin/xm-menu.sh" /usr/local/bin/xm-menu
ok "CLI 'xm' terpasang di /usr/local/bin/xm"
ok "Menu 'xm-menu' terpasang di /usr/local/bin/xm-menu"

# ---------------------------------------------------------------------------
# 6. Konfigurasi awal (interaktif — port, password, domain)
# ---------------------------------------------------------------------------
if [[ -f "$CONFIG_FILE" ]]; then
  ok "Config sudah ada di $CONFIG_FILE — tidak ditimpa."
  XM_PORT="$(python3 -c "import json; print(json.load(open('$CONFIG_FILE')).get('port', 2053))" 2>/dev/null || echo 2053)"
  XM_USER="$(python3 -c "import json; print(json.load(open('$CONFIG_FILE')).get('username', 'admin'))" 2>/dev/null || echo admin)"
  XM_PASS="(tidak diubah)"
  XM_DOMAIN="$(python3 -c "import json; print(json.load(open('$CONFIG_FILE')).get('domain', ''))" 2>/dev/null || echo '')"
else
  echo
  echo -e "${GRN}═══════════════════════════════════════════${NC}"
  echo -e "${GRN}     Konfigurasi Panel                    ${NC}"
  echo -e "${GRN}═══════════════════════════════════════════${NC}"
  echo

  # --- Domain / IP ---
  SERVER_IP="$(get_server_ip)"
  if [[ -n "$SERVER_IP" ]]; then
    info "IP publik terdeteksi: $SERVER_IP"
  fi
  read -rp "  Domain / IP publik server [$SERVER_IP]: " XM_DOMAIN
  XM_DOMAIN="${XM_DOMAIN:-$SERVER_IP}"

  # --- Port (random jika kosong) ---
  DEFAULT_PORT=$(shuf -i 1024-62000 -n 1)
  read -rp "  Port panel API [$DEFAULT_PORT]: " XM_PORT
  XM_PORT="${XM_PORT:-$DEFAULT_PORT}"

  # Validasi port
  while ! [[ "$XM_PORT" =~ ^[0-9]+$ ]] || [[ "$XM_PORT" -lt 1 || "$XM_PORT" -gt 65535 ]]; do
    warn "Port tidak valid. Harus angka 1-65535."
    read -rp "  Port panel API: " XM_PORT
  done

  # Cek port sudah dipakai
  if is_port_in_use "$XM_PORT"; then
    warn "Port $XM_PORT sudah dipakai oleh proses lain!"
    read -rp "  Tetap gunakan port ini? [y/N]: " FORCE_PORT
    if [[ "${FORCE_PORT,,}" != "y" ]]; then
      XM_PORT=$(shuf -i 1024-62000 -n 1)
      info "Port random baru: $XM_PORT"
    fi
  fi

  # --- Base path (opsional) ---
  DEFAULT_BASE="/$(gen_random_string 18)"
  read -rp "  Base path panel [$DEFAULT_BASE]: " XM_BASE
  XM_BASE="${XM_BASE:-$DEFAULT_BASE}"

  # --- Username ---
  DEFAULT_USER="$(gen_random_string 8)"
  read -rp "  Username admin [$DEFAULT_USER]: " XM_USER
  XM_USER="${XM_USER:-$DEFAULT_USER}"

  # --- Password (random jika kosong) ---
  DEFAULT_PASS="$(gen_random_string 12)"
  read -rsp "  Password admin (enter = $DEFAULT_PASS): " XM_PASS
  echo
  XM_PASS="${XM_PASS:-$DEFAULT_PASS}"

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
# 9. Auto buka port di firewall
# ---------------------------------------------------------------------------
info "Membuka port panel di firewall..."
open_firewall_port "$XM_PORT" "xray-manager panel"
ok "Port $XM_PORT dibuka di firewall."

# ---------------------------------------------------------------------------
# 10. Fail2ban (opsional)
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
# 11. SSL via Cloudflare (opsional)
# ---------------------------------------------------------------------------
echo
echo -e "${GRN}═══════════════════════════════════════════${NC}"
echo -e "${GRN}     SSL Certificate Setup (OPSIONAL)     ${NC}"
echo -e "${GRN}═══════════════════════════════════════════${NC}"
echo -e "${YLW}SSL sangat direkomendasikan untuk keamanan.${NC}"
echo -e "${YLW}Lewati hanya jika menggunakan reverse proxy atau SSH tunnel.${NC}"
echo
read -rp "$(echo -e "${YLW}[?]${NC} Terbitkan sertifikat TLS via Cloudflare sekarang? [y/N] ")" SSL
if [[ "${SSL,,}" == "y" ]]; then
  read -rp "  Domain (mis. vpn.domain.com)      : " SSL_DOMAIN
  read -rp "  Email akun Cloudflare             : " SSL_EMAIL
  read -rsp "  Cloudflare GLOBAL API KEY         : " SSL_KEY; echo
  if [[ -n "$SSL_DOMAIN" && -n "$SSL_EMAIL" && -n "$SSL_KEY" ]]; then
    bash "$SRC_DIR/ssl.sh" -d "$SSL_DOMAIN" -e "$SSL_EMAIL" -k "$SSL_KEY" --panel \
      || warn "Penerbitan SSL gagal — bisa diulang nanti: bash $APP_DIR/ssl.sh -d $SSL_DOMAIN -e EMAIL -k KEY"
  else
    warn "Data tidak lengkap — lewati. Jalankan nanti: bash $APP_DIR/ssl.sh -d DOMAIN -e EMAIL -k KEY"
  fi
fi

# ---------------------------------------------------------------------------
# Selesai — Tampilan Hasil Instalasi
# ---------------------------------------------------------------------------
PORT="$(PYTHONPATH="$APP_DIR" "$APP_DIR/venv/bin/python" -c \
  "import sys; sys.path.insert(0,'$APP_DIR'); from xraym import settings; print(settings.load('$CONFIG_FILE').port)")"
IP="$(get_server_ip)"
IP="${IP:-IP-SERVER}"
BASE="$(python3 -c "import json; print(json.load(open('$CONFIG_FILE')).get('base_path',''))" 2>/dev/null || echo '')"
# Bila SSL Cloudflare terpasang saat install, Panel URL otomatis memakai domain
# sertifikat (https) — bukan IP. Domain diambil dari panel cert (ssl.sh --panel).
PANEL_DOMAIN="$(python3 -c "import json;print(json.load(open('$CONFIG_FILE')).get('domain','') or '')" 2>/dev/null || echo '')"
if [[ -n "$PANEL_DOMAIN" ]]; then
  PANEL_URL="https://${PANEL_DOMAIN}:${PORT}${BASE}"
else
  PANEL_URL="http://${IP}:${PORT}${BASE}"
fi

# Simpan hasil install
if [[ "$XM_PASS" != "(tidak diubah)" ]]; then
  write_install_result "$XM_USER" "$XM_PASS" "$PORT" "$PANEL_URL"
fi

echo
echo -e "${GRN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GRN}     ${BOLD}OceanShark Xray Manager — Instalasi Selesai!${NC}          ${GRN}${NC}"
echo -e "${GRN}═══════════════════════════════════════════════════════════${NC}"
if [[ "$XM_PASS" != "(tidak diubah)" ]]; then
echo -e "  ${GRN}Username   :${NC} ${BOLD}${XM_USER}${NC}"
echo -e "  ${GRN}Password   :${NC} ${BOLD}${XM_PASS}${NC}"
fi
echo -e "  ${GRN}Port       :${NC} ${BOLD}${PORT}${NC}"
echo -e "  ${GRN}Panel URL  :${NC} ${BOLD}${PANEL_URL}${NC}"
echo -e "${GRN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${YLW}  ⚠ SIMPAN KREDENSIAL INI DENGAN AMAN!${NC}"
echo -e "${GRN}═══════════════════════════════════════════════════════════${NC}"
echo
echo -e "┌───────────────────────────────────────────────────────┐"
echo -e "│  ${BLU}Perintah xm:${NC}                                          │"
echo -e "│                                                       │"
echo -e "│  ${BLU}xm${NC}              - Menu Interaktif (gaya x-ui)         │"
echo -e "│  ${BLU}xm start${NC}        - Start panel                         │"
echo -e "│  ${BLU}xm stop${NC}         - Stop panel                          │"
echo -e "│  ${BLU}xm restart${NC}      - Restart panel                       │"
echo -e "│  ${BLU}xm status${NC}       - Status lengkap                      │"
echo -e "│  ${BLU}xm settings${NC}     - Lihat pengaturan                    │"
echo -e "│  ${BLU}xm log${NC}          - Lihat log                           │"
echo -e "│  ${BLU}xm enable${NC}       - Aktifkan autostart                  │"
echo -e "│  ${BLU}xm disable${NC}      - Nonaktifkan autostart               │"
echo -e "│                                                       │"
echo -e "│  ${CYN}Manajemen Inbound & Client:${NC}                           │"
echo -e "│  ${BLU}xm inbound list${NC}           - Daftar inbound            │"
echo -e "│  ${BLU}xm inbound add${NC} --protocol vless --port 8443 \\\\       │"
echo -e "│       --network tcp --security reality --dest y...:443│"
echo -e "│  ${BLU}xm client add${NC} --inbound 1 --email budi \\\\            │"
echo -e "│       --days 30 --limit-ip 2 --qr                    │"
echo -e "│  ${BLU}xm client list${NC}            - Daftar client             │"
echo -e "└───────────────────────────────────────────────────────┘"
echo
echo -e "Baca README.md untuk integrasi dengan web API Oceansharknet."
