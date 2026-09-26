from pydantic import BaseModel, Field


class MPSEntry(BaseModel):
    product_id: str
    quantity: int = Field(gt=0)
    planned_date: str


class MaterialRequirement(BaseModel):
    material_id: str
    gross_requirement: float = Field(ge=0)
    available_inventory: float = Field(ge=0)
    net_requirement: float = Field(ge=0)


class PlannedOrder(BaseModel):
    material_id: str
    quantity: float = Field(gt=0)
    required_date: str
    order_date: str
    lead_time_days: int = Field(ge=0)


class MRPResult(BaseModel):
    mps: list[MPSEntry]
    material_requirements: list[MaterialRequirement]
    planned_orders: list[PlannedOrder]


class CapacityRequirement(BaseModel):
    product_id: str
    quantity: int = Field(gt=0)
    required_hours: float = Field(gt=0)
    planned_date: str


class MachineLoad(BaseModel):
    machine_id: str
    machine_name: str
    capacity_hours: float = Field(gt=0)
    required_hours: float = Field(ge=0)
    utilization: float = Field(ge=0)


class ScheduleEntry(BaseModel):
    product_id: str
    quantity: int = Field(gt=0)
    planned_date: str
    machine_id: str
    start_hour: float = Field(ge=0)
    end_hour: float = Field(gt=0)


class ManufacturingPlan(BaseModel):
    plan_id: str
    entries: list[ScheduleEntry]
    total_quantity: int = 0
    status: str = "draft"