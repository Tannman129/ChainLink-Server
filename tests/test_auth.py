import time
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import COOKIE, create_account, digest, hasher
from app.config import get_settings
from app.main import app
from app.models import Account, WebSession


def login(client, username="alice", password="a-long-password-123"):
    csrf = client.get("/v1/auth/session").json()["csrf_token"]
    return client.post(
        "/v1/auth/login",
        json={"username": username, "password": password},
        headers={"X-CSRF-Token": csrf},
    )


@pytest.fixture
def player(engine):
    with Session(engine) as db:
        account = create_account(db, "Alice", "a-long-password-123", "player")
        assert account.username == "alice"
        assert account.password_hash.startswith("$argon2id$")
        assert hasher.verify(account.password_hash, "a-long-password-123")
        return account.id


def test_public_reads_and_anonymous_writes(anonymous_client, layout_payload):
    c = anonymous_client
    assert c.get("/").status_code == 200
    assert c.get("/v1/courses").json() == []
    assert c.post("/v1/courses", json={"name": "Test"}).status_code == 401
    assert (
        c.post(
            "/v1/courses/00000000-0000-0000-0000-000000000000/layouts",
            json=layout_payload,
        ).status_code
        == 401
    )


def test_player_denied_course_writes(anonymous_client, player, layout_payload):
    c = anonymous_client
    response = login(c)
    assert response.status_code == 200
    c.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    assert c.get("/v1/auth/session").json()["user"]["role"] == "player"
    assert c.post("/v1/courses", json={"name": "Test"}).status_code == 403
    assert (
        c.post(
            "/v1/courses/00000000-0000-0000-0000-000000000000/layouts",
            json=layout_payload,
        ).status_code
        == 403
    )


def test_csrf_rotation_logout_and_storage(anonymous_client, engine, player):
    c = anonymous_client
    assert (
        c.post(
            "/v1/auth/login",
            json={"username": "alice", "password": "a-long-password-123"},
        ).status_code
        == 403
    )
    pre = c.get("/v1/auth/session").json()["csrf_token"]
    old_cookie = c.cookies.get(COOKIE)
    response = login(c)
    assert response.status_code == 200
    cookie = c.cookies.get(COOKIE)
    assert cookie != old_cookie
    assert response.json()["csrf_token"] != pre
    assert "httponly" in response.headers["set-cookie"].lower()
    assert "samesite=strict" in response.headers["set-cookie"].lower()
    with Session(engine) as db:
        assert db.get(WebSession, digest(old_cookie)) is None
        assert db.get(WebSession, digest(cookie)).account_id == player
        assert db.get(WebSession, cookie) is None
    assert c.post("/v1/auth/logout").status_code == 403
    assert c.post("/v1/auth/logout", headers={"X-CSRF-Token": pre}).status_code == 403
    assert (
        c.post(
            "/v1/auth/logout", headers={"X-CSRF-Token": response.json()["csrf_token"]}
        ).status_code
        == 204
    )
    with Session(engine) as db:
        assert db.get(WebSession, digest(cookie)) is None
    c.cookies.set(COOKIE, cookie)
    assert c.get("/v1/auth/session").json()["user"] is None


def test_admin_csrf_required(client):
    token = client.headers.pop("X-CSRF-Token")
    assert client.post("/v1/courses", json={"name": "Test"}).status_code == 403
    client.headers["X-CSRF-Token"] = token
    assert client.post("/v1/courses", json={"name": "Test"}).status_code == 201


def test_expiration(client, engine):
    token = client.cookies.get(COOKIE)
    with Session(engine) as db:
        db.get(WebSession, digest(token)).expires_at = int(time.time()) - 1
        db.commit()
    assert client.post("/v1/courses", json={"name": "Test"}).status_code == 401
    assert client.get("/v1/auth/session").json()["user"] is None


