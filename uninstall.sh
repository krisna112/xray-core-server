#!/usr/bin/env bash
# Uninstall OceanShark Xray Manager (Xray-core dibiarkan terpasang).
set -euo pipefail

RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'; NC='\033[0m'
info() { echo -e "\033[0;34m[*]\033[0m $*"; }
ok()   { echo -e "${GRN}[✔]${NC} $*"; }
warn() { echo -e "${YLW}[!]${NC} $*"; }
err()  { echo -e "${RED}[x]${NC} $*" >&2; }

[[ $EUID -eq 0 ]] || { err "Harus root."; exit 1; }

echo -e "${YLW}[?]${NC} YAKIN ingin menghapus xray-manager?"
read -rp "    Ketik 'y' untuk melanjutkan [y/N]: " CONF
if [[ "${CONF,,}" != "y" ]]; then
    info "Dibatalkan."
    exit 0
fi

info "Menghentikan & menghapus service xray-manager..."
systemctl disable --now xray-manager 2>/dev/null || true
rm -f /etc/systemd/system/xray-manager.service
systemctl daemon-reload

info "Menghapus CLI & menu..."
rm -f /usr/local/bin/xm
rm -f /usr/local/bin/xm-menu

info "Menghapus konfigurasi fail2ban..."
rm -f /etc/fail2ban/filter.d/xray-ip-limit.conf /etc/fail2ban/jail.d/xray-ip-limit.conf
systemctl restart fail2ban 2>/dev/null || true

read -rp "$(echo -e "${YLW}[?]${NC} Hapus juga konfigurasi & database (/etc/xray-manager)? [y/N] ")" D
if [[ "${D,,}" == "y" ]]; then
  rm -rf /etc/xray-manager /var/log/xray-manager
  ok "Konfigurasi, database, & sertifikat dihapus."
fi

rm -rf /opt/xray-manager
ok "Uninstall selesai."
echo
echo "Xray-core TIDAK ikut dihapus."
echo "Untuk menghapus Xray-core, jalankan:"
echo "  bash -c \"\$(curl -fsSL https://github.com/XTLS/Xray-install/raw/main/install-release.sh)\" @ remove"
