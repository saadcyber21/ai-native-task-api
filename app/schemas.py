from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Weekday = Literal["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


class Recurrence(BaseModel):
    frequency: Literal["daily", "weekly", "monthly"]
    interval: int = Field(default=1, ge=1, le=365)
    by_weekday: list[Weekday] | None = Field(default=None, max_length=7)


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    due_at: datetime | None = None
    recurrence: Recurrence | None = None

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title must not be blank")
        return value


class TaskFromText(BaseModel):
    text: str = Field(min_length=3, max_length=4000)


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: str | None
    due_at: datetime | None
    recurrence: dict | None
    parent_id: str | None
    created_at: datetime


class BreakdownOut(BaseModel):
    parent: TaskOut
    subtasks: list[TaskOut]
