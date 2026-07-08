"""Utilitas kripto: X25519 (REALITY & WireGuard), hash password, session token."""

import base64
import hashlib
import hmac
import secrets
import time
import uuid as uuidlib

# ---------------------------------------------------------------------------
# X25519 murni-Python (RFC 7748) — untuk generate keypair REALITY & WireGuard
# tanpa dependensi eksternal.
# ---------------------------------------------------------------------------

_P = 2 ** 255 - 19
_A24 = 121665


def _decode_scalar(k: bytes) -> int:
    b = bytearray(k)
    b[0] &= 248
    b[31] &= 127
    b[31] |= 64
    return int.from_bytes(b, "little")


def _decode_u(u: bytes) -> int:
    b = bytearray(u)
    b[31] &= 127
    return int.from_bytes(b, "little")


def x25519(private_key: bytes, u: bytes = None) -> bytes:
    """Scalar multiplication; u=None berarti basepoint 9 (menghasilkan public key)."""
    x1 = _decode_u(u if u is not None else (9).to_bytes(32, "little"))
    k = _decode_scalar(private_key)
    x2, z2, x3, z3 = 1, 0, x1, 1
    swap = 0
    for t in reversed(range(255)):
        kt = (k >> t) & 1
        swap ^= kt
        if swap:
            x2, x3 = x3, x2
            z2, z3 = z3, z2
        swap = kt
        a = (x2 + z2) % _P
        aa = a * a % _P
        b = (x2 - z2) % _P
        bb = b * b % _P
        e = (aa - bb) % _P
        c = (x3 + z3) % _P
        d = (x3 - z3) % _P
        da = d * a % _P
        cb = c * b % _P
        x3 = (da + cb) % _P
        x3 = x3 * x3 % _P
        z3 = (da - cb) % _P
        z3 = z3 * z3 % _P
        z3 = z3 * x1 % _P
        x2 = aa * bb % _P
        z2 = e * (aa + _A24 * e) % _P
    if swap:
        x2, x3 = x3, x2
        z2, z3 = z3, z2
    return (x2 * pow(z2, _P - 2, _P) % _P).to_bytes(32, "little")


def _clamped_private() -> bytes:
    b = bytearray(secrets.token_bytes(32))
    b[0] &= 248
    b[31] &= 127
    b[31] |= 64
    return bytes(b)


def reality_keypair() -> tuple:
    """(privateKey, publicKey) format base64url tanpa padding — dipakai Xray REALITY."""
    priv = _clamped_private()
    pub = x25519(priv)
    enc = lambda b: base64.urlsafe_b64encode(b).decode().rstrip("=")
    return enc(priv), enc(pub)


def wireguard_keypair() -> tuple:
    """(privateKey, publicKey) format base64 standar — dipakai WireGuard."""
    priv = _clamped_private()
    pub = x25519(priv)
    return base64.b64encode(priv).decode(), base64.b64encode(pub).decode()


def wireguard_pubkey(private_b64: str) -> str:
    priv = base64.b64decode(private_b64 + "=" * (-len(private_b64) % 4))
    return base64.b64encode(x25519(priv)).decode()


# ---------------------------------------------------------------------------
# Generator id/password
# ---------------------------------------------------------------------------

def gen_uuid() -> str:
    return str(uuidlib.uuid4())


def gen_password(n: int = 16) -> str:
    return secrets.token_urlsafe(n)[:n]


def gen_short_id() -> str:
    return secrets.token_hex(4)


def gen_ss2022_key(method: str) -> str:
    size = 16 if "128" in method else 32
    return base64.b64encode(secrets.token_bytes(size)).decode()


def gen_sub_id() -> str:
    return secrets.token_hex(8)


# ---------------------------------------------------------------------------
# Password hashing (PBKDF2) & token API (SHA-256)
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return f"pbkdf2$100000${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, hexhash = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iters))
        return hmac.compare_digest(dk.hex(), hexhash)
    except (ValueError, AttributeError):
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Session cookie (HMAC-signed)
# ---------------------------------------------------------------------------

def make_session(secret: str, username: str, hours: int = 24) -> str:
    payload = f"{username}|{int(time.time()) + hours * 3600}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(payload.encode()).decode() + "." + sig


def verify_session(secret: str, cookie: str) -> str:
    """Kembalikan username jika valid, string kosong jika tidak."""
    try:
        b64, sig = cookie.split(".", 1)
        payload = base64.urlsafe_b64decode(b64.encode()).decode()
        expect = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expect):
            return ""
        username, exp = payload.rsplit("|", 1)
        if int(exp) < time.time():
            return ""
        return username
    except (ValueError, TypeError):
        return ""
