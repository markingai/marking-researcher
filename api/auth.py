"""Authentication: password validation + JWT token management."""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from . import config


def hash_password(password: str) -> str:
    """Hash a password with bcrypt. Use this to generate APP_PASSWORD_HASH."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against its bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:
        return False


def create_token(subject: str = "user") -> tuple[str, datetime]:
    """Create a JWT token. Returns (token, expires_at)."""
    expires_at = datetime.now(timezone.utc) + timedelta(hours=config.JWT_EXPIRY_HOURS)
    payload = {
        "sub": subject,
        "exp": expires_at,
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, config.JWT_SECRET, algorithm="HS256")
    return token, expires_at


def verify_token(token: str) -> dict | None:
    """Verify a JWT token. Returns payload dict or None."""
    try:
        return jwt.decode(token, config.JWT_SECRET, algorithms=["HS256"])
    except jwt.InvalidTokenError:
        return None
