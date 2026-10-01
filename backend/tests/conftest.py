"""Tests always use the mock AI, even if .env says AI_PROVIDER=live, so they never spend free-tier quota."""

import os

os.environ["AI_PROVIDER"] = "mock"
