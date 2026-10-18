"""Identity-only statistics, on SQLite and the PostgreSQL integration stack."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app import models as m
from app.auth import create_account


@pytest.fixture
def statistics_upload(client, engine):
    with Session(engine) as db:
        account_id = str(db.scalar(select(m.Account.id)))

    def upload(
        strokes,
        *,
        course="Historic course",
        layout="Main",
        linked=True,
        completed_at="2026-10-18T12:30:00Z",
        round_id=None,
        par=3,
        tee="Short",
        source_course_id=None,
        source_layout_id=None,
    ):
        payload = {
            "id": str(round_id or uuid4()),
            "completed_at": completed_at,
            "course_name": course,
            "layout_name": layout,
            "source_course_id": source_course_id,
            "source_layout_id": source_layout_id,
            "holes": [
                {"number": n, "par": par, "tee_name": tee, "basket_name": "A"}
                for n in range(1, len(strokes) + 1)
            ],
            "participants": [
                {
                    "id": str(uuid4()),
                    "name": "test-admin",
                    "account_id": account_id if linked else None,
                    "scores": [
                        {"hole_number": n, "strokes": s}
                        for n, s in enumerate(strokes, 1)
                    ],
                }
            ],
        }
        response = client.post("/v1/rounds", json=payload)
        assert response.status_code == 201, response.text
        return payload

    return upload


def test_statistics_authentication_and_privacy_headers(anonymous_client):
    response = anonymous_client.get("/v1/statistics")
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["vary"] == "Cookie"


def test_empty_and_guest_or_legacy_rounds(client, statistics_upload):
    empty = client.get("/v1/statistics").json()
    assert empty["total_rounds"] == empty["total_holes"] == 0
    assert empty["by_length"] == empty["trends"] == empty["personal_bests"] == []
    assert empty["recent_rounds"] == []
    assert all(s["percentage"] is None for s in empty["scoring"])
    statistics_upload([3] * 9, linked=False)
    # Ownership, participant position and the exact account username prove nothing.
    assert client.get("/v1/statistics").json() == empty


def test_all_scoring_categories_and_round_averages(client, statistics_upload):
    statistics_upload([1, 2, 3, 4, 5])
    response = client.get("/v1/statistics")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    result = response.json()
    assert result["total_rounds"] == 1
    assert result["total_holes"] == 5
    assert result["by_length"] == [
        {"hole_count": 5, "rounds": 1, "average_strokes": 15, "average_score_to_par": 0}
    ]
    assert all(s["count"] == 1 and s["percentage"] == 20 for s in result["scoring"])
    assert result["recent_rounds"][0]["total_par"] == 15
    assert result["recent_rounds"][0]["score_to_par"] == 0


def test_mixed_round_lengths_and_hole_weighted_percentages(client, statistics_upload):
    statistics_upload([2] * 9)
    statistics_upload([4] * 18)
    statistics_upload([3] * 7)
    result = client.get("/v1/statistics").json()
    assert result["total_rounds"] == 3
    assert result["total_holes"] == 34
    assert result["by_length"] == [
        {
            "hole_count": 7,
            "rounds": 1,
            "average_strokes": 21,
            "average_score_to_par": 0,
        },
        {
            "hole_count": 9,
            "rounds": 1,
            "average_strokes": 18,
            "average_score_to_par": -9,
        },
        {
            "hole_count": 18,
            "rounds": 1,
            "average_strokes": 72,
            "average_score_to_par": 18,
        },
    ]
    scoring = {s["result"]: s for s in result["scoring"]}
    assert scoring["birdie"]["percentage"] == pytest.approx(9 / 34 * 100, abs=0.0001)
    assert scoring["bogey"]["percentage"] == pytest.approx(18 / 34 * 100, abs=0.0001)
    assert {t["hole_count"] for t in result["trends"]} == {7, 9, 18}


def test_personal_bests_distinguish_course_layout_and_snapshot(
    client, statistics_upload
):
    statistics_upload([4] * 9)
    winner = statistics_upload([2] * 9)
    statistics_upload([3] * 9)
    statistics_upload([3] * 9, layout="Alternate")
    statistics_upload([3] * 9, course="Other course")
    statistics_upload([3] * 18)
    statistics_upload([3] * 9, tee="Long")
    statistics_upload([3] * 9, par=4)
    statistics_upload(
        [3] * 9, source_course_id=str(uuid4()), source_layout_id=str(uuid4())
    )
    result = client.get("/v1/statistics").json()
    assert len(result["personal_bests"]) == 7
    assert winner["id"] in {b["round_id"] for b in result["personal_bests"]}
    assert sorted(b["total_strokes"] for b in result["personal_bests"]) == [
        18,
        27,
        27,
        27,
        27,
        27,
        54,
    ]
    assert all(len(b["holes"]) == b["hole_count"] for b in result["personal_bests"])


def test_monthly_trends_use_utc_and_separate_lengths(client, statistics_upload):
    statistics_upload([2] * 9, completed_at="2026-09-30T23:30:00-01:00")
    statistics_upload([4] * 9, completed_at="2026-10-15T00:00:00Z")
    statistics_upload([3] * 18, completed_at="2026-10-15T00:00:00Z")
    statistics_upload([4] * 9, completed_at="2026-11-15T00:00:00Z")
    result = client.get("/v1/statistics").json()
    assert result["by_length"][0]["average_strokes"] == 30
    assert result["by_length"][0]["average_score_to_par"] == 3
    assert result["trends"] == [
        {"month": "2026-10", "hole_count": 9, "rounds": 2, "average_score_to_par": 0},
        {"month": "2026-10", "hole_count": 18, "rounds": 1, "average_score_to_par": 0},
        {"month": "2026-11", "hole_count": 9, "rounds": 1, "average_score_to_par": 9},
    ]


def test_recent_limit_ordering_and_best_ties(client, statistics_upload):
    ids = [UUID(int=n) for n in range(1, 23)]
    for round_id in reversed(ids):
        statistics_upload([3], round_id=round_id)
    latest = statistics_upload([3], completed_at="2026-11-01T00:00:00Z")
    result = client.get("/v1/statistics").json()
    assert [r["round_id"] for r in result["recent_rounds"]] == [
        latest["id"],
        *map(str, ids[:19]),
    ]
    assert result["personal_bests"][0]["round_id"] == latest["id"]
    assert result["total_rounds"] == 23  # Recent display limit never limits aggregates.


def test_linked_identity_is_independent_of_ownership(client, engine, statistics_upload):
    mine = statistics_upload([2, 3, 4])
    other_round = statistics_upload([1, 1, 1])
    with Session(engine) as db:
        other = create_account(db, "statistics-other", "long-password-123", "player")
        db.get(m.CompletedRound, UUID(mine["id"])).owner_id = other.id
        db.execute(
            update(m.RoundParticipant)
            .where(m.RoundParticipant.round_id == UUID(other_round["id"]))
            .values(account_id=other.id)
        )
        # A second player's scores in my linked round must not be counted.
        guest = m.RoundParticipant(
            round_id=UUID(mine["id"]), id=uuid4(), name="Private guest"
        )
        db.add(guest)
        db.flush()
        db.add_all(
            [
                m.RoundScore(
                    round_id=guest.round_id,
                    participant_id=guest.id,
                    hole_number=n,
                    strokes=1,
                )
                for n in range(1, 4)
            ]
        )
        db.commit()
        other_id = str(other.id)
    result = client.get("/v1/statistics").json()
    assert result["total_rounds"] == 1
    assert result["total_holes"] == 3
    assert result["by_length"][0]["average_strokes"] == 9
    assert result["recent_rounds"][0]["round_id"] == mine["id"]
    assert "Private guest" not in str(result)
    assert "statistics-other" not in str(result)
    assert client.get(f"/v1/rounds/{mine['id']}").status_code == 404
    assert client.get(f"/v1/statistics/{other_id}").status_code == 404
    login = client.post(
        "/v1/auth/login",
        json={"username": "statistics-other", "password": "long-password-123"},
    )
    assert login.status_code == 200
    result = client.get("/v1/statistics").json()
    assert result["total_rounds"] == 1
    assert result["recent_rounds"][0]["round_id"] == other_round["id"]
    assert result["by_length"][0]["average_strokes"] == 3


@pytest.mark.parametrize("damage", ["missing_score", "no_holes", "empty_tee"])
def test_incomplete_historical_scorecards_are_excluded(
    client, engine, statistics_upload, damage
):
    bad = statistics_upload([3, 3])
    good = statistics_upload([2, 2])
    with engine.begin() as conn:
        if damage == "missing_score":
            conn.execute(
                delete(m.RoundScore).where(
                    m.RoundScore.round_id == UUID(bad["id"]),
                    m.RoundScore.hole_number == 1,
                )
            )
        elif damage == "no_holes":
            conn.execute(
                delete(m.RoundHole).where(m.RoundHole.round_id == UUID(bad["id"]))
            )
        else:
            conn.execute(
                update(m.RoundHole)
                .where(m.RoundHole.round_id == UUID(bad["id"]))
                .values(tee_name="")
            )
    result = client.get("/v1/statistics").json()
    assert result["excluded_rounds"] == 1
    assert result["total_rounds"] == 1
    assert result["total_holes"] == 2
    assert result["recent_rounds"][0]["round_id"] == good["id"]
    assert result["scoring"][1]["percentage"] == 100


def test_statistics_use_historical_snapshots(client, engine, graph, statistics_upload):
    statistics_upload(
        [2, 3], source_course_id=graph["id"], source_layout_id=graph["layouts"][0]["id"]
    )
    before = client.get("/v1/statistics").json()
    with engine.begin() as conn:
        conn.execute(delete(m.Course).where(m.Course.id == UUID(graph["id"])))
    assert client.get("/v1/statistics").json() == before
