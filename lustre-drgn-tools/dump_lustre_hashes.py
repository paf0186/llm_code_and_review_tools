#!/usr/bin/env python3
"""Port of epython cfs_hashes.py to drgn, extended with rhashtable support.

Displays summary information about Lustre hash tables — both cfs_hash
and kernel rhashtable types. Shows counts, bucket configuration, theta
values, and flags for hash tables found in OBD devices, LDLM namespaces,
lu_sites, and globals.

Original: contrib/debug_tools/epython_scripts/cfs_hashes.py
Authors: Ann Koehler (Cray Inc.), ported/extended to drgn by Claude.
"""

import argparse
import json
import sys

import drgn
from drgn.helpers.linux.list import list_for_each_entry

try:
    from . import lustre_helpers as lh
except ImportError:
    import lustre_helpers as lh


CFS_HASH_THETA_BITS = 10


def _obj_addr(obj):
    """Get address of a drgn Object, whether it's a pointer or by-value."""
    try:
        return obj.address_of_().value_()
    except ValueError:
        return obj.value_()


# ── cfs_hash helpers ──────────────────────────────────────────


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


# ── rhashtable helpers ────────────────────────────────────────


def get_rhashtable_summary(name, rht):
    """Get summary info for a kernel rhashtable."""
    try:
        nelems = rht.nelems.counter.value_()
        key_len = rht.key_len.value_()
        max_elems = rht.max_elems.value_()
        addr = _obj_addr(rht)

        # Get bucket table info
        tbl_ptr = rht.tbl.value_()
        nbuckets = 0
        if tbl_ptr != 0:
            tbl = rht.tbl[0]
            nbuckets = tbl.size.value_()

        return {
            "name": name,
            "type": "rhashtable",
            "address": f"0x{addr:x}",
            "nelems": nelems,
            "key_len": key_len,
            "max_elems": max_elems,
            "nbuckets": nbuckets,
        }
    except (drgn.FaultError, drgn.ObjectAbsentError, AttributeError) as e:
        return {"name": name, "type": "rhashtable", "error": str(e)}


def print_rhashtable_text(name, rht):
    """Print one rhashtable summary line."""
    try:
        nelems = rht.nelems.counter.value_()
        key_len = rht.key_len.value_()
        max_elems = rht.max_elems.value_()
        addr = _obj_addr(rht)

        tbl_ptr = rht.tbl.value_()
        nbuckets = 0
        if tbl_ptr != 0:
            nbuckets = rht.tbl[0].size.value_()

        print(f"{name:<15s} 0x{addr:<17x} [rhashtable] "
              f"nelems={nelems} nbuckets={nbuckets} "
              f"key_len={key_len} max_elems={max_elems}")
    except (drgn.FaultError, drgn.ObjectAbsentError, AttributeError) as e:
        print(f"{name:<15s} [rhashtable] <error: {e}>")


# ── cfs_hash display ─────────────────────────────────────────


def print_hash_labels():
    """Print column header for cfs_hash summary."""
    print(
        f"{'name':<15s} {'cfs_hash':<17s}\t {'cnt':<5s} {'rhcnt':<5s} "
        f"{'xtr':<5s} {'cur':<5s} {'min':<5s} {'max':<5s} {'rhash':<5s} "
        f"{'bkt':<5s} {'nbkt':<5s} {'nhlst':<5s} {'flags':<5s} "
        f"{'theta':<11s} {'minT':<11s} {'maxT':<11s}"
    )


def print_hash_summary_text(prog, name, hsh_ptr):
    """Print one cfs_hash summary line."""
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


def _is_rhashtable(obj):
    """Check if a drgn Object is an rhashtable rather than cfs_hash."""
    type_name = str(obj.type_).split("{")[0].strip()
    return "rhashtable" in type_name


def print_hash_auto(prog, name, obj):
    """Auto-detect hash type and print appropriate summary."""
    if _is_rhashtable(obj):
        print_rhashtable_text(name, obj)
    else:
        print_hash_summary_text(prog, name, obj.address_of_())


