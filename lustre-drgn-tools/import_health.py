#!/usr/bin/env python3
"""Import health dashboard — per-target connection health from a vmcore.

Aggregates connection state, reconnect history, in-flight RPCs,
adaptive timeouts, and flags for every obd_import. Assigns a health
assessment per import and provides an aggregate summary.

Usage:
    python3 import_health.py --vmcore <path> --vmlinux <path> \
        --mod-dir <ko_dir> [--debug-dir <debug_dir>] [--text] [--pretty]
"""

import argparse
import json
import sys

import drgn

try:
    from . import lustre_helpers as lh
except ImportError:
    import lustre_helpers as lh


# Thresholds for health assessment
HIGH_CONN_CNT = 5       # more than this many reconnects => degraded
HIGH_INFLIGHT_PCT = 80  # inflight > this % of max => degraded


def _safe_int(func, default=0):
    """Call func() and return the result, or default on fault."""
    try:
        return func()
    except (drgn.FaultError, AttributeError, TypeError):
        return default


def _safe_str(func, default=""):
    """Call func() and return the result, or default on fault."""
    try:
        return func()
    except (drgn.FaultError, AttributeError, TypeError):
        return default


def _safe_bitfield(obj, field, default=0):
    """Read a bitfield member safely."""
    try:
        return int(getattr(obj, field).value_())
    except (drgn.FaultError, AttributeError, TypeError):
        return default


def _assess_health(state_str, imp_invalid, conn_cnt, inflight,
                   max_rpcs):
    """Return a health string for one import."""
    if state_str in ("EVICTED", "CLOSED"):
        return "disconnected"
    if state_str == "DISCON":
        return "disconnected"
    if state_str in ("CONNECTING", "REPLAY", "REPLAY_LOCKS",
                     "REPLAY_WAIT", "RECOVER"):
        return "reconnecting"
    if state_str == "IDLE":
        return "idle"
    if state_str == "NEW":
        return "idle"

    # state_str is FULL (or unknown)
    if imp_invalid:
        return "degraded"
    if conn_cnt > HIGH_CONN_CNT:
        return "degraded"
    if max_rpcs > 0 and inflight > 0:
        pct = (inflight * 100) / max_rpcs
        if pct >= HIGH_INFLIGHT_PCT:
            return "degraded"
    if state_str == "FULL":
        return "healthy"

    # Unknown state
    return "degraded"


HEALTH_ORDER = {
    "disconnected": 0,
    "reconnecting": 1,
    "degraded": 2,
    "idle": 3,
    "healthy": 4,
}


def _get_one_import(obd):
    """Extract health info from a single OBD device's import.

    Returns None if the device has no import.
    """
    try:
        imp_ptr = obd.u.cli.cl_import.value_()
        if imp_ptr == 0:
            return None
        imp = obd.u.cli.cl_import[0]
    except (drgn.FaultError, AttributeError):
        return None

    name = _safe_str(lambda: lh.obd_name(obd), "?")
    uuid = _safe_str(lambda: lh.obd_uuid(obd), "?")

    # Import state
    state_val = _safe_int(lambda: imp.imp_state.value_())
    state_str = lh.imp_state2str(state_val)

    # Flags (bitfields)
    imp_invalid = _safe_bitfield(imp, "imp_invalid")
    imp_deactive = _safe_bitfield(imp, "imp_deactive")
    imp_force_reconnect = _safe_bitfield(imp, "imp_force_reconnect")
    imp_force_verify = _safe_bitfield(imp, "imp_force_verify")
    imp_pingable = _safe_bitfield(imp, "imp_pingable")
    imp_connect_tried = _safe_bitfield(imp, "imp_connect_tried")

    # Connection info
    conn_cnt = _safe_int(lambda: imp.imp_conn_cnt.value_())
    generation = _safe_int(lambda: imp.imp_generation.value_())

    # In-flight
    inflight = _safe_int(lambda: imp.imp_inflight.counter.value_())
    replay_inflight = _safe_int(
        lambda: imp.imp_replay_inflight.counter.value_()
    )

    # Max RPCs — from client_obd, not from import
    max_rpcs = _safe_int(
        lambda: obd.u.cli.cl_max_rpcs_in_flight.value_()
    )

    # NID
    nid_str = "LNET_NID_ANY"
    try:
        if not imp_invalid:
            conn_ptr = imp.imp_connection.value_()
            if conn_ptr != 0:
                nid_val = imp.imp_connection[0].c_peer.nid.value_()
                nid_str = lh.nid2str(nid_val)
    except (drgn.FaultError, AttributeError):
        pass

    # Target UUID from imp_conn_current
    target_uuid = ""
    try:
        conn_cur = imp.imp_conn_current
        if conn_cur.value_() != 0:
            target_uuid = (
                conn_cur[0].oic_uuid.uuid.string_()
                .decode(errors="replace")
            )
    except (drgn.FaultError, AttributeError):
        pass

    # Adaptive timeout — network latency current value
    at_net_latency = _safe_int(
        lambda: imp.imp_at.iat_net_latency.at_current_timeout.value_()
    )

    # Service estimate timeouts for each portal
    at_service = []
    for i in range(8):  # IMP_AT_MAX_PORTALS
        portal = _safe_int(
            lambda i=i: imp.imp_at.iat_portal[i].value_()
        )
        cur_to = _safe_int(
            lambda i=i: (
                imp.imp_at
                .iat_service_estimate[i]
                .at_current_timeout.value_()
            )
        )
        if portal != 0 or cur_to != 0:
            at_service.append({"portal": portal, "timeout": cur_to})

    health = _assess_health(
        state_str, imp_invalid, conn_cnt, inflight, max_rpcs
    )

    return {
        "obd_name": name,
        "obd_uuid": uuid,
        "target_uuid": target_uuid,
        "nid": nid_str,
        "imp_state": state_str,
        "imp_invalid": imp_invalid,
        "imp_deactive": imp_deactive,
        "conn_cnt": conn_cnt,
        "generation": generation,
        "inflight": inflight,
        "replay_inflight": replay_inflight,
        "max_rpcs_in_flight": max_rpcs,
        "at_net_latency": at_net_latency,
        "at_service_estimates": at_service,
        "flags": {
            "force_reconnect": imp_force_reconnect,
            "force_verify": imp_force_verify,
            "pingable": imp_pingable,
            "connect_tried": imp_connect_tried,
        },
        "health": health,
    }


