from pydantic import BaseModel, Field


class Material(BaseModel):
    id: str
    name: str
    unit: str = "unit"
    lead_time_days: int = Field(ge=0)
    safety_stock: float = Field(ge=0)