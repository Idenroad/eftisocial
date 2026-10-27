"""Blueprint usager : /<slug>/ — Trouver, Découverte, Événements, Profil.

Toutes les routes exigent un jeton `user` scopé à la session (sauf connexion).
"""

import uuid
from datetime import datetime, timezone

from flask import (Blueprint, abort, g, jsonify, redirect, render_template,
                   request, send_file, session as flask_session, url_for)

from .. import audit, auth, matching, photos
from ..db import event_dir, sess_conn
from ..i18n import tr
from .common import complete_otp, load_session_or_404, start_otp

bp = Blueprint("user_app", __name__)


# ─── Connexion ────────────────────────────────────────────────────────────────

@bp.get("/<slug>/")
def home(slug):
    session = load_session_or_404(slug)
    if auth.resolve_token(auth.read_cookie("user"), "user", session["id"]):
        return redirect(url_for("user_app.trouver", slug=slug))
    return redirect(url_for("user_app.login", slug=slug))


@bp.route("/<slug>/connexion", methods=["GET", "POST"])
def login(slug):
    session = load_session_or_404(slug)
    if auth.resolve_token(auth.read_cookie("user"), "user", session["id"]):
        return redirect(url_for("user_app.trouver", slug=slug))

    error = None
    if request.method == "POST":
        email = request.form.get("email", "")
        # Courriel d'intervenant saisi sur la page membre → on bascule vers
        # la page admin plutôt qu'un "code expiré" trompeur.
        from ..db import core_conn, sess_conn
        with core_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM core.admins WHERE email = %s "
                    "AND session_id = %s AND active = true",
                    (email.strip(), session["id"]))
                is_admin = cur.fetchone() is not None
        if is_admin:
            with sess_conn(session["schema_name"]) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM users WHERE email = %s "
                        "AND deleted_at IS NULL", (email.strip(),))
                    is_user = cur.fetchone() is not None
            if not is_user:
                return redirect(url_for("session_admin.login", slug=slug))
        err, _ = start_otp(email, "user", session, slug)
        if err:
            error = err
        else:
            return redirect(url_for("user_app.verify", slug=slug))
    return render_template("auth/login.html", session=session,
                           role="usager", error=error)


@bp.route("/<slug>/connexion/verification", methods=["GET", "POST"])
def verify(slug):
    session = load_session_or_404(slug)
    pending = flask_session.get("pending") or {}
    if pending.get("role") != "user" or pending.get("slug") != slug:
        return redirect(url_for("user_app.login", slug=slug))

    error = None
    if request.method == "POST":
        raw, actor_or_err = complete_otp(
            pending["email"], "user", session,
            request.form.get("code", ""),
            remember=bool(request.form.get("remember")))
        if raw:
            resp = redirect(url_for("user_app.trouver", slug=slug))
            auth.set_auth_cookie(resp, "user", slug, raw,
                                 bool(request.form.get("remember")))
            return resp
        error = actor_or_err
    return render_template("auth/verify.html", session=session,
                           email=pending["email"], role="usager", error=error)


@bp.post("/<slug>/deconnexion")
@auth.require_user
def logout(slug):
    auth.revoke_token(g.raw_token)
    audit.log("auth.logout", actor_role="user", actor_id=g.actor["id"],
              actor_label=g.actor["email"], session_id=g.session["id"])
    resp = redirect(url_for("user_app.login", slug=slug))
    auth.clear_auth_cookie(resp, "user", slug)
    return resp


# ─── Trouver (swipe) ──────────────────────────────────────────────────────────

@bp.get("/<slug>/trouver")
@auth.require_user
def trouver(slug):
    return render_template("user/trouver.html", session=g.session,
                           active_tab="trouver")


@bp.get("/<slug>/api/deck")
@auth.require_user
def api_deck(slug):
    cards = matching.next_deck(g.session["schema_name"], g.actor["id"])
    for c in cards:
        c["photo_url"] = (
            url_for("user_app.media", slug=slug, uid=c["id"],
                    filename=c["photo"]) if c["photo"] else None)
    return jsonify({"cards": cards})


@bp.post("/<slug>/api/swipe")
@auth.require_user
def api_swipe(slug):
    data = request.get_json(silent=True) or {}
    target, action = data.get("target"), data.get("action")
    try:
        uuid.UUID(str(target))
    except (ValueError, TypeError):
        return jsonify({"error": "cible invalide"}), 400
    if action not in ("like", "pass"):
        return jsonify({"error": "action invalide"}), 400

    result = matching.record_swipe(
        g.session["schema_name"], g.actor["id"], target, action)
    if result["matched"]:
        audit.log("match.created", actor_role="user",
                  actor_id=g.actor["id"], actor_label=g.actor["email"],
                  session_id=g.session["id"], target_type="user",
                  target_id=target)
    return jsonify({"ok": True, **result})


# ─── Matchs ───────────────────────────────────────────────────────────────────

@bp.get("/<slug>/matchs")
@auth.require_user
def matchs(slug):
    rows = matching.list_matches(g.session["schema_name"], g.actor["id"])
    unread = matching.unread_counts(g.session["schema_name"], g.actor["id"])
    for r in rows:
        r["photo_url"] = (
            url_for("user_app.media", slug=slug, uid=r["id"],
                    filename=r["photo"]) if r["photo"] else None)
        r["unread"] = unread.get(str(r["match_id"]), 0)
    return render_template("user/matchs.html", session=g.session,
                           active_tab="trouver", matchs=rows)


# ─── Tchat ────────────────────────────────────────────────────────────────────

def _match_or_404(slug, mid):
    """Match dont l'usager courant fait partie, sinon 404."""
    try:
        uuid.UUID(mid)
    except ValueError:
        abort(404)
    m = matching.get_match(g.session["schema_name"], mid, g.actor["id"])
    if not m:
        abort(404)
    return m


@bp.get("/<slug>/matchs/<mid>")
@auth.require_user
def chat(slug, mid):
    m = _match_or_404(slug, mid)
    matching.mark_read(g.session["schema_name"], mid, g.actor["id"])
    m["photo_url"] = (
        url_for("user_app.media", slug=slug, uid=m["id"],
                filename=m["photo"]) if m["photo"] else None)
    return render_template("user/chat.html", session=g.session,
                           active_tab="trouver", match=m)


@bp.get("/<slug>/matchs/<mid>/messages")
@auth.require_user
def chat_messages(slug, mid):
    _match_or_404(slug, mid)
    try:
        after = int(request.args.get("after", 0))
    except ValueError:
        after = 0
    msgs = matching.list_messages(
        g.session["schema_name"], mid, g.actor["id"], after_id=after)
    # Marque lus les messages de l'autre membre dès qu'on les reçoit
    matching.mark_read(g.session["schema_name"], mid, g.actor["id"])
    for m in msgs:
        m["mine"] = str(m["sender_id"]) == str(g.actor["id"])
        m["created_at"] = m["created_at"].isoformat()
        m["sender_id"] = str(m["sender_id"])
    return jsonify({"messages": msgs})


@bp.post("/<slug>/matchs/<mid>/messages")
@auth.require_user
def chat_send(slug, mid):
    _match_or_404(slug, mid)
    data = request.get_json(silent=True) or {}
    msg = matching.send_message(
        g.session["schema_name"], mid, g.actor["id"], data.get("body", ""))
    if not msg:
        return jsonify({"error": "message vide ou trop long"}), 400
    msg["created_at"] = msg["created_at"].isoformat()
    msg["sender_id"] = str(msg["sender_id"])
    msg["mine"] = True
    return jsonify({"message": msg})


# ─── Match / blocage / signalement ───────────────────────────────────────────

@bp.post("/<slug>/matchs/<mid>/supprimer")
@auth.require_user
def match_delete(slug, mid):
    """Supprime le match : les deux profils retournent dans le pool."""
    try:
        uuid.UUID(mid)
    except ValueError:
        abort(404)
    if matching.delete_match(g.session["schema_name"], mid, g.actor["id"]):
        audit.log("match.delete", actor_role="user",
                  actor_id=g.actor["id"], actor_label=g.actor["email"],
                  session_id=g.session["id"], target_type="match",
                  target_id=mid)
    return redirect(url_for("user_app.matchs", slug=slug))


@bp.post("/<slug>/membre/<uid>/bloquer")
@auth.require_user
def membre_block(slug, uid):
    """Bloque un membre : invisibilité mutuelle + match/swipes supprimés."""
    try:
        uuid.UUID(uid)
    except ValueError:
        abort(404)
    matching.block_user(g.session["schema_name"], g.actor["id"], uid)
    audit.log("user.block", actor_role="user", actor_id=g.actor["id"],
              actor_label=g.actor["email"], session_id=g.session["id"],
              target_type="user", target_id=uid)
    return redirect(url_for("user_app.decouverte", slug=slug))


@bp.post("/<slug>/membre/<uid>/debloquer")
@auth.require_user
def membre_unblock(slug, uid):
    """Débloque : le membre réintègre le pool."""
    try:
        uuid.UUID(uid)
    except ValueError:
        abort(404)
    matching.unblock_user(g.session["schema_name"], g.actor["id"], uid)
    audit.log("user.unblock", actor_role="user", actor_id=g.actor["id"],
              actor_label=g.actor["email"], session_id=g.session["id"],
              target_type="user", target_id=uid)
    return redirect(url_for("user_app.mon_profil", slug=slug))


@bp.post("/<slug>/membre/<uid>/signaler")
@auth.require_user
def membre_report(slug, uid):
    """Signale un comportement aux intervenants de la résidence."""
    try:
        uuid.UUID(uid)
    except ValueError:
        abort(404)
    rid = matching.report_user(
        g.session["schema_name"], g.actor["id"], uid,
        request.form.get("reason", "autre"),
        request.form.get("details", ""))
    if rid is None:
        abort(404)
    audit.log("user.report", actor_role="user", actor_id=g.actor["id"],
              actor_label=g.actor["email"], session_id=g.session["id"],
              target_type="user", target_id=uid,
              details={"reason": request.form.get("reason", "autre")})
    return redirect(url_for("user_app.decouverte", slug=slug))


# ─── Découverte ───────────────────────────────────────────────────────────────

@bp.get("/<slug>/decouverte")
@auth.require_user
def decouverte(slug):
    interests = matching.interests_overview(
        g.session["schema_name"], g.actor["id"])
    return render_template("user/decouverte.html", session=g.session,
                           active_tab="decouverte", interests=interests)


@bp.get("/<slug>/decouverte/<interest>")
@auth.require_user
def decouverte_interest(slug, interest):
    members = matching.users_by_interest(
        g.session["schema_name"], g.actor["id"], interest)
    for m in members:
        m["photo_url"] = (
            url_for("user_app.media", slug=slug, uid=m["id"],
                    filename=m["photo"]) if m["photo"] else None)
    return render_template("user/decouverte_interet.html", session=g.session,
                           active_tab="decouverte", interest=interest,
                           members=members)


@bp.get("/<slug>/membre/<uid>")
@auth.require_user
def membre(slug, uid):
    try:
        uuid.UUID(uid)
    except ValueError:
        abort(404)
    if uid == str(g.actor["id"]):
        return redirect(url_for("user_app.mon_profil", slug=slug))
    prof = matching.get_profile(g.session["schema_name"], uid,
                                viewer_id=g.actor["id"])
    if not prof:
        abort(404)
    mine = matching.user_interests_for(g.session["schema_name"], g.actor["id"])
    for p in prof["photos"]:
        p["url"] = url_for("user_app.media", slug=slug, uid=uid,
                           filename=p["filename"])
    prof["shared"] = sorted(set(prof["interests"]) & set(mine))
    return render_template("user/membre.html", session=g.session,
                           active_tab="decouverte", profil=prof)


# ─── Événements ───────────────────────────────────────────────────────────────

def _events_list(schema: str, user_id):
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT e.*,
                       (SELECT count(*) FROM event_participants ep
                         WHERE ep.event_id = e.id) AS participants,
                       EXISTS(SELECT 1 FROM event_participants ep
                              WHERE ep.event_id = e.id
                                AND ep.user_id = %s) AS joined
                FROM events e
                ORDER BY e.event_at
                """,
                (str(user_id),))
            return [dict(r) for r in cur.fetchall()]


@bp.route("/<slug>/evenements", methods=["GET", "POST"])
@auth.require_user
def evenements(slug):
    schema = g.session["schema_name"]
    error = None
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        location = (request.form.get("location") or "").strip()
        desc = (request.form.get("description") or "").strip()
        when = request.form.get("event_at") or ""
        max_p = request.form.get("max_participants") or ""
        try:
            event_at = datetime.fromisoformat(when)
            if event_at.tzinfo is None:
                event_at = event_at.replace(tzinfo=timezone.utc)
        except ValueError:
            event_at = None
        if not title or len(title) > 120 or event_at is None:
            error = tr("Titre et date sont requis.")
        else:
            with sess_conn(schema) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO events "
                        "(title, description, location, event_at, "
                        " max_participants, creator_role, creator_id, creator_name) "
                        "VALUES (%s,%s,%s,%s,%s,'user',%s,%s) RETURNING id",
                        (title[:120], desc[:2000], location[:200], event_at,
                         int(max_p) if max_p.isdigit() else None,
                         str(g.actor["id"]), g.actor["first_name"]))
                    eid = cur.fetchone()["id"]
            event_dir(slug, eid).mkdir(parents=True, exist_ok=True)
            audit.log("event.create", actor_role="user",
                      actor_id=g.actor["id"], actor_label=g.actor["email"],
                      session_id=g.session["id"], target_type="event",
                      target_id=eid, details={"title": title[:120]})
            return redirect(url_for("user_app.evenements", slug=slug))

    return render_template("user/evenements.html", session=g.session,
                           active_tab="evenements",
                           events=_events_list(schema, g.actor["id"]),
                           error=error)


def _event_action(slug, eid, action: str):
    try:
        uuid.UUID(eid)
    except ValueError:
        abort(404)
    schema = g.session["schema_name"]
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, title, max_participants, cancelled, creator_id, "
                "creator_role FROM events WHERE id = %s", (eid,))
            ev = cur.fetchone()
            if not ev or ev["cancelled"]:
                abort(404)
            if action == "join":
                cur.execute(
                    "SELECT count(*) AS n FROM event_participants "
                    "WHERE event_id = %s", (eid,))
                n = cur.fetchone()["n"]
                if ev["max_participants"] and n >= ev["max_participants"]:
                    return tr("L'événement est complet.")
                cur.execute(
                    "INSERT INTO event_participants (event_id, user_id) "
                    "VALUES (%s,%s) ON CONFLICT DO NOTHING",
                    (eid, str(g.actor["id"])))
                audit.log("event.join", actor_role="user",
                          actor_id=g.actor["id"], actor_label=g.actor["email"],
                          session_id=g.session["id"], target_type="event",
                          target_id=eid, details={"title": ev["title"]})
            elif action == "leave":
                cur.execute(
                    "DELETE FROM event_participants "
                    "WHERE event_id = %s AND user_id = %s",
                    (eid, str(g.actor["id"])))
                audit.log("event.leave", actor_role="user",
                          actor_id=g.actor["id"], actor_label=g.actor["email"],
                          session_id=g.session["id"], target_type="event",
                          target_id=eid, details={"title": ev["title"]})
            elif action == "cancel":
                # Seul le créateur usager peut annuler son événement
                if not (ev["creator_role"] == "user"
                        and str(ev["creator_id"]) == str(g.actor["id"])):
                    abort(403)
                cur.execute(
                    "UPDATE events SET cancelled = true WHERE id = %s", (eid,))
                audit.log("event.cancel", actor_role="user",
                          actor_id=g.actor["id"], actor_label=g.actor["email"],
                          session_id=g.session["id"], target_type="event",
                          target_id=eid, details={"title": ev["title"]})
    return None


@bp.post("/<slug>/evenements/<eid>/rejoindre")
@auth.require_user
def event_join(slug, eid):
    err = _event_action(slug, eid, "join")
    if request.headers.get("Accept") == "application/json" or request.is_json:
        return jsonify({"ok": err is None, "error": err})
    return redirect(url_for("user_app.evenements", slug=slug))


@bp.post("/<slug>/evenements/<eid>/quitter")
@auth.require_user
def event_leave(slug, eid):
    _event_action(slug, eid, "leave")
    return redirect(url_for("user_app.evenements", slug=slug))


@bp.post("/<slug>/evenements/<eid>/annuler")
@auth.require_user
def event_cancel(slug, eid):
    _event_action(slug, eid, "cancel")
    return redirect(url_for("user_app.evenements", slug=slug))


# ─── Mon profil ───────────────────────────────────────────────────────────────

@bp.route("/<slug>/mon-profil", methods=["GET", "POST"])
@auth.require_user
def mon_profil(slug):
    schema = g.session["schema_name"]
    msg = error = None
    if request.method == "POST":
        first_name = (request.form.get("first_name") or "").strip()[:60]
        sex = request.form.get("sex") or ""
        bio = (request.form.get("bio") or "").strip()[:500]
        interests = request.form.getlist("interests")
        if not first_name or sex not in ("F", "M", "X"):
            error = tr("Prénom et sexe sont requis.")
        else:
            with sess_conn(schema) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE users SET first_name=%s, sex=%s, bio=%s, "
                        "updated_at=now() WHERE id=%s",
                        (first_name, sex, bio, str(g.actor["id"])))
            matching.set_user_interests(schema, g.actor["id"], interests)
            audit.log("user.update", actor_role="user",
                      actor_id=g.actor["id"], actor_label=g.actor["email"],
                      session_id=g.session["id"], target_type="user",
                      target_id=g.actor["id"])
            msg = tr("Profil mis à jour.")
            g.actor["first_name"] = first_name

    profil = matching.get_profile(schema, g.actor["id"], include_paused=True)
    for p in profil["photos"]:
        p["url"] = url_for("user_app.media", slug=slug,
                           uid=g.actor["id"], filename=p["filename"])
    blocked = matching.list_blocked(schema, g.actor["id"])
    catalog = matching.list_catalog(schema)
    return render_template("user/profil.html", session=g.session,
                           active_tab="profil", profil=profil,
                           blocked=blocked, catalog=catalog,
                           msg=msg, error=error)


@bp.post("/<slug>/mon-profil/photos")
@auth.require_user
def photo_upload(slug):
    f = request.files.get("photo")
    if not f or not f.filename:
        return redirect(url_for("user_app.mon_profil", slug=slug))
    try:
        photos.save_photo(g.session["schema_name"], slug, g.actor["id"], f)
        audit.log("user.photo_add", actor_role="user",
                  actor_id=g.actor["id"], actor_label=g.actor["email"],
                  session_id=g.session["id"], target_type="user",
                  target_id=g.actor["id"])
    except photos.PhotoError as e:
        return render_template("user/profil.html", session=g.session,
                               active_tab="profil",
                               profil=matching.get_profile(
                                   g.session["schema_name"], g.actor["id"],
                                   include_paused=True),
                               error=str(e)), 400
    return redirect(url_for("user_app.mon_profil", slug=slug))


@bp.post("/<slug>/mon-profil/photos/<pid>/supprimer")
@auth.require_user
def photo_delete(slug, pid):
    try:
        uuid.UUID(pid)
    except ValueError:
        abort(404)
    photos.delete_photo(g.session["schema_name"], slug, g.actor["id"], pid)
    return redirect(url_for("user_app.mon_profil", slug=slug))


@bp.post("/<slug>/mon-profil/photos/<pid>/principale")
@auth.require_user
def photo_primary(slug, pid):
    try:
        uuid.UUID(pid)
    except ValueError:
        abort(404)
    photos.set_primary(g.session["schema_name"], g.actor["id"], pid)
    return redirect(url_for("user_app.mon_profil", slug=slug))


@bp.post("/<slug>/mon-profil/pause")
@auth.require_user
def profil_pause(slug):
    with sess_conn(g.session["schema_name"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET paused = NOT paused, updated_at=now() "
                "WHERE id = %s RETURNING paused", (str(g.actor["id"]),))
            paused = cur.fetchone()["paused"]
    audit.log("user.pause" if paused else "user.unpause",
              actor_role="user", actor_id=g.actor["id"],
              actor_label=g.actor["email"], session_id=g.session["id"],
              target_type="user", target_id=g.actor["id"])
    return redirect(url_for("user_app.mon_profil", slug=slug))


@bp.post("/<slug>/mon-profil/supprimer")
@auth.require_user
def profil_delete(slug):
    if request.form.get("confirm") != "oui":
        return redirect(url_for("user_app.mon_profil", slug=slug))
    schema = g.session["schema_name"]
    uid = g.actor["id"]
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET deleted_at = now(), paused = true "
                "WHERE id = %s", (str(uid),))
    photos.delete_profile_dir(slug, uid)
    auth.revoke_actor_tokens("user", uid)
    audit.log("user.delete", actor_role="user", actor_id=uid,
              actor_label=g.actor["email"], session_id=g.session["id"],
              target_type="user", target_id=uid)
    resp = redirect(url_for("user_app.login", slug=slug))
    auth.clear_auth_cookie(resp, "user", slug)
    return resp


# ─── Médias (photos privées par session) ──────────────────────────────────────

def _member_or_admin(slug: str, session: dict) -> bool:
    """Jeton user OU admin de cette session (les intervenants voient les
    photos des membres qu'ils gèrent)."""
    if auth.resolve_token(auth.read_cookie("user"), "user", session["id"]):
        return True
    if auth.resolve_token(auth.read_cookie("admin"), "admin", session["id"]):
        return True
    return False


@bp.get("/<slug>/media/profils/<uid>/<filename>")
def media(slug, uid, filename):
    session = load_session_or_404(slug)
    if not _member_or_admin(slug, session):
        abort(403)
    try:
        uuid.UUID(uid)
    except ValueError:
        abort(404)
    if "/" in filename or ".." in filename:
        abort(404)
    try:
        fpath = photos.photo_path(slug, uid, filename)
    except photos.PhotoError:
        abort(404)
    if not fpath.is_file():
        abort(404)
    resp = send_file(fpath, mimetype="image/webp")
    resp.headers["Cache-Control"] = "private, max-age=3600"
    return resp


# ─── PWA ──────────────────────────────────────────────────────────────────────

@bp.get("/<slug>/manifest.webmanifest")
def manifest(slug):
    session = load_session_or_404(slug)
    return jsonify({
        "name": f"EftiSocial — {session['name']}",
        "short_name": session["name"][:12],
        "start_url": url_for("user_app.home", slug=slug),
        "scope": f"/{slug}/",
        "display": "standalone",
        "background_color": "#FFFFFF",
        "theme_color": "#006847",
        "icons": [
            {"src": url_for("static", filename="icons/icon-192.png"),
             "sizes": "192x192", "type": "image/png"},
            {"src": url_for("static", filename="icons/icon-512.png"),
             "sizes": "512x512", "type": "image/png"},
        ],
    })
