"""FastAPI application. New six-agent parts: the event channel and work runner (started here, SD-1) and the
simulation clock/settings doors. Old routes (orders, plans, negotiations, agents, supplier interface, old A2A) stay
until the Phase 2 retirement (API-4)."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import a2a, agents, negotiations, orders, planning, simulation
from app.core.errors import install_correlation_id, install_error_handlers
from app.core.workers import start_workers, stop_workers
from app.negotiation import a2a_endpoints as negotiation_endpoints
from app.sales_agent import api as sales_agent
from app.simulation import api as simulation_v2


@asynccontextmanager
async def lifespan(_: FastAPI):
    sales_agent.release_stuck_conversations()  # conversations left "busy" by a run that stopped in the middle of a reply
    start_workers()  # background work runner (event dispatcher, ...) unless BACKGROUND_WORKERS=false
    try:
        yield
    finally:
        stop_workers()


app = FastAPI(title="Decentralized MRPII", version="0.3.0", lifespan=lifespan)
install_error_handlers(app)
install_correlation_id(app)
# The Phase 5 demo frontend (Next.js dev server) calls the API from the browser. Local demo only; no auth.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Correlation-Id"],
)

app.include_router(orders.router)
app.include_router(planning.router)
app.include_router(negotiations.router)
app.include_router(agents.router)
app.include_router(agents.supplier_router)
app.include_router(simulation.router)
app.include_router(simulation_v2.router)
app.include_router(sales_agent.router)
a2a.install_a2a_spike(app)  # old endpoints (inventory, purchasing, supplier-interface) until retired
negotiation_endpoints.install(app)  # six-agent endpoints (store and acknowledge, NG-1)


@app.get("/health", tags=["system"])
def health() -> dict:
    return {"status": "ok"}
