from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Course(Base):
    __tablename__ = "courses"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="course_name_nonempty"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column()
    description: Mapped[str | None]
    layouts: Mapped[list["Layout"]] = relationship(
        back_populates="course", cascade="all, delete-orphan", order_by="Layout.name"
    )


class Layout(Base):
    __tablename__ = "layouts"
    __table_args__ = (
        UniqueConstraint("course_id", "name"),
        CheckConstraint("length(trim(name)) > 0", name="layout_name_nonempty"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    course_id: Mapped[UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str]
    course: Mapped[Course] = relationship(back_populates="layouts")
    holes: Mapped[list["Hole"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="Hole.number"
    )


class Hole(Base):
    __tablename__ = "holes"
    __table_args__ = (
        UniqueConstraint("layout_id", "number"),
        CheckConstraint("number > 0", name="hole_number_positive"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    layout_id: Mapped[UUID] = mapped_column(
        ForeignKey("layouts.id", ondelete="CASCADE"), index=True
    )
    number: Mapped[int]
    tees: Mapped[list["Tee"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="Tee.name"
    )
    baskets: Mapped[list["Basket"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="Basket.name"
    )
    configurations: Mapped[list["Configuration"]] = relationship(
        foreign_keys="Configuration.hole_id",
        order_by="Configuration.id",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    default: Mapped["HoleDefault | None"] = relationship(
        cascade="all, delete-orphan",
        lazy="selectin",
        foreign_keys="HoleDefault.hole_id",
    )


class Tee(Base):
    __tablename__ = "tees"
    __table_args__ = (
        UniqueConstraint("hole_id", "id"),
        UniqueConstraint("hole_id", "name"),
        CheckConstraint("length(trim(name)) > 0", name="tee_name_nonempty"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    hole_id: Mapped[UUID] = mapped_column(
        ForeignKey("holes.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str]


class Basket(Base):
    __tablename__ = "baskets"
    __table_args__ = (
        UniqueConstraint("hole_id", "id"),
        UniqueConstraint("hole_id", "name"),
        CheckConstraint("length(trim(name)) > 0", name="basket_name_nonempty"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    hole_id: Mapped[UUID] = mapped_column(
        ForeignKey("holes.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str]


class Configuration(Base):
    __tablename__ = "configurations"
    __table_args__ = (
        UniqueConstraint("hole_id", "id"),
        UniqueConstraint("hole_id", "tee_id", "basket_id"),
        ForeignKeyConstraint(
            ["hole_id", "tee_id"], ["tees.hole_id", "tees.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["hole_id", "basket_id"],
            ["baskets.hole_id", "baskets.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("par > 0", name="configuration_par_positive"),
        CheckConstraint(
            "distance_ft IS NULL OR distance_ft > 0",
            name="configuration_distance_positive",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    hole_id: Mapped[UUID] = mapped_column(
        ForeignKey("holes.id", ondelete="CASCADE"), index=True
    )
    tee_id: Mapped[UUID]
    basket_id: Mapped[UUID]
    par: Mapped[int]
    distance_ft: Mapped[int | None]


class HoleDefault(Base):
    __tablename__ = "hole_defaults"
    __table_args__ = (
        ForeignKeyConstraint(
            ["hole_id", "configuration_id"],
            ["configurations.hole_id", "configurations.id"],
            ondelete="CASCADE",
        ),
    )
    hole_id: Mapped[UUID] = mapped_column(
        ForeignKey("holes.id", ondelete="CASCADE"), primary_key=True
    )
    configuration_id: Mapped[UUID]
