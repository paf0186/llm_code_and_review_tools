#!/usr/bin/env python3
"""Port of epython cfs_hashes.py to drgn.

Displays summary information about Lustre cfs_hash tables — counts,
bucket configuration, theta values, and flags for all hash tables
found in OBD devices, LDLM namespaces, lu_sites, and globals.

Original: contrib/debug_tools/epython_scripts/cfs_hashes.py
Authors: Ann Koehler (Cray Inc.), ported to drgn by Claude.
"""

import argparse
import json
import sys

import drgn
from drgn.helpers.linux.list import list_for_each_entry

from . import lustre_helpers as lh


CFS_HASH_THETA_BITS = 10


def cfs_hash_cur_theta(hsh):
    """Calculate current theta (load factor) for a cfs_hash."""
    hs_cnt = hsh.hs_count.counter.value_()
    return (hs_cnt << CFS_HASH_THETA_BITS) >> hsh.hs_cur_bits.value_()


def cfs_hash_theta_int(theta):
    return theta >> CFS_HASH_THETA_BITS


def cfs_hash_theta_frac(theta):
    frac = ((theta * 1000) >> CFS_HASH_THETA_BITS) - \
           (cfs_hash_theta_int(theta) * 1000)
    return frac


def cfs_hash_format_theta(theta):
    return f"{cfs_hash_theta_int(theta)}.{cfs_hash_theta_frac(theta)}"


def get_hash_summary(prog, name, hsh_ptr):
    """Get summary info for one cfs_hash as a dict."""
    if hsh_ptr.value_() == 0:
        return {"name": name, "address": "NULL"}

    try:
        hsh = hsh_ptr[0]
        hs_cnt = hsh.hs_count.counter.value_()
        hs_ref = hsh.hs_refcount.counter.value_()
        cur_theta = cfs_hash_cur_theta(hsh)
        nbkt = lh.cfs_hash_nbkt(hsh)
        nhlist = lh.cfs_hash_bkt_nhlist(hsh)

        return {
            "name": name,
            "address": f"0x{hsh_ptr.value_():x}",
            "count": hs_cnt,
            "rehash_count": hsh.hs_rehash_count.value_(),
            "extra_bytes": hsh.hs_extra_bytes.value_(),
            "cur_bits": hsh.hs_cur_bits.value_(),
            "min_bits": hsh.hs_min_bits.value_(),
            "max_bits": hsh.hs_max_bits.value_(),
            "rehash_bits": hsh.hs_rehash_bits.value_(),
            "bkt_bits": hsh.hs_bkt_bits.value_(),
            "nbkt": nbkt,
            "nhlist": nhlist,
            "flags": f"0x{hsh.hs_flags.value_():x}",
            "theta": cfs_hash_format_theta(cur_theta),
            "min_theta": cfs_hash_format_theta(hsh.hs_min_theta.value_()),
            "max_theta": cfs_hash_format_theta(hsh.hs_max_theta.value_()),
        }
    except (drgn.FaultError, drgn.ObjectAbsentError, AttributeError):
        return {"name": name, "address": f"0x{hsh_ptr.value_():x}", "error": "fault"}


def print_hash_labels():
    """Print column header for hash summary."""
    print(
        f"{'name':<15s} {'cfs_hash':<17s}\t {'cnt':<5s} {'rhcnt':<5s} "
        f"{'xtr':<5s} {'cur':<5s} {'min':<5s} {'max':<5s} {'rhash':<5s} "
        f"{'bkt':<5s} {'nbkt':<5s} {'nhlst':<5s} {'flags':<5s} "
        f"{'theta':<11s} {'minT':<11s} {'maxT':<11s}"
    )


def print_hash_summary_text(prog, name, hsh_ptr):
    """Print one hash summary line."""
    if hsh_ptr.value_() == 0:
        print(f"{name:<15s} {'NULL':<17s}")
        return

    try:
        hsh = hsh_ptr[0]
        hs_cnt = hsh.hs_count.counter.value_()
        cur_theta = cfs_hash_cur_theta(hsh)
        nbkt = lh.cfs_hash_nbkt(hsh)
        nhlist = lh.cfs_hash_bkt_nhlist(hsh)

        print(
            f"{name:<15s} {hsh_ptr.value_():<17x}\t "
            f"{hs_cnt:<5d} {hsh.hs_rehash_count.value_():<5d} "
            f"{hsh.hs_extra_bytes.value_():<5d} {hsh.hs_cur_bits.value_():<5d} "
            f"{hsh.hs_min_bits.value_():<5d} {hsh.hs_max_bits.value_():<5d} "
            f"{hsh.hs_rehash_bits.value_():<5d} {hsh.hs_bkt_bits.value_():<5d} "
            f"{nbkt:<5d} {nhlist:<5d} {hsh.hs_flags.value_():<5x} "
            f"{cfs_hash_format_theta(cur_theta):<11s} "
            f"{cfs_hash_format_theta(hsh.hs_min_theta.value_()):<11s} "
            f"{cfs_hash_format_theta(hsh.hs_max_theta.value_()):<11s}"
        )
    except (drgn.FaultError, drgn.ObjectAbsentError, AttributeError) as e:
        print(f"{name:<15s} 0x{hsh_ptr.value_():<17x} <error: {e}>")


