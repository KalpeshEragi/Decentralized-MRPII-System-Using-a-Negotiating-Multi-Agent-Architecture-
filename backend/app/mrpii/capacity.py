from collections import defaultdict

from app.models.demand import CustomerOrder
from app.models.machine import Machine
from app.models.product import Product
from app.models.planning import (
    MPSEntry,
    CapacityRequirement,
    MachineLoad,
)


def calculate_capacity_requirements(
    mps: list[MPSEntry],
    products: list[Product],
) -> list[CapacityRequirement]:
    """
    Calculate production hours required for each MPS entry.
    """

    product_lookup = {
        product.id: product
        for product in products
    }

    requirements = []

    for entry in mps:

        if entry.product_id not in product_lookup:
            raise ValueError(
                f"Unknown product "
                f"'{entry.product_id}'"
            )

        product = product_lookup[
            entry.product_id
        ]

        required_hours = (
            entry.quantity
            * product.production_time_hours
        )

        requirements.append(
            CapacityRequirement(
                product_id=entry.product_id,
                quantity=entry.quantity,
                required_hours=required_hours,
                planned_date=entry.planned_date,
            )
        )

    return requirements


def calculate_machine_load(
    requirements: list[CapacityRequirement],
    machines: list[Machine],
) -> list[MachineLoad]:
    """
    Calculate machine capacity utilisation.

    Current baseline assumption:
    production can be performed on any available
    machine in the manufacturing work center.
    """

    available_machines = [
        machine
        for machine in machines
        if machine.available
    ]

    if not available_machines:
        raise ValueError(
            "No available machines."
        )

    total_capacity = sum(
        machine.capacity_hours_per_day
        for machine in available_machines
    )

    total_required_hours = sum(
        requirement.required_hours
        for requirement in requirements
    )

    loads = []

    for machine in available_machines:

        machine_share = (
            machine.capacity_hours_per_day
            / total_capacity
        )

        assigned_hours = (
            total_required_hours
            * machine_share
        )

        utilization = (
            assigned_hours
            / machine.capacity_hours_per_day
        )

        loads.append(
            MachineLoad(
                machine_id=machine.id,
                machine_name=machine.name,
                capacity_hours=machine.capacity_hours_per_day,
                required_hours=assigned_hours,
                utilization=utilization,
            )
        )

    return loads