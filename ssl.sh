#!/usr/bin/env bash
#
# ssl.sh — Terbitkan sertifikat TLS lewat Cloudflare DNS (acme.sh, DNS-01)
#          menggunakan EMAIL + GLOBAL API KEY Cloudflare.
#
# DNS-01 tidak butuh port 80/443 terbuka dan mendukung wildcard.
# Sertifikat dipasang ke:  /etc/xray-manager/certs/<domain>/{fullchain,privkey}.pem
# Auto-renew (via cron acme.sh) otomatis me-restart xray.
#
# Contoh:
#   sudo bash ssl.sh -d vpn.domain.com -e email@anda.com -k GLOBAL_API_KEY
#   sudo bash ssl.sh -d domain.com -w -e email@anda.com -k GLOBAL_API_KEY   # + wildcard *.domain.com
#
set -euo pipefail

RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'; BLU='\033[0;34m'; NC='\033[0m'
info() { echo -e "${BLU}[*]${NC} $*"; }
ok()   { echo -e "${GRN}[✔]${NC} $*"; }
warn() { echo -e "${YLW}[!]${NC} $*"; }
err()  { echo -e "${RED}[x]${NC} $*" >&2; }

DOMAIN=""; CF_EMAIL=""; CF_KEY=""; WILDCARD=0
FORCE_PANEL=0
XRAY_SERVICE="xray"
CERT_ROOT="/etc/xray-manager/certs"

usage() {
  cat <<EOF
Pemakaian: sudo bash ssl.sh -d <domain> -e <cf_email> -k <cf_global_api_key> [opsi]

  -d, --domain    domain utama (mis. vpn.domain.com)
  -e, --email     email akun Cloudflare
  -k, --key       Cloudflare GLOBAL API KEY
  -w, --wildcard  terbitkan juga wildcard *.<domain> (butuh domain apex)
  -p, --panel     jadikan domain ini sebagai sertifikat Panel HTTPS
                  (otomatis aktif jika belum ada panel cert; flag ini memaksa
                  mengganti panel cert yang sudah ada)
      --service   nama service xray untuk di-reload saat renew (default: xray)
      --cert-root direktori sertifikat (default: /etc/xray-manager/certs)
  -h, --help      tampilkan bantuan
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -d|--domain)   DOMAIN="$2"; shift 2;;
    -e|--email)    CF_EMAIL="$2"; shift 2;;
    -k|--key)      CF_KEY="$2"; shift 2;;
    -w|--wildcard) WILDCARD=1; shift;;
    -p|--panel)    FORCE_PANEL=1; shift;;
    --service)     XRAY_SERVICE="$2"; shift 2;;
    --cert-root)   CERT_ROOT="$2"; shift 2;;
    -h|--help)     usage; exit 0;;
    *) err "Argumen tidak dikenal: $1"; usage; exit 1;;
  esac
done

[[ $EUID -eq 0 ]] || { err "Harus dijalankan sebagai root (sudo)."; exit 1; }
[[ -n "$DOMAIN" && -n "$CF_EMAIL" && -n "$CF_KEY" ]] || {
  err "Domain, email, dan Global API Key wajib diisi."; usage; exit 1; }

# Baca cert_dir & service dari config manager bila ada (biar konsisten)
CFG="/etc/xray-manager/config.json"
if [[ -f "$CFG" ]] && command -v python3 >/dev/null; then
  CR="$(python3 -c "import json;print(json.load(open('$CFG')).get('cert_dir',''))" 2>/dev/null || true)"
  SV="$(python3 -c "import json;print(json.load(open('$CFG')).get('xray_service',''))" 2>/dev/null || true)"
  [[ -n "$CR" ]] && CERT_ROOT="$CR"
  [[ -n "$SV" ]] && XRAY_SERVICE="$SV"
fi

# ---------------------------------------------------------------------------
# 1. Dependensi & acme.sh
# ---------------------------------------------------------------------------
info "Memeriksa dependensi..."
if ! command -v socat >/dev/null || ! command -v curl >/dev/null; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y -q && apt-get install -y -q socat curl cron
fi

ACME="$HOME/.acme.sh/acme.sh"
if [[ ! -x "$ACME" ]]; then
  info "Memasang acme.sh..."
  curl -fsSL https://get.acme.sh | sh -s email="$CF_EMAIL"
fi
[[ -x "$ACME" ]] || { err "acme.sh gagal terpasang."; exit 1; }

# Gunakan Let's Encrypt sebagai CA default
"$ACME" --set-default-ca --server letsencrypt >/dev/null 2>&1 || true

# ---------------------------------------------------------------------------
# 2. Terbitkan sertifikat (DNS-01 via Cloudflare, email + global key)
# ---------------------------------------------------------------------------
export CF_Key="$CF_KEY"
export CF_Email="$CF_EMAIL"

ISSUE_ARGS=(--issue --dns dns_cf -d "$DOMAIN" --keylength ec-256)
if [[ "$WILDCARD" -eq 1 ]]; then
  ISSUE_ARGS+=(-d "*.$DOMAIN")
  info "Menerbitkan sertifikat untuk $DOMAIN dan *.$DOMAIN (DNS-01)..."
else
  info "Menerbitkan sertifikat untuk $DOMAIN (DNS-01)..."
fi

