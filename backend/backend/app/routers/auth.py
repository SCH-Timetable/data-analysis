"""
Auth endpoints.

POST /api/auth/login   → { role, token, display_name }
POST /api/auth/logout  → { ok: true }
GET  /api/auth/me      → same as login response (uses bearer token)

For this demo the "token" is just base64(email:role).
Swap for a real JWT library (python-jose / PyJWT) in production.
"""

import base64
from fastapi import APIRouter, HTTPException, Header
from app.models.schema import LoginRequest, LoginResponse, UserRole
from app.data_store import USERS, VALID_DOMAINS

router = APIRouter()


def _validate(email: str, password: str) -> tuple[bool, str | None, str | None]:
    """Returns (ok, error_message, display_name)."""
    parts = email.split('@')
    if len(parts) != 2 or parts[1] not in VALID_DOMAINS:
        return False, 'Email must use a BUA domain (@bua.edu.eg).', None
    if len(password) < 8:
        return False, 'Password must be at least 8 characters.', None
    # Access is granted only to configured accounts.
    for u in USERS:
        if u['email'].lower() == email.lower() and u['password'] == password:
            return True, None, u['name']
    return False, 'Invalid email or password.', None


def _make_token(email: str, role: str) -> str:
    payload = f"{email}:{role}"
    return base64.b64encode(payload.encode()).decode()


def _parse_token(token: str) -> tuple[str, str] | None:
    try:
        decoded = base64.b64decode(token).decode()
        email, role = decoded.split(':', 1)
        return email, role
    except Exception:
        return None


def is_admin_authorization(authorization: str) -> bool:
    scheme, _, token = authorization.partition(' ')
    if scheme.lower() != 'bearer' or not token:
        return False
    parsed = _parse_token(token)
    if not parsed:
        return False
    email, role = parsed
    return role == 'admin' and any(
        u['email'].lower() == email.lower() and u['role'] == 'admin'
        for u in USERS
    )


@router.post('/login', response_model=LoginResponse)
def login(body: LoginRequest):
    ok, err, name = _validate(body.email, body.password)
    if not ok:
        raise HTTPException(status_code=401, detail=err)
    user = next(u for u in USERS if u['email'].lower() == body.email.lower())
    role: UserRole = user['role']
    token = _make_token(body.email, role)
    return LoginResponse(role=role, token=token, display_name=name or body.email)


@router.post('/logout')
def logout():
    return {'ok': True}


@router.get('/me', response_model=LoginResponse)
def me(authorization: str = Header(default='')):
    scheme, _, token = authorization.partition(' ')
    if scheme.lower() != 'bearer' or not token:
        raise HTTPException(status_code=401, detail='Not authenticated')
    parsed = _parse_token(token)
    if not parsed:
        raise HTTPException(status_code=401, detail='Invalid token')
    email, role = parsed
    name = next((u['name'] for u in USERS if u['email'].lower() == email.lower()), email)
    return LoginResponse(role=role, token=token, display_name=name)  # type: ignore[arg-type]
