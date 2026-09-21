#!/usr/bin/env python3
"""Compatibility wrapper for the renamed analysis module."""

from __future__ import annotations

from api.nba_agent.analysis import *  # noqa: F401,F403
from api.nba_agent.analysis import main


if __name__ == "__main__":
    raise SystemExit(main())
