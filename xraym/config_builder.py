"""Merakit config.json Xray lengkap dari database."""

import copy
import json
import time

from .db import DB, jloads

# Field server-side yang sah untuk ditulis ke config xray
# (field metadata share-link seperti publicKey/fingerprint dibuang).
_REALITY_KEYS = {
    "show", "dest", "target", "xver", "serverNames", "privateKey",
    "minClientVer", "maxClientVer", "maxTimeDiff", "shortIds",
    "limitFallbackUpload", "limitFallbackDownload", "mldsa65Seed",
}
_TLS_KEYS = {
    "serverName", "rejectUnknownSni", "alpn", "minVersion", "maxVersion",
    "cipherSuites", "certificates", "disableSystemRoot",
    "enableSessionResumption", "verifyPeerCertInNames",
}


def client_is_active(c: dict, now_ms: int) -> bool:
    """Client masuk config hanya bila enable, belum expired, dan belum
    melampaui kuota. expiry_time negatif = countdown dimulai saat pertama
    dipakai (belum aktif dihitung expired)."""
    if not c["enable"]:
        return False
    exp = c["expiry_time"]
    if exp > 0 and exp <= now_ms:
        return False
    if c["total_gb"] > 0 and (c["up"] + c["down"]) >= c["total_gb"]:
        return False
    return True


def _client_entry(protocol: str, c: dict, ss_method: str = "") -> dict:
    email = c["email"]
    if protocol == "vless":
        e = {"id": c["uuid"], "email": email, "level": 0}
        if c["flow"]:
            e["flow"] = c["flow"]
        return e
    if protocol == "vmess":
        return {"id": c["uuid"], "email": email, "level": 0}
    if protocol == "trojan":
        return {"password": c["password"], "email": email, "level": 0}
    if protocol == "shadowsocks":
        e = {"password": c["password"], "email": email, "level": 0}
        if ss_method.startswith("2022-blake3-"):
            e["method"] = ss_method
        return e
    if protocol == "hysteria":
        # Hysteria2: auth = password client, email untuk atribusi stats/kuota
        return {"auth": c["password"], "email": email}
    if protocol in ("socks", "mixed"):
        return {"user": email, "pass": c["password"]}
    if protocol == "http":
        return {"user": email, "pass": c["password"]}
    return {}


def _sanitize_stream(stream: dict) -> dict:
    s = copy.deepcopy(stream)
    if isinstance(s.get("realitySettings"), dict):
        s["realitySettings"] = {k: v for k, v in s["realitySettings"].items()
                                if k in _REALITY_KEYS}
    if isinstance(s.get("tlsSettings"), dict):
        s["tlsSettings"] = {k: v for k, v in s["tlsSettings"].items()
                            if k in _TLS_KEYS}
    return s


def build_inbound(ib: dict, clients: list, now_ms: int) -> dict:
    protocol = ib["protocol"]
    settings = jloads(ib["settings"], {})
    stream = jloads(ib["stream_settings"], {})
    sniffing = jloads(ib["sniffing"], None) if ib["sniffing"] else None

    active = [c for c in clients if client_is_active(c, now_ms)]

    if protocol in ("vless", "vmess", "trojan", "shadowsocks", "hysteria"):
        method = settings.get("method", "")
        settings["clients"] = [_client_entry(protocol, c, method) for c in active]
    elif protocol in ("socks", "mixed", "http"):
        settings["accounts"] = [_client_entry(protocol, c) for c in active]
        if protocol in ("socks", "mixed"):
            settings["auth"] = "password" if settings["accounts"] else settings.get("auth", "noauth")
    elif protocol == "wireguard":
        peers = []
        for c in active:
            extra = jloads(c["extra"], {})
            if extra.get("publicKey"):
                peers.append({
                    "publicKey": extra["publicKey"],
                    "allowedIPs": extra.get("allowedIPs", []),
                })
        settings["peers"] = peers

    out = {
        "tag": ib["tag"],
        "listen": ib["listen"] or "0.0.0.0",
        "port": ib["port"],
        "protocol": "socks" if protocol == "mixed" else protocol,
        "settings": settings,
    }
    if stream and protocol != "wireguard":
        out["streamSettings"] = _sanitize_stream(stream)
    if sniffing and protocol not in ("wireguard", "dokodemo-door"):
        out["sniffing"] = sniffing
    return out


