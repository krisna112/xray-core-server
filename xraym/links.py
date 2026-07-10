"""Share link (vless://, vmess://, trojan://, ss://, wireguard conf) + QR code."""

import base64
import io
import json
import random
from urllib.parse import quote, urlencode

from . import crypto
from .db import jloads


def _address(settings, ib: dict) -> str:
    """Alamat untuk share link. Prioritas:
    1) share_addr eksplisit per-inbound,
    2) domain sertifikat (tlsSettings.serverName) bila security=TLS —
       inilah "URL SSL" yang dibuat via ssl.sh,
    3) domain global dari settings.
    Catatan: SNI REALITY adalah domain samaran (mis. yahoo.com), jadi TIDAK
    dipakai sebagai alamat sambung."""
    if ib.get("share_addr"):
        return ib["share_addr"]
    stream = jloads(ib.get("stream_settings"), {})
    if stream.get("security") == "tls":
        sni = stream.get("tlsSettings", {}).get("serverName")
        if sni:
            return sni
    return settings.domain or "ALAMAT_SERVER_BELUM_DISET"


def _tls_client(tls: dict) -> dict:
    """Baca field klien (uTLS/share-link) dari tlsSettings.
    Mendukung layout 3x-ui modern (sub-key `settings`) dan UI lawas (top-level)."""
    client = tls.get("settings")
    if isinstance(client, dict):
        return client
    # Fallback: field klien di top-level (UI lawas).
    out = {}
    for k in ("fingerprint", "allowInsecure", "pinnedPeerCertSha256",
              "verifyPeerCertByName", "echConfigList"):
        if k in tls:
            out[k] = tls[k]
    return out


def _reality_client(r: dict) -> dict:
    """Baca field klien REALITY dari realitySettings (sub-key atau top-level)."""
    client = r.get("settings")
    if isinstance(client, dict):
        return client
    out = {}
    for k in ("publicKey", "fingerprint", "serverName", "spiderX",
              "mldsa65Verify"):
        if k in r:
            out[k] = r[k]
    return out


def _stream_params(stream: dict) -> dict:
    """Ekstrak parameter transport+security untuk query string link."""
    p = {}
    net = stream.get("network", "tcp")
    p["type"] = net if net != "tcp" else "tcp"

    if net == "ws":
        ws = stream.get("wsSettings", {})
        p["path"] = ws.get("path", "/")
        if ws.get("host"):
            p["host"] = ws["host"]
    elif net == "grpc":
        grpc = stream.get("grpcSettings", {})
        p["serviceName"] = grpc.get("serviceName", "")
        # gRPC authority = Host header (untuk domain fronting via CDN)
        if grpc.get("authority"):
            p["host"] = grpc["authority"]
        p["mode"] = "gun"
    elif net == "httpupgrade":
        hu = stream.get("httpupgradeSettings", {})
        p["path"] = hu.get("path", "/")
        if hu.get("host"):
            p["host"] = hu["host"]
    elif net == "xhttp":
        xh = stream.get("xhttpSettings", {})
        p["path"] = xh.get("path", "/")
        if xh.get("host"):
            p["host"] = xh["host"]
        p["mode"] = xh.get("mode", "auto")
    elif net == "kcp":
        kcp = stream.get("kcpSettings", {})
        p["headerType"] = kcp.get("header", {}).get("type", "none")
        if kcp.get("seed"):
            p["seed"] = kcp["seed"]
    elif net == "tcp":
        tcp = stream.get("tcpSettings", {})
        if tcp.get("header", {}).get("type") == "http":
            p["headerType"] = "http"
            req = tcp["header"].get("request", {})
            paths = req.get("path") or ["/"]
            hosts = req.get("headers", {}).get("Host") or []
            p["path"] = paths[0]
            if hosts:
                p["host"] = hosts[0]

    sec = stream.get("security", "none")
    if sec == "tls":
        tls = stream.get("tlsSettings", {})
        client = _tls_client(tls)
        p["security"] = "tls"
        if tls.get("serverName"):
            p["sni"] = tls["serverName"]
        if client.get("fingerprint"):
            p["fp"] = client["fingerprint"]
        alpn = tls.get("alpn")
        if alpn:
            p["alpn"] = ",".join(alpn)
        # Domain fronting / cert pinning params
        if client.get("allowInsecure"):
            p["allowInsecure"] = "1"
        if client.get("verifyPeerCertByName"):
            p["vcn"] = client["verifyPeerCertByName"]
        pcs = client.get("pinnedPeerCertSha256")
        if pcs:
            p["pcs"] = pcs[0] if isinstance(pcs, list) else pcs
    elif sec == "reality":
        r = stream.get("realitySettings", {})
        client = _reality_client(r)
        p["security"] = "reality"
        # 3x-ui memilih SNI secara acak dari serverNames[] agar trafik
        # tidak mudah di-fingerprint ke satu SNI.
        names = [n for n in (r.get("serverNames") or []) if n]
        if names:
            p["sni"] = random.choice(names)
        p["fp"] = client.get("fingerprint", "chrome")
        p["pbk"] = client.get("publicKey", "")
        sids = [s for s in (r.get("shortIds") or []) if s]
        if sids:
            p["sid"] = sids[0]
        if client.get("spiderX"):
            p["spx"] = client["spiderX"]
    else:
        p["security"] = "none"

    return {k: v for k, v in p.items() if v != ""}