def dump_global_hashes(prog):
    """Print global hash tables."""
    print_hash_labels()
    try:
        print_hash_summary_text(prog, "conn_hash", prog["conn_hash"].address_of_())
    except (KeyError, LookupError):
        pass
    try:
        print_hash_summary_text(prog, "jobid_hash", prog["jobid_hash"].address_of_())
    except (KeyError, LookupError):
        pass
    try:
        print_hash_summary_text(prog, "cl_env_hash", prog["cl_env_hash"].address_of_())
    except (KeyError, LookupError):
        pass
    print()


def dump_obd_hashes(prog):
    """Print hash tables for each OBD device."""
    for idx, obd in lh.get_obd_devices(prog):
        name = lh.obd_name(obd)
        addr = obd.address_of_().value_()
        print(f"obd_device 0x{addr:<17x} {name}")
        print_hash_labels()

        try:
            print_hash_summary_text(prog, "uuid", obd.obd_uuid_hash.address_of_())
        except (drgn.FaultError, AttributeError):
            pass
        try:
            print_hash_summary_text(prog, "nid", obd.obd_nid_hash.address_of_())
        except (drgn.FaultError, AttributeError):
            pass
        try:
            print_hash_summary_text(prog, "nid_stats", obd.obd_nid_stats_hash.address_of_())
        except (drgn.FaultError, AttributeError):
            pass

        if "clilov" in name:
            try:
                print_hash_summary_text(prog, "lov_pools", obd.u.lov.lov_pools_hash_body.address_of_())
            except (drgn.FaultError, AttributeError):
                pass
        elif "clilmv" not in name:
            try:
                print_hash_summary_text(prog, "cl_quota0", obd.u.cli.cl_quota_hash[0].address_of_())
                print_hash_summary_text(prog, "cl_quota1", obd.u.cli.cl_quota_hash[1].address_of_())
            except (drgn.FaultError, AttributeError):
                pass

        print()


def dump_ldlm_ns_hashes(prog):
    """Print hash tables for LDLM namespaces."""
    ns_lists = [
        ("ldlm_cli_active_namespace_list", "Client"),
        ("ldlm_cli_inactive_namespace_list", "Inactive"),
        ("ldlm_srv_namespace_list", "Server"),
    ]

    for ns_sym, label in ns_lists:
        try:
            ns_list = prog[ns_sym]
        except (KeyError, LookupError):
            continue

        print(f"\n{label} namespaces-resources")
        print_hash_labels()

        for ns in list_for_each_entry(
            "struct ldlm_namespace", ns_list.address_of_(), "ns_list_chain"
        ):
            try:
                name = lh.obd_name(ns.ns_obd[0])[:20] if ns.ns_obd.value_() != 0 else "?"
                print_hash_summary_text(prog, name, ns.ns_rs_hash.address_of_())
            except (drgn.FaultError, AttributeError):
                continue


def dump_lu_sites_hashes(prog):
    """Print hash tables for lu_sites."""
    try:
        lu_sites = prog["lu_sites"]
    except (KeyError, LookupError):
        return

    print_hash_labels()
    for site in list_for_each_entry(
        "struct lu_site", lu_sites.address_of_(), "ls_linkage"
    ):
        try:
            print_hash_summary_text(prog, "lu_site", site.ls_obj_hash.address_of_())
        except (drgn.FaultError, AttributeError):
            continue
    print()


def dump_all_text(prog):
    """Dump all hash table summaries in text format."""
    dump_global_hashes(prog)
    dump_lu_sites_hashes(prog)
    dump_obd_hashes(prog)
    dump_ldlm_ns_hashes(prog)


def main():
    from .lustre_analyze import load_program

    parser = argparse.ArgumentParser(
        description="Displays summary of Lustre cfs_hash tables",
    )
    parser.add_argument("--vmcore", required=True)
    parser.add_argument("--vmlinux", required=True)
    parser.add_argument("--mod-dir", default=None)
    parser.add_argument("--debug-dir", default=None)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    prog = load_program(args.vmcore, args.vmlinux, args.mod_dir, args.debug_dir)
    dump_all_text(prog)


if __name__ == "__main__":
    main()