def _policy(settings) -> dict:
    """Policy level-0. Mode realtime menekan latensi & memori untuk trafik
    real-time (video/voice call, game) di UDP maupun TCP:
      - bufferSize kecil  → RAM ringan + antrean pendek (latensi rendah),
      - connIdle pendek   → koneksi mati cepat dibersihkan,
      - uplinkOnly/downlinkOnly=1 → half-close TCP cepat ditutup,
      - handshake pendek  → gagal-cepat, tak menahan resource.
    Statistik per-user tetap menyala agar kuota tetap dihitung."""
    level = {
        "statsUserUplink": True,
        "statsUserDownlink": True,
    }
    if settings.get("realtime", True):
        level.update({
            "handshake": 3,
            "connIdle": 120,
            "uplinkOnly": 1,
            "downlinkOnly": 1,
            "bufferSize": 4,   # KB per koneksi — cukup untuk media call, hemat RAM
        })
    else:
        level.update({"handshake": 4, "connIdle": 300})
    return {
        "levels": {"0": level},
        "system": {
            "statsInboundUplink": True,
            "statsInboundDownlink": True,
            "statsOutboundUplink": True,
            "statsOutboundDownlink": True,
        },
    }


def build(db: DB, settings) -> dict:
    """Config Xray lengkap: log, api, stats, policy, inbounds, outbounds, routing."""
    now_ms = int(time.time() * 1000)

    config = {
        "log": {
            "access": settings.xray_access_log,
            "error": settings.xray_error_log,
            "loglevel": settings.xray_loglevel,
        },
        "api": {"tag": "api", "services": ["HandlerService", "LoggerService", "StatsService"]},
        "stats": {},
        "policy": _policy(settings),
        "inbounds": [{
            "tag": "api-in",
            "listen": "127.0.0.1",
            "port": settings.xray_api_port,
            "protocol": "dokodemo-door",
            "settings": {"address": "127.0.0.1"},
        }],
        "outbounds": [],
        "routing": {"domainStrategy": "AsIs", "rules": [
            {"type": "field", "inboundTag": ["api-in"], "outboundTag": "api"},
        ]},
    }

    # Inbounds aktif (dan belum expired / over-quota di level inbound)
    for ib in db.query("SELECT * FROM inbounds ORDER BY id"):
        if not ib["enable"]:
            continue
        if ib["expiry_time"] > 0 and ib["expiry_time"] <= now_ms:
            continue
        if ib["total"] > 0 and (ib["up"] + ib["down"]) >= ib["total"]:
            continue
        clients = db.query("SELECT * FROM clients WHERE inbound_id=?", (ib["id"],))
        config["inbounds"].append(build_inbound(ib, clients, now_ms))

    # Outbounds: custom dari DB, lalu default direct + blocked
    tags = set()
    for ob in db.query("SELECT * FROM outbounds WHERE enable=1 ORDER BY id"):
        try:
            conf = json.loads(ob["config"])
        except ValueError:
            continue
        if not isinstance(conf, dict) or not conf.get("protocol"):
            continue  # baris tanpa protokol (mis. sisa data lama) — lewati
        conf["tag"] = ob["tag"]
        config["outbounds"].append(conf)
        tags.add(ob["tag"])
    if "direct" not in tags:
        config["outbounds"].append({"tag": "direct", "protocol": "freedom", "settings": {}})
    if "blocked" not in tags:
        config["outbounds"].append({"tag": "blocked", "protocol": "blackhole", "settings": {}})

    # Pastikan outbound pertama (default) adalah 'direct' kecuali user
    # menandai outbound lain dengan tag 'first'
    config["outbounds"].sort(key=lambda o: 0 if o.get("tag") == "first"
                             else (1 if o.get("tag") == "direct" else 2))

    # Routing rules custom
    for r in db.query("SELECT * FROM routing_rules WHERE enable=1 ORDER BY sort, id"):
        rule = jloads(r["rule"], None)
        if isinstance(rule, dict):
            rule.setdefault("type", "field")
            config["routing"]["rules"].append(rule)

    # Balancers
    balancers = [jloads(b["config"], None) for b in db.query("SELECT * FROM balancers")]
    balancers = [b for b in balancers if isinstance(b, dict)]
    if balancers:
        config["routing"]["balancers"] = balancers

    return config
