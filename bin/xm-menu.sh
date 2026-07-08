#!/usr/bin/env bash
#
# xm-menu.sh — Menu interaktif OceanShark Xray Manager (gaya 3x-ui)
# Dipasang ke /usr/local/bin/xm-menu oleh install.sh
# Dipanggil otomatis oleh `xm` jika tanpa argumen.
#
# Jalankan sebagai root: xm  atau  bash xm-menu.sh
#

# ─── Warna ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GRN='\033[0;32m'
YLW='\033[1;33m'
BLU='\033[0;34m'
CYN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# ─── Konstanta ────────────────────────────────────────────────────────────────
APP_DIR="/opt/xray-manager"
CONF_DIR="/etc/xray-manager"
CONFIG_FILE="$CONF_DIR/config.json"
LOG_DIR="/var/log/xray-manager"
XM_CLI="/usr/local/bin/xm"
SERVICE="xray-manager"
XRAY_SERVICE="xray"

# ─── Fungsi helper ────────────────────────────────────────────────────────────
info() { echo -e "${BLU}[*]${NC} $*"; }
ok()   { echo -e "${GRN}[✔]${NC} $*"; }
warn() { echo -e "${YLW}[!]${NC} $*"; }
err()  { echo -e "${RED}[✘]${NC} $*" >&2; }

gen_random_string() {
    local length="${1:-12}"
    openssl rand -base64 $((length * 2)) 2>/dev/null | tr -dc 'a-zA-Z0-9' | head -c "$length"
}

confirm() {
    local prompt="$1"
    local default="${2:-n}"
    echo -n -e "${YLW}[?]${NC} ${prompt} [y/N]: " && read -r temp
    if [[ "${temp,,}" == "y" ]]; then
        return 0
    else
        return 1
    fi
}

before_show_menu() {
    echo && echo -n -e "${YLW}Tekan enter untuk kembali ke menu utama: ${NC}" && read -r _temp
    show_menu
}

# Baca nilai dari config.json
get_config_value() {
    local key="$1"
    local default="${2:-}"
    if [[ -f "$CONFIG_FILE" ]] && command -v python3 >/dev/null 2>&1; then
        python3 -c "import json; print(json.load(open('$CONFIG_FILE')).get('$key','$default'))" 2>/dev/null || echo "$default"
    else
        echo "$default"
    fi
}

# Deteksi IP publik server
get_server_ip() {
    local urls=(
        "https://api4.ipify.org"
        "https://ipv4.icanhazip.com"
        "https://4.ident.me"
    )
    local ip=""
    for url in "${urls[@]}"; do
        ip=$(curl -fsSL --max-time 3 "$url" 2>/dev/null | tr -d '[:space:]')
        if [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            echo "$ip"
            return
        fi
    done
    echo "IP-SERVER"
}

# ─── Cek status ───────────────────────────────────────────────────────────────
# return: 0=running, 1=stopped, 2=not installed
check_status() {
    if [[ ! -d "$APP_DIR" ]]; then
        return 2
    fi
    if systemctl is-active --quiet "$SERVICE" 2>/dev/null; then
        return 0
    else
        return 1
    fi
}

check_xray_status() {
    systemctl is-active --quiet "$XRAY_SERVICE" 2>/dev/null && return 0 || return 1
}

check_autostart() {
    systemctl is-enabled --quiet "$SERVICE" 2>/dev/null && return 0 || return 1
}

check_install() {
    if [[ ! -d "$APP_DIR" ]]; then
        err "Xray Manager belum terinstal!"
        return 1
    fi
    return 0
}

show_status() {
    check_status
    local status=$?
    case $status in
        0) echo -e "Status Panel : ${GRN}Berjalan ✔${NC}" ;;
        1) echo -e "Status Panel : ${YLW}Tidak Berjalan${NC}" ;;
        2) echo -e "Status Panel : ${RED}Belum Terinstal${NC}" ;;
    esac

    if check_xray_status; then
        echo -e "Status Xray  : ${GRN}Berjalan ✔${NC}"
    else
        echo -e "Status Xray  : ${RED}Tidak Berjalan${NC}"
    fi

    if check_autostart; then
        echo -e "Autostart    : ${GRN}Aktif ✔${NC}"
    else
        echo -e "Autostart    : ${YLW}Nonaktif${NC}"
    fi

    if [[ -f "$CONFIG_FILE" ]]; then
        local port
        port=$(get_config_value port 2053)
        local base_path
        base_path=$(get_config_value base_path "")
        local ip
        ip=$(get_server_ip)
        echo -e "Panel URL    : ${GRN}http://${ip}:${port}${base_path}${NC}"
    fi
}

