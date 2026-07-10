"""Logika bisnis: CRUD inbound & client, apply config, view API kompatibel 3x-ui."""

import json
import re
import time

from . import config_builder, crypto, templates, xray_api
from .db import DB, jloads, now_ms


class ManagerError(Exception):
    pass


# ---------------------------------------------------------------------------
# Apply config
# ---------------------------------------------------------------------------

def apply(db: DB, settings) -> tuple:
    """Rakit config dari DB lalu terapkan ke xray. (ok, pesan).

    Kegagalan level-xray (binary tak ada / restart gagal) dikembalikan sebagai
    (False, pesan), bukan exception — supaya CRUD DB tetap tersimpan dan bisa
    diterapkan ulang saat xray tersedia."""
    config = config_builder.build(db, settings)
    try:
        return xray_api.apply_config(settings, config)
    except xray_api.XrayError as e:
        return False, str(e)


def _apply_or_rollback(db: DB, settings, ib_id: int):
    """Terapkan config; bila xray gagal start (mis. port 443 sudah dipakai)
    dan xray memang terpasang, buang inbound baru ini dari DB agar konsisten
    dengan config live yang sudah dikembalikan apply_config. Xray tak dibiarkan
    mati. Di lingkungan tanpa xray (dev), inbound tetap disimpan."""
    ok, msg = apply(db, settings)
    if not ok and xray_api.installed(settings):
        db.execute("DELETE FROM clients WHERE inbound_id=?", (ib_id,))
        db.execute("DELETE FROM inbounds WHERE id=?", (ib_id,))
        raise ManagerError(msg)


def _ensure_port_free(db: DB, settings, port: int, protocol: str = "",
                      network: str = "", listen: str = ""):
    """Cegah inbound yang akan membuat xray gagal bind (lalu mati). Memeriksa:
    port ganda di DB, tabrakan dengan port Xray API internal, dan port yang
    sudah dipakai proses lain di server (mis. nginx di 443)."""
    if db.query_one("SELECT id FROM inbounds WHERE port=?", (port,)):
        raise ManagerError(f"Port {port} sudah dipakai inbound lain")
    try:
        api_port = int(settings.xray_api_port)
    except (TypeError, ValueError):
        api_port = 0
    if api_port and port == api_port:
        raise ManagerError(
            f"Port {port} dipakai Xray API internal — pilih port lain")
    udp = protocol in ("hysteria", "wireguard") or network in ("kcp", "quic", "hysteria")
    if not xray_api.port_available(port, udp=udp, listen=listen or "0.0.0.0"):
        raise ManagerError(
            f"Port {port} sedang dipakai proses lain di server "
            "(mis. web server / nginx). Hentikan layanan itu atau pilih port lain.")


# ---------------------------------------------------------------------------
# Inbound
# ---------------------------------------------------------------------------

def _unique_tag(db: DB, base: str) -> str:
    tag, i = base, 1
    while db.query_one("SELECT id FROM inbounds WHERE tag=?", (tag,)):
        i += 1
        tag = f"{base}-{i}"
    return tag


