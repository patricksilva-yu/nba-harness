#!/usr/bin/env python3
"""Delete one bounded retention batch from the configured NBA storage backend."""

from __future__ import annotations

import argparse

from api.nba_agent.db import get_storage
from api.nba_agent.storage.operations import cleanup_expired_raw_responses


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--retention-days", type=int)
    parser.add_argument("--batch-size", type=int)
    args = parser.parse_args()
    deleted = cleanup_expired_raw_responses(
        get_storage(), retention_days=args.retention_days, batch_size=args.batch_size
    )
    print({"deleted_raw_responses": deleted})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
