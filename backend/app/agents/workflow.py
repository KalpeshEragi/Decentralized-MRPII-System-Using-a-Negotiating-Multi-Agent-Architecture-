from agents import Runner

from app.agents.sales.sales_agent import sales_agent
from app.agents.planning.planning_agent import planning_agent
from app.agents.inventory.inventory_agent import inventory_agent
from app.agents.purchasing.purchasing_agent import purchasing_agent
from app.agents.production.production_agent import production_agent
from app.agents.warehouse.warehouse_agent import warehouse_agent


async def run_mrpii_workflow():
    """
    Run the initial decentralized MRPII workflow.

    This version focuses on agent reasoning and information flow.
    A2A and Contract Net negotiation will be added later.
    """

    # ---------------------------------------------------------
    # 1. SALES
    # ---------------------------------------------------------

    order = """
    Customer Order:

    Order ID: ORD001
    Product: P001 Smart Espresso Machine
    Quantity: 12
    Due Date: 2026-09-08
    Priority: 2

    Prepare this demand information for the planning process.
    """

    sales_result = await Runner.run(
        sales_agent,
        order,
    )

    sales_output = sales_result.final_output

    print("\n========== SALES AGENT ==========")
    print(sales_output)

    # ---------------------------------------------------------
    # 2. PLANNING
    # ---------------------------------------------------------

    planning_result = await Runner.run(
        planning_agent,
        f"""
        The Sales Agent has provided the following customer demand:

        {sales_output}

        Analyze this demand and prepare the requirements
        for the Inventory and Production agents.
        """,
    )

    planning_output = planning_result.final_output

    print("\n========== PLANNING AGENT ==========")
    print(planning_output)

    # ---------------------------------------------------------
    # 3. INVENTORY
    # ---------------------------------------------------------

    inventory_result = await Runner.run(
        inventory_agent,
        f"""
        The Planning Agent has provided the following
        manufacturing requirements:

        {planning_output}

        Analyze the requirements and report:
        - Required materials
        - Available inventory
        - Potential material shortages
        - Materials that may require purchasing
        """,
    )

    inventory_output = inventory_result.final_output

    print("\n========== INVENTORY AGENT ==========")
    print(inventory_output)

    # ---------------------------------------------------------
    # 4. PURCHASING
    # ---------------------------------------------------------

    purchasing_result = await Runner.run(
        purchasing_agent,
        f"""
        The Inventory Agent reported:

        {inventory_output}

        Determine whether procurement is required.

        Consider material shortages and supplier lead times.
        Prepare a purchasing proposal if required.
        """,
    )

    purchasing_output = purchasing_result.final_output

    print("\n========== PURCHASING AGENT ==========")
    print(purchasing_output)

    # ---------------------------------------------------------
    # 5. PRODUCTION
    # ---------------------------------------------------------

    production_result = await Runner.run(
        production_agent,
        f"""
        The Planning Agent provided:

        {planning_output}

        Analyze the production requirement.

        Determine what production capacity information
        and scheduling considerations are required.
        """,
    )

    production_output = production_result.final_output

    print("\n========== PRODUCTION AGENT ==========")
    print(production_output)

    # ---------------------------------------------------------
    # 6. WAREHOUSE
    # ---------------------------------------------------------

    warehouse_result = await Runner.run(
        warehouse_agent,
        f"""
        The Inventory Agent reported:

        {inventory_output}

        The Production Agent is working with:

        {production_output}

        Determine the warehouse/material-flow requirements
        needed to support production.
        """,
    )

    warehouse_output = warehouse_result.final_output

    print("\n========== WAREHOUSE AGENT ==========")
    print(warehouse_output)

    # ---------------------------------------------------------
    # 7. FINAL PLANNING REVIEW
    # ---------------------------------------------------------

    final_result = await Runner.run(
        planning_agent,
        f"""
        You are performing the final planning review.

        ORIGINAL SALES DEMAND:
        {sales_output}

        INVENTORY ANALYSIS:
        {inventory_output}

        PURCHASING PROPOSAL:
        {purchasing_output}

        PRODUCTION ANALYSIS:
        {production_output}

        WAREHOUSE ANALYSIS:
        {warehouse_output}

        Summarize the proposed manufacturing plan.

        Clearly identify:
        - Customer demand
        - Material availability
        - Procurement requirements
        - Production requirements
        - Warehouse requirements
        - Any conflicts or risks
        - Recommended next planning action

        Do not invent numerical values that were not provided.
        """,
    )

    final_output = final_result.final_output

    print("\n========== FINAL PLAN ==========")
    print(final_output)


if __name__ == "__main__":
    import asyncio

    asyncio.run(run_mrpii_workflow())