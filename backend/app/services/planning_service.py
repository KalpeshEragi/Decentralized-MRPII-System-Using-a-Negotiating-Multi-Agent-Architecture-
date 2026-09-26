from app.data.scenarios import get_default_scenario

from app.mrpii.mps import generate_mps

from app.mrpii.mrp import (
    explode_bom,
    calculate_net_requirements,
    generate_time_phased_requirements,
)

from app.mrpii.capacity import (
    calculate_capacity_requirements,
    calculate_machine_load,
)

from app.mrpii.scheduling import (
    generate_schedule,
)

from app.mrpii.validator import (
    validate_schedule,
)

from app.models.planning import MRPResult


def create_mps():
    scenario = get_default_scenario()

    return generate_mps(
        orders=scenario["orders"],
        products=scenario["products"],
    )


def create_mrp() -> MRPResult:

    scenario = get_default_scenario()

    # -------------------------
    # 1. Master Production Schedule
    # -------------------------

    mps = generate_mps(
        orders=scenario["orders"],
        products=scenario["products"],
    )

    # -------------------------
    # 2. BOM Explosion
    # -------------------------

    gross_requirements = explode_bom(
        mps=mps,
        boms=scenario["boms"],
    )

    # -------------------------
    # 3. Inventory Netting
    # -------------------------

    material_requirements = (
        calculate_net_requirements(
            gross_requirements=gross_requirements,
            inventory=scenario["inventory"],
        )
    )

    # -------------------------
    # 4. Time-phased procurement
    # -------------------------

    planned_orders = (
        generate_time_phased_requirements(
            mps=mps,
            boms=scenario["boms"],
            inventory=scenario["inventory"],
            materials=scenario["materials"],
        )
    )

    return MRPResult(
        mps=mps,
        material_requirements=material_requirements,
        planned_orders=planned_orders,
    )


def create_capacity_plan():

    scenario = get_default_scenario()

    mps = generate_mps(
        orders=scenario["orders"],
        products=scenario["products"],
    )

    requirements = calculate_capacity_requirements(
        mps=mps,
        products=scenario["products"],
    )

    machine_load = calculate_machine_load(
        requirements=requirements,
        machines=scenario["machines"],
    )

    return {
        "requirements": requirements,
        "machine_load": machine_load,
    }


def create_schedule():

    scenario = get_default_scenario()

    mps = generate_mps(
        orders=scenario["orders"],
        products=scenario["products"],
    )

    schedule = generate_schedule(
        mps=mps,
        products=scenario["products"],
        machines=scenario["machines"],
    )

    validation = validate_schedule(
        schedule=schedule,
        machines=scenario["machines"],
        inventory=scenario["inventory"],
    )

    return {
        "schedule": schedule,
        "validation": validation,
    }


def create_full_mrpii_plan():

    scenario = get_default_scenario()

    # 1. MPS
    mps = generate_mps(
        orders=scenario["orders"],
        products=scenario["products"],
    )

    # 2. BOM explosion
    gross_requirements = explode_bom(
        mps=mps,
        boms=scenario["boms"],
    )

    # 3. MRP
    material_requirements = (
        calculate_net_requirements(
            gross_requirements=gross_requirements,
            inventory=scenario["inventory"],
        )
    )

    # 4. Procurement
    planned_orders = (
        generate_time_phased_requirements(
            mps=mps,
            boms=scenario["boms"],
            inventory=scenario["inventory"],
            materials=scenario["materials"],
        )
    )

    # 5. Capacity
    capacity_requirements = (
        calculate_capacity_requirements(
            mps=mps,
            products=scenario["products"],
        )
    )

    machine_load = calculate_machine_load(
        requirements=capacity_requirements,
        machines=scenario["machines"],
    )

    # 6. Scheduling
    schedule = generate_schedule(
        mps=mps,
        products=scenario["products"],
        machines=scenario["machines"],
    )

    # 7. Validation
    validation = validate_schedule(
        schedule=schedule,
        machines=scenario["machines"],
        inventory=scenario["inventory"],
    )

    return {
        "mps": mps,
        "material_requirements": material_requirements,
        "planned_orders": planned_orders,
        "capacity_requirements": capacity_requirements,
        "machine_load": machine_load,
        "schedule": schedule,
        "validation": validation,
    }