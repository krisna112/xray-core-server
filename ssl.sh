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
XRAY_SERVICE="xray"
CERT_ROOT="/etc/xray-manager/certs"

usage() {
  cat <<EOF
Pemakaian: sudo bash ssl.sh -d <domain> -e <cf_email> -k <cf_global_api_key> [opsi]

  -d, --domain    domain utama (mis. vpn.domain.com)
  -e, --email     email akun Cloudflare
  -k, --key       Cloudflare GLOBAL API KEY
  -w, --wildcard  terbitkan juga wildcard *.<domain> (butuh domain apex)
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
"$ACME" --install-cert -d "$DOMAIN" --ecc \
  --key-file       "$DEST/privkey.pem" \
  --fullchain-file "$DEST/fullchain.pem" \
  --reloadcmd      "systemctl restart $XRAY_SERVICE"
chmod 600 "$DEST/privkey.pem"

ok "Sertifikat siap:"
echo "    fullchain : $DEST/fullchain.pem"
echo "    privkey   : $DEST/privkey.pem"
echo
echo "Auto-renew aktif via cron acme.sh (xray otomatis restart saat perpanjangan)."
echo
echo "Buat inbound TLS memakai sertifikat ini:"
echo -e "  ${GRN}xm inbound add --protocol vless --port 443 --network ws --path /ws \\
     --security tls --cert-domain $DOMAIN${NC}"
echo "  (--cert-domain otomatis mengisi --cert, --key, dan --sni dari $DOMAIN)"
