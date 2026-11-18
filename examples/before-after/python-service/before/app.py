from datetime import datetime
from typing import Optional
import google.generativeai as genai
from pydantic import BaseModel, validator


class Item(BaseModel):
    tag: Optional[str] = None
    created: datetime = datetime.utcnow()

    class Config:
        orm_mode = True

    @validator("tag")
    def clean(cls, v):
        return v.strip() if v else v


def serialize(item: Item) -> dict:
    return item.dict()
