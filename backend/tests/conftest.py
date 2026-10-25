"""Test-wide settings: no background threads in tests (work items are run directly by the tests that need them)."""

import os

os.environ["BACKGROUND_WORKERS"] = "false"
