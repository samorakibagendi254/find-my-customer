from __future__ import annotations

import hmac
import ipaddress
import secrets
from dataclasses import dataclass
from urllib.parse import urlparse

import jwt
from fastapi import HTTPException, Request, status
from jwt import PyJWKClient

from .config import Settings, get_settings


@dataclass(frozen=True)
class Identity:
    subject: str
    email: str


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
    global _verifier
    settings = get_settings()
    if settings.auth_mode == "development":
        email = request.headers.get("X-Dev-Email", "developer@localhost").strip().lower()
        return Identity(subject=f"dev:{email}", email=email)
    token = request.headers.get("Cf-Access-Jwt-Assertion", "")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Cloudflare Access identity required")
    if _verifier is None:
        _verifier = AccessVerifier(settings)
    return _verifier.verify(token)


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def require_csrf(request: Request) -> None:
    cookie = request.cookies.get("fmc_csrf", "")
    header = request.headers.get("X-CSRF-Token", "")
    if not cookie or not header or not hmac.compare_digest(cookie, header):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")
    settings = get_settings()
    origin = request.headers.get("Origin")
    if origin and origin.rstrip("/") != settings.public_origin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin mutation denied")
    if request.headers.get("Sec-Fetch-Site") == "cross-site":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-site mutation denied")


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
