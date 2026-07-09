"""Background jobs: polling statistik, enforcement expired/kuota,
status online, limit IP (fail2ban), traffic reset terjadwal, push webhook."""

import json
import logging
import os
import re
import threading
import time
import urllib.parse
import urllib.request

from . import config_builder, manager, xray_api
from .db import DB, jloads, now_ms

log = logging.getLogger("xraym.jobs")

# contoh baris access log xray:
# 2026/07/08 10:00:00.000000 from 1.2.3.4:54321 accepted tcp:site.com:443 [in-vless-443 -> direct] email: budi
_ACCESS_RE = re.compile(
    r"from (?:tcp:|udp:)?\[?([0-9a-fA-F\.:]+?)\]?:\d+ accepted .*email: (\S+)")


class JobRunner:
    def __init__(self, db: DB, settings):
        self.db = db
        self.settings = settings
        self.stop_event = threading.Event()
        self._ip_window = {}      # email -> {ip: last_seen_epoch}
        self._log_offset = int(db.kv_get("access_log_offset", 0) or 0)
        self._log_inode = int(db.kv_get("access_log_inode", 0) or 0)
        self._last_push = 0.0

    # ------------------------------------------------------------------
    def start(self):
        t = threading.Thread(target=self._loop, daemon=True, name="xm-jobs")
        t.start()
        return t

    def stop(self):
        self.stop_event.set()

    def _loop(self):
        while not self.stop_event.wait(self.settings.job_interval):
            try:
                self.run_once()
            except Exception:  # jangan pernah mematikan loop
                log.exception("job error")

    # ------------------------------------------------------------------
    def run_once(self):
        self._collect_stats()
        self._check_ip_limits()
        changed = self._enforce()
        self._scheduled_resets()
        if changed:
            ok, msg = manager.apply(self.db, self.settings)
            if not ok:
                log.error("apply gagal: %s", msg)
        self._push_snapshot_if_due()

    # ------------------------------------------------------------------
    # 1. Statistik trafik (xray api statsquery -reset)
    # ------------------------------------------------------------------
    def _collect_stats(self):
        try:
            stats = xray_api.stats_query(self.settings, reset=True)
        except xray_api.XrayError as e:
            log.debug("statsquery gagal (xray belum jalan?): %s", e)
            return
        now = now_ms()
        for item in stats:
            parts = item["name"].split(">>>")
            if len(parts) != 4 or parts[2] != "traffic":
                continue
            kind, name, _, direction = parts
            col = "up" if direction == "uplink" else "down"
            if kind == "user":
                self.db.execute(
                    f"UPDATE clients SET {col}={col}+?, online_at=? WHERE email=?",
                    (item["value"], now, name))
                # expiry negatif = countdown mulai saat pertama kali dipakai
                row = self.db.query_one(
                    "SELECT id, expiry_time FROM clients WHERE email=?", (name,))
                if row and row["expiry_time"] < 0:
                    new_exp = now + abs(row["expiry_time"])
                    self.db.execute("UPDATE clients SET expiry_time=? WHERE id=?",
                                    (new_exp, row["id"]))
            elif kind == "inbound" and name != "api-in":
                self.db.execute(
                    f"UPDATE inbounds SET {col}={col}+? WHERE tag=?",
                    (item["value"], name))
            elif kind == "outbound":
                # Hanya update counter outbound yang tersimpan di DB.
                # 'direct'/'blocked' default tidak punya baris → stats-nya
                # diabaikan (jangan buat baris config kosong yang merusak config).
                self.db.execute(
                    f"UPDATE outbounds SET {col}={col}+? WHERE tag=?",
                    (item["value"], name))

    # ------------------------------------------------------------------
    # 2. Enforcement expired & kuota
    # ------------------------------------------------------------------
    def _enforce(self) -> bool:
        """Bandingkan set client/inbound aktif dengan yang terakhir
        diterapkan; kirim webhook untuk yang baru dinonaktifkan."""
        now = now_ms()
        active = set()
        for c in self.db.query("SELECT * FROM clients"):
            if config_builder.client_is_active(c, now):
                active.add(c["email"])
        for ib in self.db.query("SELECT * FROM inbounds WHERE enable=1"):
            if (ib["expiry_time"] > 0 and ib["expiry_time"] <= now) or \
               (ib["total"] > 0 and ib["up"] + ib["down"] >= ib["total"]):
                active.add(f"__inbound_expired__{ib['id']}")

        prev = set(json.loads(self.db.kv_get("last_active_set", "[]")))
        if active == prev:
            return False

        # Webhook untuk client yang baru nonaktif
        for email in prev - active:
            if email.startswith("__inbound_expired__"):
                continue
            c = self.db.query_one("SELECT * FROM clients WHERE email=?", (email,))
            if not c or not c["enable"]:
                continue  # dihapus / dimatikan manual
            reason = "expired"
            if c["total_gb"] > 0 and c["up"] + c["down"] >= c["total_gb"]:
                reason = "quota"
            log.info("client %s dinonaktifkan otomatis (%s)", email, reason)
            self._webhook({
                "event": "client_disabled",
                "email": email,
                "reason": reason,
                "up": c["up"], "down": c["down"],
                "totalGB": c["total_gb"],
                "expiryTime": c["expiry_time"],
            })
            label = "kuota habis" if reason == "quota" else "masa aktif berakhir"
            self._telegram(f"⚠️ Client *{email}* dinonaktifkan otomatis ({label}).")

        self.db.kv_set("last_active_set", json.dumps(sorted(active)))
        return True

    # ------------------------------------------------------------------
    # 3. Traffic reset terjadwal per-inbound (daily/weekly/monthly)
    # ------------------------------------------------------------------
    def _scheduled_resets(self):
        periods = {"daily": 86400, "weekly": 7 * 86400, "monthly": 30 * 86400}
        now = now_ms()
        for ib in self.db.query(
                "SELECT id, traffic_reset, last_reset FROM inbounds "
                "WHERE traffic_reset != 'never'"):
            period = periods.get(ib["traffic_reset"])
            if period and now - (ib["last_reset"] or 0) >= period * 1000:
                manager.reset_inbound_traffic(self.db, ib["id"])
                log.info("traffic reset otomatis inbound #%s (%s)",
                         ib["id"], ib["traffic_reset"])

    # ------------------------------------------------------------------
    # 4. Limit IP per client — tulis pelanggaran untuk fail2ban
    # ------------------------------------------------------------------
    def _check_ip_limits(self):
        path = self.settings.xray_access_log
        if not path or not os.path.exists(path):
            return
        try:
            st = os.stat(path)
            if st.st_ino != self._log_inode:      # file dirotasi
                self._log_inode, self._log_offset = st.st_ino, 0
            if st.st_size < self._log_offset:      # file dipotong
                self._log_offset = 0
            with open(path, "r", errors="replace") as f:
                f.seek(self._log_offset)
                chunk = f.read(8 * 1024 * 1024)   # maks 8MB per siklus
                self._log_offset = f.tell()
        except OSError as e:
            log.debug("gagal baca access log: %s", e)
            return
        self.db.kv_set("access_log_offset", self._log_offset)
        self.db.kv_set("access_log_inode", self._log_inode)

        now = time.time()
        for m in _ACCESS_RE.finditer(chunk):
            ip, email = m.group(1), m.group(2)
            if ip.startswith("127.") or ip == "::1":
                continue
            self._ip_window.setdefault(email, {})[ip] = now

        window = self.settings.ip_limit_window
        limits = {c["email"]: c["limit_ip"] for c in
                  self.db.query("SELECT email, limit_ip FROM clients")}
        violations = []
        for email, ips in list(self._ip_window.items()):
            # buang IP di luar jendela waktu
            for ip, seen in list(ips.items()):
                if now - seen > window:
                    del ips[ip]
            if not ips:
                del self._ip_window[email]
                continue
            self.db.execute(
                "INSERT INTO client_ips(email, ips, updated_at) VALUES(?,?,?) "
                "ON CONFLICT(email) DO UPDATE SET ips=excluded.ips, "
                "updated_at=excluded.updated_at",
                (email, json.dumps(sorted(ips)), now_ms()))
            limit = limits.get(email, 0)
            if limit and len(ips) > limit:
                # IP paling lama dipertahankan; sisanya dianggap pelanggar
                ordered = sorted(ips.items(), key=lambda kv: kv[1])
                for ip, _ in ordered[limit:]:
                    violations.append((email, ip))

        if violations:
            self._write_violations(violations)

    def _write_violations(self, violations):
        path = self.settings.ip_limit_log
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            stamp = time.strftime("%Y/%m/%d %H:%M:%S")
            with open(path, "a") as f:
                for email, ip in violations:
                    # Format sama dengan 3x-ui agar filter fail2ban kompatibel
                    f.write(f"{stamp} [LIMIT_IP] Email = {email} || SRC = {ip}\n")
                    log.warning("LIMIT_IP %s melebihi batas, IP %s dicatat", email, ip)
        except OSError as e:
            log.error("gagal tulis ip-limit log: %s", e)

    # ------------------------------------------------------------------
    # 5. Push webhook ke web API (opsional)
    # ------------------------------------------------------------------
    def _webhook(self, payload: dict):
        url = self.settings.webhook_url
        if not url:
            return
        try:
            body = json.dumps(payload).encode()
            req = urllib.request.Request(
                url, data=body, method="POST",
                headers={"Content-Type": "application/json",
                         "X-API-KEY": self.settings.webhook_api_key})
            urllib.request.urlopen(req, timeout=10).read()
        except Exception as e:
            log.warning("webhook gagal: %s", e)

    def _telegram(self, text: str):
        """Kirim notifikasi ke Telegram bila diaktifkan (tanpa dependensi luar)."""
        s = self.settings
        if not s.get("tg_enable") or not s.get("tg_bot_token") or not s.get("tg_chat_id"):
            return
        try:
            url = f"https://api.telegram.org/bot{s['tg_bot_token']}/sendMessage"
            data = urllib.parse.urlencode({
                "chat_id": s["tg_chat_id"], "text": text,
                "parse_mode": "Markdown",
            }).encode()
            urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10).read()
        except Exception as e:
            log.warning("telegram gagal: %s", e)

    def _push_snapshot_if_due(self):
        interval = self.settings.sync_push_interval
        if not interval or not self.settings.webhook_url:
            return
        if time.time() - self._last_push < interval:
            return
        self._last_push = time.time()
        clients = [manager.client_view(c)
                   for c in self.db.query("SELECT * FROM clients")]
        traffics = [manager.client_traffic_view(c)
                    for c in self.db.query("SELECT * FROM clients")]
        self._webhook({
            "event": "snapshot",
            "clients": clients,
            "traffics": traffics,
            "onlines": manager.onlines(self.db, self.settings),
            "at": now_ms(),
        })
