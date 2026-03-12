#!/usr/bin/env python3
"""Unified entry point for Lustre drgn vmcore analysis tools.

Provides a single CLI with subcommands for all available analyses.
Loads the vmcore once and dispatches to the requested tool, avoiding
repeated program initialization when running multiple analyses.

Usage:
    lustre-drgn --vmcore VMCORE --vmlinux VMLINUX <command> [options]
    lustre-drgn list                          # show available commands
    lustre-drgn help <command>                # show help for a command

Examples:
    lustre-drgn --vmcore /var/crash/vmcore --vmlinux /usr/lib/debug/vmlinux triage
    lustre-drgn --vmcore vmcore --vmlinux vmlinux locks --pretty
    lustre-drgn --vmcore vmcore --vmlinux vmlinux stacks -f UN
    lustre-drgn --vmcore vmcore --vmlinux vmlinux multi obd locks rpcs --pretty
"""

import argparse
import importlib.metadata
import json
import sys
import textwrap

try:
    _ver = importlib.metadata.version("lustre-drgn-tools")
except importlib.metadata.PackageNotFoundError:
    _ver = "dev"

# ── Command registry ─────────────────────────────────────────

COMMANDS = {
    "triage": {
        "module": "lustre_triage",
        "description": "One-shot comprehensive triage report",
        "detail": (
            "Runs all analyses (overview, backtraces, OBD devices,\n"
            "LDLM lock summary, wait queues, OSC stats) and produces\n"
            "a single structured JSON report."
        ),
        "extra_args": [
            (["-v", "--verbose"], {"action": "store_true",
                                   "help": "Include extra detail"}),
        ],
    },
    "analyze": {
        "module": "lustre_analyze",
        "description": "Core crash analysis (backtraces, locals, OBD devices)",
        "detail": (
            "Deep analysis of the crashing context: panic overview,\n"
            "full backtraces with local variables, and OBD device state.\n"
            "Specify analyses: overview, backtrace, locals, obd, all."
        ),
        "extra_args": [
            (["analyses"], {"nargs": "*", "default": ["all"],
                            "help": "Analyses: overview, backtrace, "
                                    "locals, obd, all"}),
        ],
    },
    "locks": {
        "module": "ldlm_dumplocks",
        "description": "Dump LDLM locks (granted and waiting) per namespace",
        "detail": (
            "Lists all LDLM lock namespaces and their granted/waiting\n"
            "locks with mode, resource, extent/ibits, remote NID, and\n"
            "flags. Use -n for namespace summary only."
        ),
        "extra_args": [
            (["-n"], {"dest": "nflag", "action": "store_true",
                      "help": "Print only namespace info"}),
            (["ns_addr"], {"nargs": "?", "default": None,
                           "type": lambda x: int(x, 0),
                           "help": "Namespace address (hex or decimal)"}),
        ],
    },
    "obd": {
        "module": "obd_devs",
        "description": "List OBD devices with import state and NID",
        "detail": (
            "Shows all active OBD devices from the global obd_devs\n"
            "array with import state, remote NID, connection count,\n"
            "and optional RPC statistics."
        ),
        "extra_args": [
            (["obd_device"], {"nargs": "?", "default": None,
                              "type": lambda x: int(x, 0),
                              "help": "OBD device address (hex or decimal)"}),
        ],
    },
    "rpcs": {
        "module": "ptlrpc",
        "description": "Dump ptlrpcd RPC queues (sent and pending)",
        "detail": (
            "Shows RPC queues for all ptlrpcd threads: phase, flags,\n"
            "NID, opcode, and xid for each request."
        ),
        "extra_args": [
            (["-o"], {"dest": "oflag", "action": "store_true",
                      "help": "Overview of ptlrpcd threads"}),
            (["-s"], {"dest": "sflag", "action": "store_true",
                      "help": "RPC counts per request set"}),
        ],
    },
    "stacks": {
        "module": "uniqueStacktrace",
        "description": "Unique stack traces grouped by frequency",
        "detail": (
            "Groups all tasks by unique stack trace and prints them\n"
            "sorted by frequency (least common first). Great for\n"
            "finding widespread hangs and unusual states."
        ),
        "extra_args": [
            (["-p", "--print-pid"], {"action": "store_true",
                                     "help": "Print PIDs"}),
            (["-q", "--print-taskpntr"], {"action": "store_true",
                                          "help": "Print task pointers"}),
            (["-s", "--swapper"], {"action": "store_true",
                                   "help": "Include swapper processes"}),
            (["-f", "--filter"], {"default": None,
                                  "choices": ["UN", "RU"],
                                  "help": "Filter by state "
                                          "(UN=uninterruptible, RU=running)"}),
        ],
    },
    "waitq": {
        "module": "lustre_waitq",
        "description": "Find D-state tasks blocked in Lustre code",
        "detail": (
            "Identifies tasks in uninterruptible sleep with Lustre\n"
            "frames in their stack traces. Groups by wait point and\n"
            "reports count + sample stacks."
        ),
        "extra_args": [],
    },
    "hashes": {
        "module": "dump_lustre_hashes",
        "description": "Summarize Lustre hash tables (cfs_hash + rhashtable)",
        "detail": (
            "Displays counts, bucket config, and load factors for\n"
            "all Lustre hash tables — global, per-OBD, LDLM namespace,\n"
            "and lu_site hashes."
        ),
        "extra_args": [],
    },
    "dk": {
        "module": "dk",
        "description": "Dump and sort Lustre debug kernel logs",
        "detail": (
            "Reads cfs_trace_data arrays from the vmcore, walks trace\n"
            "pages, parses ptldebug_headers, and outputs sorted dk log.\n"
            "Use -o to write to a file."
        ),
        "extra_args": [
            (["-o", "--output"], {"default": None,
                                  "help": "Write dk log to file"}),
        ],
    },
    "osc": {
        "module": "osc_stats",
        "description": "OSC grant, dirty pages, and extent stats per OST",
        "detail": (
            "Shows grant state, dirty page count, and in-flight I/O\n"
            "for each OST connection. Essential for diagnosing grant\n"
            "exhaustion and writeback stalls."
        ),
        "extra_args": [],
    },
    "deadlock": {
        "module": "ldlm_deadlock",
        "description": "LDLM deadlock and lock contention analyzer",
        "detail": (
            "Builds a wait-for graph from LDLM lock state and detects\n"
            "cycles (deadlocks), blocking chains, and BL_AST timeouts.\n"
            "Analyses: per-resource conflicts, cross-client wait-for\n"
            "graph with cycle detection, l_blocking_lock chain tracing,\n"
            "and server-side BL_AST timeout monitoring."
        ),
        "extra_args": [
            (["--conflicts-only"], {"action": "store_true",
                                    "help": "Only per-resource conflicts"}),
            (["--graph-only"], {"action": "store_true",
                                "help": "Only wait-for graph + cycles"}),
        ],
    },
    "imports": {
        "module": "import_health",
        "description": "Import health dashboard (state, reconnects, RPCs)",
        "detail": (
            "Aggregates per-target connection health: import state,\n"
            "reconnect count, in-flight RPCs, adaptive timeouts,\n"
            "and flags. Assigns health status (healthy, degraded,\n"
            "reconnecting, disconnected, idle) and sorts worst-first."
        ),
        "extra_args": [],
    },
    "stripes": {
        "module": "stripe_layout",
        "description": "Reconstruct file/directory stripe layouts",
        "detail": (
            "Extracts LOV file and LMV directory stripe layouts from\n"
            "cached Lustre inodes. Shows composite/PFL components,\n"
            "stripe sizes, OST/MDT indices, DoM, FLR mirrors, and\n"
            "resolves paths from the dentry cache where possible."
        ),
        "extra_args": [
            (["--max-inodes"], {"type": int, "default": 10000,
                                "help": "Max inodes to scan "
                                        "(default: 10000)"}),
        ],
    },
}

