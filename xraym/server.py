"""HTTP API server — kompatibel dengan gaya API 3x-ui (`/panel/api/...`)
sehingga bisa langsung disinkronkan dengan web API Oceansharknet.

Semua respons berbentuk: {"success": bool, "msg": str, "obj": ...}
Autentikasi: session cookie (POST /login) ATAU Bearer token / X-API-KEY.
"""

import datetime
import json
import logging
import os
import ssl as ssllib
import time

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

from . import __version__, crypto, links, manager, settings as settings_mod, xray_api
from .db import DB, jloads, now_ms
from .jobs import JobRunner

log = logging.getLogger("xraym.server")

WEB_DIR = os.path.join(os.path.dirname(__file__), "web")

SETTINGS = settings_mod.load()
DATABASE = DB(SETTINGS.db_path)

_login_failures = {}  # ip -> [count, blocked_until]

COOKIE_NAME = "xm_session"


def _cert_paths(domain: str):
    """(fullchain, privkey) bila sertifikat domain ada, else (None, None)."""
    base = os.path.join(SETTINGS.cert_dir, domain)
    cert = os.path.join(base, "fullchain.pem")
    key = os.path.join(base, "privkey.pem")
    if os.path.exists(cert) and os.path.exists(key):
        return cert, key
    return None, None


def ok(obj=None, msg=""):
    return JSONResponse({"success": True, "msg": msg, "obj": obj})


def fail(msg, status=200, obj=None):
    # 3x-ui mengembalikan HTTP 200 dengan success=false — ikuti perilaku itu
    return JSONResponse({"success": False, "msg": msg, "obj": obj},
                        status_code=status)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _check_token(token: str) -> bool:
    if not token:
        return False
    h = crypto.hash_token(token.strip())
    return DATABASE.query_one(
        "SELECT id FROM tokens WHERE token_hash=? AND enabled=1", (h,)) is not None


def is_authenticated(request: Request) -> bool:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer ") and _check_token(auth[7:]):
        return True
    if _check_token(request.headers.get("x-api-key", "")):
        return True
    cookie = request.cookies.get(COOKIE_NAME, "")
    if cookie and crypto.verify_session(SETTINGS.secret, cookie):
        return True
    return False


async def _read_body(request: Request) -> dict:
    """Terima JSON, form-urlencoded, maupun multipart."""
    ctype = request.headers.get("content-type", "")
    try:
        if "json" in ctype:
            data = await request.json()
            return data if isinstance(data, dict) else {}
        form = await request.form()
        return {k: v for k, v in form.items()}
    except Exception:
        try:
            data = await request.json()
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

public = APIRouter()
api = APIRouter(prefix="/panel/api")


def _render_index() -> str:
    path = os.path.join(WEB_DIR, "index.html")
    try:
        with open(path, encoding="utf-8") as f:
            html = f.read()
    except OSError:
        return "<h1>xray-manager</h1><p>UI tidak ditemukan.</p>"
    base = "/" + SETTINGS.base_path.strip("/") if SETTINGS.base_path.strip("/") else ""
    # Sisipkan base_path & versi agar fetch di frontend memakai prefix yang benar
    return (html.replace("{{BASE}}", base)
                .replace("{{VERSION}}", __version__))


@public.get("/")
async def root():
    return HTMLResponse(_render_index())


@public.get("/api")
async def api_info():
    return ok({"name": "xray-manager", "version": __version__})


@public.post("/login")
async def login(request: Request):
    ip = request.client.host if request.client else "?"
    now = time.time()
    count, blocked_until = _login_failures.get(ip, (0, 0))
    if blocked_until > now:
        return fail("Too many attempts, try again later", status=429)

    body = await _read_body(request)
    username = str(body.get("username", ""))
    password = str(body.get("password", ""))
    if (username == SETTINGS.username
            and SETTINGS.password_hash
            and crypto.verify_password(password, SETTINGS.password_hash)):
        _login_failures.pop(ip, None)
        resp = JSONResponse({"success": True, "msg": "Login berhasil", "obj": None})
        resp.set_cookie(COOKIE_NAME,
                        crypto.make_session(SETTINGS.secret, username,
                                            SETTINGS.session_hours),
                        max_age=SETTINGS.session_hours * 3600,
                        httponly=True, samesite="lax")
        return resp

    count += 1
    _login_failures[ip] = (count, now + 300 if count >= 5 else 0)
    return fail("Username atau password salah")


