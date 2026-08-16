from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

PartNumber = Literal[1, 2, 3, 4]


class Keyword(BaseModel):
    term: str
    definition: str


class Option(BaseModel):
    key: str
    text: str


class Part1Exercise(BaseModel):
    id: str
    part: int = 1
    title: str
    topic: str
    text: str
    question: str
    options: list[Option]
    correctAnswer: str
    explanation: str
    keywords: list[Keyword] = Field(default_factory=list)


class Part2Profile(BaseModel):
    number: int
    text: str


class Part2Exercise(BaseModel):
    id: str
    part: int = 2
    title: str
    instructions: str
    profiles: list[Part2Profile]
    ads: list[Option]
    solution: dict[str, str]
    explanation: dict[str, str]
    keywords: list[Keyword] = Field(default_factory=list)


class Part3Blank(BaseModel):
    number: int
    options: list[Option]
    correct: str


class Part3Segment(BaseModel):
    type: Literal["text", "blank"]
    content: Optional[str] = None
    number: Optional[int] = None


class Part3Exercise(BaseModel):
    id: str
    part: int = 3
    title: str
    instructions: str
    intro: str = ""
    segments: list[Part3Segment]
    blanks: list[Part3Blank]
    explanation: dict[str, str]
    keywords: list[Keyword] = Field(default_factory=list)


class Part4Item(BaseModel):
    number: int
    text: str


class Part4Exercise(BaseModel):
    id: str
    part: int = 4
    title: str
    instructions: str
    news: list[Part4Item]
    headlines: list[Option]
    solution: dict[str, str]
    explanation: dict[str, str]
    keywords: list[Keyword] = Field(default_factory=list)


class Exercise(BaseModel):
    """Union-style wrapper built manually from raw JSON."""

    id: str
    part: PartNumber
    title: str
    instructions: str = ""
    topic: str = ""
    example: str = ""
    text: str = ""
    question: str = ""
    options: list[Option] = Field(default_factory=list)
    correctAnswer: str = ""
    explanation: Any = ""
    keywords: list[Keyword] = Field(default_factory=list)
    profiles: list[Part2Profile] = Field(default_factory=list)
    ads: list[Option] = Field(default_factory=list)
    solution: dict[str, str] = Field(default_factory=dict)
    segments: list[Part3Segment] = Field(default_factory=list)
    blanks: list[Part3Blank] = Field(default_factory=list)
    news: list[Part4Item] = Field(default_factory=list)
    headlines: list[Option] = Field(default_factory=list)


class AnswerRequest(BaseModel):
    exercise_id: str
    answer: str
    profile_number: Optional[int] = None
    blank_number: Optional[int] = None


class GenerateRequest(BaseModel):
    part: PartNumber = 1
    topic: str = ""
    count: int = Field(1, ge=1, le=3)
