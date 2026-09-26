from datetime import date, timedelta

from app.models.machine import Machine
from app.models.planning import (
    MPSEntry,
    ScheduleEntry,
)
from app.models.product import Product


def generate_schedule(
    mps: list[MPSEntry],
    products: list[Product],
    machines: list[Machine],
) -> list[ScheduleEntry]:
    """
    Generate a simple earliest-due-date production schedule.

    Production is assigned to available machines
    while respecting daily machine capacity.
    """

    product_lookup = {
        product.id: product
        for product in products
    }

    available_machines = [
        machine
        for machine in machines
        if machine.available
    ]

    if not available_machines:
        raise ValueError(
            "No available machines."
        )

    # Sort MPS by due date and priority of urgency.
    sorted_mps = sorted(
        mps,
        key=lambda entry: entry.planned_date,
    )

    # Track used capacity per machine per date.
    machine_usage: dict[
        tuple[str, str],
        float
    ] = {}

    schedule = []

    for entry in sorted_mps:

        if entry.product_id not in product_lookup:
            raise ValueError(
                f"Unknown product "
                f"'{entry.product_id}'"
            )

        product = product_lookup[
            entry.product_id
        ]

        remaining_quantity = entry.quantity

        current_date = date.fromisoformat(
            entry.planned_date
        )

        while remaining_quantity > 0:

            assigned = False

            for machine in available_machines:

                key = (
                    machine.id,
                    current_date.isoformat(),
                )

                used_hours = machine_usage.get(
                    key,
                    0,
                )

                available_hours = (
                    machine.capacity_hours_per_day
                    - used_hours
                )

                if available_hours <= 0:
                    continue

                max_quantity = int(
                    available_hours
                    // product.production_time_hours
                )

                if max_quantity <= 0:
                    continue

                quantity = min(
                    remaining_quantity,
                    max_quantity,
                )

                start_hour = used_hours

                production_hours = (
                    quantity
                    * product.production_time_hours
                )

                end_hour = (
                    start_hour
                    + production_hours
                )

                schedule.append(
                    ScheduleEntry(
                        product_id=entry.product_id,
                        quantity=quantity,
                        planned_date=current_date.isoformat(),
                        machine_id=machine.id,
                        start_hour=start_hour,
                        end_hour=end_hour,
                    )
                )

                machine_usage[key] = end_hour

                remaining_quantity -= quantity

                assigned = True

                if remaining_quantity <= 0:
                    break

            if not assigned:

                current_date = current_date + timedelta(days=1)
    return schedule