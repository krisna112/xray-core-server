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
            "minVersion": "1.2",
            "alpn": opts.get("alpn") or ["h2", "http/1.1"],
            "certificates": [{
                "certificateFile": opts.get("cert_file", ""),
                "keyFile": opts.get("key_file", ""),
                "ocspStapling": 3600,
            }],
            # Metadata untuk share link (dibuang saat menulis config xray):
            "fingerprint": opts.get("fp", "chrome"),
        }
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
            # Metadata untuk share link (dibuang saat menulis config xray):
            "publicKey": pub or "",
            "fingerprint": opts.get("fp", "chrome"),
            "spiderX": "/",
        }
    elif security != "none":
        raise ValueError(f"Security tidak dikenal: {security}")

    return stream
