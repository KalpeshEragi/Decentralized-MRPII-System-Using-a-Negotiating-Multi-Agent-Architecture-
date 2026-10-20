"""FastAPI application of the six-agent prototype: the agents' doors, the A2A negotiation endpoints, the simulator
doors, and the background work runner (started here, SD-1). Door catalogue: dev_docs/architecture/backend_api.md."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.errors import install_correlation_id, install_error_handlers
from app.core.workers import start_workers, stop_workers
from app.hr_agent import api as hr
from app.inventory_agent import api as inventory
from app.planning_agent import api as planning
from app.purchasing_agent import api as purchasing_agent
from app.negotiation import a2a_endpoints as negotiation_endpoints
from app.observer import api as observer
from app.sales_agent import api as sales_agent
from app.simulation import api as simulation
from app.warehouse_agent import api as warehouse


@asynccontextmanager
async def lifespan(_: FastAPI):
    sales_agent.release_stuck_conversations()  # conversations left "busy" by a run that stopped in the middle of a reply
    start_workers()  # background work runner (events, negotiation, agents) unless BACKGROUND_WORKERS=false
    try:
        yield
    finally:
        stop_workers()


app = FastAPI(title="Decentralized MRPII", version="0.4.0", lifespan=lifespan)
install_error_handlers(app)
install_correlation_id(app)
# The demo frontend (Next.js dev server) calls the API from the browser. Local demo only; no auth.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Correlation-Id"],
)

app.include_router(simulation.router)
app.include_router(sales_agent.router)
app.include_router(planning.router)
app.include_router(inventory.router)
app.include_router(purchasing_agent.router)
app.include_router(hr.router)
app.include_router(warehouse.router)
app.include_router(observer.router)
negotiation_endpoints.install(app)  # A2A endpoints, store and acknowledge (NG-1)


@app.get("/health", tags=["system"])
def health() -> dict:
    return {"status": "ok"}
