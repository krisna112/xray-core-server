"""Template pembuat inbound: settings protokol + streamSettings.

Protokol yang didukung penuh oleh Xray-core resmi (v26.3.27):
  vless, vmess, trojan, shadowsocks, wireguard, hysteria (Hysteria2),
  socks, http, dokodemo-door
"mixed" dipetakan ke socks (Xray socks inbound juga menerima koneksi HTTP
pada versi baru). Hysteria2 = protokol "hysteria" + streamSettings network
"hysteria" + hysteriaSettings.version=2 (native sejak Xray v26.x). TUN bukan
protokol Xray-core — gunakan `inbound add-raw` bila core kustom Anda mendukungnya.

Transport: tcp (raw), kcp (mKCP), ws (WebSocket), grpc, httpupgrade, xhttp,
           hysteria (QUIC/UDP — untuk protokol hysteria)
Security : none, tls, reality
"""

from . import crypto

PROTOCOLS = [
    "vless", "vmess", "trojan", "shadowsocks", "wireguard", "hysteria",
    "socks", "http", "dokodemo-door",
]
NETWORKS = ["tcp", "raw", "kcp", "ws", "grpc", "httpupgrade", "xhttp"]
SECURITIES = ["none", "tls", "reality"]

# Opsi lengkap untuk dropdown form (sesuai Xray-core v26.x)
SS_METHODS = [
    "2022-blake3-aes-256-gcm", "2022-blake3-aes-128-gcm",
    "2022-blake3-chacha20-poly1305",
    "aes-256-gcm", "aes-128-gcm",
    "chacha20-ietf-poly1305", "xchacha20-ietf-poly1305",
    "none",
]
FINGERPRINTS = [
    "chrome", "firefox", "safari", "ios", "android", "edge",
    "360", "qq", "random", "randomized",
]
ALPN_OPTIONS = ["h3", "h2", "http/1.1"]
XHTTP_MODES = ["auto", "packet-up", "stream-up", "stream-one"]
TCP_HEADER_TYPES = ["none", "http"]
KCP_HEADER_TYPES = [
    "none", "srtp", "utp", "wechat-video", "dtls", "wireguard", "dns",
]
FLOWS = ["", "xtls-rprx-vision", "xtls-rprx-vision-udp443"]
VMESS_SECURITIES = ["auto", "aes-128-gcm", "chacha20-poly1305", "none", "zero"]

DEFAULT_SNIFFING = {
    "enabled": True,
    "destOverride": ["http", "tls", "quic", "fakedns"],
    "metadataOnly": False,
    "routeOnly": False,
}


def build_settings(protocol: str, opts: dict) -> dict:
    """Settings protokol level-inbound (daftar client dirakit terpisah
    oleh config_builder dari tabel clients)."""
    p = protocol
    if p == "vless":
        return {"clients": [], "decryption": "none", "fallbacks": opts.get("fallbacks", [])}
    if p == "vmess":
        return {"clients": []}
    if p == "trojan":
        return {"clients": [], "fallbacks": opts.get("fallbacks", [])}
    if p == "shadowsocks":
        method = opts.get("method") or "chacha20-ietf-poly1305"
        s = {"method": method, "clients": [], "network": "tcp,udp"}
        if method.startswith("2022-blake3-"):
            s["password"] = opts.get("server_key") or crypto.gen_ss2022_key(method)
        return s
    if p == "hysteria":
        # Hysteria2: settings.version=2, clients berisi {auth,email}
        return {"version": 2, "clients": []}
    if p == "wireguard":
        priv = opts.get("secret_key")
        if not priv:
            priv, _pub = crypto.wireguard_keypair()
        return {
            "secretKey": priv,
            "mtu": int(opts.get("mtu", 1420)),
            "peers": [],  # diisi dari clients
        }
    if p in ("socks", "mixed"):
        return {"auth": "password", "accounts": [], "udp": True,
                "ip": opts.get("udp_ip", "127.0.0.1")}
    if p == "http":
        return {"accounts": []}
    if p in ("dokodemo-door", "tunnel"):
        return {
            "address": opts.get("dest_address", "127.0.0.1"),
            "port": int(opts.get("dest_port", 80)),
            "network": opts.get("dest_network", "tcp,udp"),
            "followRedirect": bool(opts.get("follow_redirect", False)),
        }
    raise ValueError(f"Protokol tidak dikenal: {protocol}")


