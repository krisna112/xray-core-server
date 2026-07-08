"""SQLite storage — skema & helper."""

import json
import os
import sqlite3
import threading
import time

_lock = threading.RLock()
_conn = None
_db_path = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS inbounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tag TEXT UNIQUE NOT NULL,
    remark TEXT DEFAULT '',
    enable INTEGER DEFAULT 1,
    listen TEXT DEFAULT '',
    port INTEGER NOT NULL,
    protocol TEXT NOT NULL,
    settings TEXT DEFAULT '{}',           -- JSON: opsi protokol (non-client)
    stream_settings TEXT DEFAULT '{}',    -- JSON: streamSettings lengkap
    sniffing TEXT DEFAULT '',             -- JSON
    share_addr TEXT DEFAULT '',           -- override alamat share link (opsional)
    total INTEGER DEFAULT 0,              -- limit trafik inbound (bytes, 0=unlimited)
    expiry_time INTEGER DEFAULT 0,        -- epoch ms, 0=selamanya
    up INTEGER DEFAULT 0,
    down INTEGER DEFAULT 0,
    traffic_reset TEXT DEFAULT 'never',   -- never|daily|weekly|monthly
    last_reset INTEGER DEFAULT 0,
    created_at INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inbound_id INTEGER NOT NULL,
    email TEXT UNIQUE NOT NULL,
    uuid TEXT DEFAULT '',                 -- vless/vmess id
    password TEXT DEFAULT '',             -- trojan/shadowsocks/socks/http
    flow TEXT DEFAULT '',
    enable INTEGER DEFAULT 1,
    limit_ip INTEGER DEFAULT 0,           -- 0 = tanpa batas
    total_gb INTEGER DEFAULT 0,           -- limit trafik BYTES (nama ala 3x-ui), 0=unlimited
    expiry_time INTEGER DEFAULT 0,        -- epoch ms; 0=selamanya; negatif = mulai saat pertama dipakai
    up INTEGER DEFAULT 0,
    down INTEGER DEFAULT 0,
    sub_id TEXT DEFAULT '',
    tg_id TEXT DEFAULT '',
    extra TEXT DEFAULT '{}',              -- JSON: data spesifik protokol (kunci wireguard dll.)
    online_at INTEGER DEFAULT 0,          -- epoch ms terakhir terlihat aktif
    created_at INTEGER DEFAULT 0,
    updated_at INTEGER DEFAULT 0,
    FOREIGN KEY (inbound_id) REFERENCES inbounds(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS client_ips (
    email TEXT PRIMARY KEY,
    ips TEXT DEFAULT '[]',
    updated_at INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS outbounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tag TEXT UNIQUE NOT NULL,
    config TEXT NOT NULL,                 -- JSON outbound lengkap
    enable INTEGER DEFAULT 1,
    up INTEGER DEFAULT 0,
    down INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS routing_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    remark TEXT DEFAULT '',
    rule TEXT NOT NULL,                   -- JSON rule lengkap
    enable INTEGER DEFAULT 1,
    sort INTEGER DEFAULT 100
);

CREATE TABLE IF NOT EXISTS balancers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config TEXT NOT NULL                  -- JSON balancer lengkap
);

CREATE TABLE IF NOT EXISTS tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    token_hash TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,
    created_at INTEGER DEFAULT 0
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    """Buka (sekali) koneksi global thread-safe."""
    global _conn, _db_path
    with _lock:
        if _conn is not None and _db_path == db_path:
            return _conn
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(SCHEMA)
        conn.commit()
        _conn, _db_path = conn, db_path
        return conn


class DB:
    def __init__(self, db_path: str):
        self.conn = connect(db_path)

    def execute(self, sql, params=()):
        with _lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur

    def query(self, sql, params=()):
        with _lock:
            return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def query_one(self, sql, params=()):
        rows = self.query(sql, params)
        return rows[0] if rows else None

    # -- key/value kecil (offset log, dsb.) --
    def kv_get(self, key, default=None):
        row = self.query_one("SELECT value FROM kv WHERE key=?", (key,))
        return row["value"] if row else default

    def kv_set(self, key, value):
        self.execute(
            "INSERT INTO kv(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )


def now_ms() -> int:
    return int(time.time() * 1000)


def jloads(text, default=None):
    if isinstance(text, (dict, list)):
        return text
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default if default is not None else {}