# ─── Fungsi Menu ──────────────────────────────────────────────────────────────

# 1. Install / Reinstall
do_install() {
    local src_dir
    src_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd)"
    local install_script=""

    # Cari install.sh
    if [[ -f "$src_dir/install.sh" ]]; then
        install_script="$src_dir/install.sh"
    elif [[ -f "$APP_DIR/install.sh" ]]; then
        install_script="$APP_DIR/install.sh"
    else
        err "File install.sh tidak ditemukan!"
        return 1
    fi

    confirm "Akan menjalankan proses instalasi. Lanjutkan?" || return 0
    bash "$install_script"
}

# 2. Update
do_update() {
    check_install || return 1
    confirm "Akan memperbarui xray-manager. Data tidak akan hilang. Lanjutkan?" || return 0

    local src_dir
    src_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd)"

    info "Menghentikan service..."
    systemctl stop "$SERVICE" 2>/dev/null || true

    info "Menyalin file terbaru..."
    if [[ -d "$src_dir/xraym" ]]; then
        cp -r "$src_dir/xraym" "$APP_DIR/"
        cp "$src_dir/requirements.txt" "$APP_DIR/" 2>/dev/null || true
        cp "$src_dir/ssl.sh" "$APP_DIR/" 2>/dev/null || true
        cp -r "$src_dir/examples" "$APP_DIR/" 2>/dev/null || true
        # Update menu script
        install -m 0755 "$src_dir/bin/xm-menu.sh" /usr/local/bin/xm-menu 2>/dev/null || true
        install -m 0755 "$src_dir/bin/xm" /usr/local/bin/xm 2>/dev/null || true
    else
        err "Direktori source tidak ditemukan: $src_dir/xraym"
        systemctl start "$SERVICE" 2>/dev/null || true
        return 1
    fi

    info "Memperbarui dependensi Python..."
    "$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt" 2>/dev/null || true

    info "Menjalankan ulang service..."
    systemctl start "$SERVICE"
    sleep 2

    if systemctl is-active --quiet "$SERVICE"; then
        ok "Update selesai! Panel berjalan kembali."
    else
        err "Panel gagal start setelah update. Cek: journalctl -u $SERVICE -n 50"
    fi
}

# 3. Uninstall
do_uninstall() {
    check_install || return 1
    confirm "YAKIN menghapus xray-manager? Xray-core TIDAK ikut dihapus." || return 0

    local src_dir
    src_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd)"

    if [[ -f "$src_dir/uninstall.sh" ]]; then
        bash "$src_dir/uninstall.sh"
    elif [[ -f "$APP_DIR/uninstall.sh" ]]; then
        bash "$APP_DIR/uninstall.sh"
    else
        # Uninstall manual
        info "Menghentikan & menghapus service..."
        systemctl disable --now "$SERVICE" 2>/dev/null || true
        rm -f /etc/systemd/system/xray-manager.service
        systemctl daemon-reload
        rm -f /usr/local/bin/xm /usr/local/bin/xm-menu
        rm -f /etc/fail2ban/filter.d/xray-ip-limit.conf /etc/fail2ban/jail.d/xray-ip-limit.conf
        systemctl restart fail2ban 2>/dev/null || true

        confirm "Hapus juga konfigurasi & database ($CONF_DIR)?" && {
            rm -rf "$CONF_DIR" "$LOG_DIR"
            ok "Konfigurasi & database dihapus."
        }
        rm -rf "$APP_DIR"
        ok "Uninstall selesai."
    fi
}