def build_stream(network: str = "tcp", security: str = "none", opts: dict = None) -> dict:
    """Rakit streamSettings. opts:
    path, host, sni, cert_file, key_file, alpn, fp,
    dest (reality), server_names, private_key/public_key/short_ids (reality),
    header_type & seed (kcp), mode (xhttp)
    """
    opts = opts or {}
    net = "tcp" if network == "raw" else network
    stream = {"network": net, "security": security}

    if net == "tcp":
        tcp = {"header": {"type": opts.get("header_type", "none")}}
        if tcp["header"]["type"] == "http":
            tcp["header"]["request"] = {
                "version": "1.1", "method": "GET",
                "path": [opts.get("path") or "/"],
                "headers": {"Host": [opts.get("host") or ""],
                            "Connection": ["keep-alive"],
                            "Accept-Encoding": ["gzip, deflate"]},
            }
        stream["tcpSettings"] = tcp
    elif net == "kcp":
        stream["kcpSettings"] = {
            "mtu": 1350, "tti": 50, "uplinkCapacity": 5, "downlinkCapacity": 20,
            "congestion": False, "readBufferSize": 2, "writeBufferSize": 2,
            "header": {"type": opts.get("header_type", "none")},
            "seed": opts.get("seed") or crypto.gen_password(10),
        }
    elif net == "ws":
        stream["wsSettings"] = {"path": opts.get("path") or "/",
                                "host": opts.get("host") or ""}
    elif net == "grpc":
        stream["grpcSettings"] = {"serviceName": (opts.get("path") or "grpc").strip("/"),
                                  "multiMode": False}
    elif net == "httpupgrade":
        stream["httpupgradeSettings"] = {"path": opts.get("path") or "/",
                                         "host": opts.get("host") or ""}
    elif net == "xhttp":
        stream["xhttpSettings"] = {"path": opts.get("path") or "/",
                                   "host": opts.get("host") or "",
                                   "mode": opts.get("mode", "auto")}
    elif net == "hysteria":
        # Hysteria2 (QUIC/UDP). Latensi rendah untuk video call di jaringan
        # dengan packet loss; wajib TLS + ALPN h3.
        hy = {"version": 2,
              "udpIdleTimeout": int(opts.get("udp_idle", 60))}
        if opts.get("obfs_password"):
            hy["obfs"] = {"type": "salamander",
                          "password": opts["obfs_password"]}
        # brutal congestion control (bandwidth Mbps) — biarkan auto bila 0
        if opts.get("up_mbps") or opts.get("down_mbps"):
            hy["congestion"] = {
                "type": "bbr",
                "up_mbps": int(opts.get("up_mbps", 0)),
                "down_mbps": int(opts.get("down_mbps", 0)),
            }
        stream["hysteriaSettings"] = hy
        opts.setdefault("alpn", ["h3"])
    else:
        raise ValueError(f"Network tidak dikenal: {network}")

    if security == "tls":
        tls = {
            "serverName": opts.get("sni") or opts.get("host") or "",
            "minVersion": opts.get("min_version", "1.2"),
            "maxVersion": opts.get("max_version", "1.3"),
            "alpn": opts.get("alpn") or ["h2", "http/1.1"],
            "certificates": [{
                "certificateFile": opts.get("cert_file", ""),
                "keyFile": opts.get("key_file", ""),
                "ocspStapling": 3600,
            }],
        }
        # Field server-side opsional untuk domain fronting / hardening.
        # rejectUnknownSni = true → hanya terima SNI yang cocok serverName;
        #   ini mencegah klient membuktikan identitas via SNI palsu.
        if opts.get("reject_unknown_sni"):
            tls["rejectUnknownSni"] = True
        if opts.get("cipher_suites"):
            tls["cipherSuites"] = opts["cipher_suites"]
        if opts.get("disable_system_root"):
            tls["disableSystemRoot"] = True
        if opts.get("enable_session_resumption"):
            tls["enableSessionResumption"] = True
        # Field klien (uTLS/share-link) — ditempatkan di sub-key `settings`
        # (kompatibel 3x-ui). Dibuang oleh config_builder sebelum tulis ke xray.
        client = {"fingerprint": opts.get("fp", "chrome")}
        if opts.get("allow_insecure"):
            client["allowInsecure"] = True
        if opts.get("pinned_peer_cert_sha256"):
            client["pinnedPeerCertSha256"] = opts["pinned_peer_cert_sha256"]
        if opts.get("verify_peer_cert_by_name"):
            client["verifyPeerCertByName"] = opts["verify_peer_cert_by_name"]
        tls["settings"] = client
        stream["tlsSettings"] = tls
    elif security == "reality":
        priv = opts.get("private_key")
        pub = opts.get("public_key")
        if not priv:
            priv, pub = crypto.reality_keypair()
        dest = opts.get("dest") or "yahoo.com:443"
        sni = opts.get("sni") or dest.split(":")[0]
        server_names = opts.get("server_names") or [sni]
        stream["realitySettings"] = {
            "show": False,
            "dest": dest,
            "xver": 0,
            "serverNames": server_names,
            "privateKey": priv,
            "shortIds": opts.get("short_ids") or [crypto.gen_short_id(), ""],
            # Field klien (uTLS/share-link) — ditempatkan di sub-key `settings`
            # (kompatibel 3x-ui). Dibuang oleh config_builder sebelum tulis ke xray.
            "settings": {
                "publicKey": pub or "",
                "fingerprint": opts.get("fp", "chrome"),
                "serverName": "",
                "spiderX": opts.get("spider_x", "/"),
            },
        }
    elif security != "none":
        raise ValueError(f"Security tidak dikenal: {security}")

    return stream


