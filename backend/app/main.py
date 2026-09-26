from fastapi import FastAPI

from app.api.planning import router as planning_router


app = FastAPI(
    title="Decentralized MRPII",
    version="0.1.0",
)


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "system": "Decentralized MRPII",
        "version": "0.1.0",
    }


app.include_router(planning_router)