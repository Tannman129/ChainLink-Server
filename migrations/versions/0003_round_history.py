"""Private completed rounds and independent historical scorecards."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "completed_rounds",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("course_name", sa.String(), nullable=False),
        sa.Column("layout_name", sa.String(), nullable=False),
        sa.Column("source_course_id", sa.Uuid()),
        sa.Column("source_layout_id", sa.Uuid()),
        sa.Column("payload_hash", sa.String(), nullable=False),
    )
    op.create_index("ix_completed_rounds_owner_id", "completed_rounds", ["owner_id"])
    op.create_table(
        "round_holes",
        sa.Column(
            "round_id",
            sa.Uuid(),
            sa.ForeignKey("completed_rounds.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("number", sa.Integer(), primary_key=True),
        sa.Column("par", sa.Integer(), nullable=False),
        sa.Column("tee_name", sa.String(), nullable=False),
        sa.Column("basket_name", sa.String(), nullable=False),
        sa.Column("distance_ft", sa.Integer()),
        sa.CheckConstraint("number > 0", name="round_hole_number_positive"),
        sa.CheckConstraint("par > 0", name="round_hole_par_positive"),
        sa.CheckConstraint(
            "distance_ft IS NULL OR distance_ft > 0", name="round_distance_positive"
        ),
    )
    op.create_table(
        "round_participants",
        sa.Column(
            "round_id",
            sa.Uuid(),
            sa.ForeignKey("completed_rounds.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
    )
    op.create_table(
        "round_scores",
        sa.Column("round_id", sa.Uuid(), primary_key=True),
        sa.Column("participant_id", sa.Uuid(), primary_key=True),
        sa.Column("hole_number", sa.Integer(), primary_key=True),
        sa.Column("strokes", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["round_id", "participant_id"],
            ["round_participants.round_id", "round_participants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["round_id", "hole_number"],
            ["round_holes.round_id", "round_holes.number"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("strokes > 0", name="round_score_strokes_positive"),
    )


def downgrade():
    op.drop_table("round_scores")
    op.drop_table("round_participants")
    op.drop_table("round_holes")
    op.drop_index("ix_completed_rounds_owner_id", table_name="completed_rounds")
    op.drop_table("completed_rounds")