# ---------------------------------------------------------------------------
# Normalisasi payload inbound "raw" (JSON standar Xray-core dari form UI)
# ---------------------------------------------------------------------------

def normalize_raw_inbound(protocol: str, settings, stream) -> tuple:
    """Lengkapi field wajib & generate kunci yang kosong agar config valid.

    Form UI mengirim JSON standar Xray-core apa adanya; fungsi ini memastikan:
      - VLESS: decryption 'none', clients[]
      - Shadowsocks: method default + server key (untuk 2022-blake3-*)
      - WireGuard: secretKey di-generate bila kosong
      - Hysteria2: version=2
      - Socks/HTTP: struktur accounts
      - REALITY: privateKey/publicKey & shortIds di-generate bila kosong
    Client per-user tetap dirakit terpisah oleh config_builder dari tabel clients.
    """
    protocol = (protocol or "").lower()
    settings = dict(settings or {})
    stream = dict(stream or {})

    if protocol == "vless":
        settings.setdefault("decryption", "none")
        settings.setdefault("clients", [])
        settings.setdefault("fallbacks", settings.get("fallbacks", []))
    elif protocol in ("vmess", "trojan"):
        settings.setdefault("clients", [])
    elif protocol == "shadowsocks":
        method = settings.get("method") or "chacha20-ietf-poly1305"
        settings["method"] = method
        if method.startswith("2022-blake3-") and not settings.get("password"):
            settings["password"] = crypto.gen_ss2022_key(method)
        settings.setdefault("network", "tcp,udp")
        settings.setdefault("clients", [])
    elif protocol == "hysteria":
        settings.setdefault("version", 2)
        settings.setdefault("clients", [])
    elif protocol == "wireguard":
        if not settings.get("secretKey"):
            priv, _pub = crypto.wireguard_keypair()
            settings["secretKey"] = priv
        settings.setdefault("mtu", 1420)
        settings.setdefault("peers", [])
    elif protocol == "socks":
        settings.setdefault("auth", "password")
        settings.setdefault("accounts", [])
        settings.setdefault("udp", True)
    elif protocol == "http":
        settings.setdefault("accounts", [])

    reality = stream.get("realitySettings")
    if isinstance(reality, dict):
        # Migrasi: field klien top-level (UI lawas) → sub-key `settings`.
        client = reality.get("settings")
        if not isinstance(client, dict):
            client = {}
        for k in ("publicKey", "fingerprint", "spiderX", "serverName",
                  "mldsa65Verify"):
            if k in reality and k not in client:
                client[k] = reality.pop(k)
        # Generate keypair bila perlu.
        if not reality.get("privateKey"):
            priv, pub = crypto.reality_keypair()
            reality["privateKey"] = priv
            client.setdefault("publicKey", pub)
        elif not client.get("publicKey"):
            try:
                client["publicKey"] = crypto.reality_pubkey(reality["privateKey"])
            except Exception:
                pass
        client.setdefault("fingerprint", "chrome")
        client.setdefault("spiderX", "/")
        if not reality.get("shortIds"):
            reality["shortIds"] = [crypto.gen_short_id(), ""]
        if not reality.get("serverNames"):
            dest = reality.get("dest") or reality.get("target") or ""
            sni = dest.split(":")[0] if dest else ""
            reality["serverNames"] = [sni] if sni else []
        reality["settings"] = client

    tls = stream.get("tlsSettings")
    if isinstance(tls, dict):
        # Migrasi: field klien top-level (UI lawas) → sub-key `settings`.
        client = tls.get("settings")
        if not isinstance(client, dict):
            client = {}
        for k in ("fingerprint", "allowInsecure", "pinnedPeerCertSha256",
                  "verifyPeerCertByName", "echConfigList"):
            if k in tls and k not in client:
                client[k] = tls.pop(k)
        client.setdefault("fingerprint", "chrome")
        tls["settings"] = client

    return settings, stream
