from collections import defaultdict

from app.models.inventory import InventoryItem
from app.models.machine import Machine
from app.models.planning import (
    ScheduleEntry,
)


def validate_schedule(
    schedule: list[ScheduleEntry],
    machines: list[Machine],
    inventory: list[InventoryItem],
) -> dict:
    """
    Validate the generated production schedule.

    Checks:
    1. Machine exists.
    2. Machine is available.
    3. Machine daily capacity is not exceeded.
    """

    machine_lookup = {
        machine.id: machine
        for machine in machines
    }

    errors = []

    machine_usage = defaultdict(float)

    for entry in schedule:

        if entry.machine_id not in machine_lookup:

            errors.append(
                f"Unknown machine "
                f"'{entry.machine_id}'"
            )

            continue

        machine = machine_lookup[
            entry.machine_id
        ]

        if not machine.available:

            errors.append(
                f"Machine '{machine.id}' "
                f"is unavailable."
            )

        key = (
            entry.machine_id,
            entry.planned_date,
        )

        machine_usage[key] += (
            entry.end_hour
            - entry.start_hour
        )

    for (machine_id, planned_date), used_hours in (
        machine_usage.items()
    ):

        machine = machine_lookup[machine_id]

        if used_hours > machine.capacity_hours_per_day:

            errors.append(
                f"Machine '{machine_id}' exceeds "
                f"capacity on {planned_date}: "
                f"{used_hours:.2f}h > "
                f"{machine.capacity_hours_per_day:.2f}h"
            )

    return {
        "valid": len(errors) == 0,
        "errors": errors,
    }