# 4. Reset Username & Password
do_reset_user() {
    check_install || return 1
    echo
    read -rp "  Username baru [admin]: " new_user
    new_user="${new_user:-admin}"

    read -rsp "  Password baru (kosong = generate otomatis): " new_pass
    echo
    if [[ -z "$new_pass" ]]; then
        new_pass=$(gen_random_string 12)
        info "Password digenerate otomatis: ${GRN}${new_pass}${NC}"
    fi

    "$XM_CLI" user set-password --username "$new_user" --password "$new_pass"
    systemctl restart "$SERVICE" 2>/dev/null || true

    echo
    echo -e "${GRN}═══════════════════════════════════════════${NC}"
    echo -e "  Username : ${GRN}${new_user}${NC}"
    echo -e "  Password : ${GRN}${new_pass}${NC}"
    echo -e "${GRN}═══════════════════════════════════════════${NC}"
    echo -e "${YLW}  ⚠ SIMPAN KREDENSIAL INI!${NC}"
    ok "Username & password berhasil direset."
}

# 5. Reset Web Base Path
do_reset_basepath() {
    check_install || return 1
    local new_base
    new_base="/$(gen_random_string 18)"
    "$XM_CLI" settings set base_path "$new_base"
    systemctl restart "$SERVICE" 2>/dev/null || true
    ok "Base path baru: ${GRN}${new_base}${NC}"
    info "Restart service diperlukan agar aktif."
}

# 6. Ganti Port Panel
do_set_port() {
    check_install || return 1
    echo
    read -rp "  Port baru [1-65535]: " new_port
    if [[ -z "$new_port" ]]; then
        warn "Dibatalkan."
        return 0
    fi

    # Validasi port
    if ! [[ "$new_port" =~ ^[0-9]+$ ]] || [[ "$new_port" -lt 1 || "$new_port" -gt 65535 ]]; then
        err "Port tidak valid. Harus angka 1-65535."
        return 1
    fi

    "$XM_CLI" settings set port "$new_port"

    # Auto buka port di firewall
    if command -v ufw >/dev/null 2>&1; then
        ufw allow "$new_port"/tcp comment 'xray-manager panel' 2>/dev/null || true
        info "Port $new_port dibuka di UFW."
    fi
    if command -v firewall-cmd >/dev/null 2>&1; then
        firewall-cmd --permanent --add-port="$new_port"/tcp 2>/dev/null || true
        firewall-cmd --reload 2>/dev/null || true
        info "Port $new_port dibuka di firewalld."
    fi

    systemctl restart "$SERVICE" 2>/dev/null || true
    ok "Port diubah ke ${GRN}${new_port}${NC}. Panel telah direstart."
}

# 7. Lihat Pengaturan
do_show_settings() {
    check_install || return 1
    echo
    "$XM_CLI" settings show
    echo

    local port base_path ip
    port=$(get_config_value port 2053)
    base_path=$(get_config_value base_path "")
    ip=$(get_server_ip)
    echo -e "  ${GRN}Panel URL: http://${ip}:${port}${base_path}${NC}"
}

# 8. Start
do_start() {
    check_install || return 1
    check_status
    if [[ $? -eq 0 ]]; then
        info "Panel sudah berjalan. Gunakan 'Restart' jika ingin memulai ulang."
        return 0
    fi

    systemctl start "$SERVICE"
    sleep 2

    if systemctl is-active --quiet "$SERVICE"; then
        ok "Panel berhasil distart."
    else
        err "Panel gagal start. Cek log: journalctl -u $SERVICE -n 50"
    fi
}

# 9. Stop
do_stop() {
    check_install || return 1
    check_status
    if [[ $? -eq 1 ]]; then
        info "Panel sudah berhenti."
        return 0
    fi

    systemctl stop "$SERVICE"
    sleep 2

    if ! systemctl is-active --quiet "$SERVICE"; then
        ok "Panel berhasil dihentikan."
    else
        err "Gagal menghentikan panel."
    fi
}

# 10. Restart
do_restart() {
    check_install || return 1
    info "Merestart panel..."
    systemctl restart "$SERVICE"
    sleep 2

    if systemctl is-active --quiet "$SERVICE"; then
        ok "Panel berhasil direstart."
    else
        err "Panel gagal restart. Cek: journalctl -u $SERVICE -n 50"
    fi
}