@public.get("/logout")
async def logout():
    resp = ok(msg="Logout")
    resp.delete_cookie(COOKIE_NAME)
    return resp


# --------------------------- server ---------------------------------------

def _read_proc_status():
    status = {"cpu": 0.0, "mem": {"current": 0, "total": 0}, "uptime": 0}
    try:
        with open("/proc/uptime") as f:
            status["uptime"] = int(float(f.read().split()[0]))
        with open("/proc/loadavg") as f:
            status["cpu"] = float(f.read().split()[0])
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                info[k] = int(v.strip().split()[0]) * 1024
        status["mem"]["total"] = info.get("MemTotal", 0)
        status["mem"]["current"] = info.get("MemTotal", 0) - info.get("MemAvailable", 0)
    except (OSError, ValueError, IndexError):
        pass
    return status


@api.get("/server/status")
async def server_status():
    st = _read_proc_status()
    st["xray"] = {
        "state": "running" if xray_api.is_running(SETTINGS) else "stop",
        "version": xray_api.version(SETTINGS),
    }
    st["appVersion"] = __version__
    return ok(st)


@api.post("/apply")
async def apply_now():
    okk, msg = manager.apply(DATABASE, SETTINGS)
    return ok(msg=msg) if okk else fail(msg)


# --------------------------- inbounds --------------------------------------

@api.get("/inbounds/list")
async def inbounds_list():
    rows = DATABASE.query("SELECT * FROM inbounds ORDER BY id")
    return ok([manager.inbound_view(DATABASE, ib) for ib in rows])


@api.get("/inbounds/get/{ib_id}")
async def inbounds_get(ib_id: int):
    try:
        ib = manager.get_inbound(DATABASE, ib_id)
    except manager.ManagerError as e:
        return fail(str(e))
    return ok(manager.inbound_view(DATABASE, ib))


@api.post("/inbounds/add")
async def inbounds_add(request: Request):
    body = await _read_body(request)
    try:
        if "settings" in body or "streamSettings" in body:
            # payload gaya 3x-ui / JSON xray mentah
            raw = {
                "port": int(body.get("port", 0)),
                "protocol": body.get("protocol", ""),
                "listen": body.get("listen", ""),
                "tag": body.get("tag", ""),
                "settings": jloads(body.get("settings", {}), {}),
                "streamSettings": jloads(body.get("streamSettings", {}), {}),
                "sniffing": jloads(body.get("sniffing", {}), {}) or None,
            }
            if raw["sniffing"] is None:
                raw.pop("sniffing")
            ib = manager.add_inbound_raw(DATABASE, SETTINGS, raw,
                                         remark=body.get("remark", ""))
            fields = {}
            for src, dst in (("expiryTime", "expiry_time"), ("total", "total"),
                             ("trafficReset", "traffic_reset")):
                if body.get(src) is not None:
                    fields[dst] = body[src]
            if fields:
                ib = manager.update_inbound(DATABASE, SETTINGS, ib["id"], fields,
                                            apply_now=False)
        else:
            # payload template sederhana
            opts = dict(body.get("opts") or body)
            security = body.get("security", "none")
            # certDomain → isi cert/key/sni dari sertifikat ssl.sh, nyalakan TLS
            cert_domain = (body.get("certDomain") or "").strip()
            if cert_domain:
                cert, key = _cert_paths(cert_domain)
                if not cert:
                    return fail(f"Sertifikat '{cert_domain}' belum ada. "
                                f"Terbitkan dulu via ssl.sh.")
                opts["cert_file"], opts["key_file"] = cert, key
                opts.setdefault("sni", cert_domain)
                if security == "none":
                    security = "tls"
            ib = manager.add_inbound(
                DATABASE, SETTINGS,
                protocol=body.get("protocol", "vless"),
                port=int(body.get("port", 0)),
                remark=body.get("remark", ""),
                listen=body.get("listen", ""),
                network=body.get("network", "tcp"),
                security=security,
                opts=opts,
                expiry_ms=int(body.get("expiryTime", 0) or 0),
                total_bytes=int(body.get("total", 0) or 0))
    except (manager.ManagerError, ValueError) as e:
        return fail(str(e))
    return ok(manager.inbound_view(DATABASE, ib), "Inbound dibuat")


