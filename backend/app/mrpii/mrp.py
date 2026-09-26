from collections import defaultdict
from datetime import date, timedelta

from app.models.bom import BOM
from app.models.planning import (
    MPSEntry,
    MaterialRequirement,
    PlannedOrder,
)
from app.models.inventory import InventoryItem
from app.models.material import Material


def explode_bom(
    mps: list[MPSEntry],
    boms: list[BOM],
) -> dict[str, float]:

    bom_lookup = {
        bom.product_id: bom
        for bom in boms
    }

    material_requirements = defaultdict(float)

    for mps_entry in mps:

        product_id = mps_entry.product_id
        production_quantity = mps_entry.quantity

        if product_id not in bom_lookup:
            raise ValueError(
                f"No BOM found for product '{product_id}'"
            )

        bom = bom_lookup[product_id]

        for component in bom.components:

            required_quantity = (
                production_quantity
                * component.quantity
            )

            material_requirements[
                component.component_id
            ] += required_quantity

    return dict(material_requirements)


def calculate_net_requirements(
    gross_requirements: dict[str, float],
    inventory: list[InventoryItem],
) -> list[MaterialRequirement]:

    inventory_lookup = {
        item.item_id: item
        for item in inventory
    }

    results = []

    for material_id, gross_requirement in sorted(
        gross_requirements.items()
    ):

        if material_id not in inventory_lookup:
            raise ValueError(
                f"No inventory record found for "
                f"material '{material_id}'"
            )

        inventory_item = inventory_lookup[material_id]

        available = inventory_item.available_quantity

        net_requirement = max(
            0,
            gross_requirement - available,
        )

        results.append(
            MaterialRequirement(
                material_id=material_id,
                gross_requirement=gross_requirement,
                available_inventory=available,
                net_requirement=net_requirement,
            )
        )

    return results


def generate_planned_orders(
    mps: list[MPSEntry],
    material_requirements: list[MaterialRequirement],
    materials: list[Material],
) -> list[PlannedOrder]:
    """
    Convert net material requirements into planned
    procurement orders using supplier lead time.

    Required date:
        Date material is needed for production.

    Order date:
        Required date - supplier lead time.
    """

    material_lookup = {
        material.id: material
        for material in materials
    }

    planned_orders = []

    # Map material requirements to the earliest
    # production date that needs them.
    material_required_dates = {}

    for mps_entry in mps:

        product_id = mps_entry.product_id
        required_date = date.fromisoformat(
            mps_entry.planned_date
        )

        # This material date is determined later
        # through the BOM.
        #
        # For the current MRPII implementation,
        # material is required on the product
        # production date.

        # Store the earliest date.
        #
        # The actual material mapping is handled
        # below using the BOM requirements.

    for requirement in material_requirements:

        if requirement.net_requirement <= 0:
            continue

        if requirement.material_id not in material_lookup:
            raise ValueError(
                f"No material found for "
                f"'{requirement.material_id}'"
            )

        material = material_lookup[
            requirement.material_id
        ]

        # Find earliest MPS date.
        required_date = min(
            date.fromisoformat(entry.planned_date)
            for entry in mps
        )

        order_date = (
            required_date
            - timedelta(days=material.lead_time_days)
        )

        planned_orders.append(
            PlannedOrder(
                material_id=requirement.material_id,
                quantity=requirement.net_requirement,
                required_date=required_date.isoformat(),
                order_date=order_date.isoformat(),
                lead_time_days=material.lead_time_days,
            )
        )

    return planned_orders

def generate_time_phased_requirements(
    mps: list[MPSEntry],
    boms: list[BOM],
    inventory: list[InventoryItem],
    materials: list[Material],
) -> list[PlannedOrder]:
    """
    Generate time-phased planned procurement orders.

    Each MPS production date generates material demand
    on that same date.

    Inventory is consumed chronologically.
    Remaining shortages become planned procurement orders.
    """

    bom_lookup = {
        bom.product_id: bom
        for bom in boms
    }

    inventory_lookup = {
        item.item_id: item
        for item in inventory
    }

    material_lookup = {
        material.id: material
        for material in materials
    }

    # Group MPS entries by date.
    sorted_mps = sorted(
        mps,
        key=lambda entry: entry.planned_date,
    )

    remaining_inventory = {
        item_id: item.available_quantity
        for item_id, item in inventory_lookup.items()
    }

    planned_orders = []

    for mps_entry in sorted_mps:

        if mps_entry.product_id not in bom_lookup:
            raise ValueError(
                f"No BOM found for product "
                f"'{mps_entry.product_id}'"
            )

        production_date = date.fromisoformat(
            mps_entry.planned_date
        )

        bom = bom_lookup[mps_entry.product_id]

        for component in bom.components:

            material_id = component.component_id

            gross_requirement = (
                mps_entry.quantity
                * component.quantity
            )

            available = remaining_inventory.get(
                material_id,
                0,
            )

            inventory_used = min(
                available,
                gross_requirement,
            )

            remaining_inventory[material_id] -= (
                inventory_used
            )

            net_requirement = (
                gross_requirement
                - inventory_used
            )

            if net_requirement <= 0:
                continue

            if material_id not in material_lookup:
                raise ValueError(
                    f"No material found for "
                    f"'{material_id}'"
                )

            material = material_lookup[material_id]

            order_date = (
                production_date
                - timedelta(
                    days=material.lead_time_days
                )
            )

            planned_orders.append(
                PlannedOrder(
                    material_id=material_id,
                    quantity=net_requirement,
                    required_date=production_date.isoformat(),
                    order_date=order_date.isoformat(),
                    lead_time_days=material.lead_time_days,
                )
            )

    return planned_orders