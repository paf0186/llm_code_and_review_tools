#!/usr/bin/env python3
"""Lustre wait queue analysis — find tasks blocked in Lustre code.

Identifies D-state (uninterruptible sleep) tasks with Lustre frames
in their stack traces, groups them by wait point, and reports how
many tasks are stuck at each location. This is the first thing to
check when diagnosing I/O hangs or lock contention.

Usage:
    python3 lustre_waitq.py --vmcore <path> --vmlinux <path> \
        --mod-dir <ko_dir> [--debug-dir <debug_dir>] [--json] [--pretty]
"""

import argparse
import json
import sys
from collections import defaultdict

import drgn
from drgn.helpers.linux.pid import for_each_task

try:
    from . import lustre_helpers as lh
except ImportError:
    import lustre_helpers as lh

# Lustre module name patterns
LUSTRE_MODULES = {
    "lustre", "obdclass", "ptlrpc", "osc", "mdc", "lov", "lmv",
    "mgc", "fid", "fld", "llite", "ldlm", "lnet", "libcfs",
    "ko2iblnd", "ksocklnd", "lnet_selftest",
}

LUSTRE_SOURCE_PATTERNS = [
    "/lustre/", "/lnet/", "/libcfs/",
]


def _is_lustre_frame(frame_str):
    """Check if a stack frame is from Lustre code."""
    for pat in LUSTRE_SOURCE_PATTERNS:
        if pat in frame_str:
            return True
    return False


def _get_lustre_wait_point(prog, task):
    """Get the deepest Lustre frame as the 'wait point' for a D-state task."""
    try:
        trace = prog.stack_trace(task)
    except (drgn.FaultError, drgn.ObjectAbsentError, ValueError):
        return None, []

    frames = []
    lustre_frames = []
    for frame in trace:
        desc = str(frame)
        frames.append(desc)
        if _is_lustre_frame(desc):
            lustre_frames.append(desc)

    if not lustre_frames:
        return None, frames

    # The deepest Lustre frame (highest in call chain) is the wait point
    # But the most informative is typically the first Lustre frame
    # (closest to the actual blocking call)
    wait_point = lustre_frames[0]

    # Extract function name for grouping
    if " in " in wait_point:
        parts = wait_point.split(" in ", 1)
        func = parts[1].strip()
        # Remove source location for grouping
        if " at " in func:
            func = func.split(" at ")[0].strip()
        return func, frames

    return wait_point.strip(), frames


def find_lustre_waiters(prog):
    """Find all D-state tasks blocked in Lustre code."""
    try:
        from drgn.helpers.linux.sched import task_state_to_char
    except ImportError:
        return {"error": "drgn sched helpers not available"}

    waiters = defaultdict(list)
    non_lustre_d = 0
    total_d = 0

    for task in for_each_task(prog):
        try:
            try:
                state_char = task_state_to_char(task)
            except Exception:
                continue

            if state_char != 'D':
                continue

            total_d += 1
            comm = task.comm.string_().decode(errors="replace")
            pid = task.pid.value_()

            wait_point, full_stack = _get_lustre_wait_point(prog, task)

            if wait_point is None:
                non_lustre_d += 1
                continue

            waiters[wait_point].append({
                "pid": pid,
                "comm": comm,
                "stack": full_stack[:8],  # Top 8 frames
            })

        except (drgn.FaultError, drgn.ObjectAbsentError):
            continue

    # Sort by count descending
    sorted_waiters = sorted(waiters.items(), key=lambda x: len(x[1]), reverse=True)

    return {
        "analysis": "lustre_waitq",
        "total_d_state": total_d,
        "lustre_d_state": sum(len(v) for v in waiters.values()),
        "non_lustre_d_state": non_lustre_d,
        "wait_points": [
            {
                "function": wp,
                "count": len(tasks),
                "sample_tasks": [
                    {"pid": t["pid"], "comm": t["comm"]}
                    for t in tasks[:5]
                ],
                "sample_stack": tasks[0]["stack"] if tasks else [],
            }
            for wp, tasks in sorted_waiters
        ],
    }


def print_waiters_text(result):
    """Print wait queue analysis in text format."""
    if "error" in result:
        print(f"Error: {result['error']}")
        return

    print(f"D-state tasks: {result['total_d_state']} total, "
          f"{result['lustre_d_state']} in Lustre, "
          f"{result['non_lustre_d_state']} non-Lustre")
    print()

    for wp in result["wait_points"]:
        print(f"--- {wp['function']} ({wp['count']} tasks) ---")
        comms = ", ".join(f"{t['comm']}({t['pid']})" for t in wp["sample_tasks"])
        print(f"  Tasks: {comms}")
        print(f"  Stack:")
        for frame in wp["sample_stack"][:6]:
            print(f"    {frame}")
        print()


def main():
    try:
        from .lustre_analyze import load_program
    except ImportError:
        from lustre_analyze import load_program

    parser = argparse.ArgumentParser(
        description="Find tasks blocked in Lustre wait queues.",
    )
    parser.add_argument("--vmcore", required=True)
    parser.add_argument("--vmlinux", required=True)
    parser.add_argument("--mod-dir", default=None)
    parser.add_argument("--debug-dir", default=None)
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    prog = load_program(args.vmcore, args.vmlinux, args.mod_dir, args.debug_dir)
    result = find_lustre_waiters(prog)

    if args.json:
        indent = 2 if args.pretty else None
        print(json.dumps(result, indent=indent, default=str))
    else:
        print_waiters_text(result)


if __name__ == "__main__":
    main()