# ── Helpers ──────────────────────────────────────────────────


def print_command_list():
    """Print a formatted list of all available commands."""
    print("Available commands:\n")
    max_name = max(len(n) for n in COMMANDS)
    for name, info in COMMANDS.items():
        pad = " " * (max_name - len(name) + 2)
        print(f"  {name}{pad}{info['description']}")
    print(f"\n  {'list'}{' ' * (max_name - 4 + 2)}Show this command list")
    print(f"  {'help'}{' ' * (max_name - 4 + 2)}"
          f"Show detailed help for a command")
    print(f"  {'multi'}{' ' * (max_name - 5 + 2)}"
          f"Run multiple commands in one session")
    print(f"\nUse 'lustre-drgn help <command>' for detailed help.")


def print_command_help(cmd_name):
    """Print detailed help for a specific command."""
    if cmd_name not in COMMANDS:
        print(f"Unknown command: {cmd_name}")
        print(f"Run 'lustre-drgn list' to see available commands.")
        return
    info = COMMANDS[cmd_name]
    print(f"{cmd_name} — {info['description']}\n")
    print(info["detail"])
    if info.get("extra_args"):
        print("\nCommand-specific options:")
        for names, kwargs in info["extra_args"]:
            flag = ", ".join(names)
            hlp = kwargs.get("help", "")
            print(f"  {flag:30s} {hlp}")


