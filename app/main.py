"""FlueAI backend — FastAPI application factory."""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.routers import (
    ai,
    avatar,
    billing,
    health,
    learning,
    learning_intel,
    realtime,
    study,
    users,
    voice,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


def _validate_production(settings) -> None:
    """Fail fast (at boot) rather than silently running insecurely in prod."""
    if settings.app_env != "production":
        return
    missing = [
        name
        for name in ("supabase_url", "supabase_service_key")
        if not getattr(settings, name)
    ]
    # Auth needs HS256 secret OR the JWKS endpoint (derived from supabase_url).
    if not settings.supabase_jwt_secret and not settings.supabase_url:
        missing.append("supabase_jwt_secret_or_supabase_url")
    if missing:
        raise RuntimeError(f"Missing required production settings: {sorted(set(missing))}")
    origins = settings.cors_origin_list
    if not origins or "*" in origins:
        raise RuntimeError("CORS_ORIGINS must be an explicit allowlist in production (never '*').")


def create_app() -> FastAPI:
    settings = get_settings()
    _validate_production(settings)
    app = FastAPI(
        title="FlueAI Backend",
        version="0.1.0",
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url="/redoc" if settings.app_env != "production" else None,
        openapi_url="/openapi.json" if settings.app_env != "production" else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.on_event("startup")
    def _warm_speech_pipeline() -> None:
        try:
            from app.services.speech_correction import warm_speech_pipeline

            warm_speech_pipeline()
        except Exception as exc:
            logging.getLogger("flueai.startup").warning(
                "Speech pipeline warm-up skipped: %s", exc
            )

    app.include_router(health.router)
    app.include_router(ai.router)
    app.include_router(avatar.router)
    app.include_router(voice.router)
    app.include_router(realtime.router)
    app.include_router(billing.router)
    app.include_router(users.router)
    app.include_router(learning.router)
    app.include_router(learning_intel.router)
    app.include_router(study.user_router)
    app.include_router(study.content_router)
    return app


app = create_app()
