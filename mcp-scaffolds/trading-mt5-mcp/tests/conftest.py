"""Test harness wiring: import paths + .env loading."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))                  # for lib/, server.py
sys.path.insert(0, str(ROOT.parent / "_shared"))  # for rules.py, halt.py

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

# Force paper for all tests so we never accidentally hit order_send.
os.environ["TRADING_MODE"] = "paper"
