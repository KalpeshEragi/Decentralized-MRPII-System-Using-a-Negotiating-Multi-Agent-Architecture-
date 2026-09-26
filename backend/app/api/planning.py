from fastapi import APIRouter

from app.data.scenarios import get_default_scenario

from app.services.planning_service import (
    create_mps,
    create_mrp,
    create_capacity_plan,
    create_schedule,
    create_full_mrpii_plan,
)


router = APIRouter(
    prefix="/planning",
    tags=["Planning"],
)


@router.get("/scenario")
def get_scenario():

    scenario = get_default_scenario()

    return {
        "products": len(scenario["products"]),
        "materials": len(scenario["materials"]),
        "boms": len(scenario["boms"]),
        "inventory_items": len(scenario["inventory"]),
        "machines": len(scenario["machines"]),
        "orders": len(scenario["orders"]),
    }


@router.post("/mps")
def generate_master_production_schedule():

    mps = create_mps()

    return {
        "status": "success",
        "mps": mps,
    }


@router.post("/mrp")
def run_material_requirements_planning():

    mrp_result = create_mrp()

    return {
        "status": "success",
        "mrp": mrp_result,
    }


@router.post("/capacity")
def run_capacity_planning():

    result = create_capacity_plan()

    return {
        "status": "success",
        "capacity": result,
    }


@router.post("/schedule")
def run_production_schedule():

    result = create_schedule()

    return {
        "status": "success",
        "schedule": result,
    }


@router.post("/run")
def run_full_mrpii():

    result = create_full_mrpii_plan()

    return {
        "status": "success",
        "mrpii": result,
    }