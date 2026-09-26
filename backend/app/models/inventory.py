from pydantic import BaseModel, Field


class InventoryItem(BaseModel):
    item_id: str
    quantity_on_hand: float = Field(ge=0)
    allocated_quantity: float = Field(default=0, ge=0)
    incoming_quantity: float = Field(default=0, ge=0)

    @property
    def available_quantity(self) -> float:
        return (
            self.quantity_on_hand
            - self.allocated_quantity
            + self.incoming_quantity
        )