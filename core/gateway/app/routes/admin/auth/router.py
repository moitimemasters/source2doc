from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status

from source2doc.storage.admin_sessions import AdminSession, AdminSessionStorage

from app import config as app_config
from app.routes.admin.auth.dto import LoginRequest, LoginResponse, MeResponse
from app.security import admin as admin_security


router = APIRouter(prefix="/api/v1/admin/auth", tags=["admin:auth"])


@router.post("/login", response_model=LoginResponse)
async def login_route(
    request: LoginRequest,
    response: Response,
    config: app_config.Config = Depends(app_config.get_config),
    sessions: AdminSessionStorage = Depends(admin_security.get_session_storage),
) -> LoginResponse:
    if not admin_security.verify_username(request.username, config.admin_username):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    if not admin_security.verify_password(
        request.password, config.admin_password_hash.get_secret_value()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    token = admin_security.generate_token()
    expires_at = admin_security.session_expiry(config)
    await sessions.create(admin_security.hash_token(token), expires_at)

    response.set_cookie(
        key=admin_security.COOKIE_NAME,
        value=token,
        max_age=config.session_ttl_hours * 3600,
        httponly=True,
        secure=config.cookie_secure,
        samesite="strict",
        path="/",
        domain=config.cookie_domain,
    )
    return LoginResponse()


@router.post("/logout", response_model=LoginResponse)
async def logout_route(
    response: Response,
    config: app_config.Config = Depends(app_config.get_config),
    sessions: AdminSessionStorage = Depends(admin_security.get_session_storage),
    s2d_admin: str | None = Cookie(default=None, alias=admin_security.COOKIE_NAME),
) -> LoginResponse:
    if s2d_admin:
        await sessions.delete(admin_security.hash_token(s2d_admin))
    response.delete_cookie(
        key=admin_security.COOKIE_NAME,
        path="/",
        domain=config.cookie_domain,
        secure=config.cookie_secure,
        httponly=True,
        samesite="strict",
    )
    return LoginResponse()


@router.get("/me", response_model=MeResponse)
async def me_route(
    session: AdminSession = Depends(admin_security.require_admin),
) -> MeResponse:
    return MeResponse(authenticated=True, expires_at=session.expires_at.isoformat())
