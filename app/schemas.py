from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Name = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
PositiveInt = Annotated[int, Field(gt=0, strict=True, le=2147483647)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CourseCreate(Input):
    name: Name
    description: str | None = Field(default=None, max_length=10000)


class ConfigurationCreate(Input):
    tee: Name
    basket: Name
    par: PositiveInt
    distance_ft: PositiveInt | None = None
    is_default: bool = False


class HoleCreate(Input):
    number: PositiveInt
    tees: list[Name] = Field(min_length=1)
    baskets: list[Name] = Field(min_length=1)
    configurations: list[ConfigurationCreate] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_graph(self):
        if len(set(self.tees)) != len(self.tees) or len(set(self.baskets)) != len(
            self.baskets
        ):
            raise ValueError("Tee and basket names must be unique within a hole")
        pairs = [(c.tee, c.basket) for c in self.configurations]
        if len(set(pairs)) != len(pairs):
            raise ValueError("Duplicate tee/basket configuration")
        if any(
            c.tee not in self.tees or c.basket not in self.baskets
            for c in self.configurations
        ):
            raise ValueError(
                "Configurations must reference tees and baskets in this hole"
            )
        if sum(c.is_default for c in self.configurations) != 1:
            raise ValueError("Each hole requires exactly one default configuration")
        return self


class LayoutCreate(Input):
    name: Name
    holes: list[HoleCreate] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_numbers(self):
        if len({h.number for h in self.holes}) != len(self.holes):
            raise ValueError("Hole numbers must be unique within a layout")
        return self


class Output(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CourseRead(Output):
    id: UUID
    name: str
    description: str | None


class PositionRead(Output):
    id: UUID
    hole_id: UUID
    name: str


class ConfigurationRead(Output):
    id: UUID
    hole_id: UUID
    tee_id: UUID
    basket_id: UUID
    par: int
    distance_ft: int | None


class DefaultRead(Output):
    configuration_id: UUID


class HoleRead(Output):
    id: UUID
    layout_id: UUID
    number: int
    tees: list[PositionRead]
    baskets: list[PositionRead]
    configurations: list[ConfigurationRead]
    default: DefaultRead | None


class LayoutRead(Output):
    id: UUID
    course_id: UUID
    name: str
    holes: list[HoleRead]


class CourseGraph(CourseRead):
    layouts: list[LayoutRead]