set +e
"$ACME" "${ISSUE_ARGS[@]}"
RC=$?
set -e
# rc=2 berarti "sudah ada & belum perlu renew" — bukan error
if [[ $RC -ne 0 && $RC -ne 2 ]]; then
  err "Penerbitan sertifikat gagal (rc=$RC). Cek: email/API key benar? domain di Cloudflare?"
  exit 1
fi

# ---------------------------------------------------------------------------
# 3. Pasang sertifikat ke lokasi tetap + reloadcmd untuk auto-renew
# ---------------------------------------------------------------------------
DEST="$CERT_ROOT/$DOMAIN"
mkdir -p "$DEST"
info "Memasang sertifikat ke $DEST ..."
# reloadcmd juga membenahi izin: acme.sh menulis ulang privkey (600, root) saat
# perpanjangan, sedangkan service xray sering berjalan sebagai 'nobody' dan harus
# bisa membacanya. chmod 644 di reloadcmd menjaga sertifikat tetap terbaca xray
# setiap kali diperpanjang.
"$ACME" --install-cert -d "$DOMAIN" --ecc \
  --key-file       "$DEST/privkey.pem" \
  --fullchain-file "$DEST/fullchain.pem" \
  --reloadcmd      "chmod 644 '$DEST/privkey.pem' '$DEST/fullchain.pem'; systemctl restart $XRAY_SERVICE"

# Izin awal: sertifikat harus bisa dibaca service xray (bukan hanya root).
chmod 755 "$CERT_ROOT" "$DEST" 2>/dev/null || true
chmod 644 "$DEST/fullchain.pem" "$DEST/privkey.pem" 2>/dev/null || true
# Induk cert-root (mis. /etc/xray-manager) cukup bisa ditembus (o+x), isinya tetap
# tersembunyi karena tidak menambah hak baca.
chmod o+x "$(dirname "$CERT_ROOT")" 2>/dev/null || true

ok "Sertifikat siap:"
echo "    fullchain : $DEST/fullchain.pem"
echo "    privkey   : $DEST/privkey.pem"
echo
echo "Auto-renew aktif via cron acme.sh (xray otomatis restart saat perpanjangan)."

# ---------------------------------------------------------------------------
# 4. Terapkan domain ini sebagai Panel HTTPS bila:
#    - belum ada panel cert, ATAU
#    - user memaksa dengan --panel
#    Maka Panel URL otomatis memakai domain sertifikat (bukan IP).
# ---------------------------------------------------------------------------
APPLIED_PANEL=0
if [[ -f "$CFG" ]]; then
  CUR_CERT="$(python3 -c "import json;print(json.load(open('$CFG')).get('panel_cert_file','') or '')" 2>/dev/null || echo '')"
  if [[ -z "$CUR_CERT" || $FORCE_PANEL -eq 1 ]]; then
    if [[ -z "$CUR_CERT" ]]; then
      info "Belum ada panel cert — menjadikan '${DOMAIN}' sebagai Panel HTTPS..."
    else
      info "Mengganti panel cert yang ada dengan '${DOMAIN}' (--panel)..."
    fi
    python3 - "$CFG" "$DOMAIN" <<'PYEOF' || warn "Gagal memperbarui config — set manual panel cert di Pengaturan."
import json, sys, os
path, domain = sys.argv[1], sys.argv[2]
cfg = json.load(open(path))
cert_root = cfg.get("cert_dir", "/etc/xray-manager/certs")
cfg["panel_cert_file"] = os.path.join(cert_root, domain, "fullchain.pem")
cfg["panel_key_file"]  = os.path.join(cert_root, domain, "privkey.pem")
cfg["domain"]          = domain
os.replace(path, path + ".bak")
with open(path, "w") as f:
    json.dump(cfg, f, indent=2)
PYEOF
    APPLIED_PANEL=1
  fi
fi

# Baca port & base_path untuk menampilkan Panel URL
PORT="$(python3 -c "import json;print(json.load(open('$CFG')).get('port',2053))" 2>/dev/null || echo '2053')"
BASE="$(python3 -c "import json;print(json.load(open('$CFG')).get('base_path','') or '')" 2>/dev/null || echo '')"

echo
echo "Buat inbound TLS memakai sertifikat ini:"
echo -e "  ${GRN}xm inbound add --protocol vless --port 443 --network ws --path /ws \\
     --security tls --cert-domain $DOMAIN${NC}"
echo "  (--cert-domain otomatis mengisi --cert, --key, dan --sni dari $DOMAIN)"
echo
if [[ $APPLIED_PANEL -eq 1 ]]; then
  # service panel (bukan xray) yang perlu restart agar TLS terbaca di startup
  PANEL_SVC="$(python3 -c "import json;print(json.load(open('$CFG')).get('panel_service','') or 'xray-manager')" 2>/dev/null || echo 'xray-manager')"
  if [[ -n "$PANEL_SVC" ]] && systemctl restart "$PANEL_SVC" 2>/dev/null; then
    ok "Panel HTTPS diaktifkan — service ${PANEL_SVC} dimulai ulang."
  else
    warn "Aktifkan manual: systemctl restart xray-manager"
  fi
  echo -e "  ${GRN}Panel URL  : https://${DOMAIN}:${PORT}${BASE}${NC}"
fi