# 11. Restart Xray
do_restart_xray() {
    check_install || return 1
    info "Merestart Xray..."
    systemctl restart "$XRAY_SERVICE"
    sleep 1

    if systemctl is-active --quiet "$XRAY_SERVICE"; then
        ok "Xray berhasil direstart."
    else
        err "Xray gagal restart. Cek: journalctl -u $XRAY_SERVICE -n 30"
    fi
}

# 12. Cek Status
do_check_status() {
    check_install || return 1
    echo
    "$XM_CLI" status
    echo
    echo -e "${BLU}── Detail Service ──${NC}"
    systemctl status "$SERVICE" --no-pager -l 2>/dev/null || true
}

# 13. Lihat Log
do_show_log() {
    check_install || return 1
    echo
    info "Menampilkan 50 baris log terakhir..."
    journalctl -u "$SERVICE" -n 50 --no-pager
    echo
    confirm "Ikuti log secara realtime (Ctrl+C untuk stop)?" && {
        journalctl -u "$SERVICE" -f
    }
}

# 14. Aktifkan Autostart
do_enable_autostart() {
    check_install || return 1
    systemctl enable "$SERVICE" >/dev/null 2>&1
    ok "Autostart diaktifkan. Panel akan otomatis start saat boot."
}

# 15. Nonaktifkan Autostart
do_disable_autostart() {
    check_install || return 1
    systemctl disable "$SERVICE" >/dev/null 2>&1
    ok "Autostart dinonaktifkan."
}

# 16. Manajemen SSL Certificate
do_ssl_menu() {
    check_install || return 1
    echo
    echo -e "${GRN}  1.${NC} Terbitkan SSL via Cloudflare DNS"
    echo -e "${GRN}  2.${NC} Lihat sertifikat terpasang"
    echo -e "${GRN}  0.${NC} Kembali ke menu utama"
    echo
    read -rp "  Pilih: " ssl_choice

    case "$ssl_choice" in
        1)
            echo
            read -rp "  Domain (mis. vpn.domain.com)       : " ssl_domain
            read -rp "  Email akun Cloudflare              : " ssl_email
            read -rsp "  Cloudflare GLOBAL API KEY          : " ssl_key
            echo

            if [[ -z "$ssl_domain" || -z "$ssl_email" || -z "$ssl_key" ]]; then
                err "Semua data wajib diisi!"
                return 1
            fi

            local ssl_script=""
            if [[ -f "$APP_DIR/ssl.sh" ]]; then
                ssl_script="$APP_DIR/ssl.sh"
            else
                local src_dir
                src_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd)"
                if [[ -f "$src_dir/ssl.sh" ]]; then
                    ssl_script="$src_dir/ssl.sh"
                fi
            fi

            if [[ -z "$ssl_script" ]]; then
                err "ssl.sh tidak ditemukan!"
                return 1
            fi

            bash "$ssl_script" -d "$ssl_domain" -e "$ssl_email" -k "$ssl_key"
            ;;
        2)
            echo
            "$XM_CLI" cert list
            ;;
        0|"")
            return 0
            ;;
        *)
            warn "Pilihan tidak valid."
            ;;
    esac
}