def add_inbound(db: DB, settings, protocol: str, port: int, remark: str = "",
                listen: str = "", network: str = "tcp", security: str = "none",
                opts: dict = None, tag: str = "", expiry_ms: int = 0,
                total_bytes: int = 0, share_addr: str = "",
                apply_now: bool = True) -> dict:
    opts = opts or {}
    protocol = protocol.lower()
    if protocol == "tunnel":
        protocol = "dokodemo-door"
    if protocol == "mixed":
        protocol = "socks"
    if protocol not in templates.PROTOCOLS:
        raise ManagerError(
            f"Protokol '{protocol}' tidak didukung Xray-core. "
            f"Pilihan: {', '.join(templates.PROTOCOLS)}. "
            "Untuk protokol core kustom gunakan add_inbound_raw / inbound add-raw.")

    _ensure_port_free(db, settings, port, protocol, network, listen)

    # Hysteria2 (QUIC/UDP) wajib TLS + ALPN h3; network dipaksa "hysteria".
    if protocol == "hysteria":
        network, security = "hysteria", "tls"
        opts.setdefault("alpn", ["h3"])
        if not opts.get("cert_file"):
            raise ManagerError(
                "Hysteria2 wajib TLS. Sertakan sertifikat: --cert-domain <domain> "
                "(atau --cert/--key).")

    ib_settings = templates.build_settings(protocol, opts)
    stream = {}
    if protocol not in ("wireguard", "dokodemo-door"):
        stream = templates.build_stream(network, security, opts)

    tag = tag or _unique_tag(db, f"in-{protocol}-{port}")
    sniffing = (opts.get("sniffing") if opts and "sniffing" in opts
                else templates.DEFAULT_SNIFFING)
    cur = db.execute(
        "INSERT INTO inbounds(tag,remark,enable,listen,port,protocol,settings,"
        "stream_settings,sniffing,total,expiry_time,share_addr,created_at) "
        "VALUES(?,?,1,?,?,?,?,?,?,?,?,?,?)",
        (tag, remark or tag, listen, port, protocol,
         json.dumps(ib_settings), json.dumps(stream),
         json.dumps(sniffing),
         total_bytes, expiry_ms, share_addr, now_ms()))
    row = db.query_one("SELECT * FROM inbounds WHERE id=?", (cur.lastrowid,))
    if apply_now:
        _apply_or_rollback(db, settings, row["id"])
    return row


def add_inbound_raw(db: DB, settings, raw: dict, remark: str = "",
                    share_addr: str = "", apply_now: bool = True) -> dict:
    """Terima JSON inbound xray mentah (passthrough). Client tetap bisa
    dikelola bila protokolnya termasuk yang dikenal."""
    port = int(raw.get("port", 0))
    protocol = raw.get("protocol", "")
    if not port or not protocol:
        raise ManagerError("JSON inbound harus punya 'port' dan 'protocol'")
    stream_in = raw.get("streamSettings") or {}
    net = stream_in.get("network", "") if isinstance(stream_in, dict) else ""
    _ensure_port_free(db, settings, port, protocol, net, raw.get("listen", ""))
    tag = raw.get("tag") or _unique_tag(db, f"in-{protocol}-{port}")
    settings_obj, stream_obj = templates.normalize_raw_inbound(
        protocol, raw.get("settings", {}), raw.get("streamSettings", {}))
    sniffing = raw.get("sniffing", templates.DEFAULT_SNIFFING)
    cur = db.execute(
        "INSERT INTO inbounds(tag,remark,enable,listen,port,protocol,settings,"
        "stream_settings,sniffing,share_addr,created_at) VALUES(?,?,1,?,?,?,?,?,?,?,?)",
        (tag, remark or tag, raw.get("listen", ""), port, protocol,
         json.dumps(settings_obj),
         json.dumps(stream_obj),
         json.dumps(sniffing),
         share_addr, now_ms()))
    row = db.query_one("SELECT * FROM inbounds WHERE id=?", (cur.lastrowid,))
    if apply_now:
        _apply_or_rollback(db, settings, row["id"])
    return row


def get_inbound(db: DB, ib_id: int) -> dict:
    row = db.query_one("SELECT * FROM inbounds WHERE id=?", (ib_id,))
    if not row:
        raise ManagerError(f"Inbound #{ib_id} tidak ditemukan")
    return row


def update_inbound(db: DB, settings, ib_id: int, fields: dict,
                   apply_now: bool = True) -> dict:
    allowed = {"remark", "enable", "listen", "port", "settings",
               "stream_settings", "sniffing", "share_addr", "total",
               "expiry_time", "traffic_reset"}
    sets, params = [], []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k in ("settings", "stream_settings", "sniffing") and isinstance(v, (dict, list)):
            v = json.dumps(v)
        sets.append(f"{k}=?")
        params.append(v)
    if sets:
        params.append(ib_id)
        db.execute(f"UPDATE inbounds SET {', '.join(sets)} WHERE id=?", params)
    if apply_now:
        apply(db, settings)
    return get_inbound(db, ib_id)


def delete_inbound(db: DB, settings, ib_id: int, apply_now: bool = True):
    get_inbound(db, ib_id)
    db.execute("DELETE FROM clients WHERE inbound_id=?", (ib_id,))
    db.execute("DELETE FROM inbounds WHERE id=?", (ib_id,))
    if apply_now:
        apply(db, settings)


