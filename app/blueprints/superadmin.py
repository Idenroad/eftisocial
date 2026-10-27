"""Blueprint superadmin : /superadmin — sessions, admins, événements, audit."""

import uuid
from datetime import datetime, timezone

from flask import (Blueprint, abort, g, redirect, render_template, request,
                   session as flask_session, url_for)

from .. import audit, auth
from ..db import (core_conn, create_session, delete_session,
                  get_session_by_slug, list_sessions, sess_conn, slugify)
from .common import complete_otp, start_otp, valid_email

bp = Blueprint("superadmin", __name__, url_prefix="/superadmin")


# ─── Connexion superadmin ─────────────────────────────────────────────────────

@bp.route("/connexion", methods=["GET", "POST"])
def login():
    if auth.resolve_token(auth.read_cookie("superadmin"), "superadmin", None):
        return redirect(url_for("superadmin.dashboard"))

    error = None
    if request.method == "POST":
        err, _ = start_otp(request.form.get("email", ""), "superadmin",
                           None, None)
        if err:
            error = err
        else:
            return redirect(url_for("superadmin.verify"))
    return render_template("auth/login.html", session=None,
                           role="superadmin", error=error)


@bp.route("/connexion/verification", methods=["GET", "POST"])
def verify():
    pending = flask_session.get("pending") or {}
    if pending.get("role") != "superadmin":
        return redirect(url_for("superadmin.login"))

    error = None
    if request.method == "POST":
        raw, actor_or_err = complete_otp(
            pending["email"], "superadmin", None,
            request.form.get("code", ""),
            remember=bool(request.form.get("remember")))
        if raw:
            resp = redirect(url_for("superadmin.dashboard"))
            auth.set_auth_cookie(resp, "superadmin", None, raw,
                                 bool(request.form.get("remember")))
            return resp
        error = actor_or_err
    return render_template("auth/verify.html", session=None,
                           email=pending["email"], role="superadmin",
                           error=error)


@bp.post("/deconnexion")
@auth.require_superadmin
def logout():
    auth.revoke_token(g.raw_token)
    audit.log("auth.logout", actor_role="superadmin",
              actor_id=g.actor["id"], actor_label=g.actor["email"])
    resp = redirect(url_for("superadmin.login"))
    auth.clear_auth_cookie(resp, "superadmin", None)
    return resp


# ─── Tableau de bord ──────────────────────────────────────────────────────────

@bp.get("/")
@auth.require_superadmin
def dashboard():
    sessions = list_sessions()
    with core_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM core.admins WHERE active")
            admins = cur.fetchone()["n"]
    return render_template("superadmin/dashboard.html",
                           sessions=sessions, n_admins=admins)


# ─── Sessions (résidences) ────────────────────────────────────────────────────

@bp.route("/sessions", methods=["GET", "POST"])
@auth.require_superadmin
def sessions():
    error = msg = None
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()[:120]
        if not name:
            error = "Nom de résidence requis."
        else:
            try:
                slug = slugify(name)
                row = create_session(slug, name)
            except ValueError as e:
                error = str(e)
            except Exception as e:
                if "unique" in str(e).lower():
                    error = "Une session porte déjà ce nom."
                else:
                    raise
            else:
                audit.log("session.create", actor_role="superadmin",
                          actor_id=g.actor["id"],
                          actor_label=g.actor["email"],
                          session_id=row["id"], target_type="session",
                          target_id=slug, details={"name": name})
                msg = f"Session « {name} » créée : /{slug}"
    return render_template("superadmin/sessions.html",
                           sessions=list_sessions(), error=error, msg=msg)


@bp.post("/sessions/<slug>/basculer")
@auth.require_superadmin
def session_toggle(slug):
    session = get_session_by_slug(slug)
    if not session:
        abort(404)
    with core_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE core.sessions SET active = NOT active "
                "WHERE id = %s RETURNING active", (session["id"],))
            active = cur.fetchone()["active"]
            audit.log("session.toggle", actor_role="superadmin",
                      actor_id=g.actor["id"], actor_label=g.actor["email"],
                      session_id=session["id"], target_type="session",
                      target_id=slug, details={"active": active}, conn=conn)
    return redirect(url_for("superadmin.sessions"))


@bp.post("/sessions/<slug>/supprimer")
@auth.require_superadmin
def session_delete(slug):
    session = get_session_by_slug(slug)
    if not session:
        abort(404)
    if request.form.get("confirm") != slug:
        return redirect(url_for("superadmin.sessions"))
    # Audit AVANT la suppression (le log survit via ON DELETE SET NULL)
    audit.log("session.delete", actor_role="superadmin",
              actor_id=g.actor["id"], actor_label=g.actor["email"],
              session_id=session["id"], target_type="session",
              target_id=slug, details={"name": session["name"]})
    delete_session(slug)
    return redirect(url_for("superadmin.sessions"))


# ─── Admins d'une session ─────────────────────────────────────────────────────

