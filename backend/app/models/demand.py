from pydantic import BaseModel, Field


class CustomerOrder(BaseModel):
    id: str
    product_id: str
    quantity: int = Field(gt=0)
    due_date: str
    priority: int = Field(default=1, ge=1, le=5)