def test_generic_failures_and_database_rate_limit(anonymous_client, engine, player):
    c = anonymous_client
    missing = login(c, "missing")
    wrong = login(c, password="incorrect")
    assert missing.status_code == wrong.status_code == 401
    assert missing.json() == wrong.json()
    for _ in range(8):
        assert login(c, password="incorrect").status_code == 401
    # A correct password is also limited; no bypass by changing username or session.
    c.cookies.clear()
    response = login(c)
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0


def test_secure_cookie_default(anonymous_client, monkeypatch):
    monkeypatch.delenv("SESSION_COOKIE_SECURE", raising=False)
    get_settings.cache_clear()
    assert get_settings().session_cookie_secure is True
    response = anonymous_client.get("/v1/auth/session")
    assert "; Secure" in response.headers["set-cookie"]
    assert response.headers["cache-control"] == "no-store"


def test_account_validation(engine):
    with Session(engine) as db:
        for username, password, role in [
            ("ab", "long-password-123", "player"),
            ("valid", "short", "player"),
            ("valid", "long-password-123", "owner"),
        ]:
            with pytest.raises(ValueError):
                create_account(db, username, password, role)


def test_upgrade_preserves_catalog(engine):
    config = Config("alembic.ini")
    config.attributes["database_url"] = engine.url
    command.downgrade(config, "0001")
    from app import models as m

    tables = [
        m.Course.__table__,
        m.Layout.__table__,
        m.Hole.__table__,
        m.Tee.__table__,
        m.Basket.__table__,
        m.Configuration.__table__,
        m.HoleDefault.__table__,
    ]
    course, layout, hole, tee, basket, config_a, basket_b = [uuid4() for _ in range(7)]
    rows = [
        [{"id": course, "name": "Existing course", "description": "Preserve me"}],
        [{"id": layout, "course_id": course, "name": "Existing layout"}],
        [{"id": hole, "layout_id": layout, "number": 1}],
        [{"id": tee, "hole_id": hole, "name": "Long"}],
        [
            {"id": basket, "hole_id": hole, "name": "A"},
            {"id": basket_b, "hole_id": hole, "name": "B"},
        ],
        [
            {
                "id": config_a,
                "hole_id": hole,
                "tee_id": tee,
                "basket_id": basket,
                "par": 3,
                "distance_ft": 250,
            },
            {
                "id": uuid4(),
                "hole_id": hole,
                "tee_id": tee,
                "basket_id": basket_b,
                "par": 4,
                "distance_ft": None,
            },
        ],
        [{"hole_id": hole, "configuration_id": config_a}],
    ]

    def snapshot():
        with engine.connect() as conn:
            return {
                table.name: set(conn.execute(select(table)).all()) for table in tables
            }

    with engine.begin() as conn:
        for table, values in zip(tables, rows, strict=True):
            conn.execute(table.insert(), values)
    before = snapshot()
    command.upgrade(config, "0002")
    engine.dispose()  # Read committed data through fresh connections.
    assert snapshot() == before
    with Session(engine) as db:
        assert db.scalars(select(Account)).all() == []


def test_session_persists_across_clients_and_rotates_on_relogin(
    anonymous_client, engine, player
):
    response = login(anonymous_client)
    assert response.status_code == 200
    old_cookie = anonymous_client.cookies.get(COOKIE)
    engine.dispose()
    with TestClient(app) as other:
        other.cookies.update(anonymous_client.cookies)
        assert other.get("/v1/auth/session").json()["user"] == {
            "username": "alice",
            "role": "player",
        }
        assert other.cookies.get(COOKIE) == old_cookie
        assert login(other).status_code == 200
        assert other.cookies.get(COOKIE) != old_cookie
    with Session(engine) as db:
        assert db.get(WebSession, digest(old_cookie)) is None
    assert anonymous_client.get("/v1/auth/session").json()["user"] is None


def test_invalid_login_never_echoes_password(anonymous_client):
    csrf = anonymous_client.get("/v1/auth/session").json()["csrf_token"]
    password = "sensitive" * 40
    response = anonymous_client.post(
        "/v1/auth/login",
        json={"username": "alice", "password": password},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 422
    assert password not in response.text
    assert response.headers["cache-control"] == "no-store"
