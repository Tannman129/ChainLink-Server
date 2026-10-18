"""Runs on SQLite locally and live PostgreSQL via compose.test.yaml."""

from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, delete, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models as m
from app.auth import create_account
from app.main import app


@pytest.fixture
def round_payload():
    return {
        "id": str(uuid4()),
        "completed_at": "2026-10-18T12:30:00Z",
        "course_name": "Offline course",
        "layout_name": "Main",
        "holes": [
            {
                "number": 1,
                "par": 3,
                "tee_name": "Short",
                "basket_name": "A",
                "distance_ft": 250,
            },
            {"number": 2, "par": 4, "tee_name": "Long", "basket_name": "B"},
        ],
        "participants": [
            {
                "id": str(uuid4()),
                "name": "Guest Alice",
                "scores": [
                    {"hole_number": 1, "strokes": 2},
                    {"hole_number": 2, "strokes": 5},
                ],
            },
            {
                "id": str(uuid4()),
                "name": "Guest Bob",
                "scores": [
                    {"hole_number": 1, "strokes": 3},
                    {"hole_number": 2, "strokes": 6},
                ],
            },
        ],
    }


@pytest.fixture
def player_client(anonymous_client, engine):
    with Session(engine) as db:
        create_account(db, "round-player", "long-password-123", "player")
    csrf = anonymous_client.get("/v1/auth/session").json()["csrf_token"]
    response = anonymous_client.post(
        "/v1/auth/login",
        json={"username": "round-player", "password": "long-password-123"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200
    anonymous_client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return anonymous_client


def test_round_creation_multiple_guests_and_persistence(
    player_client, engine, round_payload
):
    response = player_client.post("/v1/rounds", json=round_payload)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["id"] == round_payload["id"]
    assert result["total_par"] == 7
    players = {p["name"]: p for p in result["participants"]}
    assert players["Guest Alice"]["total_strokes"] == 7
    assert players["Guest Alice"]["score_to_par"] == 0
    assert players["Guest Bob"]["total_strokes"] == 9
    assert players["Guest Bob"]["score_to_par"] == 2
    assert result["holes"][1]["distance_ft"] is None
    engine.dispose()
    assert player_client.get(f"/v1/rounds/{result['id']}").json() == result
    assert player_client.get("/v1/rounds").json() == [result]
    assert player_client.get("/v1/rounds?limit=1&offset=1").json() == []
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(m.Account)) == 1
        assert db.scalar(select(func.count()).select_from(m.RoundScore)) == 4
    assert response.headers["cache-control"] == "no-store"


def test_round_snapshot_survives_catalog_edit_and_delete(
    client, engine, graph, round_payload
):
    round_payload.update(
        course_name=graph["name"],
        layout_name=graph["layouts"][0]["name"],
        source_course_id=graph["id"],
        source_layout_id=graph["layouts"][0]["id"],
    )
    response = client.post("/v1/rounds", json=round_payload)
    assert response.status_code == 201
    original = response.json()
    with Session(engine) as db:
        db.get(m.Course, UUID(graph["id"])).name = "Renamed"
        db.execute(m.Configuration.__table__.update().values(par=8, distance_ft=999))
        db.commit()
    assert client.get(f"/v1/rounds/{original['id']}").json() == original
    with engine.begin() as conn:
        conn.execute(delete(m.Course).where(m.Course.id == UUID(graph["id"])))
    assert client.get(f"/v1/rounds/{original['id']}").json() == original


def test_duplicate_round_is_idempotent_and_conflicts_are_immutable(
    player_client, engine, round_payload
):
    first = player_client.post("/v1/rounds", json=round_payload)
    assert first.status_code == 201
    retry = deepcopy(round_payload)
    retry["participants"].reverse()
    retry["holes"].reverse()
    for participant in retry["participants"]:
        participant["scores"].reverse()
    retry["completed_at"] = "2026-10-18T07:30:00-05:00"
    response = player_client.post("/v1/rounds", json=retry)
    assert response.status_code == 200
    assert response.json() == first.json()
    retry["participants"][0]["scores"][0]["strokes"] += 1
    assert player_client.post("/v1/rounds", json=retry).status_code == 409
    assert player_client.get(f"/v1/rounds/{round_payload['id']}").json() == first.json()
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(m.CompletedRound)) == 1
        assert db.scalar(select(func.count()).select_from(m.RoundParticipant)) == 2


