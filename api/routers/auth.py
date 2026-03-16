"""Authentication router."""

from fastapi import APIRouter, HTTPException

from ..auth import verify_password, create_token
from ..config import APP_PASSWORD_HASH
from ..models import LoginRequest, LoginResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    if not APP_PASSWORD_HASH:
        raise HTTPException(status_code=500, detail="No password configured. Set APP_PASSWORD_HASH in .env")

    if not verify_password(req.password, APP_PASSWORD_HASH):
        raise HTTPException(status_code=401, detail="Invalid password")

    token, expires_at = create_token()
    return LoginResponse(token=token, expires_at=expires_at.isoformat())
