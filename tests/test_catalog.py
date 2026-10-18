from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models as m
from app.main import app


def test_health_without_database(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok", "version": "0.1.0"}
        assert client.get("/openapi.json").status_code == 200


def test_course_create_retrieve_list(client):
    response = client.post("/v1/courses", json={"name": " River Park "})
    assert response.status_code == 201
    course = response.json()
    assert UUID(course["id"])
    assert course["name"] == "River Park"
    assert client.get(f"/v1/courses/{course['id']}").json() == course
    assert client.get("/v1/courses").json() == [course]
    assert client.get("/v1/courses?limit=1&offset=1").json() == []


def test_graph_relationships_and_persistence(client, engine, graph):
    holes = graph["layouts"][0]["holes"]
    assert [h["number"] for h in holes] == [1, 2]
    hole = holes[0]
    assert len(hole["configurations"]) == 2  # Four possible pairs, only two playable.
    assert hole["default"]["configuration_id"] in {
        c["id"] for c in hole["configurations"]
    }
    assert any(c["distance_ft"] is None for c in hole["configurations"])
    for c in hole["configurations"]:
        assert c["tee_id"] in {t["id"] for t in hole["tees"]}
        assert c["basket_id"] in {b["id"] for b in hole["baskets"]}
    engine.dispose()  # Force a fresh database connection, outside the request session.
    with Session(engine) as session:
        course = session.get(m.Course, UUID(graph["id"]))
        assert len(course.layouts[0].holes) == 2
        assert session.scalar(select(func.count()).select_from(m.Configuration)) == 3
    assert client.get(f"/v1/courses/{graph['id']}/graph").json() == graph


@pytest.mark.parametrize(
    "field,value",
    [
        ("par", 0),
        ("par", -1),
        ("par", 3.5),
        ("par", True),
        ("par", "3"),
        ("distance_ft", 0),
        ("distance_ft", -10),
        ("distance_ft", 1.5),
        ("par", 2147483648),
    ],
)
def test_invalid_numbers(client, layout_payload, field, value):
    course = client.post("/v1/courses", json={"name": "Test"}).json()
    layout_payload["holes"][0]["configurations"][0][field] = value
    assert (
        client.post(
            f"/v1/courses/{course['id']}/layouts", json=layout_payload
        ).status_code
        == 422
    )
    assert client.get(f"/v1/courses/{course['id']}/graph").json()["layouts"] == []


@pytest.mark.parametrize(
    "issue",
    [
        "tee",
        "basket",
        "no_default",
        "two_defaults",
        "duplicate_pair",
        "duplicate_tee",
        "duplicate_hole",
        "empty_holes",
    ],
)
def test_invalid_graph(client, layout_payload, issue):
    hole = layout_payload["holes"][0]
    if issue in ("tee", "basket"):
        hole["configurations"][0][issue] = "Missing"
    elif issue == "no_default":
        hole["configurations"][0]["is_default"] = False
    elif issue == "two_defaults":
        hole["configurations"][1]["is_default"] = True
    elif issue == "duplicate_pair":
        hole["configurations"].append(deepcopy(hole["configurations"][1]))
    elif issue == "duplicate_tee":
        hole["tees"].append("Short")
    elif issue == "duplicate_hole":
        layout_payload["holes"].append(deepcopy(hole))
    else:
        layout_payload["holes"] = []
    assert (
        client.post(f"/v1/courses/{uuid4()}/layouts", json=layout_payload).status_code
        == 422
    )


def test_missing_malformed_and_conflict(client, layout_payload, graph):
    for suffix in ("", "/graph"):
        assert client.get(f"/v1/courses/{uuid4()}{suffix}").status_code == 404
    assert client.get("/v1/courses/not-a-uuid").status_code == 422
    assert (
        client.post(f"/v1/courses/{uuid4()}/layouts", json=layout_payload).status_code
        == 404
    )
    assert (
        client.post(
            f"/v1/courses/{graph['id']}/layouts", json=layout_payload
        ).status_code
        == 409
    )
    assert len(client.get(f"/v1/courses/{graph['id']}/graph").json()["layouts"]) == 1
    assert client.post("/v1/courses", json={"name": "   "}).status_code == 422
    assert (
        client.post("/v1/courses", json={"name": "Test", "unknown": 1}).status_code
        == 422
    )


@pytest.mark.parametrize(
    "invalid", ["tee", "basket", "par", "distance", "pair", "default", "second_default"]
)
def test_database_constraints(engine, graph, invalid):
    first, second = graph["layouts"][0]["holes"]
    c = first["configurations"][0]
    values = {
        "hole_id": UUID(first["id"]),
        "tee_id": UUID(c["tee_id"]),
        "basket_id": UUID(
            next(b["id"] for b in first["baskets"] if b["id"] != c["basket_id"])
        ),
        "par": 3,
    }
    if invalid == "tee":
        values["tee_id"] = UUID(second["tees"][0]["id"])
    elif invalid == "basket":
        values["basket_id"] = UUID(second["baskets"][0]["id"])
    elif invalid == "par":
        values["par"] = 0
    elif invalid == "distance":
        values["distance_ft"] = -1
    elif invalid == "pair":
        values.update(tee_id=UUID(c["tee_id"]), basket_id=UUID(c["basket_id"]))
    with Session(engine) as session:
        if invalid in ("default", "second_default"):
            if invalid == "default":
                existing = session.get(m.HoleDefault, UUID(first["id"]))
                session.delete(existing)
                session.flush()
            session.add(
                m.HoleDefault(
                    hole_id=UUID(first["id"]),
                    configuration_id=UUID(
                        second["configurations"][0]["id"]
                        if invalid == "default"
                        else c["id"]
                    ),
                )
            )
        else:
            session.add(m.Configuration(**values))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_database_cascade(engine, graph):
    with engine.begin() as connection:
        connection.execute(delete(m.Course).where(m.Course.id == UUID(graph["id"])))
    with Session(engine) as session:
        for model in (
            m.Course,
            m.Layout,
            m.Hole,
            m.Tee,
            m.Basket,
            m.Configuration,
            m.HoleDefault,
        ):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def test_migration_round_trip(engine):
    config = Config("alembic.ini")
    config.attributes["database_url"] = engine.url
    command.check(config)
    command.downgrade(config, "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    command.upgrade(config, "head")
    assert "configurations" in inspect(engine).get_table_names()
