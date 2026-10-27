"""Blueprint intervenant : /<slug>/admin — gestion des membres et événements.

Chaque admin est rattaché à UNE session. Le décorateur require_admin vérifie
le jeton, le rattachement et le statut actif à chaque requête.
"""

import uuid
from datetime import datetime, timezone

from flask import (Blueprint, abort, g, redirect, render_template, request,
                   session as flask_session, url_for)

from .. import audit, auth, matching, photos
from ..db import sess_conn
from .common import complete_otp, load_session_or_404, start_otp, valid_email

bp = Blueprint("session_admin", __name__, url_prefix="/<slug>/admin")


# ─── Connexion admin ──────────────────────────────────────────────────────────

@bp.route("/connexion", methods=["GET", "POST"])
def login(slug):
    session = load_session_or_404(slug)
    if auth.resolve_token(auth.read_cookie("admin"), "admin", session["id"]):
        return redirect(url_for("session_admin.dashboard", slug=slug))

    error = None
    if request.method == "POST":
        err, _ = start_otp(request.form.get("email", ""), "admin",
                           session, slug)
        if err:
            error = err
        else:
            return redirect(url_for("session_admin.verify", slug=slug))
    return render_template("auth/login.html", session=session,
                           role="intervenant", error=error)


@bp.route("/connexion/verification", methods=["GET", "POST"])
def verify(slug):
    session = load_session_or_404(slug)
    pending = flask_session.get("pending") or {}
    if pending.get("role") != "admin" or pending.get("slug") != slug:
        return redirect(url_for("session_admin.login", slug=slug))

    error = None
    if request.method == "POST":
        raw, actor_or_err = complete_otp(
            pending["email"], "admin", session,
            request.form.get("code", ""),
            remember=bool(request.form.get("remember")))
        if raw:
            resp = redirect(url_for("session_admin.dashboard", slug=slug))
            auth.set_auth_cookie(resp, "admin", slug, raw,
                                 bool(request.form.get("remember")))
            return resp
        error = actor_or_err
    return render_template("auth/verify.html", session=session,
                           email=pending["email"], role="intervenant",
                           error=error)


@bp.post("/deconnexion")
@auth.require_admin
def logout(slug):
    auth.revoke_token(g.raw_token)
    audit.log("auth.logout", actor_role="admin", actor_id=g.actor["id"],
              actor_label=g.actor["email"], session_id=g.session["id"])
    resp = redirect(url_for("session_admin.login", slug=slug))
    auth.clear_auth_cookie(resp, "admin", slug)
    return resp


# ─── Tableau de bord ──────────────────────────────────────────────────────────

@bp.get("/")
@auth.require_admin
def dashboard(slug):
    schema = g.session["schema_name"]
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) AS n FROM users WHERE deleted_at IS NULL")
            users = cur.fetchone()["n"]
            cur.execute(
                "SELECT count(*) AS n FROM users WHERE deleted_at IS NULL "
                "AND paused = true")
            paused = cur.fetchone()["n"]
            cur.execute("SELECT count(*) AS n FROM matches")
            matches = cur.fetchone()["n"]
            cur.execute(
                "SELECT count(*) AS n FROM events "
                "WHERE cancelled = false AND event_at > now()")
            events = cur.fetchone()["n"]
    return render_template("admin/dashboard.html", session=g.session,
                           stats={"users": users, "paused": paused,
                                  "matches": matches, "events": events})


# ─── Utilisateurs ─────────────────────────────────────────────────────────────

