"""FastAPI dependency injection."""

from fastapi import Depends, HTTPException, Header

from .auth import verify_token


async def get_current_user(authorization: str = Header(None)) -> dict:
    """Validate JWT token from Authorization header."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    parts = authorization.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization format")

    payload = verify_token(parts[1])
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return payload