@api.post("/inbounds/update/{ib_id}")
async def inbounds_update(ib_id: int, request: Request):
    body = await _read_body(request)
    fields = {}
    mapping = {"remark": "remark", "enable": "enable", "listen": "listen",
               "port": "port", "settings": "settings",
               "streamSettings": "stream_settings", "sniffing": "sniffing",
               "shareAddr": "share_addr", "total": "total",
               "expiryTime": "expiry_time", "trafficReset": "traffic_reset"}
    for src, dst in mapping.items():
        if src in body and body[src] is not None:
            val = body[src]
            if dst in ("settings", "stream_settings", "sniffing"):
                val = jloads(val, {})
            if dst == "enable":
                val = 1 if val in (True, 1, "1", "true", "True") else 0
            fields[dst] = val
    try:
        ib = manager.update_inbound(DATABASE, SETTINGS, ib_id, fields)
    except manager.ManagerError as e:
        return fail(str(e))
    return ok(manager.inbound_view(DATABASE, ib), "Inbound diperbarui")


@api.post("/inbounds/del/{ib_id}")
async def inbounds_del(ib_id: int):
    try:
        manager.delete_inbound(DATABASE, SETTINGS, ib_id)
    except manager.ManagerError as e:
        return fail(str(e))
    return ok(msg="Inbound dihapus")


@api.post("/inbounds/resetTraffic/{ib_id}")
async def inbounds_reset(ib_id: int):
    try:
        manager.get_inbound(DATABASE, ib_id)
    except manager.ManagerError as e:
        return fail(str(e))
    manager.reset_inbound_traffic(DATABASE, ib_id)
    manager.apply(DATABASE, SETTINGS)
    return ok(msg="Traffic inbound direset")


@api.post("/inbounds/onlines")
async def inbounds_onlines():
    return ok(manager.onlines(DATABASE, SETTINGS))


@api.post("/inbounds/updateClient/{secret}")
async def inbounds_update_client(secret: str, request: Request):
    """Kompatibilitas 3x-ui klasik: body {id: inboundId,
    settings: '{"clients": [{...}]}'} — client dicari via uuid/password."""
    body = await _read_body(request)
    row = manager.find_client_by_secret(DATABASE, secret)
    if not row:
        return fail("client not found")
    settings_obj = jloads(body.get("settings", "{}"), {})
    clients = settings_obj.get("clients") or []
    if not clients:
        return fail("payload settings.clients kosong")
    try:
        c = manager.update_client(DATABASE, SETTINGS, row["email"], clients[0])
    except manager.ManagerError as e:
        return fail(str(e))
    return ok(manager.client_view(c), "Client diperbarui")


# --------------------------- clients ---------------------------------------

@api.get("/clients/list")
async def clients_list():
    rows = DATABASE.query("SELECT * FROM clients ORDER BY id")
    online = set(manager.onlines(DATABASE, SETTINGS))
    out = []
    for c in rows:
        v = manager.client_view(c)
        v["online"] = c["email"] in online
        out.append(v)
    return ok(out)


@api.get("/clients/get/{email}")
async def clients_get(email: str):
    try:
        c = manager.get_client(DATABASE, email)
    except manager.ManagerError as e:
        return fail(str(e))
    return ok(manager.client_view(c))


@api.get("/clients/traffic/{email}")
async def clients_traffic(email: str):
    try:
        c = manager.get_client(DATABASE, email)
    except manager.ManagerError as e:
        return fail(str(e))
    return ok(manager.client_traffic_view(c))


