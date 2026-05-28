from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.config import settings
from app.db.session import Base, engine

app = FastAPI(
    title=settings.app_name,
    docs_url="/docs" if settings.api_docs_enabled else None,
    redoc_url="/redoc" if settings.api_docs_enabled else None,
    openapi_url="/openapi.json" if settings.api_docs_enabled else None,
)

app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts or ["*"])

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if settings.force_https_redirect:
    app.add_middleware(HTTPSRedirectMiddleware)


@app.middleware("http")
async def set_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


@app.on_event("startup")
def on_startup() -> None:
    if settings.environment == "production":
        if settings.auth_jwt_secret_key == "change-me-in-production":
            raise RuntimeError("AUTH_JWT_SECRET_KEY inseguro para producción.")
        if settings.auth_debug_return_reset_token:
            raise RuntimeError("AUTH_DEBUG_RETURN_RESET_TOKEN debe estar en false en producción.")
        if not settings.auth_allowed_emails:
            raise RuntimeError("AUTH_ALLOWED_EMAILS no puede estar vacío en producción.")
    Base.metadata.create_all(bind=engine)


@app.get("/healthz")
def healthz() -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "vige-backend"})


app.include_router(router, prefix="/api", tags=["vige"])
