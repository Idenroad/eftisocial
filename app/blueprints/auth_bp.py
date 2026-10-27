"""Routes racines : page d'accueil, choix de résidence, service worker."""

from flask import (Blueprint, redirect, render_template, request, send_file,
                   url_for)

from ..db import get_session_by_slug, slugify

bp = Blueprint("root", __name__)


@bp.get("/sw.js")
def service_worker():
    """Sert le service worker à la racine pour un scope '/' (PWA)."""
    from flask import current_app
    from pathlib import Path
    resp = send_file(Path(current_app.static_folder) / "sw.js",
                     mimetype="text/javascript")
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@bp.get("/")
def index():
    """Accueil : l'usager entre le nom de sa résidence (fourni par
    l'intervenant) et est redirigé vers la bonne session."""
    return render_template("index.html")


@bp.post("/")
def index_redirect():
    name = (request.form.get("residence") or "").strip()
    if not name:
        return render_template("index.html", error="Entrez le nom de votre résidence.")
    try:
        slug = slugify(name)
    except ValueError:
        slug = ""
    session = get_session_by_slug(slug)
    if not session:
        return render_template(
            "index.html",
            error="Résidence introuvable. Vérifiez le nom auprès de votre intervenant.",
            residence=name)
    return redirect(url_for("user_app.home", slug=session["slug"]))
