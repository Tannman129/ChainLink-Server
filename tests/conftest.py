"""Migrate a fresh database per test; never connect to the application's DATABASE_URL."""

import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.database import get_session
from app.main import app


@pytest.fixture
def engine(tmp_path):
    test_url = os.getenv("TEST_DATABASE_URL")
    admin = None
    schema = None
    if test_url:
        url = make_url(test_url)
        if url.drivername != "postgresql+psycopg":
            raise ValueError("TEST_DATABASE_URL must use postgresql+psycopg")
        schema = "chainlink_test_" + uuid4().hex
        admin = create_engine(url)
        with admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        url = url.update_query_dict({"options": f"-csearch_path={schema}"})
    else:
        url = make_url(f"sqlite:///{tmp_path / 'catalog.db'}")
    engine = create_engine(url)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    config = Config("alembic.ini")
    config.attributes["database_url"] = url
    try:
        command.upgrade(config, "head")
        yield engine
    finally:
        engine.dispose()
        if admin is not None:
            with admin.begin() as conn:
                conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()


@pytest.fixture
def client(engine):
    def session_override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def layout_payload():
    return {
        "name": "Main",
        "holes": [
            {
                "number": 1,
                "tees": ["Short", "Long"],
                "baskets": ["A", "B"],
                "configurations": [
                    {
                        "tee": "Short",
                        "basket": "A",
                        "par": 3,
                        "distance_ft": 250,
                        "is_default": True,
                    },
                    {"tee": "Long", "basket": "B", "par": 4},
                ],
            },
            {
                "number": 2,
                "tees": ["Short"],
                "baskets": ["A"],
                "configurations": [
                    {"tee": "Short", "basket": "A", "par": 3, "is_default": True}
                ],
            },
        ],
    }


@pytest.fixture
def graph(client, layout_payload):
    course = client.post(
        "/v1/courses", json={"name": "River Park", "description": "Local course"}
    ).json()
    response = client.post(f"/v1/courses/{course['id']}/layouts", json=layout_payload)
    assert response.status_code == 201, response.text
    return client.get(f"/v1/courses/{course['id']}/graph").json()
