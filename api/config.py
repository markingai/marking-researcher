"""API-specific configuration."""

import os
import secrets
from pathlib import Path

# Load .env from project root
_project_root = Path(__file__).parent.parent
_env_path = _project_root / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _val = _line.split("=", 1)
            os.environ.setdefault(_key.strip(), _val.strip())

# Paths
PROJECT_ROOT = _project_root
API_DIR = Path(__file__).parent
DB_PATH = Path(os.environ.get("DB_PATH", str(API_DIR / "marking_eval.db")))
UPLOADS_DIR = Path(os.environ.get("UPLOADS_DIR", str(API_DIR / "uploads")))
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

# Auth
APP_PASSWORD_HASH = os.environ.get("APP_PASSWORD_HASH", "")
JWT_SECRET = os.environ.get("JWT_SECRET", secrets.token_hex(32))
JWT_EXPIRY_HOURS = 24

# Server
API_PORT = int(os.environ.get("API_PORT", "8000"))
CORS_ORIGINS = os.environ.get(
    "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
).split(",")

# Upload limits
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50MB
ALLOWED_UPLOAD_TYPES = {".pdf", ".csv"}
