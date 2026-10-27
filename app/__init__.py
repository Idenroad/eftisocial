"""EftiSocial — application Flask.

Application factory : config, CSRF, en-têtes de sécurité, blueprints.
"""

from pathlib import Path

from flask import Flask, g, render_template
from flask_wtf import CSRFProtect

from .config import Config
from .security import apply_security_headers

csrf = CSRFProtect()


def create_app(config_object=Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_object)

    if app.config["SECRET_KEY"] == "dev-secret-change-me":
        app.logger.warning(
            "SECRET_KEY est la valeur par défaut — définissez-en une "
            "aléatoire dans .env (openssl rand -hex 32).")

    # Fichiers/données : toujours des chemins absolus
    app.config["DATA_DIR"] = Path(app.config["DATA_DIR"]).resolve()
    app.config["DATA_DIR"].mkdir(parents=True, exist_ok=True)

    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=app.config["SESSION_COOKIE_SECURE"],
        MAX_CONTENT_LENGTH=app.config["MAX_PHOTO_BYTES"] + 1024 * 1024,
        WTF_CSRF_TIME_LIMIT=None,
        PREFERRED_URL_SCHEME="https" if app.config["SESSION_COOKIE_SECURE"] else "http",
    )

    csrf.init_app(app)
    app.after_request(apply_security_headers)

    # i18n : résolution de la langue à chaque requête + cookie si ?lang=
    from . import i18n

    @app.before_request
    def _resolve_lang():
        i18n.resolve_lang()

    @app.after_request
    def _set_lang_cookie(resp):
        if getattr(g, "set_lang_cookie", False):
            resp.set_cookie("efti_lang", g.lang, max_age=365 * 86400,
                            path="/", samesite="Lax",
                            httponly=True,
                            secure=app.config["SESSION_COOKIE_SECURE"])
        return resp

    app.jinja_env.globals["t"] = i18n.tr

    from .blueprints import auth_bp, session_admin, superadmin, user_app

    app.register_blueprint(auth_bp.bp)
    app.register_blueprint(user_app.bp)
    app.register_blueprint(session_admin.bp)
    app.register_blueprint(superadmin.bp)

    @app.context_processor
    def inject_globals():
        """Variables dispo dans tous les templates."""
        return {
            "actor": getattr(g, "actor", None),
            "role": getattr(g, "role", None),
            "session": getattr(g, "session", None),
            "demo_mode": app.config.get("DEMO_MODE", False),
            "lang": getattr(g, "lang", "fr"),
        }

    @app.errorhandler(404)
    def not_found(e):
        return render_template("404.html"), 404

    @app.errorhandler(413)
    def too_large(e):
        return render_template("erreur.html",
                               message="Fichier trop volumineux."), 413

    @app.errorhandler(500)
    def server_error(e):
        app.logger.exception("Erreur interne: %s", e)
        return render_template(
            "erreur.html",
            message="Une erreur est survenue. Réessayez."), 500

    return app