def share_link(settings, ib: dict, c: dict) -> str:
    """Bangun share link/config untuk satu client."""
    protocol = ib["protocol"]
    stream = jloads(ib.get("stream_settings"), {})
    ib_settings = jloads(ib.get("settings"), {})
    addr = _address(settings, ib)
    port = ib["port"]
    name = quote(f"{ib.get('remark') or ib.get('tag')}-{c['email']}")

    if protocol == "vless":
        params = _stream_params(stream)
        if c.get("flow"):
            params["flow"] = c["flow"]
        return f"vless://{c['uuid']}@{addr}:{port}?{urlencode(params)}#{name}"

    if protocol == "vmess":
        params = _stream_params(stream)
        net = stream.get("network", "tcp")
        obj = {
            "v": "2",
            "ps": f"{ib.get('remark') or ib.get('tag')}-{c['email']}",
            "add": addr,
            "port": str(port),
            "id": c["uuid"],
            "aid": "0",
            "scy": "auto",
            "net": net,
            "type": params.get("headerType", "none"),
            "host": params.get("host", ""),
            "path": params.get("path", params.get("serviceName", "")),
            "tls": params.get("security") if params.get("security") == "tls" else "",
            "sni": params.get("sni", ""),
            "fp": params.get("fp", ""),
            "alpn": params.get("alpn", ""),
            "allowInsecure": 1 if params.get("allowInsecure") else "",
        }
        raw = json.dumps(obj, separators=(",", ":"))
        return "vmess://" + base64.b64encode(raw.encode()).decode()

    if protocol == "trojan":
        params = _stream_params(stream)
        return f"trojan://{quote(c['password'])}@{addr}:{port}?{urlencode(params)}#{name}"

    if protocol == "shadowsocks":
        method = ib_settings.get("method", "chacha20-ietf-poly1305")
        if method.startswith("2022-blake3-"):
            # SS2022: password = serverKey:userKey
            userinfo = f"{method}:{ib_settings.get('password', '')}:{c['password']}"
            userinfo = quote(userinfo, safe=":")
            return f"ss://{userinfo}@{addr}:{port}#{name}"
        userinfo = base64.urlsafe_b64encode(
            f"{method}:{c['password']}".encode()).decode().rstrip("=")
        return f"ss://{userinfo}@{addr}:{port}#{name}"

    if protocol == "wireguard":
        extra = jloads(c.get("extra"), {})
        server_pub = crypto.wireguard_pubkey(ib_settings.get("secretKey", ""))
        address = ", ".join(extra.get("allowedIPs", ["10.66.66.2/32"]))
        return (
            "[Interface]\n"
            f"PrivateKey = {extra.get('privateKey', '')}\n"
            f"Address = {address}\n"
            "DNS = 1.1.1.1\n"
            f"MTU = {ib_settings.get('mtu', 1420)}\n\n"
            "[Peer]\n"
            f"PublicKey = {server_pub}\n"
            "AllowedIPs = 0.0.0.0/0, ::/0\n"
            f"Endpoint = {addr}:{port}\n"
            "PersistentKeepalive = 25\n"
        )

    if protocol == "hysteria":
        tls = stream.get("tlsSettings", {})
        hy = stream.get("hysteriaSettings", {})
        client = _tls_client(tls)
        params = {"security": "tls", "alpn": "h3",
                  "sni": tls.get("serverName") or addr}
        if client.get("fingerprint"):
            params["fp"] = client["fingerprint"]
        if client.get("allowInsecure"):
            params["insecure"] = "1"
        obfs = hy.get("obfs") or {}
        if obfs.get("password"):
            params["obfs"] = "salamander"
            params["obfs-password"] = obfs["password"]
        return f"hysteria2://{quote(c['password'])}@{addr}:{port}?{urlencode(params)}#{name}"

    if protocol in ("socks", "mixed"):
        return f"socks://{quote(c['email'])}:{quote(c['password'])}@{addr}:{port}#{name}"
    if protocol == "http":
        return f"http://{quote(c['email'])}:{quote(c['password'])}@{addr}:{port}#{name}"

    return ""


# ---------------------------------------------------------------------------
# QR code
# ---------------------------------------------------------------------------

def qr_svg(text: str) -> str:
    """QR sebagai string SVG (tanpa perlu Pillow)."""
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage,
                      box_size=12, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode()


def qr_terminal(text: str) -> str:
    """QR sebagai ASCII untuk dicetak di terminal."""
    import qrcode

    qr = qrcode.QRCode(border=1)
    qr.add_data(text)
    qr.make(fit=True)
    buf = io.StringIO()
    qr.print_ascii(out=buf, invert=True)
    return buf.getvalue()