@pytest.mark.parametrize("role", ["player", "administrator"])
@pytest.mark.parametrize("linked", [False, True])
def test_round_owner_isolation(player_client, engine, round_payload, role, linked):
    if linked:
        round_payload["participants"][0]["account_id"] = own_account_id(engine)
    assert player_client.post("/v1/rounds", json=round_payload).status_code == 201
    with Session(engine) as db:
        create_account(db, "other-account", "long-password-123", role)
    with TestClient(app) as other:
        csrf = other.get("/v1/auth/session").json()["csrf_token"]
        logged = other.post(
            "/v1/auth/login",
            json={"username": "other-account", "password": "long-password-123"},
            headers={"X-CSRF-Token": csrf},
        )
        assert logged.status_code == 200
        other.headers["X-CSRF-Token"] = logged.json()["csrf_token"]
        assert other.get("/v1/rounds").json() == []
        assert other.get(f"/v1/rounds/{round_payload['id']}").status_code == 404
        assert other.post("/v1/rounds", json=round_payload).status_code == (
            403 if linked else 409
        )


def test_round_authentication_and_csrf(anonymous_client, round_payload):
    assert anonymous_client.get("/v1/rounds").status_code == 401
    assert anonymous_client.get(f"/v1/rounds/{round_payload['id']}").status_code == 401
    assert anonymous_client.post("/v1/rounds", json=round_payload).status_code == 401


def test_round_write_requires_csrf(player_client, round_payload):
    player_client.headers.pop("X-CSRF-Token")
    assert player_client.post("/v1/rounds", json=round_payload).status_code == 403


@pytest.mark.parametrize(
    "problem",
    [
        "missing_score",
        "duplicate_score",
        "unknown_hole",
        "duplicate_hole",
        "duplicate_player",
        "zero",
        "bool",
        "naive_time",
        "owner",
        "empty",
        "overflow",
    ],
)
def test_round_rejects_incomplete_or_invalid_scorecards(
    player_client, engine, round_payload, problem
):
    p = round_payload
    if problem == "missing_score":
        p["participants"][0]["scores"].pop()
    elif problem == "duplicate_score":
        p["participants"][0]["scores"][1]["hole_number"] = 1
    elif problem == "unknown_hole":
        p["participants"][0]["scores"][1]["hole_number"] = 3
    elif problem == "duplicate_hole":
        p["holes"][1]["number"] = 1
    elif problem == "duplicate_player":
        p["participants"][1]["id"] = p["participants"][0]["id"]
    elif problem in {"zero", "bool", "overflow"}:
        p["participants"][0]["scores"][0]["strokes"] = {
            "zero": 0,
            "bool": True,
            "overflow": 2147483647,
        }[problem]
    elif problem == "naive_time":
        p["completed_at"] = "2026-10-18T12:30:00"
    elif problem == "owner":
        p["owner_id"] = str(uuid4())
    else:
        p["participants"] = []
    assert player_client.post("/v1/rounds", json=p).status_code == 422
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(m.CompletedRound)) == 0


