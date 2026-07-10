"""CLI `xm` — kelola inbound, client, outbound, routing, token, dan settings."""

import argparse
import datetime as dt
import getpass
import json
import secrets
import sys

from . import __version__, crypto, links, manager, settings as settings_mod, xray_api
from .db import DB, jloads, now_ms


def _fmt_bytes(n):
    if not n:
        return "0"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}B"
        n /= 1024
    return f"{n:.1f}PB"


def _fmt_expiry(ms):
    if ms == 0:
        return "selamanya"
    if ms < 0:
        days = abs(ms) / 86400000
        return f"{days:.0f} hari setelah dipakai"
    d = dt.datetime.fromtimestamp(ms / 1000)
    mark = "" if ms > now_ms() else " (EXPIRED)"
    return d.strftime("%Y-%m-%d %H:%M") + mark


def _parse_expiry(args) -> int:
    """--days N atau --expire YYYY-MM-DD → epoch ms. --start-on-use membuat negatif."""
    ms = 0
    if getattr(args, "expire", None):
        d = dt.datetime.strptime(args.expire, "%Y-%m-%d")
        ms = int(d.replace(hour=23, minute=59, second=59).timestamp() * 1000)
    elif getattr(args, "days", None):
        if getattr(args, "start_on_use", False):
            return -int(args.days * 86400000)
        ms = now_ms() + int(args.days * 86400000)
    return ms


def _table(headers, rows):
    widths = [len(h) for h in headers]
    srows = [[str(c) for c in r] for r in rows]
    for r in srows:
        for i, c in enumerate(r):
            widths[i] = max(widths[i], len(c))
    line = "  ".join(h.ljust(w) for h, w in zip(headers, widths))
    print(line)
    print("-" * len(line))
    for r in srows:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)))


