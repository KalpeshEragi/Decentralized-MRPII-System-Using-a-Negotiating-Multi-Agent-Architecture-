from pydantic import BaseModel, Field


class ProductionOrder(BaseModel):
    id: str
    product_id: str
    quantity: int = Field(gt=0)
    planned_date: str
    machine_id: str | None = None
    status: str = "planned"