def test_round_migration_preserves_all_existing_tables(client, engine, graph):
    config = Config("alembic.ini")
    config.attributes["database_url"] = engine.url
    command.downgrade(config, "0002")
    metadata = MetaData()
    metadata.reflect(engine)
    tables = [t for t in metadata.tables.values() if t.name != "alembic_version"]

    def snapshot():
        with engine.connect() as conn:
            return {t.name: set(conn.execute(select(t)).all()) for t in tables}

    before = snapshot()
    assert all(
        before[name]
        for name in (
            "courses",
            "layouts",
            "holes",
            "tees",
            "baskets",
            "configurations",
            "hole_defaults",
            "accounts",
            "web_sessions",
            "login_buckets",
        )
    )
    command.upgrade(config, "0003")
    assert snapshot() == before
    assert {
        "completed_rounds",
        "round_holes",
        "round_participants",
        "round_scores",
    } <= set(inspect(engine).get_table_names())
    command.downgrade(config, "0002")
    assert snapshot() == before
    command.upgrade(config, "head")
    assert snapshot() == before


def test_round_database_constraints(player_client, engine, round_payload):
    assert player_client.post("/v1/rounds", json=round_payload).status_code == 201
    with engine.begin() as conn:
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(m.RoundScore.__table__.update().values(strokes=0))
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(
                m.RoundScore.__table__.insert().values(
                    round_id=UUID(round_payload["id"]),
                    participant_id=uuid4(),
                    hole_number=1,
                    strokes=3,
                )
            )
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(m.RoundScore.__table__.update().values(hole_number=99))
        assert conn.scalar(text("SELECT count(*) FROM round_scores")) == 4


def own_account_id(engine):
    with Session(engine) as db:
        return str(
            db.scalar(select(m.Account.id).where(m.Account.username == "round-player"))
        )


def test_explicit_identity_and_immutable_retries(player_client, engine, round_payload):
    account_id = own_account_id(engine)
    round_payload["participants"][0]["account_id"] = account_id
    first = player_client.post("/v1/rounds", json=round_payload)
    assert first.status_code == 201
    players = {p["id"]: p for p in first.json()["participants"]}
    assert players[round_payload["participants"][0]["id"]]["account_id"] == account_id
    assert players[round_payload["participants"][1]["id"]]["account_id"] is None
    assert all("username" not in p and "account" not in p for p in players.values())
    assert player_client.post("/v1/rounds", json=round_payload).json() == first.json()
    round_payload["participants"][0]["account_id"] = None
    assert player_client.post("/v1/rounds", json=round_payload).status_code == 409
    assert player_client.get(f"/v1/rounds/{round_payload['id']}").json() == first.json()
    # One account may play in multiple rounds.
    round_payload["id"] = str(uuid4())
    round_payload["participants"][0]["account_id"] = account_id
    assert player_client.post("/v1/rounds", json=round_payload).status_code == 201


@pytest.mark.parametrize("existing", [True, False])
def test_cannot_link_other_accounts(player_client, engine, round_payload, existing):
    with Session(engine) as db:
        other_id = (
            create_account(db, "other-player", "long-password-123", "player").id
            if existing
            else uuid4()
        )
    round_payload["participants"][0]["account_id"] = str(other_id)
    assert player_client.post("/v1/rounds", json=round_payload).status_code == 403
    assert player_client.get("/v1/rounds").json() == []


def test_duplicate_identity_rejected(player_client, engine, round_payload):
    for participant in round_payload["participants"]:
        participant["account_id"] = own_account_id(engine)
    assert player_client.post("/v1/rounds", json=round_payload).status_code == 422
    assert player_client.get("/v1/rounds").json() == []


def test_names_and_ownership_do_not_claim_identity(
    player_client, engine, round_payload
):
    round_payload["participants"][0]["name"] = "round-player"
    first = player_client.post("/v1/rounds", json=round_payload)
    assert first.status_code == 201
    assert all(p["account_id"] is None for p in first.json()["participants"])
    for participant in round_payload["participants"]:
        participant["account_id"] = None
    assert player_client.post("/v1/rounds", json=round_payload).status_code == 200
    round_payload["participants"][0]["account_id"] = own_account_id(engine)
    assert player_client.post("/v1/rounds", json=round_payload).status_code == 409


