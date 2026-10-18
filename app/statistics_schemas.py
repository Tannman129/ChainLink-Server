"""Statistics use valid linked scorecards; averages and trends separate lengths."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.round_schemas import RoundHoleInput


class Performance(BaseModel):
    round_id: UUID
    completed_at: datetime
    course_name: str
    layout_name: str
    hole_count: int
    total_par: int
    total_strokes: int
    score_to_par: int


class PersonalBest(Performance):
    holes: list[RoundHoleInput]


class LengthSummary(BaseModel):
    hole_count: int
    rounds: int
    average_strokes: float
    average_score_to_par: float


class ScoringFrequency(BaseModel):
    result: str
    count: int
    percentage: float | None


class MonthlyTrend(BaseModel):
    month: str
    hole_count: int
    rounds: int
    average_score_to_par: float


class StatisticsRead(BaseModel):
    total_rounds: int
    total_holes: int
    excluded_rounds: int
    by_length: list[LengthSummary]
    scoring: list[ScoringFrequency]
    personal_bests: list[PersonalBest]
    recent_rounds: list[Performance]
    trends: list[MonthlyTrend]
