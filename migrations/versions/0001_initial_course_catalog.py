"""Initial course catalog"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "courses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.CheckConstraint("length(trim(name)) > 0", name="course_name_nonempty"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "layouts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.CheckConstraint("length(trim(name)) > 0", name="layout_name_nonempty"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_id", "name"),
    )
    op.create_index(
        op.f("ix_layouts_course_id"), "layouts", ["course_id"], unique=False
    )
    op.create_table(
        "holes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("layout_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.CheckConstraint("number > 0", name="hole_number_positive"),
        sa.ForeignKeyConstraint(["layout_id"], ["layouts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("layout_id", "number"),
    )
    op.create_index(op.f("ix_holes_layout_id"), "holes", ["layout_id"], unique=False)
    op.create_table(
        "baskets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("hole_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.CheckConstraint("length(trim(name)) > 0", name="basket_name_nonempty"),
        sa.ForeignKeyConstraint(["hole_id"], ["holes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hole_id", "id"),
        sa.UniqueConstraint("hole_id", "name"),
    )
    op.create_index(op.f("ix_baskets_hole_id"), "baskets", ["hole_id"], unique=False)
    op.create_table(
        "tees",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("hole_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.CheckConstraint("length(trim(name)) > 0", name="tee_name_nonempty"),
        sa.ForeignKeyConstraint(["hole_id"], ["holes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hole_id", "id"),
        sa.UniqueConstraint("hole_id", "name"),
    )
    op.create_index(op.f("ix_tees_hole_id"), "tees", ["hole_id"], unique=False)
    op.create_table(
        "configurations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("hole_id", sa.Uuid(), nullable=False),
        sa.Column("tee_id", sa.Uuid(), nullable=False),
        sa.Column("basket_id", sa.Uuid(), nullable=False),
        sa.Column("par", sa.Integer(), nullable=False),
        sa.Column("distance_ft", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "distance_ft IS NULL OR distance_ft > 0",
            name="configuration_distance_positive",
        ),
        sa.CheckConstraint("par > 0", name="configuration_par_positive"),
        sa.ForeignKeyConstraint(
            ["hole_id", "basket_id"],
            ["baskets.hole_id", "baskets.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["hole_id", "tee_id"], ["tees.hole_id", "tees.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["hole_id"], ["holes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hole_id", "id"),
        sa.UniqueConstraint("hole_id", "tee_id", "basket_id"),
    )
    op.create_index(
        op.f("ix_configurations_hole_id"), "configurations", ["hole_id"], unique=False
    )
    op.create_table(
        "hole_defaults",
        sa.Column("hole_id", sa.Uuid(), nullable=False),
        sa.Column("configuration_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["hole_id", "configuration_id"],
            ["configurations.hole_id", "configurations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["hole_id"], ["holes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("hole_id"),
    )


def downgrade():
    op.drop_table("hole_defaults")
    op.drop_index(op.f("ix_configurations_hole_id"), table_name="configurations")
    op.drop_table("configurations")
    op.drop_index(op.f("ix_tees_hole_id"), table_name="tees")
    op.drop_table("tees")
    op.drop_index(op.f("ix_baskets_hole_id"), table_name="baskets")
    op.drop_table("baskets")
    op.drop_index(op.f("ix_holes_layout_id"), table_name="holes")
    op.drop_table("holes")
    op.drop_index(op.f("ix_layouts_course_id"), table_name="layouts")
    op.drop_table("layouts")
    op.drop_table("courses")
