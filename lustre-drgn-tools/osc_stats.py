#!/usr/bin/env python3
"""OSC client statistics — grant, dirty pages, and extent state per OST.

Shows the OSC grant state, dirty page count, and in-flight I/O
for each OST connection. Essential for diagnosing grant exhaustion,
write stalls, and I/O hangs.

Usage:
    python3 osc_stats.py --vmcore <path> --vmlinux <path> \
        --mod-dir <ko_dir> [--debug-dir <debug_dir>] [--pretty]
"""

import argparse
import json
import os
import sys

import drgn
from drgn.helpers.linux.list import list_for_each_entry

try:
    from . import lustre_helpers as lh
except ImportError:
    import lustre_helpers as lh


def _obj_addr(obj):
    try:
        return obj.address_of_().value_()
    except ValueError:
        return obj.value_()


def get_osc_stats(prog):
    """Get OSC grant and dirty stats for all OST devices."""
    results = []

    for idx, obd in lh.get_obd_devices(prog):
        try:
            name = lh.obd_name(obd)
            if "-osc-" not in name:
                continue

            # Navigate to osc_device -> client_obd
            # obd->obd_lu_dev->ld_type should be osc
            cli = obd.u.cli

            granted = cli.cl_avail_grant.value_()
            dirty_grant = cli.cl_dirty_grant.value_()
            dirty_pages = cli.cl_dirty_pages.value_()
            lost_grant = cli.cl_lost_grant.value_()

            try:
                max_pages = cli.cl_max_pages_per_rpc.value_()
            except (AttributeError, drgn.FaultError):
                max_pages = -1

            try:
                max_rpcs = cli.cl_max_rpcs_in_flight.value_()
            except (AttributeError, drgn.FaultError):
                max_rpcs = -1

            # Get import state
            imp_state = "?"
            try:
                imp = obd.u.cli.cl_import[0]
                imp_state_val = imp.imp_state.value_()
                imp_state = lh.imp_state2str(imp_state_val)
            except (drgn.FaultError, AttributeError):
                pass

            # Grant sanity checks
            warnings = []
            if granted < 0:
                warnings.append("negative avail_grant")
            if lost_grant != 0:
                warnings.append(f"lost_grant={lost_grant}")
            if dirty_pages > 0 and dirty_grant == 0:
                warnings.append("dirty pages but no dirty grant")
            if dirty_grant < 0:
                warnings.append("negative dirty_grant")

            entry = {
                "name": name,
                "avail_grant": granted,
                "dirty_grant": dirty_grant,
                "dirty_pages": dirty_pages,
                "lost_grant": lost_grant,
                "max_pages_per_rpc": max_pages,
                "max_rpcs_in_flight": max_rpcs,
                "import_state": imp_state,
            }
            if warnings:
                entry["warnings"] = warnings
            results.append(entry)

        except (drgn.FaultError, drgn.ObjectAbsentError, AttributeError):
            continue

    sorted_devs = sorted(results, key=lambda x: x["name"])
    warn_count = sum(1 for d in sorted_devs if d.get("warnings"))
    result = {
        "analysis": "osc_stats",
        "count": len(sorted_devs),
        "devices": sorted_devs,
    }
    if warn_count:
        result["devices_with_warnings"] = warn_count
    return result


def print_stats_text(result):
    """Print OSC stats in text format."""
    if "error" in result:
        print(f"Error: {result['error']}")
        return

    print(f"{'OSC Device':<45s} {'State':<8s} {'AvailGrant':>12s} "
          f"{'DirtyGrant':>12s} {'DirtyPg':>8s} {'LostGrant':>12s}")
    print("=" * 105)

    for dev in result["devices"]:
        warn_flag = " !" if dev.get("warnings") else ""
        print(f"{dev['name']:<45s} {dev['import_state']:<8s} "
              f"{dev['avail_grant']:>12d} {dev['dirty_grant']:>12d} "
              f"{dev['dirty_pages']:>8d} {dev['lost_grant']:>12d}"
              f"{warn_flag}")

    warn_count = result.get("devices_with_warnings", 0)
    print(f"\nTotal: {result['count']} OSC devices")
    if warn_count:
        print(f"\nWARNINGS ({warn_count} device(s)):")
        for dev in result["devices"]:
            if dev.get("warnings"):
                print(f"  {dev['name']}: {'; '.join(dev['warnings'])}")


def main():
    try:
        from .lustre_analyze import load_program
    except ImportError:
        from lustre_analyze import load_program

    parser = argparse.ArgumentParser(
        description="Dump OSC grant and dirty page statistics.",
    )
    parser.add_argument("--vmcore", required=True)
    parser.add_argument("--vmlinux", required=True)
    parser.add_argument("--mod-dir", default=None)
    parser.add_argument("--debug-dir", default=None)
    parser.add_argument("--text", action="store_true", help="Text output (default is JSON)")
    parser.add_argument("--pretty", action="store_true",
                        help="Pretty-print JSON (also set LUSTRE_DRGN_PRETTY=1)")
    args = parser.parse_args()

    prog = load_program(args.vmcore, args.vmlinux, args.mod_dir, args.debug_dir)
    result = get_osc_stats(prog)

    if args.text:
        print_stats_text(result)
    else:
        lh.json_output(result, args)


if __name__ == "__main__":
    main()
