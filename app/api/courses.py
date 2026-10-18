from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models as m
from app import schemas as s
from app.auth import administrator
from app.database import get_session

SessionDependency = Annotated[Session, Depends(get_session)]

router = APIRouter(prefix="/v1/courses", tags=["courses"])


def require_course(course_id: UUID, session: Session) -> m.Course:
    course = session.get(m.Course, course_id)
    if course is None:
        raise HTTPException(404, "Course not found")
    return course


@router.get("", response_model=list[s.CourseRead])
def list_courses(
    session: SessionDependency,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    return session.scalars(
        select(m.Course)
        .order_by(m.Course.name, m.Course.id)
        .limit(limit)
        .offset(offset)
    ).all()


@router.post(
    "",
    response_model=s.CourseRead,
    status_code=201,
    dependencies=[Depends(administrator)],
)
def create_course(body: s.CourseCreate, session: SessionDependency):
    course = m.Course(**body.model_dump())
    session.add(course)
    session.commit()
    session.refresh(course)
    return course


@router.get("/{course_id}", response_model=s.CourseRead)
def get_course(course_id: UUID, session: SessionDependency):
    return require_course(course_id, session)


@router.get("/{course_id}/graph", response_model=s.CourseGraph)
def get_graph(course_id: UUID, session: SessionDependency):
    return require_course(course_id, session)


@router.post(
    "/{course_id}/layouts",
    response_model=s.LayoutRead,
    status_code=201,
    dependencies=[Depends(administrator)],
)
def create_layout(course_id: UUID, body: s.LayoutCreate, session: SessionDependency):
    require_course(course_id, session)
    layout = m.Layout(course_id=course_id, name=body.name)
    session.add(layout)
    try:
        session.flush()
        for item in body.holes:
            hole = m.Hole(layout_id=layout.id, number=item.number)
            session.add(hole)
            session.flush()
            tees = {name: m.Tee(hole_id=hole.id, name=name) for name in item.tees}
            baskets = {
                name: m.Basket(hole_id=hole.id, name=name) for name in item.baskets
            }
            session.add_all([*tees.values(), *baskets.values()])
            session.flush()
            for config in item.configurations:
                row = m.Configuration(
                    hole_id=hole.id,
                    tee_id=tees[config.tee].id,
                    basket_id=baskets[config.basket].id,
                    par=config.par,
                    distance_ft=config.distance_ft,
                )
                session.add(row)
                session.flush()
                if config.is_default:
                    session.add(m.HoleDefault(hole_id=hole.id, configuration_id=row.id))
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            409, "Layout conflicts with existing catalog data"
        ) from None
    session.refresh(layout)
    return layout
