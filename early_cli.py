"""Command-line entry to the EARLY tools, for hooks and timers outside an MCP client.

    early_cli.py stop [--round N] [--folder ID]
    early_cli.py timesheet START END [--folder ID] [--round HOURS]

Prints the tool's JSON result; exits 1 when it holds an error.
"""

import argparse
import asyncio
import json
import sys
from typing import Any

import early


async def stop(round_minutes: int, folder_id: str | None) -> dict[str, Any]:
    """Stop the running timer, but only when its activity is in folder_id (if given)."""
    tracking = await early.current_tracking()
    if "error" in tracking:
        if "does not exist" in tracking.get("detail", ""):
            return {"stopped": False, "reason": "nothing tracking"}
        return tracking  # auth, network or config trouble must not look like an idle timer
    folder = str(tracking.get("activity", {}).get("folderId"))
    if folder_id and folder != str(folder_id):
        return {"stopped": False, "reason": f"running activity is in folder {folder}, not {folder_id}"}
    # Stop the timer that passed the folder check, not whatever runs by the time of a second lookup.
    return await early.stop_running(tracking, round_minutes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="early_cli")
    sub = parser.add_subparsers(dest="command", required=True)
    p_stop = sub.add_parser("stop", help="stop the running timer")
    p_stop.add_argument("--round", type=int, default=0, dest="round_minutes")
    p_stop.add_argument("--folder")
    p_sheet = sub.add_parser("timesheet", help="roll entries up into timesheet rows")
    p_sheet.add_argument("start")
    p_sheet.add_argument("end")
    p_sheet.add_argument("--folder")
    p_sheet.add_argument("--round", type=float, default=0.25, dest="round_hours")
    args = parser.parse_args(argv)

    if args.command == "stop":
        result = asyncio.run(stop(args.round_minutes, args.folder))
    else:
        result = asyncio.run(early.timesheet(args.start, args.end, args.folder, args.round_hours))
    json.dump(result, sys.stdout, indent=2)
    print()
    return 1 if "error" in result else 0


if __name__ == "__main__":
    sys.exit(main())
