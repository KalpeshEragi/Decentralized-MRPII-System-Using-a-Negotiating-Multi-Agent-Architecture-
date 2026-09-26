import asyncio

from agents import Runner

from app.agents.sales.sales_agent import sales_agent


async def main():
    result = await Runner.run(
        sales_agent,
        """
        Customer order:

        Order ID: ORD001
        Product: P001 Smart Espresso Machine
        Quantity: 12
        Due date: 2026-09-08
        Priority: 2

        Prepare this demand information for the Planning Agent.
        """,
    )

    print(result.final_output)


if __name__ == "__main__":
    asyncio.run(main())