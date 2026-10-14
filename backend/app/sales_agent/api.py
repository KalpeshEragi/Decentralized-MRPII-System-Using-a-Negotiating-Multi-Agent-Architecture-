"""Temporary test-channel door: the chat page and the three endpoints it uses.

These endpoints are replaced by the real API doors in a later checkpoint. Routes only: the work is in `manager.py`.
"""

from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, StringConstraints
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.llm.client import LLMClient, OllamaClient
from app.sales_agent import manager

router = APIRouter(prefix="/sales-test", tags=["sales agent test channel"])

CHANNEL = "TEST"
CHAT_PAGE = Path(__file__).parent / "test_channel" / "chat.html"

# Spaces around the text are removed, and a message made only of spaces is refused.
Phone = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30)]
CustomerMessage = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class ChatRequest(BaseModel):
    phone: Phone
    message: CustomerMessage


def get_llm_client() -> LLMClient:
    """The model used for replies. Tests replace this function with a fake model."""
    return OllamaClient.from_settings()


@router.get("", include_in_schema=False)
def chat_page():
    return FileResponse(CHAT_PAGE)


@router.post("/chat")
def send_message(
    request: ChatRequest, db: Session = Depends(get_db), llm_client: LLMClient = Depends(get_llm_client)
):
    reply = manager.handle_customer_message(db, CHANNEL, request.phone, request.message, llm_client, date.today())
    return {"reply": reply}


@router.get("/history/{phone}")
def read_history(phone: str, db: Session = Depends(get_db)):
    return {"messages": manager.read_chat_history(db, CHANNEL, phone)}


@router.delete("/history/{phone}")
def clear_history(phone: str, db: Session = Depends(get_db)):
    manager.clear_chat(db, CHANNEL, phone)
    return {"status": "cleared"}
