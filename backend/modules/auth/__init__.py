"""Authentication module - login requirement decorator."""

from functools import wraps
from flask import session, request, jsonify, redirect, url_for


def login_required(f):
    """Decorator: redirect to login if not authenticated.

    For API routes (path starts with /api/): returns 401 JSON.
    For page routes: redirects to /login.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "unauthorized", "redirect": "/login"}), 401
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated
