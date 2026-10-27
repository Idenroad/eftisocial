"""Tests des événements : création (user/admin/superadmin), inscription,
capacité, annulation, suppression."""

import uuid
from datetime import datetime, timedelta, timezone

from .conftest import (csrf_of, login_admin, login_user, mk_admin, mk_session,
                       mk_user, post)


def _mk_event(schema, creator_id=None, role="admin", max_p=None,
              title="Soirée-Qaqq"):
    """Insère un événement directement en DB. Retourne l'uuid."""
    from app.db import sess_conn
    eid = uuid.uuid4()
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO events (id, title, location, event_at, "
                "max_participants, creator_role, creator_id, creator_name) "
                "VALUES (%s,%s,'Salle',%s,%s,%s,%s,'Organisateur')",
                (str(eid), title,
                 datetime.now(timezone.utc) + timedelta(days=2),
                 max_p, role, creator_id and str(creator_id)))
    return str(eid)


def test_user_creates_event(app, client):
    s = mk_session("res-ev-a")
    mk_user(s["schema_name"], "u@a.local", otp="111111")
    login_user(client, "res-ev-a", "u@a.local", "111111")
    when = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M")
    resp = post(client, "/res-ev-a/evenements", "/res-ev-a/evenements",
                data={"title": "Soirée cartes", "location": "Salon",
                      "event_at": when})
    assert resp.status_code == 302
    from app.db import sess_conn
    with sess_conn(s["schema_name"]) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT title, creator_role FROM events")
            rows = cur.fetchall()
    assert len(rows) == 1 and rows[0]["creator_role"] == "user"


def test_join_leave_event(app, client):
    s = mk_session("res-ev-b")
    uid = mk_user(s["schema_name"], "u@b.local", otp="111111")
    eid = _mk_event(s["schema_name"])
    login_user(client, "res-ev-b", "u@b.local", "111111")

    post(client, f"/res-ev-b/evenements/{eid}/rejoindre",
         "/res-ev-b/evenements")
    from app.db import sess_conn
    with sess_conn(s["schema_name"]) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM event_participants "
                        "WHERE event_id=%s AND user_id=%s", (eid, uid))
            assert cur.fetchone() is not None

    post(client, f"/res-ev-b/evenements/{eid}/quitter",
         "/res-ev-b/evenements")
    with sess_conn(s["schema_name"]) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM event_participants "
                        "WHERE event_id=%s", (eid,))
            assert cur.fetchone()["n"] == 0


def test_event_capacity(app, client):
    """Un événement complet refuse les nouvelles inscriptions."""
    s = mk_session("res-ev-c")
    u1 = mk_user(s["schema_name"], "u1@c.local", otp="111111")
    u2 = mk_user(s["schema_name"], "u2@c.local", otp="222222")
    eid = _mk_event(s["schema_name"], max_p=1)

    login_user(client, "res-ev-c", "u1@c.local", "111111")
    post(client, f"/res-ev-c/evenements/{eid}/rejoindre", "/res-ev-c/evenements")

    c2 = app.test_client()
    login_user(c2, "res-ev-c", "u2@c.local", "222222")
    post(c2, f"/res-ev-c/evenements/{eid}/rejoindre", "/res-ev-c/evenements")

    from app.db import sess_conn
    with sess_conn(s["schema_name"]) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM event_participants "
                        "WHERE event_id=%s", (eid,))
            assert cur.fetchone()["n"] == 1


def test_cancel_only_own_event(app, client):
    """Seul le créateur usager peut annuler son événement."""
    s = mk_session("res-ev-d")
    u1 = mk_user(s["schema_name"], "u1@d.local", otp="111111")
    u2 = mk_user(s["schema_name"], "u2@d.local", otp="222222")
    eid = _mk_event(s["schema_name"], creator_id=u1, role="user")

    # u2 (non créateur) : 403
    login_user(client, "res-ev-d", "u2@d.local", "222222")
    resp = post(client, f"/res-ev-d/evenements/{eid}/annuler",
                "/res-ev-d/evenements")
    assert resp.status_code == 403

    # u1 (créateur) : OK
    c1 = app.test_client()
    login_user(c1, "res-ev-d", "u1@d.local", "111111")
    resp = post(c1, f"/res-ev-d/evenements/{eid}/annuler",
                "/res-ev-d/evenements")
    assert resp.status_code == 302
    from app.db import sess_conn
    with sess_conn(s["schema_name"]) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT cancelled FROM events WHERE id=%s", (eid,))
            assert cur.fetchone()["cancelled"] is True


def test_admin_deletes_event(app, client):
    """L'intervenant peut supprimer l'événement d'un membre."""
    s = mk_session("res-ev-e")
    mk_admin(s["id"], "int@e.local", otp="4444")
    u1 = mk_user(s["schema_name"], "u1@e.local")
    eid = _mk_event(s["schema_name"], creator_id=u1, role="user")

    login_admin(client, "res-ev-e", "int@e.local", "4444")
    resp = post(client, f"/res-ev-e/admin/evenements/{eid}/supprimer",
                "/res-ev-e/admin/evenements")
    assert resp.status_code == 302
    from app.db import sess_conn
    with sess_conn(s["schema_name"]) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT cancelled FROM events WHERE id=%s", (eid,))
            assert cur.fetchone()["cancelled"] is True


def test_event_not_visible_cross_session(app, client):
    """Un événement de res-ev-f est invisible dans res-ev-g."""
    sf = mk_session("res-ev-f")
    sg = mk_session("res-ev-g")
    eid = _mk_event(sf["schema_name"])
    mk_user(sg["schema_name"], "u@g.local", otp="111111")
    login_user(client, "res-ev-g", "u@g.local", "111111")
    # Tenter de rejoindre l'event de l'autre session : 404 dans ce schéma
    resp = post(client, f"/res-ev-g/evenements/{eid}/rejoindre",
                "/res-ev-g/evenements")
    assert resp.status_code in (302, 404)
    html = client.get("/res-ev-g/evenements").get_data(as_text=True)
    assert "Soirée-Qaqq" not in html
