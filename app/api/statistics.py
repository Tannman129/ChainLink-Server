"""Private statistics derived solely from explicit participant identity links."""

from collections import Counter, defaultdict
from datetime import UTC

from fastapi import APIRouter
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import noload

from app import models as m
from app.api.rounds import DB, Owner
from app.round_schemas import RoundHoleInput, RoundScoreInput
from app.statistics_schemas import StatisticsRead

router = APIRouter(prefix="/v1/statistics", tags=["statistics"])


def average(values):
    return round(sum(values) / len(values), 4) if values else None


def scoring_result(delta):
    if delta < -1:
        return "eagle_or_better"
    return {-1: "birdie", 0: "par", 1: "bogey"}.get(delta, "worse")


@router.get("", response_model=StatisticsRead)
def personal_statistics(db: DB, owner: Owner):
    # Ownership is deliberately absent: a linked player may have been recorded
    # by another scorekeeper. Never load or expose the other participants.
    rounds = db.execute(
        select(m.RoundParticipant, m.CompletedRound)
        .join(m.CompletedRound, m.RoundParticipant.round_id == m.CompletedRound.id)
        .where(m.RoundParticipant.account_id == owner.id)
        .order_by(m.CompletedRound.completed_at.desc(), m.CompletedRound.id)
        .options(noload(m.CompletedRound.participants))
    ).all()
    results = []
    bests = {}
    lengths = defaultdict(list)
    months = defaultdict(list)
    outcomes = Counter()
    excluded = 0
    for participant, row in rounds:
        holes = {h.number: h for h in row.holes}
        scores = {s.hole_number: s.strokes for s in participant.scores}
        # Validate imported/legacy values using the upload contract before any
        # aggregation. An invalid linked scorecard is excluded in its entirety.
        try:
            for hole in row.holes:
                RoundHoleInput.model_validate(hole, from_attributes=True)
            for score in participant.scores:
                RoundScoreInput.model_validate(score, from_attributes=True)
        except ValidationError:
            excluded += 1
            continue
        if (
            not 1 <= len(holes) <= 100
            or len(holes) != len(row.holes)
            or len(scores) != len(participant.scores)
            or scores.keys() != holes.keys()
            or sum(scores.values()) > 2147483647
            or sum(h.par for h in holes.values()) > 2147483647
            or row.completed_at is None
        ):
            excluded += 1
            continue
        completed_at = row.completed_at
        if completed_at.tzinfo is None:
            completed_at = completed_at.replace(tzinfo=UTC)
        completed_at = completed_at.astimezone(UTC)
        par = sum(h.par for h in holes.values())
        strokes = sum(scores.values())
        result = {
            "round_id": row.id,
            "completed_at": completed_at,
            "course_name": row.course_name,
            "layout_name": row.layout_name,
            "hole_count": len(holes),
            "total_par": par,
            "total_strokes": strokes,
            "score_to_par": strokes - par,
        }
        results.append(result)
        lengths[len(holes)].append(result)
        months[(completed_at.strftime("%Y-%m"), len(holes))].append(result)
        for number, strokes_on_hole in scores.items():
            delta = strokes_on_hole - holes[number].par
            outcomes[scoring_result(delta)] += 1
        # Snapshot setup prevents comparisons across changed tees/par/distances.
        setup = tuple(
            (h.number, h.par, h.tee_name, h.basket_name, h.distance_ft)
            for h in row.holes
        )
        key = (
            row.source_course_id,
            row.source_layout_id,
            row.course_name,
            row.layout_name,
            setup,
        )
        if key not in bests or result["total_strokes"] < bests[key]["total_strokes"]:
            bests[key] = dict(
                result,
                holes=[
                    {
                        "number": h.number,
                        "par": h.par,
                        "tee_name": h.tee_name,
                        "basket_name": h.basket_name,
                        "distance_ft": h.distance_ft,
                    }
                    for h in row.holes
                ],
            )
    total_holes = sum(r["hole_count"] for r in results)
    return {
        "total_rounds": len(results),
        "total_holes": total_holes,
        "excluded_rounds": excluded,
        "by_length": [
            {
                "hole_count": count,
                "rounds": len(rows),
                "average_strokes": average([r["total_strokes"] for r in rows]),
                "average_score_to_par": average([r["score_to_par"] for r in rows]),
            }
            for count, rows in sorted(lengths.items())
        ],
        "scoring": [
            {
                "result": name,
                "count": outcomes[name],
                "percentage": round(outcomes[name] / total_holes * 100, 4)
                if total_holes
                else None,
            }
            for name in ("eagle_or_better", "birdie", "par", "bogey", "worse")
        ],
        "personal_bests": sorted(
            bests.values(),
            key=lambda r: (
                r["course_name"],
                r["layout_name"],
                r["hole_count"],
                str(r["round_id"]),
            ),
        ),
        "recent_rounds": results[:20],
        "trends": [
            {
                "month": month,
                "hole_count": count,
                "rounds": len(rows),
                "average_score_to_par": average([r["score_to_par"] for r in rows]),
            }
            for (month, count), rows in sorted(months.items())
        ],
    }
