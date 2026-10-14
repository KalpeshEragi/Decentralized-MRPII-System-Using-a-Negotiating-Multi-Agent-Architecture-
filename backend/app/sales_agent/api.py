"""The Sales Agent's API doors. Routes only: the work is in `manager.py` and `views.py`.

Door numbers follow dev_docs/sales_agent/3_sales_agent_backend.md. Door 3 (Planning result arrives) comes with the fake
Planning in a later checkpoint, and door 7 (health check) is the backend's existing `/health`.

    1  POST   /sales/test-channel/messages          a customer message goes in; the answer comes later (door 2)
    2  GET    /sales/conversations/{id}/messages    new messages of a conversation (`?after=<message id>`)
    4  GET    /sales/conversations/{id}             a conversation, its stage and the collected details
    5  GET    /sales/inquiries/{id}                 an inquiry with its options
    6  GET    /sales/customers/{id}  or  /sales/customers?phone=      a customer, saved notes and recent orders
    8  POST   /sales/test-channel/reset             close every test conversation
       GET    /sales/test-channel                   the test chat page
       GET    /sales/test-channel/history/{phone}   the open conversation of a test phone number (for the page)
       DELETE /sales/test-channel/history/{phone}   clear one test chat
"""

import logging
import uuid
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, StringConstraints
from sqlalchemy.orm import Session

from app.core.database import get_db, new_session
from app.llm.client import LLMClient, OllamaClient
from app.sales_agent import manager, views

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sales", tags=["sales agent"])

CHANNEL = "TEST"
CHAT_PAGE = Path(__file__).parent / "test_channel" / "chat.html"

# Spaces around the text are removed, and text made only of spaces is refused.
Phone = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30)]
ProviderMessageId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
CustomerMessage = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class SendMessageRequest(BaseModel):
    phone: Phone
    message_id: ProviderMessageId  # the channel's own id for this message; sending the same id twice is harmless
    text: CustomerMessage


def get_llm_client() -> LLMClient:
    """The model used for replies. Tests replace this function with a fake model."""
    return OllamaClient.from_settings()


def get_session_factory() -> Callable[[], Session]:
    """How the background answer opens its own database session. Tests replace this to use the test database."""
    return new_session


def answer_in_background(session_factory: Callable[[], Session], conversation_id: uuid.UUID, llm_client: LLMClient) -> None:
    try:
        with session_factory() as db:
            manager.process_conversation(db, conversation_id, llm_client, date.today())
    except Exception:  # a failure here must not stop the server; the customer's message stays saved
        logger.exception("could not answer conversation %s", conversation_id)


def release_stuck_conversations() -> None:
    """Called when the backend starts. Never stops the backend from starting (the database may be unavailable)."""
    try:
        with new_session() as db:
            manager.release_stuck_conversations(db)
    except Exception:
        logger.warning("could not release stuck Sales Agent conversations at startup", exc_info=True)


# -- door 1 and the test chat page ----------------------------------------------------------------------------------


@router.post("/test-channel/messages", status_code=202)
def send_message(
    request: SendMessageRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    llm_client: LLMClient = Depends(get_llm_client),
    session_factory: Callable[[], Session] = Depends(get_session_factory),
):
    accepted = manager.accept_message(db, CHANNEL, request.phone, request.message_id, request.text)
    background_tasks.add_task(answer_in_background, session_factory, accepted.conversation_id, llm_client)
    return {
        "status": "duplicate" if accepted.duplicate else "received",
        "conversation_id": str(accepted.conversation_id),
        "message_id": str(accepted.message_id),
    }


@router.get("/test-channel", include_in_schema=False)
def chat_page():
    return FileResponse(CHAT_PAGE)


@router.get("/test-channel/history/{phone}")
def read_history(phone: str, db: Session = Depends(get_db)):
    return views.chat_of_sender(db, CHANNEL, phone)


@router.delete("/test-channel/history/{phone}")
def clear_history(phone: str, db: Session = Depends(get_db)):
    manager.clear_chat(db, CHANNEL, phone)
    return {"status": "cleared"}


# -- door 8 ---------------------------------------------------------------------------------------------------------


@router.post("/test-channel/reset")
def reset_test_channel(db: Session = Depends(get_db)):
    """Closes every open test conversation. Nothing is deleted."""
    return {"status": "reset", "closed_conversations": manager.reset_test_channel(db)}


# -- doors 2, 4, 5, 6 -----------------------------------------------------------------------------------------------


@router.get("/conversations/{conversation_id}/messages")
def get_new_messages(conversation_id: uuid.UUID, after: uuid.UUID | None = None, db: Session = Depends(get_db)):
    return views.new_messages(db, conversation_id, after)


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: uuid.UUID, db: Session = Depends(get_db)):
    return views.conversation_view(db, conversation_id)


@router.get("/inquiries/{inquiry_id}")
def get_inquiry(inquiry_id: uuid.UUID, db: Session = Depends(get_db)):
    return views.inquiry_view(db, inquiry_id)


@router.get("/customers")
def get_customer_by_phone(phone: Phone, db: Session = Depends(get_db)):
    return views.customer_view_by_phone(db, phone)


@router.get("/customers/{customer_id}")
def get_customer(customer_id: uuid.UUID, db: Session = Depends(get_db)):
    return views.customer_view(db, customer_id)