@bp.route("/sessions/<slug>/admins", methods=["GET", "POST"])
@auth.require_superadmin
def admins(slug):
    session = get_session_by_slug(slug)
    if not session:
        abort(404)
    error = msg = None

    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        first_name = (request.form.get("first_name") or "").strip()[:60]
        if not valid_email(email):
            error = "Courriel invalide."
        elif not first_name:
            error = "Prénom requis."
        else:
            with core_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM core.admins "
                        "WHERE session_id = %s AND email = %s",
                        (session["id"], email))
                    if cur.fetchone():
                        error = "Cet intervenant existe déjà."
                    else:
                        cur.execute(
                            "INSERT INTO core.admins "
                            "(session_id, email, first_name) "
                            "VALUES (%s,%s,%s) RETURNING id",
                            (session["id"], email, first_name))
                        aid = cur.fetchone()["id"]
                        audit.log("admin.create", actor_role="superadmin",
                                  actor_id=g.actor["id"],
                                  actor_label=g.actor["email"],
                                  session_id=session["id"],
                                  target_type="admin", target_id=aid,
                                  details={"email": email}, conn=conn)
                        msg = f"Intervenant {first_name} ({email}) créé."

    with core_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, first_name, active, created_at "
                "FROM core.admins WHERE session_id = %s ORDER BY first_name",
                (session["id"],))
            rows = [dict(r) for r in cur.fetchall()]
    return render_template("superadmin/admins.html", session_row=session,
                           admins=rows, error=error, msg=msg)


@bp.post("/sessions/<slug>/admins/<aid>/supprimer")
@auth.require_superadmin
def admin_delete(slug, aid):
    session = get_session_by_slug(slug)
    if not session:
        abort(404)
    try:
        uuid.UUID(aid)
    except ValueError:
        abort(404)
    with core_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM core.admins "
                "WHERE id = %s AND session_id = %s RETURNING email",
                (aid, session["id"]))
            row = cur.fetchone()
            if row:
                audit.log("admin.delete", actor_role="superadmin",
                          actor_id=g.actor["id"],
                          actor_label=g.actor["email"],
                          session_id=session["id"], target_type="admin",
                          target_id=aid, details={"email": row["email"]},
                          conn=conn)
                cur.execute(
                    "UPDATE core.auth_tokens SET revoked = true "
                    "WHERE role = 'admin' AND actor_id = %s", (aid,))
    return redirect(url_for("superadmin.admins", slug=slug))


# ─── Événements d'une session (créés par le superadmin) ──────────────────────

@bp.route("/sessions/<slug>/evenements", methods=["GET", "POST"])
@auth.require_superadmin
def evenements(slug):
    session = get_session_by_slug(slug)
    if not session:
        abort(404)
    schema = session["schema_name"]
    error = None

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()[:120]
        location = (request.form.get("location") or "").strip()[:200]
        desc = (request.form.get("description") or "").strip()[:2000]
        when = request.form.get("event_at") or ""
        max_p = request.form.get("max_participants") or ""
        try:
            event_at = datetime.fromisoformat(when)
            if event_at.tzinfo is None:
                event_at = event_at.replace(tzinfo=timezone.utc)
        except ValueError:
            event_at = None
        if not title or event_at is None:
            error = "Titre et date sont requis."
        else:
            with sess_conn(schema) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO events "
                        "(title, description, location, event_at, "
                        " max_participants, creator_role, creator_id, creator_name) "
                        "VALUES (%s,%s,%s,%s,%s,'superadmin',%s,%s) RETURNING id",
                        (title, desc, location, event_at,
                         int(max_p) if max_p.isdigit() else None,
                         str(g.actor["id"]), g.actor["first_name"]))
                    eid = cur.fetchone()["id"]
                    audit.log("superadmin.event_create",
                              actor_role="superadmin",
                              actor_id=g.actor["id"],
                              actor_label=g.actor["email"],
                              session_id=session["id"],
                              target_type="event", target_id=eid,
                              details={"title": title}, conn=conn)
            return redirect(url_for("superadmin.evenements", slug=slug))

    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT e.*, (SELECT count(*) FROM event_participants ep "
                " WHERE ep.event_id = e.id) AS participants "
                "FROM events e ORDER BY e.event_at DESC")
            events = [dict(r) for r in cur.fetchall()]
    return render_template("superadmin/evenements.html", session_row=session,
                           events=events, error=error)


@bp.post("/sessions/<slug>/evenements/<eid>/supprimer")
@auth.require_superadmin
def evenement_delete(slug, eid):
    session = get_session_by_slug(slug)
    if not session:
        abort(404)
    try:
        uuid.UUID(eid)
    except ValueError:
        abort(404)
    with sess_conn(session["schema_name"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE events SET cancelled = true WHERE id = %s "
                "RETURNING title", (eid,))
            row = cur.fetchone()
            if row:
                audit.log("superadmin.event_delete",
                          actor_role="superadmin", actor_id=g.actor["id"],
                          actor_label=g.actor["email"],
                          session_id=session["id"], target_type="event",
                          target_id=eid, details={"title": row["title"]},
                          conn=conn)
    return redirect(url_for("superadmin.evenements", slug=slug))


# ─── Journal d'audit global ───────────────────────────────────────────────────

@bp.get("/journal")
@auth.require_superadmin
def journal():
    logs = audit.list_logs(limit=500)
    with core_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, slug FROM core.sessions")
            sess_map = {str(r["id"]): r["name"] for r in cur.fetchall()}
    return render_template("superadmin/journal.html", logs=logs,
                           sess_map=sess_map)
