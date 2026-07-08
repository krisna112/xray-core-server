#!/usr/bin/env bash
# Uninstall OceanShark Xray Manager (Xray-core dibiarkan terpasang).
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Harus root."; exit 1; }

echo "Menghentikan & menghapus service xray-manager..."
systemctl disable --now xray-manager 2>/dev/null || true
rm -f /etc/systemd/system/xray-manager.service
systemctl daemon-reload

rm -f /usr/local/bin/xm
rm -f /etc/fail2ban/filter.d/xray-ip-limit.conf /etc/fail2ban/jail.d/xray-ip-limit.conf
systemctl restart fail2ban 2>/dev/null || true

read -rp "Hapus juga konfigurasi & database (/etc/xray-manager)? [y/N] " D
if [[ "${D,,}" == "y" ]]; then
  rm -rf /etc/xray-manager /var/log/xray-manager
  echo "Konfigurasi & database dihapus."
fi

rm -rf /opt/xray-manager
echo "Selesai. Xray-core tidak ikut dihapus (jalankan: xray-uninstall bila perlu)."
