#!/usr/bin/env python3
"""Run the post-game pipeline every 15 minutes on this Mac with launchd.

    python scripts/pipeline_schedule.py install     # write the LaunchAgent and start it
    python scripts/pipeline_schedule.py uninstall   # stop it and remove the LaunchAgent

The pipeline skips runs outside the evening game window itself, so launchd only
needs a fixed interval. launchd does not run jobs while the Mac sleeps; a run
missed during sleep happens once on wake, and per-game state catches up on the
rest. The job runs as this user and reads the repository's .env.
"""

from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
from pathlib import Path

LABEL = "com.nbaharness.pipeline"
ROOT = Path(__file__).resolve().parents[1]
AGENT = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOG = Path.home() / "Library" / "Logs" / "nba-harness-pipeline.log"
DOMAIN = f"gui/{os.getuid()}"


def install() -> None:
    AGENT.parent.mkdir(parents=True, exist_ok=True)
    AGENT.write_bytes(plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [str(ROOT / ".venv" / "bin" / "python"), "-m", "api.nba_agent.pipeline"],
        "WorkingDirectory": str(ROOT),
        "StartInterval": 15 * 60,
        "StandardOutPath": str(LOG),
        "StandardErrorPath": str(LOG),
    }))
    subprocess.run(["launchctl", "bootout", f"{DOMAIN}/{LABEL}"], capture_output=True)
    subprocess.run(["launchctl", "bootstrap", DOMAIN, str(AGENT)], check=True)
    print(f"Installed {AGENT}\nLogs: {LOG}")


def uninstall() -> None:
    subprocess.run(["launchctl", "bootout", f"{DOMAIN}/{LABEL}"], capture_output=True)
    AGENT.unlink(missing_ok=True)
    print(f"Removed {LABEL}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=["install", "uninstall"])
    {"install": install, "uninstall": uninstall}[parser.parse_args().action]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
