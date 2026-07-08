#!/usr/bin/env bash
#
# OceanShark Xray Manager — updater (git pull + restart)
# Menarik kode terbaru dari GitHub, menyalin ke /opt/xray-manager,
# memperbarui dependensi/CLI/service, lalu restart panel & Xray.
# Config (/etc/xray-manager/config.json) & database TIDAK disentuh.
#
# Jalankan sebagai root DARI dalam folder hasil `git clone`:
#   cd /root/xray-core-server && sudo bash update.sh
#
set -euo pipefail

APP_DIR="/opt/xray-manager"
CONF_DIR="/etc/xray-manager"
# Direktori source (lokasi script ini berada = hasil git clone)
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'; BLU='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'
info() { echo -e "${BLU}[*]${NC} $*"; }
ok()   { echo -e "${GRN}[✔]${NC} $*"; }
warn() { echo -e "${YLW}[!]${NC} $*"; }
err()  { echo -e "${RED}[x]${NC} $*" >&2; }

[[ $EUID -eq 0 ]] || { err "Harus dijalankan sebagai root (gunakan sudo)."; exit 1; }
[[ -d "$APP_DIR" ]] || { err "Belum terpasang di $APP_DIR. Jalankan 'sudo bash install.sh' dulu."; exit 1; }

# ---------------------------------------------------------------------------
# 1. Tarik kode terbaru (git pull)
# ---------------------------------------------------------------------------
if [[ -d "$SRC_DIR/.git" ]]; then
  info "Menarik kode terbaru (git pull)..."
  OLD_REV="$(git -C "$SRC_DIR" rev-parse --short HEAD 2>/dev/null || echo '?')"
  if git -C "$SRC_DIR" pull --ff-only; then
    NEW_REV="$(git -C "$SRC_DIR" rev-parse --short HEAD 2>/dev/null || echo '?')"
    if [[ "$OLD_REV" == "$NEW_REV" ]]; then
      ok "Sudah versi terbaru ($NEW_REV) — tetap menyalin ulang & restart."
    else
      ok "Update kode: $OLD_REV → $NEW_REV"
    fi
  else
    warn "git pull gagal (mungkin ada perubahan lokal). Melanjutkan dengan kode yang ada."
  fi
else
  warn "Bukan direktori git — melewati 'git pull'. Untuk update otomatis, jalankan dari folder hasil 'git clone'."
fi

# ---------------------------------------------------------------------------
# 2. Salin kode ke APP_DIR (config & database TIDAK disentuh)
# ---------------------------------------------------------------------------
info "Menyalin kode ke $APP_DIR ..."
rm -rf "$APP_DIR/xraym"
cp -r "$SRC_DIR/xraym" "$APP_DIR/"
cp "$SRC_DIR/requirements.txt" "$APP_DIR/" 2>/dev/null || true
cp "$SRC_DIR/ssl.sh" "$APP_DIR/" 2>/dev/null || true
cp "$SRC_DIR/install.sh" "$APP_DIR/" 2>/dev/null || true
cp "$SRC_DIR/uninstall.sh" "$APP_DIR/" 2>/dev/null || true
cp "$SRC_DIR/update.sh" "$APP_DIR/" 2>/dev/null || true
cp -r "$SRC_DIR/examples" "$APP_DIR/" 2>/dev/null || true
cp -r "$SRC_DIR/fail2ban" "$APP_DIR/" 2>/dev/null || true
ok "Kode tersalin."

# ---------------------------------------------------------------------------
# 3. Perbarui dependensi Python (bila ada yang baru)
# ---------------------------------------------------------------------------
if [[ -x "$APP_DIR/venv/bin/pip" ]]; then
  info "Memeriksa dependensi Python..."
  "$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt" || warn "pip install ada peringatan."
  ok "Dependensi mutakhir."
else
  warn "Virtualenv tidak ditemukan — lewati update dependensi."
fi

# ---------------------------------------------------------------------------
# 4. Perbarui CLI `xm`, menu, dan unit systemd
# ---------------------------------------------------------------------------
install -m 0755 "$SRC_DIR/bin/xm" /usr/local/bin/xm 2>/dev/null || true
install -m 0755 "$SRC_DIR/bin/xm-menu.sh" /usr/local/bin/xm-menu 2>/dev/null || true
if cp "$SRC_DIR/systemd/xray-manager.service" /etc/systemd/system/xray-manager.service 2>/dev/null; then
  systemctl daemon-reload
fi
ok "CLI & service unit mutakhir."

# ---------------------------------------------------------------------------
# 5. Restart panel + rakit ulang config Xray dari database
# ---------------------------------------------------------------------------
info "Merestart panel (xray-manager)..."
systemctl restart xray-manager
sleep 1
if systemctl is-active --quiet xray-manager; then
  ok "Panel aktif kembali."
else
  err "Panel gagal start. Cek: journalctl -u xray-manager -n 50"
fi

info "Merakit ulang config Xray & restart core..."
if command -v xm >/dev/null 2>&1; then
  xm apply || warn "xm apply gagal — cek: journalctl -u xray -n 50"
else
  PYTHONPATH="$APP_DIR" XM_CONFIG="$CONF_DIR/config.json" \
    "$APP_DIR/venv/bin/python" -c \
    "import sys; sys.path.insert(0,'$APP_DIR'); \
     from xraym import settings, db as dbmod, manager; \
     st=settings.load('$CONF_DIR/config.json'); d=dbmod.DB(st.db_path); \
     ok,msg=manager.apply(d, st); print('apply:', ok, msg)" \
    || warn "Rakit ulang config gagal."
fi

echo
echo -e "${GRN}═══════════════════════════════════════════════${NC}"
echo -e "${GRN}  ${BOLD}Update selesai.${NC} Panel & Xray sudah direstart.${NC}"
echo -e "${GRN}═══════════════════════════════════════════════${NC}"
echo -e "  Status : ${BOLD}xm status${NC}   ·   Log: ${BOLD}journalctl -u xray-manager -f${NC}"