def reset_inbound_traffic(db: DB, ib_id: int, include_clients: bool = True):
    db.execute("UPDATE inbounds SET up=0, down=0, last_reset=? WHERE id=?",
               (now_ms(), ib_id))
    if include_clients:
        db.execute("UPDATE clients SET up=0, down=0 WHERE inbound_id=?", (ib_id,))


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._@+-]{1,64}$")


def _next_wg_ip(db: DB, inbound_id: int) -> str:
    used = set()
    for c in db.query("SELECT extra FROM clients WHERE inbound_id=?", (inbound_id,)):
        for ip in jloads(c["extra"], {}).get("allowedIPs", []):
            m = re.match(r"10\.66\.66\.(\d+)/32", ip)
            if m:
                used.add(int(m.group(1)))
    n = 2
    while n in used:
        n += 1
    return f"10.66.66.{n}/32"


def add_client(db: DB, settings, inbound_id: int, email: str = "",
               uuid: str = "", password: str = "", flow: str = "",
               limit_ip: int = 0, total_bytes: int = 0, expiry_ms: int = 0,
               enable: bool = True, sub_id: str = "", tg_id: str = "",
               extra: dict = None, apply_now: bool = True) -> dict:
    ib = get_inbound(db, inbound_id)
    protocol = ib["protocol"]

    email = (email or "").strip() or f"user{int(time.time())}"
    if not _EMAIL_RE.match(email):
        raise ManagerError("Email/nama client hanya boleh huruf, angka, . _ @ + -")
    if db.query_one("SELECT id FROM clients WHERE email=?", (email,)):
        raise ManagerError(f"Duplicate email: {email}")

    extra = dict(extra) if extra else {}
    if protocol in ("vless", "vmess"):
        uuid = uuid or crypto.gen_uuid()
        if protocol == "vless" and not flow:
            stream = jloads(ib["stream_settings"], {})
            if stream.get("security") == "reality" and stream.get("network") == "tcp":
                flow = "xtls-rprx-vision"
    elif protocol == "shadowsocks":
        method = jloads(ib["settings"], {}).get("method", "")
        password = password or (crypto.gen_ss2022_key(method)
                                if method.startswith("2022-blake3-")
                                else crypto.gen_password(16))
    elif protocol in ("trojan", "socks", "http", "mixed", "hysteria"):
        password = password or crypto.gen_password(16)
    elif protocol == "wireguard":
        priv = extra.get("privateKey")
        pub = extra.get("publicKey")
        if not priv or not pub:
            priv, pub = crypto.wireguard_keypair()
        extra["privateKey"] = priv
        extra["publicKey"] = pub
        if "allowedIPs" not in extra:
            extra["allowedIPs"] = [_next_wg_ip(db, inbound_id)]

    cur = db.execute(
        "INSERT INTO clients(inbound_id,email,uuid,password,flow,enable,limit_ip,"
        "total_gb,expiry_time,sub_id,tg_id,extra,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (inbound_id, email, uuid, password, flow, 1 if enable else 0,
         int(limit_ip), int(total_bytes), int(expiry_ms),
         sub_id or crypto.gen_sub_id(), tg_id, json.dumps(extra),
         now_ms(), now_ms()))
    row = db.query_one("SELECT * FROM clients WHERE id=?", (cur.lastrowid,))
    if apply_now:
        apply(db, settings)
    return row


def get_client(db: DB, email: str) -> dict:
    row = db.query_one("SELECT * FROM clients WHERE email=?", (email,))
    if not row:
        raise ManagerError(f"Client not found: {email}")
    return row


def find_client_by_secret(db: DB, secret: str) -> dict:
    return db.query_one("SELECT * FROM clients WHERE uuid=? OR password=?",
                        (secret, secret))