@api.post("/clients/add")
async def clients_add(request: Request):
    body = await _read_body(request)
    client = jloads(body.get("client", {}), {}) or body
    inbound_ids = body.get("inboundIds") or []
    if isinstance(inbound_ids, str):
        inbound_ids = jloads(inbound_ids, [])
    inbound_id = int(inbound_ids[0]) if inbound_ids else int(body.get("inboundId", 0) or 0)
    if not inbound_id:
        return fail("inboundIds wajib diisi")
    try:
        c = manager.add_client(
            DATABASE, SETTINGS, inbound_id,
            email=str(client.get("email", "")),
            uuid=str(client.get("id", "") or client.get("uuid", "")),
            password=str(client.get("password", "")),
            flow=str(client.get("flow", "")),
            limit_ip=int(client.get("limitIp", 0) or 0),
            total_bytes=int(client.get("totalGB", 0) or 0),
            expiry_ms=int(client.get("expiryTime", 0) or 0),
            enable=client.get("enable", True) in (True, 1, "1", "true", "True"),
            sub_id=str(client.get("subId", "")),
            tg_id=str(client.get("tgId", "")))
    except (manager.ManagerError, ValueError) as e:
        return fail(str(e))
    return ok(manager.client_view(c), "Client dibuat")


@api.post("/clients/update/{email}")
async def clients_update(email: str, request: Request):
    body = await _read_body(request)
    client = jloads(body.get("client", {}), {}) or body
    try:
        c = manager.update_client(DATABASE, SETTINGS, email, client)
    except manager.ManagerError as e:
        return fail(str(e))
    return ok(manager.client_view(c), "Client diperbarui")


@api.post("/clients/del/{email}")
async def clients_del(email: str):
    try:
        manager.delete_client(DATABASE, SETTINGS, email)
    except manager.ManagerError as e:
        return fail(str(e))
    return ok(msg="Client dihapus")


@api.post("/clients/resetTraffic/{email}")
async def clients_reset(email: str):
    try:
        manager.reset_client_traffic(DATABASE, SETTINGS, email)
    except manager.ManagerError as e:
        return fail(str(e))
    return ok(msg="Traffic client direset")


@api.get("/clients/ips/{email}")
async def clients_ips(email: str):
    row = DATABASE.query_one("SELECT * FROM client_ips WHERE email=?", (email,))
    return ok(jloads(row["ips"], []) if row else [])


@api.post("/clients/clearips/{email}")
async def clients_clear_ips(email: str):
    DATABASE.execute("DELETE FROM client_ips WHERE email=?", (email,))
    return ok(msg="Daftar IP dihapus")


@api.get("/clients/link/{email}")
async def clients_link(email: str):
    try:
        c = manager.get_client(DATABASE, email)
        ib = manager.get_inbound(DATABASE, c["inbound_id"])
    except manager.ManagerError as e:
        return fail(str(e))
    return ok({"email": email, "link": links.share_link(SETTINGS, ib, c)})


@api.get("/clients/qr/{email}")
async def clients_qr(email: str):
    try:
        c = manager.get_client(DATABASE, email)
        ib = manager.get_inbound(DATABASE, c["inbound_id"])
        svg = links.qr_svg(links.share_link(SETTINGS, ib, c))
    except manager.ManagerError as e:
        return fail(str(e))
    except ImportError:
        return fail("Package 'qrcode' belum terpasang")
    return Response(content=svg, media_type="image/svg+xml")


# --------------------------- settings & certs (untuk web UI) ---------------

# Field settings yang boleh dibaca/ubah dari web UI (yang lain rahasia).
_SETTINGS_PUBLIC = ["domain", "listen", "port", "base_path", "session_hours",
                    "job_interval", "ip_limit_window", "cert_dir", "webhook_url",
                    "webhook_api_key", "sync_push_interval", "xray_service",
                    "realtime", "timezone", "tg_enable", "tg_bot_token",
                    "tg_chat_id"]
_SETTINGS_EDITABLE = ["domain", "listen", "port", "base_path", "session_hours",
                      "webhook_url", "webhook_api_key", "sync_push_interval",
                      "job_interval", "ip_limit_window", "realtime", "timezone",
                      "tg_enable", "tg_bot_token", "tg_chat_id"]
# Field yang butuh restart service agar berlaku (bind panel di-startup)
_SETTINGS_NEED_RESTART = {"listen", "port", "base_path"}