def import_module(name):
    """Import a script module by name (handles both package and direct)."""
    try:
        mod = __import__(f"lustre_drgn_tools.{name}", fromlist=[name])
    except ImportError:
        mod = __import__(name)
    return mod


def run_command(cmd_name, prog, args, text_mode):
    """Dispatch to the appropriate module's JSON/text function."""
    info = COMMANDS[cmd_name]
    mod = import_module(info["module"])

    # Each module exposes different function names; dispatch by command.
    if cmd_name == "triage":
        result = mod.run_triage(
            prog, verbose=getattr(args, "verbose", False))
    elif cmd_name == "analyze":
        analyses = getattr(args, "analyses", ["all"])
        result = mod.run_analyses(prog, analyses)
    elif cmd_name == "locks":
        ns_addr = getattr(args, "ns_addr", None)
        nflag = getattr(args, "nflag", False)
        if text_mode:
            mod.dump_locks_text(prog, ns_addr=ns_addr,
                                skip_resources=nflag)
            return None
        result = mod.get_locks_json(prog, ns_addr=ns_addr,
                                    skip_resources=nflag)
    elif cmd_name == "obd":
        obd_addr = getattr(args, "obd_device", None)
        if text_mode:
            mod.print_devices_text(prog, obd_addr=obd_addr)
            return None
        result = mod.get_devices_json(prog, obd_addr=obd_addr)
    elif cmd_name == "rpcs":
        oflag = getattr(args, "oflag", False)
        sflag = getattr(args, "sflag", False)
        if text_mode:
            if oflag:
                mod.dump_overview_text(prog)
            elif sflag:
                mod.dump_pcsets_text(prog)
            else:
                mod.dump_daemon_rpclists_text(prog)
            return None
        result = mod.get_rpcs_json(prog)
    elif cmd_name == "stacks":
        swapper = getattr(args, "swapper", False)
        filt = getattr(args, "filter", None)
        traces = mod.get_all_stack_traces(
            prog, include_swapper=swapper, task_filter=filt)
        if text_mode:
            mod.print_traces_text(
                traces,
                print_pid=getattr(args, "print_pid", False),
                print_ptr=getattr(args, "print_taskpntr", False),
            )
            return None
        result = mod.get_traces_json(traces)
    elif cmd_name == "waitq":
        result = mod.find_lustre_waiters(prog)
        if text_mode:
            mod.print_waiters_text(result)
            return None
    elif cmd_name == "hashes":
        if text_mode:
            mod.dump_all_text(prog)
            return None
        result = mod.dump_all_json(prog)
    elif cmd_name == "dk":
        if text_mode:
            mod.dump_dk_text(prog,
                             output_file=getattr(args, "output", None))
            return None
        result = mod.dump_dk_json(prog)
        if getattr(args, "output", None) and result:
            with open(args.output, "w") as f:
                json.dump(result, f, indent=2 if args.pretty else None)
            print(f"Wrote dk log to {args.output}", file=sys.stderr)
            return None
    elif cmd_name == "osc":
        result = mod.get_osc_stats(prog)
        if text_mode:
            mod.print_stats_text(result)
            return None
    elif cmd_name == "deadlock":
        if getattr(args, "conflicts_only", False):
            result = {
                "analysis": "ldlm_conflicts",
                "contended_resources": mod.analyze_conflicts(prog),
            }
        elif getattr(args, "graph_only", False):
            result = {
                "analysis": "ldlm_wait_for_graph",
                "wait_for_graph": mod.analyze_deadlocks(prog),
            }
        else:
            result = mod.analyze_all(prog)
        if text_mode:
            mod.print_analysis_text(result)
            return None
    elif cmd_name == "imports":
        result = mod.get_import_health(prog)
        if text_mode:
            mod.print_health_text(result)
            return None
    elif cmd_name == "stripes":
        max_inodes = getattr(args, "max_inodes", 10000)
        result = mod.get_stripe_layouts(prog, max_inodes=max_inodes)
        if text_mode:
            mod.print_layouts_text(result)
            return None
    else:
        print(f"Unknown command: {cmd_name}", file=sys.stderr)
        return None

    return result


