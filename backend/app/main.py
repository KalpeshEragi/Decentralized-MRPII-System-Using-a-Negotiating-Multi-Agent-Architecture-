"""FastAPI application: orders, plans, negotiations and agents APIs, the supplier interface, and the three A2A
endpoints (one app) behind which the Inventory and Purchasing Agents react."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import a2a, agents, negotiations, orders, planning, simulation
from app.core.errors import install_error_handlers
from app.sales_agent import api as sales_test_channel

app = FastAPI(title="Decentralized MRPII", version="0.3.0")
install_error_handlers(app)
# The Phase 5 demo frontend (Next.js dev server) calls the API from the browser. Local demo only; no auth.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(orders.router)
app.include_router(planning.router)
app.include_router(negotiations.router)
app.include_router(agents.router)
app.include_router(agents.supplier_router)
app.include_router(simulation.router)
app.include_router(sales_test_channel.router)
a2a.install_a2a_spike(app)


@app.get("/health", tags=["system"])
def health() -> dict:
    return {"status": "ok"}
