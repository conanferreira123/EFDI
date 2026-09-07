"""
Security primitives: password hashing and JWT encode/decode.

Kept separate from the auth service/router layer so these low-level
operations have zero dependency on FastAPI, the database, or business
logic -- they are pure functions over strings, which makes them trivial
to unit test in isolation.

NOTE: password hashing uses the `bcrypt` library directly rather than
passlib. passlib 1.7.4 (the latest release) probes bcrypt internals
(`bcrypt.__about__`) that were removed in bcrypt>=4.1, which raises
errors at hash-time. Calling bcrypt directly avoids that broken
compatibility shim entirely.
"""
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings

# bcrypt has a hard 72-byte input limit; truncating is the standard,
# documented mitigation (passwords longer than this still retain well
# over 72 bytes of entropy, which is more than sufficient).
_BCRYPT_MAX_BYTES = 72


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password for storage. Never store plaintext passwords."""
    password_bytes = plain_password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Check a plaintext password against a stored bcrypt hash."""
    password_bytes = plain_password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    try:
        return bcrypt.checkpw(password_bytes, password_hash.encode("utf-8"))
    except ValueError:
        # Malformed hash (e.g. corrupted data) -- treat as verification failure
        # rather than letting an exception propagate out of an auth check.
        return False


def create_access_token(*, username: str, user_id: int, role: str) -> tuple[str, int]:
    """
    Create a signed JWT access token.

    Returns (token, expires_in_seconds) so the caller (login endpoint)
    can report expiry to the client without re-deriving it.
    """
    expire_delta = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    expire_at = datetime.now(timezone.utc) + expire_delta

    payload = {
        "sub": username,
        "user_id": user_id,
        "role": role,
        "exp": expire_at,
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return token, int(expire_delta.total_seconds())


def decode_access_token(token: str) -> dict:
    """
    Decode and validate a JWT access token.

    Raises jose.JWTError (caught by the caller in app/core/dependencies.py)
    if the token is invalid, malformed, or expired.
    """
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


__all__ = [
    "hash_password",
    "verify_password",
    "create_access_token",
    "decode_access_token",
    "JWTError",
]