def update_client(db: DB, settings, email: str, fields: dict,
                  apply_now: bool = True) -> dict:
    row = get_client(db, email)
    mapping = {
        "email": "email", "id": "uuid", "uuid": "uuid", "password": "password",
        "flow": "flow", "enable": "enable", "limitIp": "limit_ip",
        "limit_ip": "limit_ip", "totalGB": "total_gb", "total_gb": "total_gb",
        "expiryTime": "expiry_time", "expiry_time": "expiry_time",
        "subId": "sub_id", "sub_id": "sub_id", "tgId": "tg_id", "tg_id": "tg_id",
    }
    sets, params = [], []
    for key, col in mapping.items():
        if key not in fields or fields[key] is None:
            continue
        val = fields[key]
        if col == "email":
            val = str(val).strip()
            if not val or val == row["email"]:
                continue
            if not _EMAIL_RE.match(val):
                raise ManagerError("Email/nama client tidak valid")
            if db.query_one("SELECT id FROM clients WHERE email=? AND id<>?",
                            (val, row["id"])):
                raise ManagerError(f"Duplicate email: {val}")
        if col == "enable":
            val = 1 if val in (True, 1, "1", "true", "True") else 0
        if col in ("limit_ip", "total_gb", "expiry_time"):
            val = int(val)
        sets.append(f"{col}=?")
        params.append(val)

    # Update extra fields
    extra = jloads(row.get("extra", "{}"), {})
    extra_changed = False
    for key, val in fields.items():
        if key not in mapping and key not in ("up", "down", "online"):
            extra[key] = val
            extra_changed = True
    if extra_changed:
        sets.append("extra=?")
        params.append(json.dumps(extra))

    if sets:
        sets.append("updated_at=?")
        params.append(now_ms())
        params.append(row["id"])
        db.execute(f"UPDATE clients SET {', '.join(sets)} WHERE id=?", params)
    if apply_now:
        apply(db, settings)
    return db.query_one("SELECT * FROM clients WHERE id=?", (row["id"],))


def delete_client(db: DB, settings, email: str, apply_now: bool = True):
    row = get_client(db, email)
    db.execute("DELETE FROM clients WHERE id=?", (row["id"],))
    db.execute("DELETE FROM client_ips WHERE email=?", (email,))
    if apply_now:
        apply(db, settings)


def detach_client(db: DB, settings, email: str, inbound_ids: list,
                  apply_now: bool = True):
    """Lepaskan client dari inbound tertentu (kompatibilitas 3x-ui
    POST /panel/api/clients/{email}/detach).

    Karena di xray-manager setiap client hanya melekat pada satu inbound,
    melepaskannya dari inbound tersebut berarti menghapus client — namun
    bila inbound_ids tidak mencakup inbound client, tidak ada yang dihapus."""
    row = get_client(db, email)
    ib_set = {int(i) for i in (inbound_ids or []) if i}
    if row["inbound_id"] not in ib_set:
        return  # client tidak ada di inbound yang diminta → nothing to do
    db.execute("DELETE FROM clients WHERE id=?", (row["id"],))
    db.execute("DELETE FROM client_ips WHERE email=?", (email,))
    if apply_now:
        apply(db, settings)


def reset_client_traffic(db: DB, settings, email: str, apply_now: bool = True):
    row = get_client(db, email)
    db.execute("UPDATE clients SET up=0, down=0, updated_at=? WHERE id=?",
               (now_ms(), row["id"]))
    if apply_now:
        apply(db, settings)  # client yang tadinya over-quota jadi aktif lagi


def onlines(db: DB, settings) -> list:
    """Email client yang terlihat aktif dalam 2x interval job terakhir."""
    threshold = now_ms() - settings.job_interval * 2 * 1000
    rows = db.query("SELECT email FROM clients WHERE online_at>=?", (threshold,))
    return [r["email"] for r in rows]


# ---------------------------------------------------------------------------
# View — bentuk respons kompatibel 3x-ui
# ---------------------------------------------------------------------------

def client_traffic_view(c: dict) -> dict:
    active = config_builder.client_is_active(c, now_ms())
    return {
        "id": c["id"],
        "inboundId": c["inbound_id"],
        "enable": bool(active),
        "email": c["email"],
        "up": c["up"],
        "down": c["down"],
        "total": c["total_gb"],
        "expiryTime": c["expiry_time"],
    }


