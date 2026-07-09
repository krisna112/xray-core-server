# OceanShark Xray Manager

Manajer **Xray-core** yang ringan untuk VPS (Debian/Ubuntu) — versi *simple* dari
[3x-ui](https://github.com/mhsanaei/3x-ui): fokus pada **add inbound, add client
(expiry date + kuota + limit IP)**, **share link/QR**, **statistik trafik**, dan
**API sinkronisasi** yang kompatibel dengan gaya `/panel/api/...` milik 3x-ui —
sehingga langsung bisa disinkronkan oleh web API Anda
(`Api-Web-Oceansharknet-Members`) tanpa mengubah `PanelAPI.php`.

Dikelola lewat **Web UI** (dashboard bawaan), **CLI `xm`**, dan **HTTP API** —
cocok untuk banyak node yang dikendalikan dari satu web member.

---

## Fitur

Berjalan di atas **Xray-core v26.3.27** (dipin oleh installer) — Hysteria2 native,
WireGuard FullCone NAT, XHTTP/3, dan mKCP versi ini.

| Kategori | Dukungan |
|---|---|
| **Protokol inbound** | VLESS, VMess, Trojan, Shadowsocks (termasuk 2022-blake3), WireGuard, **Hysteria2 (QUIC/UDP)**, SOCKS/HTTP (Mixed), Dokodemo-door / Tunnel |
| **Transport** | TCP (Raw), mKCP, WebSocket, gRPC, HTTPUpgrade, XHTTP, Hysteria (QUIC) |
| **Latensi rendah** | Profil **realtime** (bawaan ON): buffer kecil, connIdle pendek, UDP/QUIC lolos utuh — ringan untuk video/voice call (WhatsApp/Zoom) di UDP maupun TCP |
| **Security** | none, TLS, XTLS (flow `xtls-rprx-vision`), REALITY |
| **Per-client** | kuota trafik, tanggal expired (fixed / mulai-saat-dipakai), limit IP, status online, share link, QR code |
| **Statistik** | per inbound, per client, per outbound + reset (manual & terjadwal) |
| **Outbound & routing** | WARP, NordVPN, proxy chaining, custom routing rules, load balancer |
| **Storage** | SQLite (default) |
| **Enforcement** | auto-disable saat expired / over-kuota; integrasi **fail2ban** untuk limit IP |
| **Sinkronisasi** | webhook event + endpoint snapshot untuk ditarik web API |

> **Catatan protokol.** **Hysteria2 sudah native** di Xray-core v26.3.27 dan punya
> template siap-pakai (`--protocol hysteria`, wajib TLS). **TUN** bukan protokol
> Xray-core resmi — bila core kustom Anda mendukungnya, tambahkan lewat
> `xm inbound add-raw file.json` (JSON inbound mentah).

> **Mode realtime (video/voice call).** Config yang dihasilkan memakai profil
> *realtime* (aktif secara default): buffer per-koneksi kecil, `connIdle` pendek,
> half-close TCP cepat ditutup, dan UDP/QUIC diteruskan utuh (tidak diblok). Hasilnya
> latensi rendah & hemat RAM untuk panggilan video/suara di **UDP maupun TCP**.
> Untuk kembali ke throughput maksimal ala default Xray:
> `xm settings set realtime false && systemctl restart xray-manager`.
> Untuk pengalaman call terbaik di jaringan buruk, gunakan **Hysteria2** (QUIC) atau
> **mKCP** (`--network kcp`) yang berbasis UDP.

---

## Arsitektur singkat

```
                    ┌───────────────────────────────┐
   xm (CLI)  ─────► │  xray-manager  (Python)        │
   Web API  ──────► │  • SQLite  /etc/xray-manager   │
   (HTTP /panel/api)│  • rakit config.json           │──► /usr/local/etc/xray/config.json
                    │  • jobs: stats, expiry, IP-limit│──► systemctl restart xray
                    └───────────────────────────────┘         │
                              │  webhook / snapshot            ▼
                              ▼                          Xray-core (statsquery API :10085)
                    Api-Web-Oceansharknet-Members
```

Setiap perubahan (via CLI atau API) → tulis config Xray → validasi (`xray -test`)
→ restart service. Background job menarik statistik dari Xray tiap 20 detik,
menonaktifkan client yang expired/over-kuota, dan mencatat pelanggaran limit IP
ke log yang dibaca fail2ban.

---

## Instalasi di VPS (Debian / Ubuntu)

Butuh VPS Debian 11/12 atau Ubuntu 20.04/22.04/24.04, akses **root**.

```bash
# 1. Ambil kode ke VPS
git clone https://github.com/krisna112/xray-core-server.git /root/xray-core-server
cd /root/xray-core-server

# 2. Jalankan installer sebagai root
sudo bash install.sh
```

> Simpan folder clone `/root/xray-core-server` — folder inilah yang dipakai untuk
> **update** nanti (`git pull`). Jangan dihapus setelah instalasi.

Installer akan:

1. memasang dependensi (`python3-venv`, `curl`, dll.);
2. memasang **Xray-core** via skrip resmi XTLS (dilewati bila sudah ada);
3. menyalin aplikasi ke `/opt/xray-manager` + membuat virtualenv;
4. memasang CLI `xm` ke `/usr/local/bin/xm`;
5. menanyakan **domain/IP, port panel, username & password admin**;
6. membuat service systemd `xray-manager` (auto-start saat boot);
7. opsional memasang **fail2ban** untuk limit IP.

Setelah selesai:

```bash
xm status
```

Lalu buka **Web UI** di browser: `http://IP-VPS:2053` (atau port yang Anda pilih),
login dengan username/password admin yang tadi diisi.

### Buka port firewall

Buka port panel API dan port inbound yang Anda pakai:

```bash
ufw allow 2053/tcp          # port panel API (sesuaikan)
ufw allow 8443/tcp          # contoh port inbound VLESS
```

---

## Update di VPS (`git pull` + restart)

Cukup tarik kode terbaru lalu jalankan updater — **config, database, inbound, dan
client Anda tetap aman** (tidak ditimpa), hanya kode aplikasi yang diperbarui:

```bash
cd /root/xray-core-server     # folder hasil git clone saat instalasi
sudo bash update.sh
```

`update.sh` otomatis melakukan: `git pull` → salin kode ke `/opt/xray-manager`
→ perbarui dependensi Python, CLI `xm`, dan unit systemd → **restart panel**
(`xray-manager`) → **rakit ulang config Xray & restart core** (`xm apply`).

Bila lebih suka manual:

```bash
cd /root/xray-core-server
git pull                                   # tarik update dari GitHub
sudo rm -rf /opt/xray-manager/xraym
sudo cp -r xraym /opt/xray-manager/        # salin kode terbaru
sudo systemctl restart xray-manager        # restart panel
sudo xm apply                              # rakit ulang config Xray & restart core
```

> **Catatan:** installer tidak menimpa `/etc/xray-manager/config.json` maupun
> database bila sudah ada, jadi `sudo bash install.sh` juga aman untuk update —
> tetapi `update.sh` lebih ringkas (tanpa prompt SSL/fail2ban). Bila ada konflik
> `git pull` karena file yang berubah lokal, jalankan `git stash` dulu atau
> `git reset --hard origin/main` (menghapus perubahan lokal).

---

## Web UI

Dashboard bawaan disajikan langsung oleh service (satu file, tanpa build Node) di
alamat panel — sama seperti port/base_path API:

```
http://IP-VPS:2053            # atau https + base_path bila diatur
```

Fitur Web UI (mirip 3x-ui, versi ringkas):

- **Dashboard** — status Xray, jumlah inbound/client, client online, CPU, memori, uptime, dan daftar client yang akan segera berakhir.
- **Inbounds** — buat inbound (pilih protokol, port, transport, security, path/host, **pilih sertifikat TLS dari dropdown**), aktif/nonaktif, reset trafik, hapus. Panel **auto-refresh** (Manual/5/10/30/60 dtk) — berhenti saat tab tak aktif.
- **Clients** — tambah client (kuota, expiry hari, limit IP), edit/perpanjang, aktif/nonaktif, reset trafik, hapus, dan **Share link + QR** sekali klik.
- **Pengaturan** (bertab ala 3x-ui):
  - **General** — domain share link, **Listen IP & port panel**, **URI path (base path)**, **durasi sesi login**, **Panel HTTPS** (pilih domain sertifikat → panel disajikan via HTTPS), interval job & limit IP, profil realtime. (Listen/port/URI/HTTPS berlaku setelah `systemctl restart xray-manager`.)
  - **Tanggal & Waktu** — jam server (live) + zona waktu tampilan tanggal.
  - **Notifikasi** — bot **Telegram** (token, chat ID, tombol tes) untuk pemberitahuan saat client dinonaktifkan otomatis + webhook sinkronisasi ke web API.
  - **Sertifikat** — daftar sertifikat TLS: tanggal kedaluwarsa (+ sisa hari), **Public Key Path & Private Key Path**, inbound yang memakainya, dan status **auto-renew** (acme.sh cron + cek harian panel; xray otomatis di-restart & izin dibenahi).

> **Share link otomatis pakai URL SSL.** Untuk inbound TLS, link/QR memakai
> **domain sertifikat + port inbound + path** (mis.
> `vless://…@vpn.domain.com:443?type=ws&path=/ws&security=tls…`). Untuk REALITY,
> link memakai `domain` global (SNI REALITY sengaja dibuat menyamar).

Login memakai session cookie (username/password admin). Untuk akses server-to-server
dari web member, tetap gunakan **API token** (`xm token create`).

---

## Pemakaian CLI (`xm`)

### Membuat inbound

```bash
# VLESS + REALITY (paling direkomendasikan, tanpa perlu domain/sertifikat)
xm inbound add --protocol vless --port 8443 \
   --network tcp --security reality --dest yahoo.com:443

# VMess + WebSocket (cocok di belakang CDN)
xm inbound add --protocol vmess --port 8080 --network ws --path /vmessws --host cdn.domain.com

# Trojan + TLS — cara mudah: pakai sertifikat hasil ssl.sh (lihat bagian SSL)
xm inbound add --protocol trojan --port 443 --network tcp --security tls \
   --cert-domain vpn.domain.com
#   (--cert-domain otomatis mengisi --cert, --key, dan --sni)

# atau tunjuk file sertifikat manual:
xm inbound add --protocol trojan --port 443 --network tcp --security tls \
   --sni vpn.domain.com \
   --cert /etc/letsencrypt/live/vpn.domain.com/fullchain.pem \
   --key  /etc/letsencrypt/live/vpn.domain.com/privkey.pem

# Shadowsocks 2022
xm inbound add --protocol shadowsocks --port 8388 --method 2022-blake3-aes-128-gcm

# WireGuard
xm inbound add --protocol wireguard --port 51820

# Hysteria2 (QUIC/UDP) — paling ringan & mulus untuk video/voice call.
# Wajib TLS: pakai sertifikat dari ssl.sh (lihat bagian SSL).
xm inbound add --protocol hysteria --port 443 --cert-domain vpn.domain.com

# gRPC / HTTPUpgrade / XHTTP tinggal ganti --network grpc|httpupgrade|xhttp

xm inbound list
xm inbound show 1        # detail (JSON)
xm inbound disable 1     # nonaktifkan sementara
xm inbound reset-traffic 1
```

Saat membuat inbound REALITY, `publicKey` & `shortId` ditampilkan (dan sudah
otomatis dimasukkan ke share link tiap client).

Untuk inbound yang tidak tercakup template (fallbacks, Hysteria2 core kustom, dll.):

```bash
xm inbound add-raw examples/inbound-raw-fallback.json --remark "vless 443 + fallback"
```

### Membuat & mengelola client

```bash
# Client 30 hari, kuota 50 GB, maksimal 2 IP, sekalian cetak QR di terminal
xm client add --inbound 1 --email budi --days 30 --gb 50 --limit-ip 2 --qr

# Expired pada tanggal tertentu
xm client add --inbound 1 --email siti --expire 2026-12-31

# Kuota mulai berjalan saat pertama kali dipakai (bukan saat dibuat)
xm client add --inbound 1 --email demo --days 3 --start-on-use

xm client list
xm client list --inbound 1
xm client link budi --qr          # share link + QR
xm client update budi --add-days 30          # perpanjang 30 hari
xm client update budi --gb 100 --limit-ip 3  # ubah kuota / limit IP
xm client reset-traffic budi
xm client disable budi
xm client ips budi                # IP yang sedang dipakai
xm client del budi
```

**UUID/password otomatis dibuat** bila tidak diisi. Client yang expired atau
melampaui kuota otomatis hilang dari config Xray pada siklus job berikutnya
(≤ `job_interval` detik) — tanpa perlu intervensi manual.

### Outbound, routing, load balancer

```bash
# WARP (isi private key WARP Anda di file JSON dulu)
xm outbound add examples/outbound-warp.json
# NordVPN (SOCKS)
xm outbound add examples/outbound-nordvpn.json
xm outbound list

# Routing: arahkan Netflix/OpenAI lewat WARP
xm route add --file examples/route-warp-streaming.json --remark "streaming via warp"
xm route list

# Load balancer round-robin antar outbound
xm balancer add examples/balancer.json
```

### Token API & login panel

```bash
xm token create web-oceansharknet   # cetak token SEKALI — simpan!
xm token list
xm user set-password --username admin --password 'baru123'
xm settings show
xm settings set domain vpn.domain.com
```

---

## HTTP API (kompatibel 3x-ui)

Service mendengarkan di `http://IP:<port>` (default `2053`). Semua respons:

```json
{ "success": true, "msg": "...", "obj": ... }
```

Autentikasi salah satu:

- **Bearer token / X-API-KEY** (dibuat lewat `xm token create`) — untuk server-to-server.
- **Session cookie** via `POST /login` `{ "username", "password" }`.

### Endpoint utama

| Method | Path | Fungsi |
|---|---|---|
| POST | `/login` | login → set cookie session |
| GET  | `/panel/api/server/status` | status server & xray |
| GET  | `/panel/api/inbounds/list` | daftar inbound + client |
| GET  | `/panel/api/inbounds/get/{id}` | detail satu inbound |
| POST | `/panel/api/inbounds/add` | tambah inbound (template *atau* JSON xray mentah) |
| POST | `/panel/api/inbounds/update/{id}` | ubah inbound |
| POST | `/panel/api/inbounds/del/{id}` | hapus inbound |
| POST | `/panel/api/inbounds/resetTraffic/{id}` | reset trafik inbound |
| POST | `/panel/api/inbounds/onlines` | daftar email online |
| POST | `/panel/api/inbounds/updateClient/{secret}` | update client by UUID/password (gaya 3x-ui) |
| GET  | `/panel/api/clients/list` | daftar semua client |
| GET  | `/panel/api/clients/get/{email}` | detail client |
| GET  | `/panel/api/clients/traffic/{email}` | trafik client |
| POST | `/panel/api/clients/add` | tambah client `{client:{...}, inboundIds:[id]}` |
| POST | `/panel/api/clients/update/{email}` | ubah client |
| POST | `/panel/api/clients/del/{email}` | hapus client |
| POST | `/panel/api/clients/resetTraffic/{email}` | reset trafik client |
| GET  | `/panel/api/clients/ips/{email}` | IP yang dipakai client |
| POST | `/panel/api/clients/clearips/{email}` | hapus catatan IP |
| GET  | `/panel/api/clients/link/{email}` | share link |
| GET  | `/panel/api/clients/qr/{email}` | QR code (SVG) |
| GET  | `/panel/api/settings` | baca setelan publik (dipakai Web UI) |
| POST | `/panel/api/settings/update` | ubah domain/webhook/interval |
| GET  | `/panel/api/certs` | daftar sertifikat TLS + kedaluwarsa |
| GET  | `/panel/api/sync/snapshot` | **snapshot penuh** (inbound + client + trafik + online) |

Bentuk field (`email`, `up`, `down`, `total`, `expiryTime`, `limitIp`, `totalGB`,
`inboundIds`, `traffic.up/down/usage`) mengikuti 3x-ui, jadi `PanelAPI.php`
(`addClient`, `updateClient`, `getClientTraffics`, `getInbounds`, dll.) bekerja
apa adanya.

### Contoh cepat

```bash
TOKEN="xm_...."             # dari: xm token create
BASE="http://IP-VPS:2053"

# daftar client
curl -s "$BASE/panel/api/clients/list" -H "X-API-KEY: $TOKEN"

# tambah client dari web (gaya PanelAPI::addClient)
curl -s "$BASE/panel/api/clients/add" -H "X-API-KEY: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"client":{"email":"member01","totalGB":53687091200,"expiryTime":1767139199000,"limitIp":2},"inboundIds":[1]}'

# tarik snapshot untuk cron sinkronisasi web
curl -s "$BASE/panel/api/sync/snapshot" -H "X-API-KEY: $TOKEN"
```

---

## Integrasi dengan Api-Web-Oceansharknet-Members

`PanelAPI.php` sudah memakai path `/panel/api/...`. Cukup daftarkan server ini
sebagai node dengan kolom seperti biasa dan gunakan **API token** sebagai
`apiToken` (konstruktor `PanelAPI` menerima Bearer token — divalidasi lewat
`GET /panel/api/server/status`):

```php
// contoh
$panel = new PanelAPI('http://IP-VPS:2053', '', $serverId, 'xm_TOKEN_ANDA');
$panel->login('', '');            // token → validasi bearer, tidak perlu user/pass
$panel->addClient(1, [
    'email'      => 'member01',
    'id'         => $uuid,            // vless/vmess
    'totalGB'    => 50 * 1024**3,
    'expiryTime' => $expiryMs,        // epoch milidetik
    'limitIp'    => 2,
]);
$traffic = $panel->getClientTraffics('member01');
```

### Dua arah sinkronisasi

**a. Web → VPS (kelola client).** Web memanggil `clients/add`, `clients/update`,
`clients/del`, `inbounds/updateClient/{secret}` — persis alur `PanelAPI.php` saat ini.

**b. VPS → Web (sinkron expiry & usage).** Dua opsi, bisa dipakai bersama:

- **Pull (disarankan, tanpa ubah VPS):** cron di web memanggil
  `GET /panel/api/sync/snapshot` lalu memperbarui tabel `clients`
  (`total_usage_bytes`, `expiry_date`, dsb.) — sejalan dengan `UsageSync.php`.
- **Push webhook:** set di VPS agar mengirim event ke endpoint web Anda saat ada
  client dinonaktifkan otomatis (expired/kuota):

  ```bash
  xm settings set webhook_url  https://web-anda.com/api/panel_event.php
  xm settings set webhook_api_key  RAHASIA_SAMA_DENGAN_WEB
  xm settings set sync_push_interval 300   # (opsional) push snapshot tiap 5 menit; 0=nonaktif
  systemctl restart xray-manager
  ```

  Payload event dikirim `POST` JSON dengan header `X-API-KEY`:

  ```json
  { "event": "client_disabled", "email": "member01", "reason": "quota",
    "up": 1, "down": 2, "totalGB": 5, "expiryTime": 1767139199000 }
  ```

  Endpoint `sync_expired_date.php` Anda sudah memvalidasi `X-API-KEY` — buat file
  serupa (mis. `panel_event.php`) yang menerima payload di atas untuk memperbarui
  status member secara realtime.

---

## SSL / TLS (Cloudflare)

Sertifikat TLS diterbitkan lewat **`ssl.sh`** yang memakai
[`acme.sh`](https://github.com/acmesh-official/acme.sh) dengan **Cloudflare DNS
(DNS-01)** — pakai **email + Global API Key** Cloudflare. Metode DNS ini:

- **tidak butuh port 80/443 terbuka** saat penerbitan;
- **mendukung wildcard** (`*.domain.com`);
- **auto-renew** otomatis (cron `acme.sh`) dan **me-restart Xray** setiap perpanjangan.

> Menemukan Global API Key: dashboard Cloudflare → **My Profile → API Tokens →
> Global API Key → View**. Domain harus sudah memakai nameserver Cloudflare.

### Terbitkan sertifikat

```bash
# Satu domain
sudo bash ssl.sh -d vpn.domain.com -e email@anda.com -k GLOBAL_API_KEY

# Domain apex + wildcard *.domain.com
sudo bash ssl.sh -d domain.com -w -e email@anda.com -k GLOBAL_API_KEY
```

Setelah terpasang di VPS, script ada di `/opt/xray-manager/ssl.sh`. Installer juga
menawarkan langkah ini secara interaktif di akhir instalasi.

Sertifikat disimpan di `/etc/xray-manager/certs/<domain>/{fullchain,privkey}.pem`.

### Pakai di inbound

```bash
xm cert list                     # daftar sertifikat + tanggal expired
xm cert path vpn.domain.com      # tampilkan path cert & key

# Buat inbound TLS — cukup sebut domainnya:
xm inbound add --protocol vless --port 443 --network ws --path /ws \
   --security tls --cert-domain vpn.domain.com
```

`--cert-domain` otomatis mengisi `--cert`, `--key`, `--sni`, dan menyalakan TLS.
Cocok untuk VLESS/VMess/Trojan di atas WS/gRPC/HTTPUpgrade/XHTTP + TLS.

> **REALITY tidak butuh sertifikat/domain** — jadi untuk setup tercepat & paling
> tahan blokir, pakai `--security reality` (lihat contoh VLESS di atas) tanpa perlu
> menjalankan `ssl.sh` sama sekali.

### Amankan panel dengan HTTPS

Sertifikat yang sama juga bisa dipakai untuk menyajikan **panel via HTTPS**.
Di **Pengaturan → General → Panel HTTPS**, pilih domain sertifikat (path
cert/key terisi otomatis), lalu **Simpan** dan `systemctl restart xray-manager`.
Panel kini diakses di `https://<domain>:<port><uri-path>`.

> **Penting:** kolom **Listen IP** adalah alamat *bind* socket — isi IP lokal
> (`0.0.0.0` = semua interface), **bukan domain**. Mengisi domain di Listen IP
> membuat panel gagal start (`could not bind on any address`) karena domain
> menunjuk ke IP publik ber-NAT yang tak ada di interface VPS. Domain cukup
> diatur lewat **Panel HTTPS** + kolom **Domain**. (Jika panel terlanjur gagal
> start karena ini, jalankan `xm settings set listen 0.0.0.0` lalu
> `systemctl restart xray-manager` — versi terbaru juga otomatis fallback ke
> `0.0.0.0`.)

---

## Fail2ban (enforcement limit IP)

Bila dipasang saat instalasi (atau manual dari folder `fail2ban/`), setiap client
yang melebihi `limit-ip`-nya akan dicatat ke `/var/log/xray-manager/ip-limit.log`
dalam format yang sama dengan 3x-ui:

```
2026/07/08 10:00:00 [LIMIT_IP] Email = member01 || SRC = 1.2.3.4
```

Jail `xray-ip-limit` akan mem-ban IP pelanggar (default `bantime 600`, ubah di
`/etc/fail2ban/jail.d/xray-ip-limit.conf`). Cek status:

```bash
fail2ban-client status xray-ip-limit
```

> Agar limit IP berfungsi, log akses Xray harus aktif (installer sudah
> mengaturnya di `/var/log/xray/access.log`).

---

## Operasional

```bash
systemctl status xray-manager        # status service manager
journalctl -u xray-manager -f        # log realtime
systemctl restart xray-manager       # restart setelah ubah settings
systemctl status xray                 # status xray core
cat /usr/local/etc/xray/config.json  # config xray hasil rakitan

xm apply                              # rakit ulang config & restart xray manual
```

File & lokasi penting:

| Lokasi | Isi |
|---|---|
| `/opt/xray-manager` | aplikasi + virtualenv |
| `/etc/xray-manager/config.json` | konfigurasi manager (port, kredensial, webhook) |
| `/etc/xray-manager/xray-manager.db` | database SQLite (inbound, client, dll.) |
| `/usr/local/etc/xray/config.json` | config Xray hasil rakitan (jangan diedit manual) |
| `/var/log/xray-manager/ip-limit.log` | log pelanggaran IP (fail2ban) |

### Backup

Cukup salin dua file:

```bash
cp /etc/xray-manager/config.json /etc/xray-manager/xray-manager.db /root/backup/
```

---

## Uninstall

```bash
sudo bash uninstall.sh
```

Menghapus service, CLI, dan (opsional) config/database. Xray-core dibiarkan
terpasang — hapus terpisah dengan `xray-uninstall` bila perlu.

---

## Konfigurasi (`/etc/xray-manager/config.json`)

| Key | Default | Keterangan |
|---|---|---|
| `port` | `2053` | port panel API |
| `base_path` | `""` | prefix path (mis. `/rahasia`) untuk menyamarkan panel |
| `domain` | `""` | domain/IP untuk share link & QR |
| `cert_dir` | `/etc/xray-manager/certs` | lokasi sertifikat TLS hasil `ssl.sh` |
| `realtime` | `true` | profil latensi-rendah UDP+TCP (video/voice call); `false` = throughput maks |
| `job_interval` | `20` | detik — polling stats + enforcement |
| `ip_limit_window` | `60` | detik — jendela hitung IP unik per client |
| `xray_api_port` | `10085` | port API stats Xray (localhost) |
| `webhook_url` | `""` | endpoint web untuk event push |
| `webhook_api_key` | `""` | dikirim sebagai `X-API-KEY` |
| `sync_push_interval` | `0` | detik; push snapshot berkala (0 = nonaktif) |
| `timezone` | `""` | zona waktu tampilan tanggal di panel (mis. `Asia/Jakarta`); kosong = waktu lokal browser |
| `tg_enable` | `false` | aktifkan notifikasi Telegram saat client dinonaktifkan otomatis |
| `tg_bot_token` | `""` | token bot Telegram |
| `tg_chat_id` | `""` | chat ID tujuan notifikasi Telegram |

Ubah lewat `xm settings set <key> <value>` lalu `systemctl restart xray-manager`
(atau langsung dari tab **Pengaturan** di Web UI).

---

## Struktur proyek

```
install.sh              installer VPS (Debian/Ubuntu)
update.sh               updater (git pull + salin kode + restart panel & Xray)
uninstall.sh            uninstaller
ssl.sh                  penerbit TLS via Cloudflare DNS (acme.sh) + auto-renew
requirements.txt        dependensi Python
bin/xm                  wrapper CLI
systemd/                unit service
fail2ban/               filter + jail limit IP
examples/               contoh outbound/routing/balancer/inbound-raw
xraym/
  settings.py           baca/tulis konfigurasi
  crypto.py             X25519 (REALITY/WireGuard), hash password, session
  db.py                 skema & helper SQLite
  templates.py          template settings + streamSettings per protokol
  config_builder.py     rakit config.json Xray lengkap dari DB
  xray_api.py           test/restart xray, statsquery
  manager.py            logika CRUD inbound & client
  links.py              share link (vless/vmess/trojan/ss/wg) + QR
  jobs.py               background: stats, expiry, limit IP, webhook
  server.py             HTTP API (FastAPI) kompatibel 3x-ui + penyaji Web UI
  cli.py                CLI `xm`
  web/index.html        Web UI (dashboard, satu file, tanpa build)
```

## Lisensi

MIT.