# 17. Manajemen IP Limit (Fail2ban)
do_iplimit_menu() {
    check_install || return 1
    echo
    echo -e "${GRN}  1.${NC} Install & Konfigurasi Fail2ban"
    echo -e "${GRN}  2.${NC} Status Fail2ban"
    echo -e "${GRN}  3.${NC} Lihat IP yang Dibanned"
    echo -e "${GRN}  4.${NC} Unban IP"
    echo -e "${GRN}  0.${NC} Kembali ke menu utama"
    echo
    read -rp "  Pilih: " f2b_choice

    case "$f2b_choice" in
        1)
            info "Menginstal fail2ban..."
            apt-get install -y -q fail2ban 2>/dev/null || {
                err "Gagal menginstal fail2ban."
                return 1
            }
            # Copy konfigurasi filter dan jail
            local src_dir
            src_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd)"
            if [[ -f "$src_dir/fail2ban/filter.d/xray-ip-limit.conf" ]]; then
                cp "$src_dir/fail2ban/filter.d/xray-ip-limit.conf" /etc/fail2ban/filter.d/
                cp "$src_dir/fail2ban/jail.d/xray-ip-limit.conf" /etc/fail2ban/jail.d/
            elif [[ -f "$APP_DIR/fail2ban/filter.d/xray-ip-limit.conf" ]]; then
                cp "$APP_DIR/fail2ban/filter.d/xray-ip-limit.conf" /etc/fail2ban/filter.d/
                cp "$APP_DIR/fail2ban/jail.d/xray-ip-limit.conf" /etc/fail2ban/jail.d/
            fi
            touch "$LOG_DIR/ip-limit.log"
            systemctl restart fail2ban
            ok "Fail2ban terpasang dan dikonfigurasi (jail: xray-ip-limit)."
            ;;
        2)
            echo
            systemctl status fail2ban --no-pager -l 2>/dev/null || warn "Fail2ban tidak terpasang."
            ;;
        3)
            echo
            if command -v fail2ban-client >/dev/null 2>&1; then
                fail2ban-client status xray-ip-limit 2>/dev/null || warn "Jail xray-ip-limit belum dikonfigurasi."
            else
                warn "Fail2ban tidak terpasang."
            fi
            ;;
        4)
            read -rp "  IP yang ingin di-unban: " unban_ip
            if [[ -n "$unban_ip" ]]; then
                fail2ban-client set xray-ip-limit unbanip "$unban_ip" 2>/dev/null && ok "IP $unban_ip di-unban." || err "Gagal unban."
            fi
            ;;
        0|"")
            return 0
            ;;
    esac
}

# 18. Manajemen Firewall
do_firewall_menu() {
    echo
    echo -e "${GRN}  1.${NC} ${GRN}Install${NC} Firewall (UFW)"
    echo -e "${GRN}  2.${NC} Daftar Port [numbered]"
    echo -e "${GRN}  3.${NC} ${GRN}Buka${NC} Port"
    echo -e "${GRN}  4.${NC} ${RED}Hapus${NC} Port dari Daftar"
    echo -e "${GRN}  5.${NC} ${GRN}Aktifkan${NC} Firewall"
    echo -e "${GRN}  6.${NC} ${RED}Nonaktifkan${NC} Firewall"
    echo -e "${GRN}  7.${NC} Status Firewall"
    echo -e "${GRN}  0.${NC} Kembali ke menu utama"
    echo
    read -rp "  Pilih: " fw_choice

    case "$fw_choice" in
        1)
            info "Menginstal UFW..."
            apt-get install -y -q ufw 2>/dev/null || {
                err "Gagal menginstal UFW."
                return 1
            }
            # Auto-allow SSH agar tidak terkunci
            ufw allow 22/tcp comment 'SSH' 2>/dev/null || true
            ok "UFW terpasang. SSH (port 22) telah dibuka."
            warn "Aktifkan firewall melalui opsi 5."
            ;;
        2)
            echo
            ufw status numbered 2>/dev/null || warn "UFW tidak terpasang."
            ;;
        3)
            read -rp "  Port yang ingin dibuka (mis. 443 atau 8443/tcp): " open_port
            if [[ -n "$open_port" ]]; then
                ufw allow "$open_port" 2>/dev/null && ok "Port $open_port dibuka." || err "Gagal membuka port."
            fi
            ;;
        4)
            ufw status numbered 2>/dev/null
            read -rp "  Nomor rule yang ingin dihapus: " rule_num
            if [[ -n "$rule_num" ]]; then
                echo "y" | ufw delete "$rule_num" 2>/dev/null && ok "Rule #$rule_num dihapus." || err "Gagal menghapus rule."
            fi
            ;;
        5)
            confirm "Aktifkan firewall? Pastikan SSH (port 22) sudah dibuka." && {
                echo "y" | ufw enable 2>/dev/null
                ok "Firewall diaktifkan."
            }
            ;;
        6)
            ufw disable 2>/dev/null
            ok "Firewall dinonaktifkan."
            ;;
        7)
            echo
            ufw status verbose 2>/dev/null || warn "UFW tidak terpasang."
            ;;
        0|"")
            return 0
            ;;
    esac
}

