"""Repository-wide deterministic Flask session configuration for tests."""

import os


os.environ["SHOPPING_APP_ENV"] = "testing"
os.environ["SHOPPING_APP_SECRET_KEY"] = (
    "tests-only-deterministic-session-signing-key-2026-08-04"
)