def get_import_health(prog):
    """Return import health data for all OBD devices.

    Returns a dict with analysis name, summary counts, and
    per-import details sorted worst-health-first.
    """
    imports = []

    for _idx, obd in lh.get_obd_devices(prog):
        info = _get_one_import(obd)
        if info is not None:
            imports.append(info)

    # Sort by health: worst first, then by name
    imports.sort(
        key=lambda x: (HEALTH_ORDER.get(x["health"], -1), x["obd_name"])
    )

    # Aggregate summary
    counts = {}
    for imp in imports:
        h = imp["health"]
        counts[h] = counts.get(h, 0) + 1

    return {
        "analysis": "import_health",
        "total_imports": len(imports),
        "summary": counts,
        "imports": imports,
    }


def print_health_text(result):
    """Print import health dashboard in text format."""
    if "error" in result:
        print(f"Error: {result['error']}")
        return

    total = result["total_imports"]
    summary = result["summary"]

    print("=== Import Health Dashboard ===")
    print(f"Total imports: {total}")
    print(f"  healthy:       {summary.get('healthy', 0)}")
    print(f"  degraded:      {summary.get('degraded', 0)}")
    print(f"  reconnecting:  {summary.get('reconnecting', 0)}")
    print(f"  disconnected:  {summary.get('disconnected', 0)}")
    print(f"  idle:          {summary.get('idle', 0)}")
    print()

    print(
        f"{'OBD Name':<40s} {'State':<12s} {'Health':<14s} "
        f"{'NID':<22s} {'ConnCnt':>7s} {'Inflt':>5s} "
        f"{'Max':>5s} {'ATnet':>5s}"
    )
    print("=" * 118)

    for imp in result["imports"]:
        flags = ""
        if imp["imp_invalid"]:
            flags += "I"
        if imp["imp_deactive"]:
            flags += "D"
        if imp["flags"]["force_reconnect"]:
            flags += "R"
        if imp["flags"]["force_verify"]:
            flags += "V"
        if flags:
            flags = f" [{flags}]"

        print(
            f"{imp['obd_name']:<40s} {imp['imp_state']:<12s} "
            f"{imp['health']:<14s} {imp['nid']:<22s} "
            f"{imp['conn_cnt']:>7d} {imp['inflight']:>5d} "
            f"{imp['max_rpcs_in_flight']:>5d} "
            f"{imp['at_net_latency']:>5d}{flags}"
        )

    print("=" * 118)


def main():
    try:
        from .lustre_analyze import load_program
    except ImportError:
        from lustre_analyze import load_program

    parser = argparse.ArgumentParser(
        description="Import health dashboard — connection health "
                    "from a vmcore.",
    )
    parser.add_argument("--vmcore", required=True)
    parser.add_argument("--vmlinux", required=True)
    parser.add_argument("--mod-dir", default=None)
    parser.add_argument("--debug-dir", default=None)
    parser.add_argument(
        "--text", action="store_true",
        help="Text output (default is JSON)",
    )
    parser.add_argument(
        "--pretty", action="store_true",
        help="Pretty-print JSON (also set LUSTRE_DRGN_PRETTY=1)",
    )
    args = parser.parse_args()

    prog = load_program(
        args.vmcore, args.vmlinux, args.mod_dir, args.debug_dir
    )
    result = get_import_health(prog)

    if args.text:
        print_health_text(result)
    else:
        lh.json_output(result, args)


if __name__ == "__main__":
    main()
