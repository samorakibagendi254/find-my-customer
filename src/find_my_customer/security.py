from __future__ import annotations

import hmac
import ipaddress
import secrets
import hashlib
import threading
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from urllib.parse import urlparse

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import HTTPException, Request, status
from jwt import PyJWKClient
from sqlalchemy import select, update

from .config import Settings, get_settings
from .database import session_factory
from .models import AuthSession


@dataclass(frozen=True)
class Identity:
    subject: str
    email: str


PASSWORD_HASHER = PasswordHasher()
_DUMMY_PASSWORD_HASH = "$argon2id$v=19$m=65536,t=3,p=4$GoM5hQCKjuw+irE6qa/5DQ$DizYGgygO9rxk22+3LaZBopUn2Ytc7H3VkJglMPK/Rk"
SESSION_COOKIE = "fmc_session"
SESSION_TTL = timedelta(hours=8)


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(encoded_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def _session_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def create_session(identity: Identity) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    with session_factory()() as session:
        session.add(
            AuthSession(
                token_hash=_session_hash(token),
                subject=identity.subject,
                email=identity.email,
                created_at=now,
                last_seen_at=now,
                expires_at=now + SESSION_TTL,
            )
        )
        session.commit()
    return token


def revoke_session(token: str) -> None:
    with session_factory()() as session:
        session.execute(
            update(AuthSession)
            .where(AuthSession.token_hash == _session_hash(token), AuthSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(timezone.utc))
        )
        session.commit()


def session_identity(token: str) -> Identity | None:
    if not token or len(token) < 40 or len(token) > 128:
        return None
    now = datetime.now(timezone.utc)
    with session_factory()() as session:
        auth_session = session.scalar(
            select(AuthSession).where(
                AuthSession.token_hash == _session_hash(token),
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > now,
            )
        )
        if auth_session is None:
            return None
        auth_session.last_seen_at = now
        session.commit()
        return Identity(subject=auth_session.subject, email=auth_session.email)


class LoginRateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._failures: dict[str, list[datetime]] = {}

    def _prune(self, key: str, now: datetime) -> list[datetime]:
        cutoff = now - timedelta(minutes=15)
        failures = [item for item in self._failures.get(key, []) if item > cutoff]
        self._failures[key] = failures
        return failures

    def blocked(self, key: str) -> int:
        now = datetime.now(timezone.utc)
        with self._lock:
            failures = self._prune(key, now)
            if len(failures) < 5:
                return 0
            retry_at = failures[0] + timedelta(minutes=15)
            return max(1, int((retry_at - now).total_seconds()))

    def failure(self, key: str) -> None:
        now = datetime.now(timezone.utc)
        with self._lock:
            self._prune(key, now).append(now)

    def success(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


login_limiter = LoginRateLimiter()


class AccessVerifier:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.jwks = PyJWKClient(f"{settings.cloudflare_team_domain}/cdn-cgi/access/certs", cache_jwk_set=True)

    def verify(self, token: str) -> Identity:
        try:
            signing_key = self.jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.settings.cloudflare_access_audience,
                issuer=self.settings.cloudflare_team_domain,
                options={"require": ["exp", "iat", "aud", "iss", "sub"]},
            )
        except jwt.PyJWTError as error:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Access identity") from error
        email = str(claims.get("email", "")).strip().lower()
        subject = str(claims.get("sub", "")).strip()
        if not email or not subject:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incomplete Access identity")
        if self.settings.allowed_emails and email not in self.settings.allowed_emails:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Identity is not allowed")
        return Identity(subject=subject, email=email)


_verifier: AccessVerifier | None = None


def current_identity(request: Request) -> Identity:
    settings = get_settings()
    if settings.auth_mode == "development":
        email = request.headers.get("X-Dev-Email", "developer@localhost").strip().lower()
        return Identity(subject=f"dev:{email}", email=email)
    if settings.auth_mode == "local":
        identity = session_identity(request.cookies.get(SESSION_COOKIE, ""))
        if identity is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login required")
        return identity
    global _verifier
    token = request.headers.get("Cf-Access-Jwt-Assertion", "")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Cloudflare Access identity required")
    if _verifier is None:
        _verifier = AccessVerifier(settings)
    return _verifier.verify(token)


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def require_csrf(request: Request, submitted_token: str | None = None) -> None:
    cookie = request.cookies.get("fmc_csrf", "")
    header = request.headers.get("X-CSRF-Token", "") or submitted_token or ""
    if not cookie or not header or not hmac.compare_digest(cookie, header):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")
    settings = get_settings()
    origin = request.headers.get("Origin")
    if origin and origin.rstrip("/") != settings.public_origin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin mutation denied")
    if request.headers.get("Sec-Fetch-Site") == "cross-site":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-site mutation denied")


def login_key(request: Request, email: str) -> str:
    remote = request.client.host if request.client else "unknown"
    return f"{remote}:{email.strip().lower()}"


def validate_public_url(value: str) -> str:
    raw = value.strip()
    if len(raw) > 2048:
        raise ValueError("URL is too long")
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Enter a public HTTP(S) startup URL")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError("Local addresses are not allowed")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return raw
    if not address.is_global:
        raise ValueError("Private or reserved addresses are not allowed")
    return raw