def _apply_and_report(db, st):
    ok, msg = manager.apply(db, st)
    if ok:
        print("✔ Config diterapkan, xray direstart.")
    else:
        print(f"✘ Gagal apply: {msg}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Perintah
# ---------------------------------------------------------------------------

def cmd_status(db, st, args):
    print(f"xray-manager  : v{__version__}")
    print(f"xray core     : {xray_api.version(st)}")
    print(f"xray service  : {'running' if xray_api.is_running(st) else 'STOP'}")
    print(f"panel         : http://{st.domain or 'IP-SERVER'}:{st.port}{st.base_path}")
    n_ib = db.query_one("SELECT COUNT(*) c FROM inbounds")["c"]
    n_cl = db.query_one("SELECT COUNT(*) c FROM clients")["c"]
    online = manager.onlines(db, st)
    print(f"inbounds      : {n_ib}")
    print(f"clients       : {n_cl}  (online: {len(online)})")


def cmd_apply(db, st, args):
    _apply_and_report(db, st)


# ------------------------------ inbound ------------------------------------

def cmd_inbound_list(db, st, args):
    rows = db.query("SELECT * FROM inbounds ORDER BY id")
    _table(
        ["ID", "TAG", "PROTO", "PORT", "NET", "SEC", "UP", "DOWN", "EXPIRED", "ON"],
        [[ib["id"], ib["tag"], ib["protocol"], ib["port"],
          jloads(ib["stream_settings"], {}).get("network", "-"),
          jloads(ib["stream_settings"], {}).get("security", "-"),
          _fmt_bytes(ib["up"]), _fmt_bytes(ib["down"]),
          _fmt_expiry(ib["expiry_time"]), "✔" if ib["enable"] else "✘"]
         for ib in rows])


def _resolve_cert_domain(st, args):
    """--cert-domain <domain> → isi cert/key/sni dari <cert_dir>/<domain>/.
    Aktifkan TLS otomatis bila security masih 'none'."""
    domain = getattr(args, "cert_domain", "")
    if not domain:
        return
    import os
    base = os.path.join(st.cert_dir, domain)
    cert = os.path.join(base, "fullchain.pem")
    key = os.path.join(base, "privkey.pem")
    if not (os.path.exists(cert) and os.path.exists(key)):
        print(f"✘ Sertifikat untuk '{domain}' tidak ditemukan di {base}\n"
              f"  Terbitkan dulu: sudo bash ssl.sh -d {domain} -e EMAIL -k GLOBAL_API_KEY",
              file=sys.stderr)
        sys.exit(1)
    args.cert = args.cert or cert
    args.key = args.key or key
    args.sni = args.sni or domain
    if args.security == "none":
        args.security = "tls"


def cmd_inbound_add(db, st, args):
    _resolve_cert_domain(st, args)
    opts = {
        "path": args.path, "host": args.host, "sni": args.sni,
        "cert_file": args.cert, "key_file": args.key, "dest": args.dest,
        "method": args.method, "fp": args.fp,
        "dest_address": args.dest_address, "dest_port": args.dest_port,
        "header_type": args.header_type,
    }
    opts = {k: v for k, v in opts.items() if v}
    try:
        ib = manager.add_inbound(
            db, st, protocol=args.protocol, port=args.port, remark=args.remark,
            listen=args.listen, network=args.network, security=args.security,
            opts=opts, expiry_ms=_parse_expiry(args),
            total_bytes=int(args.total_gb * 1024 ** 3) if args.total_gb else 0,
            apply_now=False)
    except manager.ManagerError as e:
        print(f"✘ {e}", file=sys.stderr)
        sys.exit(1)
    print(f"✔ Inbound #{ib['id']} [{ib['tag']}] {ib['protocol']} port {ib['port']} dibuat.")
    stream = jloads(ib["stream_settings"], {})
    if stream.get("security") == "reality":
        r = stream["realitySettings"]
        rc = r.get("settings") or {}  # field klien
        print(f"  REALITY publicKey : {rc.get('publicKey') or r.get('publicKey')}")
        print(f"  REALITY shortId   : {(r.get('shortIds') or [''])[0]}")
        print(f"  dest/SNI          : {r.get('dest')} / {(r.get('serverNames') or [''])[0]}")
    _apply_and_report(db, st)


def cmd_inbound_add_raw(db, st, args):
    raw = json.load(open(args.file)) if args.file != "-" else json.load(sys.stdin)
    try:
        ib = manager.add_inbound_raw(db, st, raw, remark=args.remark, apply_now=False)
    except manager.ManagerError as e:
        print(f"✘ {e}", file=sys.stderr)
        sys.exit(1)
    print(f"✔ Inbound raw #{ib['id']} [{ib['tag']}] dibuat.")
    _apply_and_report(db, st)


def cmd_inbound_del(db, st, args):
    manager.delete_inbound(db, st, args.id, apply_now=False)
    print(f"✔ Inbound #{args.id} dihapus (beserta client-nya).")
    _apply_and_report(db, st)


def cmd_inbound_show(db, st, args):
    ib = manager.get_inbound(db, args.id)
    print(json.dumps(manager.inbound_view(db, ib), indent=2))


def cmd_inbound_toggle(db, st, args, enable):
    manager.update_inbound(db, st, args.id, {"enable": 1 if enable else 0},
                           apply_now=False)
    print(f"✔ Inbound #{args.id} {'diaktifkan' if enable else 'dinonaktifkan'}.")
    _apply_and_report(db, st)


def cmd_inbound_reset(db, st, args):
    manager.reset_inbound_traffic(db, args.id, include_clients=not args.keep_clients)
    print(f"✔ Traffic inbound #{args.id} direset.")
    _apply_and_report(db, st)


# ------------------------------ client -------------------------------------

def cmd_client_list(db, st, args):
    if args.inbound:
        rows = db.query("SELECT * FROM clients WHERE inbound_id=? ORDER BY id",
                        (args.inbound,))
    else:
        rows = db.query("SELECT * FROM clients ORDER BY inbound_id, id")
    online = set(manager.onlines(db, st))
    _table(
        ["ID", "EMAIL", "INB", "USAGE", "QUOTA", "IPLIM", "EXPIRED", "ON", "NET"],
        [[c["id"], c["email"], c["inbound_id"],
          _fmt_bytes(c["up"] + c["down"]),
          _fmt_bytes(c["total_gb"]) if c["total_gb"] else "∞",
          c["limit_ip"] or "∞",
          _fmt_expiry(c["expiry_time"]),
          "✔" if c["enable"] else "✘",
          "●" if c["email"] in online else "○"]
         for c in rows])


def cmd_client_add(db, st, args):
    try:
        c = manager.add_client(
            db, st, args.inbound, email=args.email or "",
            uuid=args.uuid or "", password=args.password or "",
            flow=args.flow or "", limit_ip=args.limit_ip,
            total_bytes=int(args.gb * 1024 ** 3) if args.gb else 0,
            expiry_ms=_parse_expiry(args), apply_now=False)
    except manager.ManagerError as e:
        print(f"✘ {e}", file=sys.stderr)
        sys.exit(1)
    print(f"✔ Client '{c['email']}' dibuat di inbound #{args.inbound}.")
    print(f"  kuota  : {_fmt_bytes(c['total_gb']) if c['total_gb'] else 'unlimited'}")
    print(f"  expired: {_fmt_expiry(c['expiry_time'])}")
    print(f"  limitIP: {c['limit_ip'] or 'unlimited'}")
    _apply_and_report(db, st)
    ib = manager.get_inbound(db, args.inbound)
    link = links.share_link(st, ib, c)
    print("\nShare link/config:\n" + link)
    if args.qr:
        try:
            print(links.qr_terminal(link))
        except ImportError:
            print("(package qrcode belum terpasang — QR dilewati)")


def cmd_client_update(db, st, args):
    fields = {}
    if args.email_new:
        fields["email"] = args.email_new
    if args.gb is not None:
        fields["totalGB"] = int(args.gb * 1024 ** 3)
    if args.limit_ip is not None:
        fields["limitIp"] = args.limit_ip
    exp = _parse_expiry(args)
    if exp:
        fields["expiryTime"] = exp
    if args.add_days:
        c = manager.get_client(db, args.email)
        base = c["expiry_time"] if c["expiry_time"] > now_ms() else now_ms()
        fields["expiryTime"] = base + int(args.add_days * 86400000)
    if not fields:
        print("Tidak ada perubahan. Lihat: xm client update -h")
        return
    c = manager.update_client(db, st, args.email, fields, apply_now=False)
    print(f"✔ Client '{c['email']}' diperbarui. Expired: {_fmt_expiry(c['expiry_time'])}")
    _apply_and_report(db, st)


def cmd_client_del(db, st, args):
    manager.delete_client(db, st, args.email, apply_now=False)
    print(f"✔ Client '{args.email}' dihapus.")
    _apply_and_report(db, st)


def cmd_client_show(db, st, args):
    c = manager.get_client(db, args.email)
    print(json.dumps(manager.client_view(c), indent=2))


def cmd_client_link(db, st, args):
    c = manager.get_client(db, args.email)
    ib = manager.get_inbound(db, c["inbound_id"])
    link = links.share_link(st, ib, c)
    print(link)
    if args.qr:
        try:
            print(links.qr_terminal(link))
        except ImportError:
            print("(package qrcode belum terpasang — QR dilewati)")


def cmd_client_reset(db, st, args):
    manager.reset_client_traffic(db, st, args.email, apply_now=False)
    print(f"✔ Traffic '{args.email}' direset.")
    _apply_and_report(db, st)


def cmd_client_toggle(db, st, args, enable):
    manager.update_client(db, st, args.email, {"enable": enable}, apply_now=False)
    print(f"✔ Client '{args.email}' {'diaktifkan' if enable else 'dinonaktifkan'}.")
    _apply_and_report(db, st)


def cmd_client_ips(db, st, args):
    row = db.query_one("SELECT * FROM client_ips WHERE email=?", (args.email,))
    ips = jloads(row["ips"], []) if row else []
    print("\n".join(ips) if ips else "(belum ada IP tercatat)")


# ------------------------------ outbound / routing -------------------------

def cmd_outbound_list(db, st, args):
    rows = db.query("SELECT * FROM outbounds ORDER BY id")
    _table(["ID", "TAG", "PROTO", "UP", "DOWN", "ON"],
           [[o["id"], o["tag"], jloads(o["config"], {}).get("protocol", "?"),
             _fmt_bytes(o["up"]), _fmt_bytes(o["down"]),
             "✔" if o["enable"] else "✘"] for o in rows])


def cmd_outbound_add(db, st, args):
    conf = json.load(open(args.file)) if args.file != "-" else json.load(sys.stdin)
    tag = args.tag or conf.get("tag")
    if not tag:
        print("✘ Outbound butuh tag (--tag atau field 'tag' di JSON).", file=sys.stderr)
        sys.exit(1)
    db.execute(
        "INSERT INTO outbounds(tag, config, enable) VALUES(?,?,1) "
        "ON CONFLICT(tag) DO UPDATE SET config=excluded.config, enable=1",
        (tag, json.dumps(conf)))
    print(f"✔ Outbound '{tag}' disimpan.")
    _apply_and_report(db, st)


def cmd_outbound_del(db, st, args):
    db.execute("DELETE FROM outbounds WHERE tag=?", (args.tag,))
    print(f"✔ Outbound '{args.tag}' dihapus.")
    _apply_and_report(db, st)


def cmd_route_list(db, st, args):
    rows = db.query("SELECT * FROM routing_rules ORDER BY sort, id")
    _table(["ID", "REMARK", "RULE", "ON"],
           [[r["id"], r["remark"], r["rule"][:70], "✔" if r["enable"] else "✘"]
            for r in rows])


def cmd_route_add(db, st, args):
    rule = json.loads(args.json) if args.json else json.load(open(args.file))
    db.execute("INSERT INTO routing_rules(remark, rule, sort) VALUES(?,?,?)",
               (args.remark, json.dumps(rule), args.sort))
    print("✔ Routing rule ditambahkan.")
    _apply_and_report(db, st)


def cmd_route_del(db, st, args):
    db.execute("DELETE FROM routing_rules WHERE id=?", (args.id,))
    print(f"✔ Routing rule #{args.id} dihapus.")
    _apply_and_report(db, st)


def cmd_balancer_add(db, st, args):
    conf = json.load(open(args.file)) if args.file != "-" else json.load(sys.stdin)
    db.execute("INSERT INTO balancers(config) VALUES(?)", (json.dumps(conf),))
    print("✔ Balancer ditambahkan.")
    _apply_and_report(db, st)


def cmd_balancer_list(db, st, args):
    for b in db.query("SELECT * FROM balancers"):
        print(f"#{b['id']}: {b['config']}")


def cmd_balancer_del(db, st, args):
    db.execute("DELETE FROM balancers WHERE id=?", (args.id,))
    print(f"✔ Balancer #{args.id} dihapus.")
    _apply_and_report(db, st)


# ------------------------------ token / user / settings --------------------

def cmd_token_create(db, st, args):
    token = "xm_" + secrets.token_urlsafe(32)
    db.execute("INSERT INTO tokens(name, token_hash, created_at) VALUES(?,?,?)",
               (args.name, crypto.hash_token(token), now_ms()))
    print("✔ Token API dibuat. SIMPAN — hanya ditampilkan sekali:")
    print(token)


def cmd_token_list(db, st, args):
    _table(["ID", "NAME", "ENABLED"],
           [[t["id"], t["name"], "✔" if t["enabled"] else "✘"]
            for t in db.query("SELECT * FROM tokens")])


def cmd_token_del(db, st, args):
    db.execute("DELETE FROM tokens WHERE name=?", (args.name,))
    print(f"✔ Token '{args.name}' dihapus.")


def cmd_user_set_password(db, st, args):
    pw = args.password or getpass.getpass("Password baru: ")
    st["password_hash"] = crypto.hash_password(pw)
    if args.username:
        st["username"] = args.username
    st.save()
    print("✔ Kredensial login panel diperbarui. Restart service: "
          "systemctl restart xray-manager")


def cmd_cert_list(db, st, args):
    import datetime as _dt
    import os
    import ssl as _ssl
    root = st.cert_dir
    if not os.path.isdir(root):
        print(f"(belum ada sertifikat di {root})")
        print("Terbitkan: sudo bash ssl.sh -d DOMAIN -e EMAIL -k GLOBAL_API_KEY")
        return
    rows = []
    for domain in sorted(os.listdir(root)):
        full = os.path.join(root, domain, "fullchain.pem")
        if not os.path.exists(full):
            continue
        expiry = "?"
        try:
            data = _ssl._ssl._test_decode_cert(full)  # type: ignore[attr-defined]
            expiry = _dt.datetime.strptime(
                data["notAfter"], "%b %d %H:%M:%S %Y %Z").strftime("%Y-%m-%d")
        except Exception:
            pass
        rows.append([domain, expiry, os.path.join(root, domain)])
    if not rows:
        print(f"(belum ada sertifikat di {root})")
        return
    _table(["DOMAIN", "EXPIRED", "PATH"], rows)


def cmd_cert_path(db, st, args):
    import os
    base = os.path.join(st.cert_dir, args.domain)
    cert = os.path.join(base, "fullchain.pem")
    key = os.path.join(base, "privkey.pem")
    if not (os.path.exists(cert) and os.path.exists(key)):
        print(f"✘ Sertifikat '{args.domain}' tidak ada di {base}", file=sys.stderr)
        print(f"  Terbitkan: sudo bash ssl.sh -d {args.domain} -e EMAIL -k GLOBAL_API_KEY",
              file=sys.stderr)
        sys.exit(1)
    print(f"cert: {cert}")
    print(f"key : {key}")


def cmd_settings_show(db, st, args):
    view = dict(st)
    view["password_hash"] = "***" if view.get("password_hash") else ""
    view["secret"] = "***"
    print(json.dumps(view, indent=2))


def cmd_settings_set(db, st, args):
    if args.key not in settings_mod.DEFAULTS:
        print(f"✘ Key tidak dikenal: {args.key}", file=sys.stderr)
        print("  Pilihan: " + ", ".join(sorted(settings_mod.DEFAULTS)), file=sys.stderr)
        sys.exit(1)
    default = settings_mod.DEFAULTS[args.key]
    val = args.value
    if isinstance(default, bool):
        val = val.lower() in ("1", "true", "yes")
    elif isinstance(default, int):
        val = int(val)
    st[args.key] = val
    st.save()
    print(f"✔ {args.key} = {val!r} tersimpan. Restart service agar aktif: "
          "systemctl restart xray-manager")


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _add_expiry_args(p):
    p.add_argument("--days", type=float, help="masa aktif N hari dari sekarang")
    p.add_argument("--expire", help="tanggal expired YYYY-MM-DD")
    p.add_argument("--start-on-use", action="store_true",
                   help="countdown --days dimulai saat client pertama kali dipakai")


def build_parser():
    p = argparse.ArgumentParser(
        prog="xm", description="OceanShark Xray Manager — CLI")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="ringkasan status").set_defaults(fn=cmd_status)
    sub.add_parser("apply", help="rakit ulang config & restart xray").set_defaults(fn=cmd_apply)

    # inbound
    ib = sub.add_parser("inbound", help="kelola inbound").add_subparsers(
        dest="sub", required=True)
    s = ib.add_parser("list");   s.set_defaults(fn=cmd_inbound_list)
    s = ib.add_parser("add", help="buat inbound dari template")
    s.add_argument("--protocol", required=True,
                   help="vless|vmess|trojan|shadowsocks|wireguard|hysteria|socks|http|dokodemo-door")
    s.add_argument("--port", type=int, required=True)
    s.add_argument("--remark", default="")
    s.add_argument("--listen", default="")
    s.add_argument("--network", default="tcp",
                   help="tcp|kcp|ws|grpc|httpupgrade|xhttp")
    s.add_argument("--security", default="none", help="none|tls|reality")
    s.add_argument("--path", default="", help="path ws/httpupgrade/xhttp atau serviceName grpc")
    s.add_argument("--host", default="", help="Host header")
    s.add_argument("--sni", default="")
    s.add_argument("--dest", default="", help="dest REALITY, mis. yahoo.com:443")
    s.add_argument("--cert", default="", help="file fullchain.pem (tls)")
    s.add_argument("--key", default="", help="file privkey.pem (tls)")
    s.add_argument("--cert-domain", default="",
                   help="pakai sertifikat hasil ssl.sh: otomatis isi --cert/--key/--sni "
                        "dan aktifkan TLS")
    s.add_argument("--fp", default="chrome", help="uTLS fingerprint")
    s.add_argument("--method", default="", help="metode shadowsocks")
    s.add_argument("--header-type", default="none", help="none|http (tcp) / tipe header kcp")
    s.add_argument("--dest-address", default="", help="target dokodemo-door")
    s.add_argument("--dest-port", type=int, default=0, help="port target dokodemo-door")
    s.add_argument("--total-gb", type=float, default=0, help="limit trafik inbound (GB)")
    _add_expiry_args(s)
    s.set_defaults(fn=cmd_inbound_add)
    s = ib.add_parser("add-raw", help="tambah inbound dari JSON xray mentah")
    s.add_argument("file", help="path file JSON, atau - untuk stdin")
    s.add_argument("--remark", default="")
    s.set_defaults(fn=cmd_inbound_add_raw)
    s = ib.add_parser("del");    s.add_argument("id", type=int); s.set_defaults(fn=cmd_inbound_del)
    s = ib.add_parser("show");   s.add_argument("id", type=int); s.set_defaults(fn=cmd_inbound_show)
    s = ib.add_parser("enable"); s.add_argument("id", type=int)
    s.set_defaults(fn=lambda db, st, a: cmd_inbound_toggle(db, st, a, True))
    s = ib.add_parser("disable"); s.add_argument("id", type=int)
    s.set_defaults(fn=lambda db, st, a: cmd_inbound_toggle(db, st, a, False))
    s = ib.add_parser("reset-traffic"); s.add_argument("id", type=int)
    s.add_argument("--keep-clients", action="store_true",
                   help="jangan ikut reset traffic client")
    s.set_defaults(fn=cmd_inbound_reset)

    # client
    cl = sub.add_parser("client", help="kelola client").add_subparsers(
        dest="sub", required=True)
    s = cl.add_parser("list"); s.add_argument("--inbound", type=int)
    s.set_defaults(fn=cmd_client_list)
    s = cl.add_parser("add", help="tambah client")
    s.add_argument("--inbound", type=int, required=True, help="ID inbound")
    s.add_argument("--email", default="", help="nama/email unik client")
    s.add_argument("--uuid", default="", help="UUID (otomatis bila kosong)")
    s.add_argument("--password", default="", help="password (otomatis bila kosong)")
    s.add_argument("--flow", default="", help="mis. xtls-rprx-vision")
    s.add_argument("--gb", type=float, default=0, help="kuota trafik GB (0=unlimited)")
    s.add_argument("--limit-ip", type=int, default=0, help="maks IP bersamaan (0=unlimited)")
    s.add_argument("--qr", action="store_true", help="cetak QR di terminal")
    _add_expiry_args(s)
    s.set_defaults(fn=cmd_client_add)
    s = cl.add_parser("update", help="ubah client")
    s.add_argument("email")
    s.add_argument("--email-new", default="")
    s.add_argument("--gb", type=float, default=None)
    s.add_argument("--limit-ip", type=int, default=None)
    s.add_argument("--add-days", type=float, default=0,
                   help="perpanjang N hari dari expired sekarang")
    _add_expiry_args(s)
    s.set_defaults(fn=cmd_client_update)
    s = cl.add_parser("del");  s.add_argument("email"); s.set_defaults(fn=cmd_client_del)
    s = cl.add_parser("show"); s.add_argument("email"); s.set_defaults(fn=cmd_client_show)
    s = cl.add_parser("link"); s.add_argument("email")
    s.add_argument("--qr", action="store_true"); s.set_defaults(fn=cmd_client_link)
    s = cl.add_parser("reset-traffic"); s.add_argument("email")
    s.set_defaults(fn=cmd_client_reset)
    s = cl.add_parser("enable"); s.add_argument("email")
    s.set_defaults(fn=lambda db, st, a: cmd_client_toggle(db, st, a, True))
    s = cl.add_parser("disable"); s.add_argument("email")
    s.set_defaults(fn=lambda db, st, a: cmd_client_toggle(db, st, a, False))
    s = cl.add_parser("ips", help="IP yang dipakai client"); s.add_argument("email")
    s.set_defaults(fn=cmd_client_ips)

    # outbound
    ob = sub.add_parser("outbound", help="kelola outbound (WARP, proxy chain, dll)")
    obs = ob.add_subparsers(dest="sub", required=True)
    s = obs.add_parser("list"); s.set_defaults(fn=cmd_outbound_list)
    s = obs.add_parser("add", help="tambah outbound dari file JSON")
    s.add_argument("file", help="path JSON atau - untuk stdin")
    s.add_argument("--tag", default="")
    s.set_defaults(fn=cmd_outbound_add)
    s = obs.add_parser("del"); s.add_argument("tag"); s.set_defaults(fn=cmd_outbound_del)

    # routing
    rt = sub.add_parser("route", help="kelola routing rules").add_subparsers(
        dest="sub", required=True)
    s = rt.add_parser("list"); s.set_defaults(fn=cmd_route_list)
    s = rt.add_parser("add")
    s.add_argument("--json", default="", help="rule JSON inline")
    s.add_argument("--file", default="", help="path file JSON rule")
    s.add_argument("--remark", default="")
    s.add_argument("--sort", type=int, default=100)
    s.set_defaults(fn=cmd_route_add)
    s = rt.add_parser("del"); s.add_argument("id", type=int); s.set_defaults(fn=cmd_route_del)

    # balancer
    bl = sub.add_parser("balancer", help="load balancer outbound").add_subparsers(
        dest="sub", required=True)
    s = bl.add_parser("list"); s.set_defaults(fn=cmd_balancer_list)
    s = bl.add_parser("add"); s.add_argument("file"); s.set_defaults(fn=cmd_balancer_add)
    s = bl.add_parser("del"); s.add_argument("id", type=int); s.set_defaults(fn=cmd_balancer_del)

    # token
    tk = sub.add_parser("token", help="token API untuk web/sinkronisasi").add_subparsers(
        dest="sub", required=True)
    s = tk.add_parser("create"); s.add_argument("name"); s.set_defaults(fn=cmd_token_create)
    s = tk.add_parser("list"); s.set_defaults(fn=cmd_token_list)
    s = tk.add_parser("del"); s.add_argument("name"); s.set_defaults(fn=cmd_token_del)

    # cert
    ct = sub.add_parser("cert", help="sertifikat TLS (diterbitkan ssl.sh)").add_subparsers(
        dest="sub", required=True)
    s = ct.add_parser("list", help="daftar sertifikat terpasang")
    s.set_defaults(fn=cmd_cert_list)
    s = ct.add_parser("path", help="tampilkan path cert/key sebuah domain")
    s.add_argument("domain")
    s.set_defaults(fn=cmd_cert_path)

    # user & settings
    us = sub.add_parser("user", help="akun login panel").add_subparsers(
        dest="sub", required=True)
    s = us.add_parser("set-password")
    s.add_argument("--username", default="")
    s.add_argument("--password", default="")
    s.set_defaults(fn=cmd_user_set_password)

    se = sub.add_parser("settings", help="konfigurasi aplikasi").add_subparsers(
        dest="sub", required=True)
    s = se.add_parser("show"); s.set_defaults(fn=cmd_settings_show)
    s = se.add_parser("set"); s.add_argument("key"); s.add_argument("value")
    s.set_defaults(fn=cmd_settings_set)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    st = settings_mod.load()
    db = DB(st.db_path)
    try:
        args.fn(db, st, args)
    except manager.ManagerError as e:
        print(f"✘ {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
