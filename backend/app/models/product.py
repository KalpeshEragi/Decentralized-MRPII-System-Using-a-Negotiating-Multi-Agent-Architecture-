from pydantic import BaseModel, Field


class Product(BaseModel):
    id: str
    name: str
    description: str | None = None
    unit: str = "unit"
    production_time_hours: float = Field(gt=0)