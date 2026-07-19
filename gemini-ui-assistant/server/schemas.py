"""Request/response models for the assistant API.

The context models double as an allowlist: any field not declared here is
rejected or dropped before the context can reach Gemini.
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_QUESTION_CHARS = 500
MAX_TEXT_FIELD_CHARS = 300
MAX_LIST_ITEMS = 20


class UISection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default="", max_length=MAX_TEXT_FIELD_CHARS)
    label: str = Field(default="", max_length=MAX_TEXT_FIELD_CHARS)
    description: str = Field(default="", max_length=MAX_TEXT_FIELD_CHARS)


class UIMetric(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label: str = Field(default="", max_length=MAX_TEXT_FIELD_CHARS)
    value: str = Field(default="", max_length=MAX_TEXT_FIELD_CHARS)
    help_text: str = Field(default="", max_length=MAX_TEXT_FIELD_CHARS)


class UIAction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label: str = Field(default="", max_length=MAX_TEXT_FIELD_CHARS)
    description: str = Field(default="", max_length=MAX_TEXT_FIELD_CHARS)


class UIContext(BaseModel):
    model_config = ConfigDict(extra="ignore")

    page: str = Field(default="", max_length=MAX_TEXT_FIELD_CHARS)
    page_title: str = Field(default="", max_length=MAX_TEXT_FIELD_CHARS)
    visible_sections: list[UISection] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    visible_metrics: list[UIMetric] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    available_actions: list[UIAction] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    ui_context: UIContext = Field(default_factory=UIContext)

    @field_validator("question")
    @classmethod
    def question_not_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Question must not be empty.")
        return stripped


class AskResponse(BaseModel):
    answer: str
    mock: bool = False