# 19. Buat Inbound Cepat
do_quick_inbound() {
    check_install || return 1
    echo
    echo -e "${BLU}── Wizard Buat Inbound ──${NC}"
    echo
    echo "  Protokol yang tersedia:"
    echo -e "    ${GRN}1)${NC} vless       ${GRN}2)${NC} vmess       ${GRN}3)${NC} trojan"
    echo -e "    ${GRN}4)${NC} shadowsocks ${GRN}5)${NC} hysteria"
    echo
    read -rp "  Pilih protokol [1]: " proto_choice
    proto_choice="${proto_choice:-1}"
    local protocol
    case "$proto_choice" in
        1) protocol="vless" ;;
        2) protocol="vmess" ;;
        3) protocol="trojan" ;;
        4) protocol="shadowsocks" ;;
        5) protocol="hysteria" ;;
        *) protocol="vless" ;;
    esac

    read -rp "  Port inbound: " ib_port
    if [[ -z "$ib_port" ]]; then
        err "Port wajib diisi!"
        return 1
    fi

    echo
    echo "  Network:"
    echo -e "    ${GRN}1)${NC} tcp    ${GRN}2)${NC} ws    ${GRN}3)${NC} grpc    ${GRN}4)${NC} httpupgrade"
    echo
    read -rp "  Pilih network [1]: " net_choice
    net_choice="${net_choice:-1}"
    local network
    case "$net_choice" in
        1) network="tcp" ;;
        2) network="ws" ;;
        3) network="grpc" ;;
        4) network="httpupgrade" ;;
        *) network="tcp" ;;
    esac

    echo
    echo "  Security:"
    echo -e "    ${GRN}1)${NC} none    ${GRN}2)${NC} tls    ${GRN}3)${NC} reality"
    echo
    read -rp "  Pilih security [1]: " sec_choice
    sec_choice="${sec_choice:-1}"
    local security extra_args=""
    case "$sec_choice" in
        1) security="none" ;;
        2)
            security="tls"
            read -rp "  Domain sertifikat (--cert-domain): " cert_domain
            if [[ -n "$cert_domain" ]]; then
                extra_args="--cert-domain $cert_domain"
            fi
            ;;
        3)
            security="reality"
            read -rp "  Dest REALITY [yahoo.com:443]: " reality_dest
            reality_dest="${reality_dest:-yahoo.com:443}"
            extra_args="--dest $reality_dest"
            ;;
        *) security="none" ;;
    esac

    # Path untuk ws/httpupgrade/grpc
    if [[ "$network" == "ws" || "$network" == "httpupgrade" ]]; then
        read -rp "  Path (mis. /ws) [/]: " ws_path
        ws_path="${ws_path:-/}"
        extra_args="$extra_args --path $ws_path"
    elif [[ "$network" == "grpc" ]]; then
        read -rp "  Service Name [grpc]: " grpc_sn
        grpc_sn="${grpc_sn:-grpc}"
        extra_args="$extra_args --path $grpc_sn"
    fi

    read -rp "  Remark (opsional): " remark

    echo
    info "Membuat inbound $protocol port $ib_port ($network/$security)..."
    local cmd="$XM_CLI inbound add --protocol $protocol --port $ib_port --network $network --security $security"
    [[ -n "$remark" ]] && cmd="$cmd --remark $remark"
    [[ -n "$extra_args" ]] && cmd="$cmd $extra_args"

    eval "$cmd"

    # Auto buka port di firewall
    if command -v ufw >/dev/null 2>&1; then
        ufw allow "$ib_port" comment "xray-$protocol" 2>/dev/null || true
    fi
}

# 20. Buat Client Cepat
do_quick_client() {
    check_install || return 1
    echo
    echo -e "${BLU}── Wizard Buat Client ──${NC}"
    echo
    info "Daftar inbound saat ini:"
    "$XM_CLI" inbound list
    echo

    read -rp "  ID Inbound: " ib_id
    if [[ -z "$ib_id" ]]; then
        err "ID Inbound wajib diisi!"
        return 1
    fi

    read -rp "  Email / nama client: " email
    if [[ -z "$email" ]]; then
        email="user$(date +%s)"
        info "Email otomatis: $email"
    fi

    read -rp "  Masa aktif (hari) [30]: " days
    days="${days:-30}"

    read -rp "  Limit IP bersamaan [2]: " limit_ip
    limit_ip="${limit_ip:-2}"

    read -rp "  Kuota trafik (GB, 0=unlimited) [0]: " quota_gb
    quota_gb="${quota_gb:-0}"

    echo
    info "Membuat client '$email' di inbound #$ib_id..."
    local cmd="$XM_CLI client add --inbound $ib_id --email $email --days $days --limit-ip $limit_ip --qr"
    if [[ "$quota_gb" != "0" ]]; then
        cmd="$cmd --gb $quota_gb"
    fi
    eval "$cmd"
}