# ── Main ─────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        prog="lustre-drgn",
        description="Unified entry point for Lustre drgn vmcore analysis.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            commands:
              list              Show all available commands
              help <cmd>        Show detailed help for a command
              multi <cmds...>   Run multiple commands in one session

            examples:
              lustre-drgn --vmcore VM --vmlinux VL triage --pretty
              lustre-drgn --vmcore VM --vmlinux VL locks -n
              lustre-drgn --vmcore VM --vmlinux VL multi obd locks rpcs
              lustre-drgn --vmcore VM --vmlinux VL stacks -f UN
        """),
    )

    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {_ver}")

    # Global args (shared across all commands)
    parser.add_argument("--vmcore",
                        help="Path to vmcore file")
    parser.add_argument("--vmlinux",
                        help="Path to vmlinux")
    parser.add_argument("--mod-dir", default=None,
                        help="Directory with Lustre .ko files")
    parser.add_argument("--debug-dir", default=None,
                        help="Directory with Lustre .debug files")
    parser.add_argument("--pretty", action="store_true",
                        help="Pretty-print JSON output")
    parser.add_argument("--text", action="store_true",
                        help="Text output instead of JSON")

    # Subcommand
    parser.add_argument("command",
                        help="Command to run (or 'list', 'help', 'multi')")

    # Remaining args passed to the command
    parser.add_argument("rest", nargs=argparse.REMAINDER,
                        help=argparse.SUPPRESS)

    args = parser.parse_args()
    cmd = args.command

    # Handle meta-commands that don't need a vmcore
    if cmd == "list":
        print_command_list()
        return

    if cmd == "help":
        if args.rest:
            print_command_help(args.rest[0])
        else:
            parser.print_help()
        return

    # Validate vmcore/vmlinux for real commands
    if cmd in COMMANDS or cmd == "multi":
        if not args.vmcore or not args.vmlinux:
            parser.error("--vmcore and --vmlinux are required")

    if cmd == "multi":
        cmds_to_run = args.rest
        if not cmds_to_run:
            print("Usage: lustre-drgn ... multi <cmd1> <cmd2> ...",
                  file=sys.stderr)
            return
        bad = [c for c in cmds_to_run if c not in COMMANDS]
        if bad:
            print(f"Unknown commands: {', '.join(bad)}", file=sys.stderr)
            print_command_list()
            return

        from lustre_analyze import load_program

        prog = load_program(args.vmcore, args.vmlinux,
                            args.mod_dir, args.debug_dir)

        combined = {}
        for c in cmds_to_run:
            result = run_command(c, prog, args, args.text)
            if result is not None:
                combined[c] = result

        if combined:
            indent = 2 if args.pretty else None
            print(json.dumps(combined, indent=indent, default=str))
        return

    if cmd not in COMMANDS:
        print(f"Unknown command: {cmd}")
        print_command_list()
        sys.exit(1)

    # Parse command-specific args
    cmd_parser = argparse.ArgumentParser(
        prog=f"lustre-drgn {cmd}",
        description=COMMANDS[cmd]["description"],
    )
    for names, kwargs in COMMANDS[cmd].get("extra_args", []):
        cmd_parser.add_argument(*names, **kwargs)
    cmd_args = cmd_parser.parse_args(args.rest)

    # Merge command-specific args into the main namespace
    for k, v in vars(cmd_args).items():
        setattr(args, k, v)

    # Set LUSTRE_DRGN_PRETTY for helpers that check the env var
    import os
    if args.pretty:
        os.environ["LUSTRE_DRGN_PRETTY"] = "1"

    from lustre_analyze import load_program

    prog = load_program(args.vmcore, args.vmlinux,
                        args.mod_dir, args.debug_dir)

    result = run_command(cmd, prog, args, args.text)
    if result is not None:
        indent = 2 if args.pretty else None
        print(json.dumps(result, indent=indent, default=str))


if __name__ == "__main__":
    main()
