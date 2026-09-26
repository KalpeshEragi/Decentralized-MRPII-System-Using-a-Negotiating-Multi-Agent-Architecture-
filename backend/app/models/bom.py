from pydantic import BaseModel, Field


class BOMLine(BaseModel):
    component_id: str
    quantity: float = Field(gt=0)


class BOM(BaseModel):
    product_id: str
    components: list[BOMLine]