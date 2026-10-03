"""Google OpenID Connect and revocable, server-side browser sessions."""
import hashlib
import secrets
import uuid
from urllib.parse import urlsplit
from datetime import datetime, timedelta, timezone

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from httpx import HTTPError
from joserfc.errors import JoseError
from starlette.responses import RedirectResponse

from app.config import settings
from app.db import get_db
from app.models import BrowserSession, User

router = APIRouter(prefix="/auth", tags=["Authentication"])
COOKIE = "audio_session"
oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET.get_secret_value(),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256"},
)


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def configured():
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET.get_secret_value())


def validate_auth_settings():
    if settings.SESSION_HOURS < 1 or settings.GUEST_RESULT_MINUTES < 1:
        raise RuntimeError("Session and guest expiry must be positive")
    endpoint = urlsplit(settings.APP_URL)
    if not endpoint.hostname or endpoint.path not in {"", "/"} or endpoint.query or endpoint.fragment or endpoint.username:
        raise RuntimeError("APP_URL must be a frontend origin without a path or credentials")
    if settings.APP_ENV == "production":
        if len(settings.AUTH_SECRET.get_secret_value()) < 32:
            raise RuntimeError("Set AUTH_SECRET to a random secret of at least 32 characters")
        if endpoint.scheme != "https":
            raise RuntimeError("APP_URL must be the public HTTPS frontend URL")
    elif endpoint.scheme not in {"http", "https"}:
        raise RuntimeError("APP_URL must be an HTTP or HTTPS frontend origin")


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


async def current_session(request: Request, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get(COOKIE)
    session = await db.get(BrowserSession, token_hash(token)) if token else None
    if session is None or session.expires_at <= now():
        raise HTTPException(401, "Your session expired. Refresh the page to continue.")
    return session


async def require_user(session: BrowserSession = Depends(current_session)):
    if not session.user_id:
        raise HTTPException(401, "Sign in to access saved recordings.")
    return session.user_id


def check_origin(request: Request):
    """Cookies authenticate the request; an Origin check prevents cross-site writes."""
    allowed = {settings.APP_URL.rstrip("/")}
    if settings.APP_ENV != "production":
        allowed.add(str(request.base_url).rstrip("/"))
    if request.headers.get("origin") not in allowed:
        raise HTTPException(403, "Request origin is not allowed.")


async def new_session(db, response, user_id=None):
    token = secrets.token_urlsafe(32)
    session = BrowserSession(
        token_hash=token_hash(token), user_id=user_id, guest_used=False,
        expires_at=now() + timedelta(hours=settings.SESSION_HOURS),
    )
    await db.execute(delete(BrowserSession).where(BrowserSession.expires_at <= now()))
    db.add(session)
    await db.commit()
    # No Max-Age: the guest allowance belongs to this browser session.
    response.set_cookie(COOKIE, token, httponly=True, secure=settings.APP_ENV == "production", samesite="lax", path="/")
    return session


@router.get("/me")
async def me(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    from app.guests import guest_jobs
    try:
        session = await current_session(request, db)
    except HTTPException:
        session = await new_session(db, response)
    user = await db.get(User, session.user_id) if session.user_id else None
    guest = next((job for job in guest_jobs.values() if job.session_hash == session.token_hash and (job.expires_at > now() or job.status in {"transcribing", "summarizing"})), None)
    response.headers["Cache-Control"] = "no-store"
    return {
        "user": {"name": user.name, "email": user.email} if user else None,
        "google_enabled": configured(),
        "guest_used": session.guest_used,
        "guest_result_minutes": settings.GUEST_RESULT_MINUTES,
        "guest_upload": guest.detail().model_dump(mode="json") if guest else None,
    }


@router.get("/google")
async def login(request: Request):
    if not configured():
        raise HTTPException(503, "Google sign-in has not been configured yet.")
    request.session.clear()
    return await oauth.google.authorize_redirect(
        request, settings.APP_URL.rstrip("/") + "/api/auth/google/callback",
        prompt="select_account",
    )


@router.get("/google/callback")
async def callback(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        # Authlib checks state, nonce, signature, issuer, audience and expiry.
        token = await oauth.google.authorize_access_token(request)
        info = token.get("userinfo")
        if not info or not info.get("sub") or info.get("email_verified") is not True:
            raise ValueError("Unverified Google identity")
    except (OAuthError, JoseError, HTTPError, ValueError):
        request.session.clear()
        return RedirectResponse(settings.APP_URL.rstrip("/") + "/?auth_error=google", status_code=303)
    user = await db.scalar(select(User).where(User.google_sub == info["sub"]))
    if user is None:
        user = User(id=str(uuid.uuid4()), google_sub=info["sub"], email=info["email"], name=info.get("name") or info["email"])
        try:
            async with db.begin_nested():
                db.add(user)
                await db.flush()
        except IntegrityError:
            # Two callbacks for the same Google account may arrive together.
            user = await db.scalar(select(User).where(User.google_sub == info["sub"]))
    else:
        user.email = info["email"]
        user.name = info.get("name") or info["email"]
    # Rotate the cookie and revoke the old guest/account session on login.
    old_token = request.cookies.get(COOKIE)
    if old_token:
        await db.execute(delete(BrowserSession).where(BrowserSession.token_hash == token_hash(old_token)))
        from app.guests import forget_session
        await forget_session(token_hash(old_token))
    request.session.clear()
    response = RedirectResponse(settings.APP_URL.rstrip("/") + "/", status_code=303)
    await new_session(db, response, user.id)
    return response


@router.post("/logout", dependencies=[Depends(check_origin)])
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get(COOKIE)
    if token:
        await db.execute(delete(BrowserSession).where(BrowserSession.token_hash == token_hash(token)))
        await db.commit()
        from app.guests import forget_session
        await forget_session(token_hash(token))
    request.session.clear()
    response.delete_cookie(COOKIE, path="/")
    response.headers["Cache-Control"] = "no-store"
    return {"status": "signed_out"}
