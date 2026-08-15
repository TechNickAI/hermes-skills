"""Pytest configuration for the skill library.

Isolates tests from the developer's environment. Anyone actually running a
Hermes agent has ``HERMES_HOME`` exported, and a test that resolves paths
relative to it would read their live profile instead of this checkout.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _isolate_from_live_hermes(monkeypatch):
    monkeypatch.delenv("HERMES_HOME", raising=False)
