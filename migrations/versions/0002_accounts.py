"""Accounts, opaque sessions and shared login throttling; catalog untouched."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("username", sa.String(), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.CheckConstraint(
            "role IN ('player', 'administrator')", name="account_role_valid"
        ),
    )
    op.create_table(
        "web_sessions",
        sa.Column("token_hash", sa.String(), primary_key=True),
        sa.Column(
            "account_id", sa.Uuid(), sa.ForeignKey("accounts.id", ondelete="CASCADE")
        ),
        sa.Column("expires_at", sa.Integer(), nullable=False),
    )
    op.create_index("ix_web_sessions_account_id", "web_sessions", ["account_id"])
    op.create_index("ix_web_sessions_expires_at", "web_sessions", ["expires_at"])
    op.create_table(
        "login_buckets",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=False),
    )
    op.create_index("ix_login_buckets_expires_at", "login_buckets", ["expires_at"])


def downgrade():
    op.drop_table("login_buckets")
    op.drop_table("web_sessions")
    op.drop_table("accounts")