def test_identity_database_constraints(player_client, engine, round_payload):
    account_id = UUID(own_account_id(engine))
    assert player_client.post("/v1/rounds", json=round_payload).status_code == 201
    with engine.begin() as conn:
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(
                m.RoundParticipant.__table__.update().values(account_id=uuid4())
            )
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(
                m.RoundParticipant.__table__.update().values(account_id=account_id)
            )
        conn.execute(
            m.RoundParticipant.__table__.update()
            .where(
                m.RoundParticipant.id == UUID(round_payload["participants"][0]["id"])
            )
            .values(account_id=account_id)
        )
        # Deleting an identity cannot cascade into immutable historical scores.
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(delete(m.Account).where(m.Account.id == account_id))
        assert conn.scalar(select(func.count()).select_from(m.RoundScore)) == 4


def test_identity_migration_preserves_legacy_upload(
    player_client, engine, round_payload
):
    import hashlib
    import json

    from app.round_schemas import RoundCreate

    config = Config("alembic.ini")
    config.attributes["database_url"] = engine.url
    command.downgrade(config, "0003")
    # Construct exactly the canonical fingerprint used before identity support.
    payload = RoundCreate.model_validate(round_payload).model_dump(mode="json")
    payload["holes"].sort(key=lambda h: h["number"])
    payload["participants"].sort(key=lambda p: p["id"])
    for participant in payload["participants"]:
        participant.pop("account_id")
        participant["scores"].sort(key=lambda s: s["hole_number"])
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    metadata = MetaData()
    metadata.reflect(engine)
    # SQLite reflection sees UUID storage as CHAR; restore bind processors when
    # seeding the old schema without using the new participant model column.
    for name, table in metadata.tables.items():
        if name in m.Base.metadata.tables:
            for column in table.columns:
                column.type = m.Base.metadata.tables[name].c[column.name].type
    with engine.begin() as conn:
        conn.execute(
            metadata.tables["completed_rounds"]
            .insert()
            .values(
                **RoundCreate.model_validate(round_payload).model_dump(
                    exclude={"holes", "participants"}
                ),
                owner_id=UUID(own_account_id(engine)),
                payload_hash=fingerprint,
            )
        )
        for hole in round_payload["holes"]:
            conn.execute(
                metadata.tables["round_holes"]
                .insert()
                .values(
                    round_id=UUID(round_payload["id"]),
                    **hole,
                )
            )
        for p in round_payload["participants"]:
            conn.execute(
                metadata.tables["round_participants"]
                .insert()
                .values(
                    round_id=UUID(round_payload["id"]),
                    id=UUID(p["id"]),
                    name=p["name"],
                )
            )
            for score in p["scores"]:
                conn.execute(
                    metadata.tables["round_scores"]
                    .insert()
                    .values(
                        round_id=UUID(round_payload["id"]),
                        participant_id=UUID(p["id"]),
                        **score,
                    )
                )

    def snapshot():
        with engine.connect() as conn:
            return {
                name: set(conn.execute(select(table)).all())
                for name, table in metadata.tables.items()
                if name != "alembic_version"
            }

    before = snapshot()
    command.upgrade(config, "head")
    assert snapshot() == before
    result = player_client.get(f"/v1/rounds/{round_payload['id']}")
    assert result.status_code == 200
    assert all(p["account_id"] is None for p in result.json()["participants"])
    retry = player_client.post("/v1/rounds", json=round_payload)
    assert retry.status_code == 200
    assert retry.json() == result.json()
    command.downgrade(config, "0003")
    assert snapshot() == before
    command.upgrade(config, "head")
    assert snapshot() == before


def test_administrator_cannot_impersonate_account(client, engine, round_payload):
    with Session(engine) as db:
        account = create_account(db, "another-player", "long-password-123", "player")
        round_payload["participants"][0]["account_id"] = str(account.id)
    assert client.post("/v1/rounds", json=round_payload).status_code == 403
    assert client.get("/v1/rounds").json() == []