# ── dump functions ────────────────────────────────────────────


def dump_global_hashes(prog):
    """Print global hash tables."""
    print("Global hash tables:")
    print_hash_labels()

    for sym_name in ["conn_hash", "jobid_hash", "cl_env_hash"]:
        try:
            obj = prog[sym_name]
            if _is_rhashtable(obj):
                print_rhashtable_text(sym_name, obj)
            else:
                print_hash_summary_text(prog, sym_name, obj.address_of_())
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

        for field_name, label in [
            ("obd_uuid_hash", "uuid"),
            ("obd_nid_hash", "nid"),
            ("obd_nid_stats_hash", "nid_stats"),
        ]:
            try:
                field = getattr(obd, field_name)
                if _is_rhashtable(field):
                    print_rhashtable_text(label, field)
                else:
                    print_hash_summary_text(prog, label, field.address_of_())
            except (drgn.FaultError, AttributeError):
                pass

        if "clilov" in name:
            try:
                print_hash_summary_text(prog, "lov_pools", obd.u.lov.lov_pools_hash_body.address_of_())
            except (drgn.FaultError, AttributeError):
                pass
        elif "clilmv" not in name:
            try:
                for i in range(2):
                    qh = obd.u.cli.cl_quota_hash[i]
                    if _is_rhashtable(qh):
                        print_rhashtable_text(f"cl_quota{i}", qh)
                    else:
                        print_hash_summary_text(prog, f"cl_quota{i}", qh.address_of_())
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
                rs_hash = ns.ns_rs_hash
                if _is_rhashtable(rs_hash):
                    print_rhashtable_text(name, rs_hash)
                else:
                    print_hash_summary_text(prog, name, rs_hash.address_of_())
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
            ls_obj = site.ls_obj_hash
            if _is_rhashtable(ls_obj):
                print_rhashtable_text("lu_site", ls_obj)
            else:
                print_hash_summary_text(prog, "lu_site", ls_obj.address_of_())
        except (drgn.FaultError, AttributeError):
            continue
    print()


def dump_all_text(prog):
    """Dump all hash table summaries in text format."""
    dump_global_hashes(prog)
    dump_lu_sites_hashes(prog)
    dump_obd_hashes(prog)
    dump_ldlm_ns_hashes(prog)


# ── JSON output helpers ──────────────────────────────────────


def _cfs_hash_to_dict(prog, name, hsh_ptr):
    """Return a dict summarizing one cfs_hash, or None on error."""
    if hsh_ptr.value_() == 0:
        return {"name": name, "type": "cfs_hash", "error": "NULL"}

    try:
        hsh = hsh_ptr[0]
        cur_theta = cfs_hash_cur_theta(hsh)
        return {
            "name": name,
            "type": "cfs_hash",
            "address": f"0x{hsh_ptr.value_():x}",
            "count": hsh.hs_count.counter.value_(),
            "cur_bits": hsh.hs_cur_bits.value_(),
            "min_bits": hsh.hs_min_bits.value_(),
            "max_bits": hsh.hs_max_bits.value_(),
            "bkt_cnt": lh.cfs_hash_nbkt(hsh),
            "flags": f"0x{hsh.hs_flags.value_():x}",
            "theta": cfs_hash_format_theta(cur_theta),
            "min_theta": cfs_hash_format_theta(
                hsh.hs_min_theta.value_()),
            "max_theta": cfs_hash_format_theta(
                hsh.hs_max_theta.value_()),
        }
    except (drgn.FaultError, drgn.ObjectAbsentError,
            AttributeError) as e:
        return {"name": name, "type": "cfs_hash",
                "address": f"0x{hsh_ptr.value_():x}",
                "error": str(e)}


def _hash_to_dict(prog, name, obj):
    """Auto-detect hash type and return a summary dict."""
    if _is_rhashtable(obj):
        return get_rhashtable_summary(name, obj)
    return _cfs_hash_to_dict(prog, name, obj.address_of_())


