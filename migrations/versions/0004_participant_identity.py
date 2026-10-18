"""Optional, explicitly authorized participant account identity."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    # SQLite supports an inline FK on a nullable added column, avoiding a
    # table rebuild that could cascade-delete existing participant scores.
    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            "ALTER TABLE round_participants ADD COLUMN account_id CHAR(32) "
            "CONSTRAINT fk_round_participant_account REFERENCES accounts(id)"
        )
    else:
        op.add_column(
            "round_participants",
            sa.Column("account_id", sa.Uuid(), nullable=True),
        )
        op.create_foreign_key(
            "fk_round_participant_account",
            "round_participants",
            "accounts",
            ["account_id"],
            ["id"],
        )
    op.create_index(
        "ix_round_participants_account_id", "round_participants", ["account_id"]
    )
    # PostgreSQL and SQLite both allow multiple NULLs in a unique index.
    op.create_index(
        "uq_round_participant_account",
        "round_participants",
        ["round_id", "account_id"],
        unique=True,
    )


def downgrade():
    op.drop_index("uq_round_participant_account", table_name="round_participants")
    op.drop_index("ix_round_participants_account_id", table_name="round_participants")
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint(
            "fk_round_participant_account", "round_participants", type_="foreignkey"
        )
    op.drop_column("round_participants", "account_id")
