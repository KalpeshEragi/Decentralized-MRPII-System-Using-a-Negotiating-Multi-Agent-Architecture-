"""The customer driver (demo.md §9, DM-3, DM-7): simulated customers, an outside-world adapter, not an agent. They use
only Sales' doors, over HTTP like any outside caller; they never touch an agent's data. Two modes (`customer_chat_mode`):

- structured (0, default; large runs): request, choice and "yes" go as data (`/sales/simulated-customers/...`);
- chat (1; one or two orders shown live): they write chat messages (`/sales/test-channel/messages`) that Sales reads
  with the language model, and answer what Sales shows them (a letter for an option, then "yes").

Morning: `customer_orders_per_day` new requests (product, quantity, requested date drawn from a generator seeded per
run and day, DM-6: same seed, same orders). After the agents settled: every request Planning answered gets a decision
by a fixed rule — accept REQUESTED; else LATER_DATE if at most `customer_later_date_max_days` later; else decline.
Accepting is the customer's acceptance only: Planning commits (or not) on its own.
"""

import logging
import random
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.core import http_doors
from app.core.config import get_settings
from app.sales_agent import reads as sales
from app.simulation.settings import setting

logger = logging.getLogger(__name__)


CHAT_PHONE = "+91chat"  # chat-mode customers' phone numbers start with this


def _headers() -> dict:
    return {"X-Door-Key": get_settings().simulation_door_key or ""}


def place_orders(db: Session, day: date) -> list[dict]:
    """Today's new customer requests. `db` is only read (settings, products); the requests go through Sales' door."""
    count = int(setting(db, "customer_orders_per_day"))
    products = sales.active_products(db)
    if count <= 0 or not products:
        return []
    rng = random.Random(f"{setting(db, 'customer_seed')}:{day.isoformat()}")
    low, high = int(setting(db, "customer_quantity_min")), int(setting(db, "customer_quantity_max"))
    lead_low, lead_high = int(setting(db, "customer_lead_days_min")), int(setting(db, "customer_lead_days_max"))
    chat = bool(int(setting(db, "customer_chat_mode")))
    db.rollback()  # nothing is held while Sales and Planning work
    placed = []
    for number in range(count):
        product = rng.choice(products)
        body = {"phone": f"+91-sim-{day.strftime('%Y%m%d')}-{number:03d}",
                "product_id": product["product_id"], "quantity": str(rng.randint(low, high)),
                "requested_date": (day + timedelta(days=rng.randint(lead_low, lead_high))).isoformat()}
        if chat:
            response = _say(f"{CHAT_PHONE}{day.strftime('%Y%m%d')}{number:03d}", f"{day}:{number}:request",
                            f"Hello, I would like {body['quantity']} {product['name']} by "
                            f"{date.fromisoformat(body['requested_date']):%B %d, %Y}, please.")
            placed.append({**body, "mode": "chat", "status": response.status_code})
            continue
        response = http_doors.post("/sales/simulated-customers/requests", body, _headers())
        if response.status_code >= 400:
            logger.warning("simulated customer request refused: %s", response.text[:200])
            continue
        placed.append({**body, **response.json()})
    return placed


def answer_options(db: Session) -> list[dict]:
    """Every answered request gets the customer's decision (fixed rule, demo.md §9). Returns what was done."""
    later_limit = int(setting(db, "customer_later_date_max_days"))
    if int(setting(db, "customer_chat_mode")):
        return _answer_in_chat(db, later_limit)
    waiting = sales.simulated_inquiries_answered(db)
    db.rollback()
    decided = []
    for inquiry in waiting:
        choice = _choose(inquiry, later_limit)
        path = f"/sales/simulated-customers/inquiries/{inquiry['inquiry_id']}"
        if choice is None:
            response = http_doors.post(f"{path}/decline", {}, _headers())
        else:
            response = http_doors.post(f"{path}/accept", {"option_id": choice["option_id"]}, _headers())
        decided.append({"inquiry_id": inquiry["inquiry_id"], "choice": choice["kind"] if choice else "DECLINE",
                        "status": response.status_code})
    return decided


def _choose(inquiry: dict, later_limit: int) -> dict | None:
    by_kind = {o["kind"]: o for o in inquiry["options"]}
    if "REQUESTED" in by_kind:
        return by_kind["REQUESTED"]
    later = by_kind.get("LATER_DATE")
    if later and (date.fromisoformat(later["delivery_date"])
                  - date.fromisoformat(inquiry["requested_date"])).days <= later_limit:
        return later
    return None


def _say(phone: str, message_key: str, text: str):
    """One chat message from a simulated customer (a fixed message id per key: sending twice is harmless)."""
    return http_doors.post("/sales/test-channel/messages",
                           {"phone": phone, "message_id": f"sim-{phone}-{message_key}", "text": text}, {})


def _answer_in_chat(db: Session, later_limit: int) -> list[dict]:
    """Chat mode: answer what Sales showed — a letter for the chosen option, "yes" to the confirmation question, or a
    plain "no, thank you" when no option fits the rule."""
    waiting = sales.chat_inquiries(db, CHAT_PHONE)
    db.rollback()
    done = []
    for inquiry in waiting:
        if inquiry["stage"] == "OPTIONS_PRESENTED" and inquiry["options"]:
            choice = _choose(inquiry, later_limit)
            text = choice["letter"] if choice else "No, thank you."
        elif inquiry["stage"] == "AWAITING_CONFIRMATION":
            text = "Yes"
        else:
            continue
        response = _say(inquiry["phone"], f"{inquiry['inquiry_id']}:{inquiry['stage']}", text)
        done.append({"inquiry_id": inquiry["inquiry_id"], "said": text, "status": response.status_code})
    return done
