"""Test-wide settings: no background threads in tests (work items are run directly by the tests that need them), and
strict event payload checks (EM-3)."""

import os

os.environ["BACKGROUND_WORKERS"] = "false"
os.environ["EVENT_PAYLOAD_CHECK"] = "strict"  # EM-3: tests refuse an event payload that does not match the catalogue
