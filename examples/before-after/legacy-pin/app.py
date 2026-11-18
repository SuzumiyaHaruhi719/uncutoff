from datetime import datetime
from typing import Optional
from pydantic import BaseModel, validator


class LegacyItem(BaseModel):
    tag: Optional[str] = None
    created: datetime = datetime.utcnow()

    class Config:
        orm_mode = True

    @validator("tag")
    def clean(cls, v):
        return v.strip() if v else v


def dump(item: LegacyItem) -> dict:
    return item.dict()