def _list_users(schema):
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.id, u.email, u.first_name, u.sex, u.paused,
                       u.created_at,
                       (SELECT filename FROM photos p WHERE p.user_id = u.id
                        ORDER BY p.is_primary DESC, p.position LIMIT 1)
                        AS photo,
                       (SELECT count(*) FROM user_interests ui
                        WHERE ui.user_id = u.id) AS n_interests
                FROM users u WHERE u.deleted_at IS NULL
                ORDER BY u.first_name
                """)
            return [dict(r) for r in cur.fetchall()]


@bp.route("/utilisateurs", methods=["GET", "POST"])
@auth.require_admin
def utilisateurs(slug):
    schema = g.session["schema_name"]
    error = msg = None

    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        first_name = (request.form.get("first_name") or "").strip()[:60]
        sex = request.form.get("sex") or ""
        if not valid_email(email):
            error = "Courriel invalide."
        elif not first_name or sex not in ("F", "M", "X"):
            error = "Prénom et sexe requis."
        else:
            with sess_conn(schema) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM users WHERE email = %s", (email,))
                    if cur.fetchone():
                        error = "Ce courriel est déjà utilisé."
                    else:
                        cur.execute(
                            "INSERT INTO users (email, first_name, sex, "
                            "created_by) VALUES (%s,%s,%s,'admin') "
                            "RETURNING id", (email, first_name, sex))
                        uid = cur.fetchone()["id"]
                        audit.log(
                            "admin.user_create", actor_role="admin",
                            actor_id=g.actor["id"],
                            actor_label=g.actor["email"],
                            session_id=g.session["id"], target_type="user",
                            target_id=uid,
                            details={"email": email, "first_name": first_name},
                            conn=conn)
                        msg = f"Compte créé pour {first_name} ({email})."

    return render_template("admin/utilisateurs.html", session=g.session,
                           users=_list_users(schema), error=error, msg=msg)


@bp.route("/utilisateurs/<uid>", methods=["GET", "POST"])
@auth.require_admin
def utilisateur_edit(slug, uid):
    try:
        uuid.UUID(uid)
    except ValueError:
        abort(404)
    schema = g.session["schema_name"]
    error = msg = None

    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM users WHERE id = %s AND deleted_at IS NULL",
                (uid,))
            user = cur.fetchone()
            if not user:
                abort(404)

            if request.method == "POST":
                first_name = (request.form.get("first_name") or "").strip()[:60]
                sex = request.form.get("sex") or ""
                bio = (request.form.get("bio") or "").strip()[:500]
                paused = bool(request.form.get("paused"))
                if not first_name or sex not in ("F", "M", "X"):
                    error = "Prénom et sexe requis."
                else:
                    cur.execute(
                        "UPDATE users SET first_name=%s, sex=%s, bio=%s, "
                        "paused=%s, updated_at=now() WHERE id=%s",
                        (first_name, sex, bio, paused, uid))
                    interests = request.form.getlist("interests")
                    audit.log(
                        "admin.user_update", actor_role="admin",
                        actor_id=g.actor["id"], actor_label=g.actor["email"],
                        session_id=g.session["id"], target_type="user",
                        target_id=uid,
                        details={"paused": paused, "first_name": first_name},
                        conn=conn)
                    msg = "Compte mis à jour."
                    user.update(first_name=first_name, sex=sex, bio=bio,
                                paused=paused)

    if request.method == "POST" and not error:
        matching.set_user_interests(
            schema, uid, request.form.getlist("interests"))

    profil = matching.get_profile(schema, uid, include_paused=True)
    for p in profil["photos"]:
        p["url"] = url_for("user_app.media", slug=slug, uid=uid,
                           filename=p["filename"])
    return render_template("admin/utilisateur_edit.html", session=g.session,
                           user=profil, email=user["email"], uid=uid,
                           error=error, msg=msg)


@bp.post("/utilisateurs/<uid>/supprimer")
@auth.require_admin
def utilisateur_delete(slug, uid):
    try:
        uuid.UUID(uid)
    except ValueError:
        abort(404)
    schema = g.session["schema_name"]
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET deleted_at = now(), paused = true "
                "WHERE id = %s AND deleted_at IS NULL RETURNING email",
                (uid,))
            row = cur.fetchone()
            if not row:
                abort(404)
            audit.log("admin.user_delete", actor_role="admin",
                      actor_id=g.actor["id"], actor_label=g.actor["email"],
                      session_id=g.session["id"], target_type="user",
                      target_id=uid, details={"email": row["email"]},
                      conn=conn)
    photos.delete_profile_dir(slug, uid)
    auth.revoke_actor_tokens("user", uid)
    return redirect(url_for("session_admin.utilisateurs", slug=slug))


# ─── Événements ───────────────────────────────────────────────────────────────

@bp.route("/evenements", methods=["GET", "POST"])
@auth.require_admin
def evenements(slug):
    schema = g.session["schema_name"]
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
                        "VALUES (%s,%s,%s,%s,%s,'admin',%s,%s) RETURNING id",
                        (title, desc, location, event_at,
                         int(max_p) if max_p.isdigit() else None,
                         str(g.actor["id"]), g.actor["first_name"]))
                    eid = cur.fetchone()["id"]
                    audit.log("admin.event_create", actor_role="admin",
                              actor_id=g.actor["id"],
                              actor_label=g.actor["email"],
                              session_id=g.session["id"],
                              target_type="event", target_id=eid,
                              details={"title": title}, conn=conn)
            return redirect(url_for("session_admin.evenements", slug=slug))

    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT e.*, (SELECT count(*) FROM event_participants ep "
                " WHERE ep.event_id = e.id) AS participants "
                "FROM events e ORDER BY e.event_at DESC")
            events = [dict(r) for r in cur.fetchall()]
    return render_template("admin/evenements.html", session=g.session,
                           events=events, error=error)


@bp.post("/evenements/<eid>/supprimer")
@auth.require_admin
def evenement_delete(slug, eid):
    try:
        uuid.UUID(eid)
    except ValueError:
        abort(404)
    with sess_conn(g.session["schema_name"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE events SET cancelled = true WHERE id = %s "
                "RETURNING title", (eid,))
            row = cur.fetchone()
            if row:
                audit.log("admin.event_delete", actor_role="admin",
                          actor_id=g.actor["id"],
                          actor_label=g.actor["email"],
                          session_id=g.session["id"], target_type="event",
                          target_id=eid, details={"title": row["title"]},
                          conn=conn)
    return redirect(url_for("session_admin.evenements", slug=slug))


# ─── Signalements ─────────────────────────────────────────────────────────────

@bp.get("/signalements")
@auth.require_admin
def signalements(slug):
    from .. import matching
    reports = matching.list_reports(g.session["schema_name"], open_only=False)
    return render_template("admin/signalements.html", session=g.session,
                           reports=reports)


@bp.post("/signalements/<rid>/traite")
@auth.require_admin
def signalement_traite(slug, rid):
    from .. import matching
    try:
        uuid.UUID(rid)
    except ValueError:
        abort(404)
    if matching.mark_report_handled(g.session["schema_name"], rid):
        audit.log("admin.report_handled", actor_role="admin",
                  actor_id=g.actor["id"], actor_label=g.actor["email"],
                  session_id=g.session["id"], target_type="report",
                  target_id=rid)
    return redirect(url_for("session_admin.signalements", slug=slug))


# ─── Passions : catalogue suggéré + interdictions ────────────────────────────

@bp.route("/passions", methods=["GET", "POST"])
@auth.require_admin
def passions(slug):
    from .. import matching
    schema = g.session["schema_name"]
    error = None
    if request.method == "POST":
        action = request.form.get("action")
        name = request.form.get("name", "")
        if action == "catalog_add":
            if not matching.add_catalog(schema, name):
                error = "Passion invalide ou interdite."
            else:
                audit.log("admin.interest_add", actor_role="admin",
                          actor_id=g.actor["id"], actor_label=g.actor["email"],
                          session_id=g.session["id"], target_type="interest",
                          target_id=name)
        elif action == "catalog_del":
            matching.remove_catalog(schema, name)
        elif action == "ban_add":
            n = matching.add_banned(schema, name)
            if not n:
                error = "Mot invalide."
            else:
                audit.log("admin.interest_ban", actor_role="admin",
                          actor_id=g.actor["id"], actor_label=g.actor["email"],
                          session_id=g.session["id"], target_type="interest",
                          target_id=n)
        elif action == "ban_del":
            matching.remove_banned(schema, name)
        return redirect(url_for("session_admin.passions", slug=slug))

    return render_template(
        "admin/passions.html", session=g.session,
        catalog=matching.list_catalog(schema),
        banned=sorted(matching.get_banned(schema)),
        error=error)


# ─── Journal d'audit de la session ────────────────────────────────────────────

@bp.get("/journal")
@auth.require_admin
def journal(slug):
    logs = audit.list_logs(session_id=g.session["id"], limit=300)
    return render_template("admin/journal.html", session=g.session, logs=logs)