# 21. Lihat Semua Inbound
do_list_inbound() {
    check_install || return 1
    echo
    "$XM_CLI" inbound list
}

# 22. Lihat Semua Client
do_list_client() {
    check_install || return 1
    echo
    "$XM_CLI" client list
}

# 23. Aktifkan BBR
do_enable_bbr() {
    if lsmod | grep -q tcp_bbr 2>/dev/null; then
        ok "TCP BBR sudah aktif!"
        sysctl net.ipv4.tcp_congestion_control 2>/dev/null
        return 0
    fi

    confirm "Aktifkan TCP BBR untuk mempercepat koneksi?" || return 0

    modprobe tcp_bbr 2>/dev/null || true
    if ! grep -q "tcp_bbr" /etc/modules-load.d/bbr.conf 2>/dev/null; then
        echo "tcp_bbr" >> /etc/modules-load.d/bbr.conf
    fi

    cat > /etc/sysctl.d/99-bbr.conf <<EOF
net.core.default_qdisc=fq
net.ipv4.tcp_congestion_control=bbr
EOF
    sysctl -p /etc/sysctl.d/99-bbr.conf 2>/dev/null

    if sysctl net.ipv4.tcp_congestion_control 2>/dev/null | grep -q bbr; then
        ok "TCP BBR berhasil diaktifkan!"
    else
        err "Gagal mengaktifkan BBR. Kernel mungkin tidak mendukung."
    fi
}

# 24. Speedtest
do_speedtest() {
    if ! command -v speedtest-cli >/dev/null 2>&1 && ! command -v speedtest >/dev/null 2>&1; then
        info "Menginstal speedtest-cli..."
        if command -v pip3 >/dev/null 2>&1; then
            pip3 install speedtest-cli 2>/dev/null
        elif command -v apt-get >/dev/null 2>&1; then
            apt-get install -y -q speedtest-cli 2>/dev/null
        fi
    fi

    echo
    if command -v speedtest-cli >/dev/null 2>&1; then
        speedtest-cli
    elif command -v speedtest >/dev/null 2>&1; then
        speedtest
    else
        err "Speedtest gagal diinstal."
    fi
}

