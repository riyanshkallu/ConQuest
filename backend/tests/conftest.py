"""Tests always use the mock AI, even if .env says AI_PROVIDER=live, so they never spend free-tier quota."""

import os

os.environ["AI_PROVIDER"] = "mock"
# In-memory SQLite by default. Set TEST_DATABASE_URL to run the suite against a throwaway
# Postgres (the same database Supabase uses). Never point it at real data: tests delete rows.
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "sqlite://")
