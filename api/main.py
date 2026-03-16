"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import CORS_ORIGINS
from .database import init_db
from .routers import auth, strategies, datasets, runs, results, prompts, uploads, settings, subjects


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup."""
    init_db()
    # Load dynamic strategies for custom subjects
    from .services.strategy_service import ensure_dynamic_strategies_loaded
    ensure_dynamic_strategies_loaded()
    yield


app = FastAPI(
    title="Marking Eval API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router)
app.include_router(strategies.router)
app.include_router(datasets.router)
app.include_router(runs.router)
app.include_router(results.router)
app.include_router(prompts.router)
app.include_router(uploads.router)
app.include_router(settings.router)
app.include_router(subjects.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