# ─── Menu Utama ───────────────────────────────────────────────────────────────
show_menu() {
    clear
    echo -e "
${CYN}╔════════════════════════════════════════════════╗${NC}
${CYN}│${NC}  ${BOLD}${GRN}OceanShark Xray Manager${NC}                      ${CYN}│${NC}
${CYN}│${NC}  ${GRN}0.${NC} Keluar                                    ${CYN}│${NC}
${CYN}│${NC}────────────────────────────────────────────────${CYN}│${NC}
${CYN}│${NC}  ${GRN}1.${NC} Install / Reinstall                       ${CYN}│${NC}
${CYN}│${NC}  ${GRN}2.${NC} Update                                    ${CYN}│${NC}
${CYN}│${NC}  ${GRN}3.${NC} Uninstall                                 ${CYN}│${NC}
${CYN}│${NC}────────────────────────────────────────────────${CYN}│${NC}
${CYN}│${NC}  ${GRN}4.${NC} Reset Username & Password                 ${CYN}│${NC}
${CYN}│${NC}  ${GRN}5.${NC} Reset Web Base Path                       ${CYN}│${NC}
${CYN}│${NC}  ${GRN}6.${NC} Ganti Port Panel                          ${CYN}│${NC}
${CYN}│${NC}  ${GRN}7.${NC} Lihat Pengaturan Saat Ini                 ${CYN}│${NC}
${CYN}│${NC}────────────────────────────────────────────────${CYN}│${NC}
${CYN}│${NC}  ${GRN}8.${NC} Start                                     ${CYN}│${NC}
${CYN}│${NC}  ${GRN}9.${NC} Stop                                      ${CYN}│${NC}
${CYN}│${NC}  ${GRN}10.${NC} Restart                                  ${CYN}│${NC}
${CYN}│${NC}  ${GRN}11.${NC} Restart Xray                             ${CYN}│${NC}
${CYN}│${NC}  ${GRN}12.${NC} Cek Status                               ${CYN}│${NC}
${CYN}│${NC}  ${GRN}13.${NC} Lihat Log                                ${CYN}│${NC}
${CYN}│${NC}────────────────────────────────────────────────${CYN}│${NC}
${CYN}│${NC}  ${GRN}14.${NC} Aktifkan Autostart                       ${CYN}│${NC}
${CYN}│${NC}  ${GRN}15.${NC} Nonaktifkan Autostart                    ${CYN}│${NC}
${CYN}│${NC}────────────────────────────────────────────────${CYN}│${NC}
${CYN}│${NC}  ${GRN}16.${NC} Manajemen SSL Certificate                ${CYN}│${NC}
${CYN}│${NC}  ${GRN}17.${NC} Manajemen IP Limit (Fail2ban)            ${CYN}│${NC}
${CYN}│${NC}  ${GRN}18.${NC} Manajemen Firewall                       ${CYN}│${NC}
${CYN}│${NC}────────────────────────────────────────────────${CYN}│${NC}
${CYN}│${NC}  ${GRN}19.${NC} Buat Inbound Cepat                       ${CYN}│${NC}
${CYN}│${NC}  ${GRN}20.${NC} Buat Client Cepat                        ${CYN}│${NC}
${CYN}│${NC}  ${GRN}21.${NC} Lihat Semua Inbound                      ${CYN}│${NC}
${CYN}│${NC}  ${GRN}22.${NC} Lihat Semua Client                       ${CYN}│${NC}
${CYN}│${NC}────────────────────────────────────────────────${CYN}│${NC}
${CYN}│${NC}  ${GRN}23.${NC} Aktifkan BBR                             ${CYN}│${NC}
${CYN}│${NC}  ${GRN}24.${NC} Speedtest                                ${CYN}│${NC}
${CYN}╚════════════════════════════════════════════════╝${NC}
"
    show_status
    echo && read -rp "Masukkan pilihan [0-24]: " num

    case "${num}" in
        0)  exit 0 ;;
        1)  do_install ;;
        2)  do_update ;;
        3)  do_uninstall ;;
        4)  do_reset_user ;;
        5)  do_reset_basepath ;;
        6)  do_set_port ;;
        7)  do_show_settings ;;
        8)  do_start ;;
        9)  do_stop ;;
        10) do_restart ;;
        11) do_restart_xray ;;
        12) do_check_status ;;
        13) do_show_log ;;
        14) do_enable_autostart ;;
        15) do_disable_autostart ;;
        16) do_ssl_menu ;;
        17) do_iplimit_menu ;;
        18) do_firewall_menu ;;
        19) do_quick_inbound ;;
        20) do_quick_client ;;
        21) do_list_inbound ;;
        22) do_list_client ;;
        23) do_enable_bbr ;;
        24) do_speedtest ;;
        *)  err "Masukkan angka yang benar [0-24]" ;;
    esac

    before_show_menu
}

# ─── Entry Point ──────────────────────────────────────────────────────────────

# Cek root
[[ $EUID -eq 0 ]] || { err "Harus dijalankan sebagai root (gunakan sudo)."; exit 1; }

# Jika dipanggil dengan argumen subcommand, langsung jalankan
if [[ $# -gt 0 ]]; then
    case "$1" in
        start)    do_start ;;
        stop)     do_stop ;;
        restart)  do_restart ;;
        restart-xray) do_restart_xray ;;
        status)   do_check_status ;;
        settings) do_show_settings ;;
        enable)   do_enable_autostart ;;
        disable)  do_disable_autostart ;;
        log)      do_show_log ;;
        *)        echo "Subcommand tidak dikenal: $1"; echo "Gunakan: xm {start|stop|restart|status|settings|enable|disable|log}"; exit 1 ;;
    esac
else
    show_menu
fi
