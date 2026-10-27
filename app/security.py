"""En-têtes de sécurité HTTP : CSP stricte, anti-clickjacking, etc.

CSP volontairement stricte : aucun inline ('self' uniquement) — tout le JS/CSS
vit dans /static. img-src accepte data:/blob: pour les aperçus d'upload photo.
"""

CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data: blob:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "manifest-src 'self'; "
    "worker-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


def apply_security_headers(resp):
    """Ajoute les en-têtes de sécurité à chaque réponse."""
    resp.headers["Content-Security-Policy"] = CSP
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["Permissions-Policy"] = (
        "geolocation=(), microphone=(), camera=(self)"
    )
    resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    resp.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    # Pages authentifiées : jamais mises en cache navigateur
    resp.headers["Cache-Control"] = "no-store"
    return resp