def client_view(c: dict) -> dict:
    extra = jloads(c.get("extra", "{}"), {})
    v = {
        "id": c["uuid"] or c["password"],
        "email": c["email"],
        "enable": bool(c["enable"]),
        "flow": c["flow"],
        "limitIp": c["limit_ip"],
        "totalGB": c["total_gb"],
        "expiryTime": c["expiry_time"],
        "subId": c["sub_id"],
        "tgId": c["tg_id"],
        "inboundIds": [c["inbound_id"]],
        "traffic": {"up": c["up"], "down": c["down"],
                    "usage": c["up"] + c["down"], "total": c["total_gb"]},
        "online": False,
        "createdAt": c["created_at"],
        "updatedAt": c["updated_at"],
    }
    if c["password"]:
        v["password"] = c["password"]
    # Merge protocol-specific fields (security, auth, WireGuard keys dll.) ke top-level
    if isinstance(extra, dict):
        for k, val in extra.items():
            if k not in v:
                v[k] = val
    return v


def inbound_view(db: DB, ib: dict) -> dict:
    clients = db.query("SELECT * FROM clients WHERE inbound_id=?", (ib["id"],))
    settings_obj = jloads(ib["settings"], {})
    # tampilkan client di settings agar mirip 3x-ui
    settings_obj = dict(settings_obj)
    settings_obj["clients"] = [client_view(c) for c in clients]
    return {
        "id": ib["id"],
        "up": ib["up"],
        "down": ib["down"],
        "total": ib["total"],
        "remark": ib["remark"],
        "enable": bool(ib["enable"]),
        "expiryTime": ib["expiry_time"],
        "trafficReset": ib["traffic_reset"],
        "listen": ib["listen"],
        "port": ib["port"],
        "protocol": ib["protocol"],
        "settings": json.dumps(settings_obj),
        "streamSettings": json.dumps(jloads(ib["stream_settings"], {})),
        "sniffing": json.dumps(jloads(ib["sniffing"], {})),
        "tag": ib["tag"],
        "shareAddr": ib.get("share_addr") or "",
        "clientStats": [client_traffic_view(c) for c in clients],
    }


# ---------------------------------------------------------------------------
# Outbound
# ---------------------------------------------------------------------------

def _unique_outbound_tag(db: DB, base: str) -> str:
    tag, i = base, 1
    while db.query_one("SELECT id FROM outbounds WHERE tag=?", (tag,)):
        i += 1
        tag = f"{base}-{i}"
    return tag


def list_outbounds(db: DB) -> list:
    return db.query("SELECT * FROM outbounds ORDER BY id")


def get_outbound(db: DB, ob_id: int) -> dict:
    row = db.query_one("SELECT * FROM outbounds WHERE id=?", (ob_id,))
    if not row:
        raise ManagerError(f"Outbound #{ob_id} tidak ditemukan")
    return row


def add_outbound(db: DB, settings, tag: str, config: dict,
                 enable: bool = True, apply_now: bool = True) -> dict:
    tag = (tag or "").strip()
    if not tag:
        raise ManagerError("Tag outbound wajib diisi")
    if not isinstance(config, dict) or not config.get("protocol"):
        raise ManagerError("Config outbound harus dict JSON dengan field 'protocol'")
    tag = _unique_outbound_tag(db, tag)
    cur = db.execute(
        "INSERT INTO outbounds(tag,config,enable) VALUES(?,?,?)",
        (tag, json.dumps(config), 1 if enable else 0))
    row = db.query_one("SELECT * FROM outbounds WHERE id=?", (cur.lastrowid,))
    if apply_now:
        apply(db, settings)
    return row


def update_outbound(db: DB, settings, ob_id: int, fields: dict,
                    apply_now: bool = True) -> dict:
    get_outbound(db, ob_id)
    allowed = {"tag", "config", "enable"}
    sets, params = [], []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k == "config" and isinstance(v, (dict, list)):
            v = json.dumps(v)
        if k == "enable":
            v = 1 if v in (True, 1, "1", "true", "True") else 0
        sets.append(f"{k}=?")
        params.append(v)
    if sets:
        params.append(ob_id)
        db.execute(f"UPDATE outbounds SET {', '.join(sets)} WHERE id=?", params)
    if apply_now:
        apply(db, settings)
    return get_outbound(db, ob_id)