@api.get("/settings")
async def settings_get():
    from . import templates as tmpl
    st = settings_mod.load()
    view = {k: st.get(k) for k in _SETTINGS_PUBLIC}
    view["editable"] = _SETTINGS_EDITABLE
    view["serverTime"] = int(time.time() * 1000)   # untuk jam server tab Tanggal & Waktu
    # status auto-renew sertifikat (acme.sh terpasang → cron auto-renew aktif)
    view["autoRenew"] = os.path.exists(os.path.expanduser("~/.acme.sh/acme.sh"))
    view["protocols"] = tmpl.PROTOCOLS
    view["networks"] = ["tcp", "kcp", "ws", "grpc", "httpupgrade", "xhttp"]
    view["securities"] = tmpl.SECURITIES
    # Opsi lengkap untuk dropdown form pembuatan inbound (standar Xray-core)
    view["methods"] = tmpl.SS_METHODS
    view["fingerprints"] = tmpl.FINGERPRINTS
    view["alpns"] = tmpl.ALPN_OPTIONS
    view["xhttpModes"] = tmpl.XHTTP_MODES
    view["tcpHeaders"] = tmpl.TCP_HEADER_TYPES
    view["kcpHeaders"] = tmpl.KCP_HEADER_TYPES
    view["flows"] = tmpl.FLOWS
    view["vmessSecurities"] = tmpl.VMESS_SECURITIES
    return ok(view)


@api.get("/keygen/{kind}")
async def keygen(kind: str, request: Request):
    """Generator kunci server-side untuk form inbound (butuh x25519, dsb.)."""
    kind = (kind or "").lower()
    if kind == "reality":
        priv, pub = crypto.reality_keypair()
        return ok({"privateKey": priv, "publicKey": pub})
    if kind in ("wireguard", "wg"):
        priv, pub = crypto.wireguard_keypair()
        return ok({"privateKey": priv, "publicKey": pub})
    if kind in ("shortid", "shortids", "sid"):
        return ok({"shortId": crypto.gen_short_id()})
    if kind == "uuid":
        return ok({"uuid": crypto.gen_uuid()})
    if kind == "password":
        return ok({"password": crypto.gen_password(16)})
    if kind in ("ss2022", "sspass"):
        method = request.query_params.get("method", "2022-blake3-aes-256-gcm")
        return ok({"password": crypto.gen_ss2022_key(method)})
    if kind == "wgpubkey":
        priv = request.query_params.get("private", "")
        try:
            return ok({"publicKey": crypto.wireguard_pubkey(priv)})
        except Exception:
            return fail("privateKey WireGuard tidak valid")
    if kind == "realitypubkey":
        priv = request.query_params.get("private", "")
        try:
            return ok({"publicKey": crypto.reality_pubkey(priv)})
        except Exception:
            return fail("privateKey REALITY tidak valid")
    return fail(f"Jenis keygen '{kind}' tidak dikenal")


_TRUE = (True, 1, "1", "true", "True", "on", "yes")


@api.post("/settings/update")
async def settings_update(request: Request):
    body = await _read_body(request)
    st = settings_mod.load()
    changed = []
    for k in _SETTINGS_EDITABLE:
        if k in body and body[k] is not None:
            default = settings_mod.DEFAULTS[k]
            val = body[k]
            if isinstance(default, bool):          # cek bool dulu (subclass int)
                val = val in _TRUE
            elif isinstance(default, int):
                try:
                    val = int(val)
                except (TypeError, ValueError):
                    continue
            # Validasi & normalisasi field khusus
            if k == "port" and not (1 <= val <= 65535):
                return fail("Port panel harus 1-65535.")
            if k == "session_hours" and val < 1:
                val = 1
            if k == "base_path":
                p = str(val).strip().strip("/")
                val = "/" + p if p else ""
            if k == "listen":
                val = str(val).strip() or "0.0.0.0"
            st[k] = val
            changed.append(k)
    st.save()
    # perbarui juga instance SETTINGS di memori agar langsung berlaku
    for k in changed:
        SETTINGS[k] = st[k]
    # Perubahan profil realtime mempengaruhi policy config → rakit ulang xray
    if "realtime" in changed:
        try:
            manager.apply(DATABASE, SETTINGS)
        except Exception as e:
            log.warning("apply setelah ubah realtime gagal: %s", e)
    need_restart = sorted(_SETTINGS_NEED_RESTART & set(changed))
    msg = "Tersimpan."
    if need_restart:
        msg += (f" Perubahan {', '.join(need_restart)} berlaku setelah "
                "restart service: systemctl restart xray-manager")
    return ok({"changed": changed, "needRestart": need_restart}, msg)