def _collect_global_hashes(prog):
    """Return list of dicts for global hash tables."""
    results = []
    for sym_name in ["conn_hash", "jobid_hash", "cl_env_hash"]:
        try:
            obj = prog[sym_name]
            results.append(_hash_to_dict(prog, sym_name, obj))
        except (KeyError, LookupError):
            pass
    return results


def _collect_obd_hashes(prog):
    """Return list of per-OBD hash table dicts."""
    results = []
    for idx, obd in lh.get_obd_devices(prog):
        name = lh.obd_name(obd)
        addr = obd.address_of_().value_()
        entry = {
            "obd_device": f"0x{addr:x}",
            "name": name,
            "hashes": [],
        }

        for field_name, label in [
            ("obd_uuid_hash", "uuid"),
            ("obd_nid_hash", "nid"),
            ("obd_nid_stats_hash", "nid_stats"),
        ]:
            try:
                field = getattr(obd, field_name)
                entry["hashes"].append(
                    _hash_to_dict(prog, label, field))
            except (drgn.FaultError, AttributeError):
                pass

        if "clilov" in name:
            try:
                entry["hashes"].append(_cfs_hash_to_dict(
                    prog, "lov_pools",
                    obd.u.lov.lov_pools_hash_body.address_of_()))
            except (drgn.FaultError, AttributeError):
                pass
        elif "clilmv" not in name:
            try:
                for i in range(2):
                    qh = obd.u.cli.cl_quota_hash[i]
                    entry["hashes"].append(
                        _hash_to_dict(prog, f"cl_quota{i}", qh))
            except (drgn.FaultError, AttributeError):
                pass

        results.append(entry)
    return results


def _collect_ldlm_ns_hashes(prog):
    """Return list of LDLM namespace hash dicts."""
    ns_lists = [
        ("ldlm_cli_active_namespace_list", "client_active"),
        ("ldlm_cli_inactive_namespace_list", "client_inactive"),
        ("ldlm_srv_namespace_list", "server"),
    ]
    results = []
    for ns_sym, label in ns_lists:
        try:
            ns_list = prog[ns_sym]
        except (KeyError, LookupError):
            continue

        for ns in list_for_each_entry(
            "struct ldlm_namespace",
            ns_list.address_of_(), "ns_list_chain"
        ):
            try:
                ns_name = (lh.obd_name(ns.ns_obd[0])[:20]
                           if ns.ns_obd.value_() != 0 else "?")
                rs_hash = ns.ns_rs_hash
                d = _hash_to_dict(prog, ns_name, rs_hash)
                d["ns_type"] = label
                results.append(d)
            except (drgn.FaultError, AttributeError):
                continue
    return results


def _collect_lu_sites_hashes(prog):
    """Return list of lu_site hash dicts."""
    results = []
    try:
        lu_sites = prog["lu_sites"]
    except (KeyError, LookupError):
        return results

    for site in list_for_each_entry(
        "struct lu_site", lu_sites.address_of_(), "ls_linkage"
    ):
        try:
            ls_obj = site.ls_obj_hash
            results.append(_hash_to_dict(prog, "lu_site", ls_obj))
        except (drgn.FaultError, AttributeError):
            continue
    return results


def dump_all_json(prog):
    """Return a structured dict with all hash table summaries."""
    return {
        "global_hashes": _collect_global_hashes(prog),
        "lu_site_hashes": _collect_lu_sites_hashes(prog),
        "obd_hashes": _collect_obd_hashes(prog),
        "ldlm_namespace_hashes": _collect_ldlm_ns_hashes(prog),
    }


def main():
    try:
        from .lustre_analyze import load_program
    except ImportError:
        from lustre_analyze import load_program

    parser = argparse.ArgumentParser(
        description="Displays summary of Lustre hash tables (cfs_hash and rhashtable)",
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

    if args.text:
        dump_all_text(prog)
    else:
        result = dump_all_json(prog)
        lh.json_output(result, args)


if __name__ == "__main__":
    main()