def delete_outbound(db: DB, settings, ob_id: int, apply_now: bool = True):
    get_outbound(db, ob_id)
    db.execute("DELETE FROM outbounds WHERE id=?", (ob_id,))
    if apply_now:
        apply(db, settings)


def outbound_view(ob: dict) -> dict:
    return {
        "id": ob["id"],
        "tag": ob["tag"],
        "config": json.dumps(jloads(ob["config"], {})),
        "enable": bool(ob["enable"]),
        "up": ob.get("up", 0),
        "down": ob.get("down", 0),
    }


# ---------------------------------------------------------------------------
# Routing rules
# ---------------------------------------------------------------------------

def list_routing(db: DB) -> list:
    return db.query("SELECT * FROM routing_rules ORDER BY sort, id")


def get_routing(db: DB, r_id: int) -> dict:
    row = db.query_one("SELECT * FROM routing_rules WHERE id=?", (r_id,))
    if not row:
        raise ManagerError(f"Routing rule #{r_id} tidak ditemukan")
    return row


def add_routing(db: DB, settings, remark: str, rule: dict,
                enable: bool = True, sort: int = 100,
                apply_now: bool = True) -> dict:
    if not isinstance(rule, dict):
        raise ManagerError("Rule routing harus dict JSON")
    cur = db.execute(
        "INSERT INTO routing_rules(remark,rule,enable,sort) VALUES(?,?,?,?)",
        (remark or "", json.dumps(rule), 1 if enable else 0, int(sort)))
    row = db.query_one("SELECT * FROM routing_rules WHERE id=?", (cur.lastrowid,))
    if apply_now:
        apply(db, settings)
    return row


def update_routing(db: DB, settings, r_id: int, fields: dict,
                   apply_now: bool = True) -> dict:
    get_routing(db, r_id)
    allowed = {"remark", "rule", "enable", "sort"}
    sets, params = [], []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k == "rule" and isinstance(v, (dict, list)):
            v = json.dumps(v)
        if k == "enable":
            v = 1 if v in (True, 1, "1", "true", "True") else 0
        if k == "sort":
            v = int(v)
        sets.append(f"{k}=?")
        params.append(v)
    if sets:
        params.append(r_id)
        db.execute(f"UPDATE routing_rules SET {', '.join(sets)} WHERE id=?", params)
    if apply_now:
        apply(db, settings)
    return get_routing(db, r_id)


def delete_routing(db: DB, settings, r_id: int, apply_now: bool = True):
    get_routing(db, r_id)
    db.execute("DELETE FROM routing_rules WHERE id=?", (r_id,))
    if apply_now:
        apply(db, settings)


def routing_view(r: dict) -> dict:
    return {
        "id": r["id"],
        "remark": r["remark"],
        "rule": json.dumps(jloads(r["rule"], {})),
        "enable": bool(r["enable"]),
        "sort": r["sort"],
    }


# ---------------------------------------------------------------------------
# Balancers
# ---------------------------------------------------------------------------

def list_balancers(db: DB) -> list:
    return db.query("SELECT * FROM balancers ORDER BY id")


def add_balancer(db: DB, settings, config: dict, apply_now: bool = True) -> dict:
    if not isinstance(config, dict):
        raise ManagerError("Config balancer harus dict JSON")
    cur = db.execute("INSERT INTO balancers(config) VALUES(?)",
                     (json.dumps(config),))
    row = db.query_one("SELECT * FROM balancers WHERE id=?", (cur.lastrowid,))
    if apply_now:
        apply(db, settings)
    return row


def delete_balancer(db: DB, settings, b_id: int, apply_now: bool = True):
    row = db.query_one("SELECT * FROM balancers WHERE id=?", (b_id,))
    if not row:
        raise ManagerError(f"Balancer #{b_id} tidak ditemukan")
    db.execute("DELETE FROM balancers WHERE id=?", (b_id,))
    if apply_now:
        apply(db, settings)


def balancer_view(b: dict) -> dict:
    return {
        "id": b["id"],
        "config": json.dumps(jloads(b["config"], {})),
    }