@api.post("/settings/test-telegram")
async def settings_test_telegram(request: Request):
    """Kirim pesan tes ke Telegram (tombol Test di tab Notifikasi)."""
    import urllib.parse
    import urllib.request
    body = await _read_body(request)
    token = str(body.get("tg_bot_token") or SETTINGS.get("tg_bot_token") or "").strip()
    chat = str(body.get("tg_chat_id") or SETTINGS.get("tg_chat_id") or "").strip()
    if not token or not chat:
        return fail("Bot token & chat ID wajib diisi.")
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": chat,
            "text": "✅ Tes notifikasi OceanShark Xray Manager berhasil.",
        }).encode()
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10).read()
    except Exception as e:
        return fail(f"Gagal kirim ke Telegram: {e}")
    return ok(msg="Pesan tes terkirim ke Telegram.")


@api.get("/certs")
async def certs_list():
    root = SETTINGS.cert_dir
    out = []
    if os.path.isdir(root):
        for domain in sorted(os.listdir(root)):
            full = os.path.join(root, domain, "fullchain.pem")
            key = os.path.join(root, domain, "privkey.pem")
            if not os.path.exists(full):
                continue
            expiry = None
            days_left = None
            try:
                data = ssllib._ssl._test_decode_cert(full)  # type: ignore[attr-defined]
                dt = datetime.datetime.strptime(
                    data["notAfter"], "%b %d %H:%M:%S %Y %Z")
                expiry = dt.strftime("%Y-%m-%d")
                days_left = (dt - datetime.datetime.utcnow()).days
            except Exception:
                pass
            out.append({
                "domain": domain,
                "expiry": expiry,
                "daysLeft": days_left,
                "publicKeyPath": full,       # sertifikat (fullchain)
                "privateKeyPath": key,       # private key
            })
    return ok(out)


# --------------------------- sync (untuk cron web API) ---------------------

@api.get("/sync/snapshot")
async def sync_snapshot():
    """Satu payload lengkap untuk sinkronisasi: inbound + client + trafik +
    online. Web API cukup memanggil endpoint ini secara berkala."""
    inbounds = [manager.inbound_view(DATABASE, ib)
                for ib in DATABASE.query("SELECT * FROM inbounds ORDER BY id")]
    clients = DATABASE.query("SELECT * FROM clients ORDER BY id")
    online = set(manager.onlines(DATABASE, SETTINGS))
    client_views = []
    for c in clients:
        v = manager.client_view(c)
        v["online"] = c["email"] in online
        client_views.append(v)
    return ok({
        "at": now_ms(),
        "xray": {"state": "running" if xray_api.is_running(SETTINGS) else "stop",
                 "version": xray_api.version(SETTINGS)},
        "inbounds": inbounds,
        "clients": client_views,
        "traffics": [manager.client_traffic_view(c) for c in clients],
        "onlines": sorted(online),
    })


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    app = FastAPI(title="xray-manager", version=__version__,
                  docs_url=None, redoc_url=None, openapi_url=None)
    base = "/" + SETTINGS.base_path.strip("/") if SETTINGS.base_path.strip("/") else ""

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        path = request.url.path
        open_paths = {base + "/", base + "/login", base + "/logout",
                      base + "/api", base or "/"}
        if path in open_paths:
            return await call_next(request)
        if not path.startswith(base + "/panel/api"):
            return JSONResponse({"success": False, "msg": "Not found"}, 404)
        if not is_authenticated(request):
            return JSONResponse({"success": False, "msg": "Unauthorized"}, 401)
        return await call_next(request)

    app.include_router(public, prefix=base)
    app.include_router(api, prefix=base)
    return app


app = create_app()


def main():
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    runner = JobRunner(DATABASE, SETTINGS)
    runner.start()
    log.info("xray-manager v%s — listen %s:%s base_path=%r",
             __version__, SETTINGS.listen, SETTINGS.port, SETTINGS.base_path)
    uvicorn.run(app, host=SETTINGS.listen, port=int(SETTINGS.port),
                log_level="warning")


if __name__ == "__main__":
    main()
