"""Which background work runs, and starting/stopping it (system_design.md §4.1).

Each part of the system adds its registrations here. Today the FastAPI lifespan calls `start_workers`; a separate
worker program could call the same function later without any agent changing.
"""

from app.core.config import get_settings
from app.core.database import new_session
from app.core.work_runner import WorkRunner
from app.events import channel
from app.hr_agent import manager as hr
from app.inventory_agent import manager as inventory
from app.negotiation import layer as negotiation
from app.planning_agent import manager as planning
from app.purchasing_agent import a2a as purchasing
from app.sales_agent import plan_events as sales
from app.simulation import suppliers as simulated_suppliers
from app.warehouse_agent import manager as warehouse

# each registers its inbox, queues and event subscriptions; simulated suppliers are not an agent (PI-1)
AGENTS = (planning, inventory, hr, warehouse, purchasing, sales, simulated_suppliers)

runner = WorkRunner(session_factory=new_session)


def register_all() -> None:
    settings = get_settings()
    runner.poll_seconds = settings.worker_poll_seconds
    runner.register(channel.dispatcher_registration(settings.event_dispatcher_workers))
    runner.register(negotiation.outbox_registration())
    for agent in AGENTS:
        agent.register(runner.register)


def start_workers() -> bool:
    """Start the background threads unless switched off (BACKGROUND_WORKERS=false). Returns whether they started."""
    if not get_settings().background_workers:
        return False
    register_all()
    runner.start()
    return True


def stop_workers() -> None:
    runner.stop()
