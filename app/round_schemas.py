"""Completed scorecards supplied by an offline scorekeeper."""

from datetime import datetime
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.schemas import Input, Name, Output, PositiveInt


class RoundHoleInput(Input):
    number: PositiveInt
    par: PositiveInt
    tee_name: Name
    basket_name: Name
    distance_ft: PositiveInt | None = None


class RoundScoreInput(Input):
    hole_number: PositiveInt
    strokes: PositiveInt


class RoundParticipantInput(Input):
    id: UUID
    account_id: UUID | None = Field(
        default=None,
        description="Explicit self-identification: only the authenticated account UUID is allowed. Omit or use null for a guest.",
    )
    name: Name
    scores: list[RoundScoreInput] = Field(min_length=1, max_length=100)


class RoundCreate(Input):
    id: UUID
    completed_at: AwareDatetime
    course_name: Name
    layout_name: Name
    source_course_id: UUID | None = None
    source_layout_id: UUID | None = None
    holes: list[RoundHoleInput] = Field(min_length=1, max_length=100)
    participants: list[RoundParticipantInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def complete_scorecard(self):
        numbers = {hole.number for hole in self.holes}
        if len(numbers) != len(self.holes):
            raise ValueError("Duplicate hole number")
        if len({p.id for p in self.participants}) != len(self.participants):
            raise ValueError("Duplicate participant ID")
        accounts = [p.account_id for p in self.participants if p.account_id is not None]
        if len(set(accounts)) != len(accounts):
            raise ValueError("Duplicate participant account")
        for participant in self.participants:
            if (
                len(participant.scores) != len(numbers)
                or {score.hole_number for score in participant.scores} != numbers
            ):
                raise ValueError("Every participant must have one score per hole")
            if sum(score.strokes for score in participant.scores) > 2147483647:
                raise ValueError("Participant total exceeds supported range")
        if sum(hole.par for hole in self.holes) > 2147483647:
            raise ValueError("Round par exceeds supported range")
        return self


class RoundParticipantRead(Output):
    id: UUID
    account_id: UUID | None
    name: str
    scores: list[RoundScoreInput]
    total_strokes: int
    score_to_par: int


class RoundRead(Output):
    id: UUID
    completed_at: datetime
    course_name: str
    layout_name: str
    source_course_id: UUID | None
    source_layout_id: UUID | None
    holes: list[RoundHoleInput]
    participants: list[RoundParticipantRead]
    total_par: int
