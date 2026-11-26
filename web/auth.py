"""Login simples, CSRF e rate limit em memória."""

import hmac
import os
import secrets
import time
from pathlib import Path

from flask import abort, g, redirect, request, session, url_for
from werkzeug.security import check_password_hash

BASE = Path(__file__).parent
SECRET_FILE = BASE / ".secret_key"


def secret_key() -> str:
    """Chave persistida para sessões não caírem a cada restart."""
    if SECRET_FILE.exists():
        return SECRET_FILE.read_text(encoding="utf-8").strip()
    key = secrets.token_hex(32)
    SECRET_FILE.write_text(key, encoding="utf-8")
    os.chmod(SECRET_FILE, 0o600)
    return key


def configured() -> bool:
    return bool(os.getenv("WEB_PASSWORD_HASH") or os.getenv("WEB_PASSWORD"))


def check_password(password: str) -> bool:
    hashed = os.getenv("WEB_PASSWORD_HASH", "")
    if hashed:
        try:
            return check_password_hash(hashed, password)
        except Exception:
            return False
    plain = os.getenv("WEB_PASSWORD", "")
    return bool(plain) and hmac.compare_digest(plain, password)


# IP -> [tentativas, primeiro timestamp]
_ATTEMPTS = {}
MAX_ATTEMPTS = 5
WINDOW = 300


def rate_limited(ip: str) -> bool:
    now = time.time()
    attempts, first = _ATTEMPTS.get(ip, (0, now))
    if now - first > WINDOW:
        attempts, first = 0, now
    _ATTEMPTS[ip] = (attempts + 1, first)
    return attempts >= MAX_ATTEMPTS


def reset_rate(ip: str):
    _ATTEMPTS.pop(ip, None)


def login_required(view):
    from functools import wraps

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login", next=request.full_path.rstrip("?") or "/"))
        return view(*args, **kwargs)
    return wrapped


def csrf_token() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


def check_csrf():
    from flask import request
    if request.method in ("POST", "PUT", "DELETE"):
        sent = request.form.get("csrf") or request.headers.get("X-CSRF-Token", "")
        expected = session.get("csrf", "")
        if not expected or not hmac.compare_digest(sent, expected):
            abort(400, "CSRF inválido")


def init_app(app):
    from flask import request

    @app.before_request
    def _csrf():
        check_csrf()

    @app.context_processor
    def _inject():
        return {"csrf_token": csrf_token, "web_user": session.get("user", "")}

    @app.before_request
    def _load_g():
        g.ip = request.remote_addr or "?"
