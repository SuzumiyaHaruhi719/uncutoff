from datetime import UTC, datetime
from google import genai
from pydantic import BaseModel, ConfigDict, field_validator


class Item(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    tag: str | None = None
    created: datetime = datetime.now(UTC)

    @field_validator("tag")
    @classmethod
    def clean(cls, v: str | None) -> str | None:
        return v.strip() if v else v


def serialize(item: Item) -> dict:
    return item.model_dump()


def create_client() -> genai.Client:
    return genai.Client()
