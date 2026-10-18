"""Owner-private, immutable completed rounds; no catalog dependencies."""

import hashlib
import json
from datetime import UTC
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models as m
from app import round_schemas as s
from app.auth import check_csrf, current_session
from app.database import get_session

DB = Annotated[Session, Depends(get_session)]
router = APIRouter(prefix="/v1/rounds", tags=["rounds"])


def round_owner(request: Request, db: DB) -> m.Account:
    row = current_session(request, db)
    account = db.get(m.Account, row.account_id) if row and row.account_id else None
    if account is None:
        raise HTTPException(401, "Login required")
    if request.method == "POST":
        check_csrf(request, row)
    return account


Owner = Annotated[m.Account, Depends(round_owner)]


def read_round(row: m.CompletedRound):
    total_par = sum(hole.par for hole in row.holes)
    return {
        "id": row.id,
        "completed_at": row.completed_at.replace(tzinfo=UTC)
        if row.completed_at.tzinfo is None
        else row.completed_at,
        "course_name": row.course_name,
        "layout_name": row.layout_name,
        "source_course_id": row.source_course_id,
        "source_layout_id": row.source_layout_id,
        "holes": [
            s.RoundHoleInput.model_validate(hole, from_attributes=True)
            for hole in row.holes
        ],
        "total_par": total_par,
        "participants": [
            {
                "id": participant.id,
                "account_id": participant.account_id,
                "name": participant.name,
                "scores": [
                    s.RoundScoreInput.model_validate(score, from_attributes=True)
                    for score in participant.scores
                ],
                "total_strokes": sum(score.strokes for score in participant.scores),
                "score_to_par": sum(score.strokes for score in participant.scores)
                - total_par,
            }
            for participant in row.participants
        ],
    }


def existing_upload(db, round_id, owner_id, fingerprint):
    row = db.get(m.CompletedRound, round_id)
    if row is None or row.owner_id != owner_id or row.payload_hash != fingerprint:
        raise HTTPException(409, "Round UUID conflicts with an existing upload")
    return row


@router.post("", response_model=s.RoundRead, status_code=201)
def create_round(body: s.RoundCreate, response: Response, db: DB, owner: Owner):
    if any(p.account_id not in (None, owner.id) for p in body.participants):
        raise HTTPException(403, "Participants may only link to your own account")
    # Normalize timestamps and unordered collections for stable retry comparisons.
    body.completed_at = body.completed_at.astimezone(UTC)
    payload = body.model_dump(mode="json")
    payload["holes"].sort(key=lambda hole: hole["number"])
    payload["participants"].sort(key=lambda participant: participant["id"])
    for participant in payload["participants"]:
        # Preserve fingerprints of pre-identity uploads; omitted and null are equal.
        if participant["account_id"] is None:
            participant.pop("account_id")
        participant["scores"].sort(key=lambda score: score["hole_number"])
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if db.get(m.CompletedRound, body.id) is not None:
        response.status_code = 200
        return read_round(existing_upload(db, body.id, owner.id, fingerprint))
    row = m.CompletedRound(
        **body.model_dump(exclude={"holes", "participants"}),
        owner_id=owner.id,
        payload_hash=fingerprint,
        holes=[m.RoundHole(**hole.model_dump()) for hole in body.holes],
        participants=[
            m.RoundParticipant(id=p.id, name=p.name, account_id=p.account_id)
            for p in body.participants
        ],
    )
    try:
        db.add(row)
        db.flush()  # Persist snapshot holes and participants before composite-FK scores.
        for participant in body.participants:
            db.add_all(
                [
                    m.RoundScore(
                        round_id=row.id,
                        participant_id=participant.id,
                        **score.model_dump(),
                    )
                    for score in participant.scores
                ]
            )
        db.commit()
    except IntegrityError:
        # Unique round UUID also protects against simultaneous retries.
        db.rollback()
        response.status_code = 200
        return read_round(existing_upload(db, body.id, owner.id, fingerprint))
    db.refresh(row)
    return read_round(row)


@router.get("", response_model=list[s.RoundRead])
def list_rounds(
    db: DB,
    owner: Owner,
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    rows = db.scalars(
        select(m.CompletedRound)
        .where(m.CompletedRound.owner_id == owner.id)
        .order_by(m.CompletedRound.completed_at.desc(), m.CompletedRound.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return [read_round(row) for row in rows]


@router.get("/{round_id}", response_model=s.RoundRead)
def get_round(round_id: UUID, db: DB, owner: Owner):
    row = db.scalar(
        select(m.CompletedRound).where(
            m.CompletedRound.id == round_id, m.CompletedRound.owner_id == owner.id
        )
    )
    if row is None:
        raise HTTPException(404, "Round not found")
    return read_round(row)
