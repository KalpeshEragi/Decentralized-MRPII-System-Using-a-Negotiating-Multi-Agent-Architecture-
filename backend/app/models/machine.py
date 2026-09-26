from pydantic import BaseModel, Field


class Machine(BaseModel):
    id: str
    name: str
    work_center: str
    capacity_hours_per_day: float = Field(gt=0)
    available: bool = True