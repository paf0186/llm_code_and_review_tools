#!/usr/bin/env python3
"""Port of epython ldlm_dumplocks.py to drgn.

Dumps lists of granted and waiting LDLM locks for each namespace.

Original: contrib/debug_tools/epython_scripts/ldlm_dumplocks.py
Authors: Ann Koehler (Cray Inc.), ported to drgn by Claude.
"""

import argparse
import json
import sys

import drgn
from drgn.helpers.linux.list import (
    list_for_each_entry,
    list_empty,
)

try:
    from . import lustre_helpers as lh
except ImportError:
    import lustre_helpers as lh


# Lock types
LDLM_PLAIN = 10
LDLM_EXTENT = 11
LDLM_FLOCK = 12
LDLM_IBITS = 13


def dump_lock_text(lock, pos, lstname):
    """Print one LDLM lock in text format."""
    if lock.value_() == 0:
        print("   NULL LDLM lock")
        return

    try:
        # Get refcount — different field names across versions
        try:
            refcounter = lock.l_handle.h_ref.refs.counter.value_()
        except AttributeError:
            try:
                refcounter = lock.l_refc.counter.value_()
            except AttributeError:
                refcounter = -1

        cookie = lock.l_handle.h_cookie.value_()
        pid = lock.l_pid.value_()
        addr = _obj_addr(lock)

        print(f"   -- Lock: (ldlm_lock) 0x{addr:x}/0x{cookie:x} "
              f"(rc: {refcounter}) (pos: {pos}/{lstname}) (pid: {pid})")

        # Node info — export or import
        try:
            if lock.l_export.value_() != 0 and lock.l_export[0].exp_connection.value_() != 0:
                nid = lock.l_export[0].exp_connection[0].c_peer.nid.value_()
                remote = lock.l_remote_handle.cookie.value_()
                print(f"       Node: NID {lh.nid2str(nid)} (remote: 0x{remote:x}) export")
            elif lock.l_conn_export.value_() != 0:
                obd = lock.l_conn_export[0].exp_obd
                imp = obd.u.cli.cl_import[0]
                nid = imp.imp_connection[0].c_peer.nid.value_()
                remote = lock.l_remote_handle.cookie.value_()
                print(f"       Node: NID {lh.nid2str(nid)} (remote: 0x{remote:x}) import")
            else:
                print("       Node: local")
        except (drgn.FaultError, AttributeError):
            print("       Node: <unavailable>")

        # Resource info
        try:
            res = lock.l_resource[0]
            res_addr = lock.l_resource.value_()
            n = res.lr_name.name
            print(f"       Resource: 0x{res_addr:x} "
                  f"[0x{n[0].value_():x}:0x{n[1].value_():x}:"
                  f"0x{n[2].value_():x}].{n[3].value_():x}")
        except (drgn.FaultError, AttributeError):
            pass

        # Mode and flags
        req_mode = lock.l_req_mode.value_()
        granted_mode = lock.l_granted_mode.value_()
        readers = lock.l_readers.value_()
        writers = lock.l_writers.value_()
        flags = lock.l_flags.value_()
        print(f"       Req mode: {lh.lockmode2str(req_mode)}, "
              f"grant mode: {lh.lockmode2str(granted_mode)}, "
              f"rc: {refcounter}, read: {readers}, write: {writers} "
              f"flags: 0x{flags:x}")

        # Type-specific info
        try:
            lr_type = lock.l_resource[0].lr_type.value_()
            if lr_type == LDLM_EXTENT:
                ext = lock.l_policy_data.l_extent
                req_ext = lock.l_req_extent
                print(f"       Extent: {ext.start.value_()} -> {ext.end.value_()} "
                      f"(req {req_ext.start.value_()}-{req_ext.end.value_()})")
            elif lr_type == LDLM_FLOCK:
                fl = lock.l_policy_data.l_flock
                print(f"       Pid: {fl.pid.value_()} "
                      f"Flock: 0x{fl.start.value_():x} -> 0x{fl.end.value_():x}")
            elif lr_type == LDLM_IBITS:
                bits = lock.l_policy_data.l_inodebits.bits.value_()
                print(f"       Bits: 0x{bits:x}")
        except (drgn.FaultError, AttributeError):
            pass

    except (drgn.FaultError, drgn.ObjectAbsentError):
        try:
            addr = _obj_addr(lock)
        except Exception:
            addr = 0
        print(f"   Corrupted lock 0x{addr:x}")


def dump_resource_text(prog, res):
    """Print one LDLM resource with its granted and waiting locks."""
    try:
        n = res.lr_name.name
        refcount = res.lr_refcount.counter.value_()
        res_addr = _obj_addr(res)
        print(f"-- Resource: (ldlm_resource) 0x{res_addr:x} "
              f"[0x{n[0].value_():x}:0x{n[1].value_():x}:"
              f"0x{n[2].value_():x}].{n[3].value_():x} (rc: {refcount})")
    except (drgn.FaultError, drgn.ObjectAbsentError):
        print(f"-- Corrupted resource 0x{_obj_addr(res):x}")
        return

    # Granted locks
    try:
        if not list_empty(res.lr_granted.address_of_()):
            print("   Granted locks: ")
            pos = 0
            for lock in list_for_each_entry(
                "struct ldlm_lock", res.lr_granted.address_of_(), "l_res_link"
            ):
                pos += 1
                dump_lock_text(lock, pos, "grnt")
    except (drgn.FaultError, drgn.ObjectAbsentError):
        pass

    # Waiting locks
    try:
        if not list_empty(res.lr_waiting.address_of_()):
            print("   Waiting locks: ")
            pos = 0
            for lock in list_for_each_entry(
                "struct ldlm_lock", res.lr_waiting.address_of_(), "l_res_link"
            ):
                pos += 1
                dump_lock_text(lock, pos, "wait")
    except (drgn.FaultError, drgn.ObjectAbsentError):
        pass


def dump_ns_resources(prog, ns, skip_resources=False):
    """Dump all resources in a namespace using cfs_hash traversal."""
    if skip_resources:
        return

    rs_hash = ns.ns_rs_hash
    lr_hash_offset = prog.type("struct ldlm_resource").member("lr_hash").offset

    for _bkt, _off, hnode in lh.cfs_hash_for_each_node(prog, rs_hash):
        res_addr = hnode.value_() - lr_hash_offset
        try:
            res = drgn.Object(prog, "struct ldlm_resource", address=res_addr)
            dump_resource_text(prog, res)
        except (drgn.FaultError, drgn.ObjectAbsentError):
            continue


def _obj_addr(obj):
    """Get address of a drgn Object, whether it's a pointer or by-value."""
    try:
        return obj.address_of_().value_()
    except ValueError:
        # Object is a pointer value (e.g., from list_for_each_entry)
        return obj.value_()


def print_namespace(ns, client_server):
    """Print namespace header."""
    name = lh.obd_name(ns.ns_obd[0]) if ns.ns_obd.value_() != 0 else "<unknown>"
    refcount = ns.ns_bref.counter.value_()
    pool_granted = ns.ns_pool.pl_granted.counter.value_()
    nr_unused = ns.ns_nr_unused.value_()
    addr = _obj_addr(ns)

    print(f"Namespace: (ldlm_namespace) 0x{addr:x}, {name}\t"
          f"(rc: {refcount}, side: {client_server})\t"
          f"poolcnt: {pool_granted} unused: {nr_unused}")


def dump_all_namespaces(prog, ns_sym_name, client_server, skip_resources=False):
    """Dump all namespaces from a namespace list symbol."""
    try:
        ns_list = prog[ns_sym_name]
    except (KeyError, LookupError):
        return

    for ns in list_for_each_entry(
        "struct ldlm_namespace", ns_list.address_of_(), "ns_list_chain"
    ):
        print_namespace(ns, client_server)
        dump_ns_resources(prog, ns, skip_resources)


def dump_locks_text(prog, ns_addr=None, skip_resources=False):
    """Dump all LDLM locks in text format."""
    if ns_addr:
        ns = drgn.Object(prog, "struct ldlm_namespace", address=ns_addr)
        print_namespace(ns, "")
        dump_ns_resources(prog, ns, skip_resources)
    else:
        dump_all_namespaces(prog, "ldlm_srv_namespace_list", "server", skip_resources)
        dump_all_namespaces(prog, "ldlm_cli_active_namespace_list", "client", skip_resources)
        dump_all_namespaces(prog, "ldlm_cli_inactive_namespace_list", "inactive", skip_resources)


def get_locks_json(prog, ns_addr=None, skip_resources=False):
    """Return LDLM lock info as structured JSON data."""
    namespaces = []

    def collect_ns(ns_sym_name, side):
        try:
            ns_list = prog[ns_sym_name]
        except (KeyError, LookupError):
            return

        for ns in list_for_each_entry(
            "struct ldlm_namespace", ns_list.address_of_(), "ns_list_chain"
        ):
            name = lh.obd_name(ns.ns_obd[0]) if ns.ns_obd.value_() != 0 else "<unknown>"
            ns_info = {
                "address": f"0x{_obj_addr(ns):x}",
                "name": name,
                "side": side,
                "refcount": ns.ns_bref.counter.value_(),
                "pool_granted": ns.ns_pool.pl_granted.counter.value_(),
                "nr_unused": ns.ns_nr_unused.value_(),
            }

            if not skip_resources:
                resources = []
                rs_hash = ns.ns_rs_hash
                lr_hash_off = prog.type("struct ldlm_resource").member("lr_hash").offset

                for _bkt, _off, hnode in lh.cfs_hash_for_each_node(prog, rs_hash):
                    res_addr = hnode.value_() - lr_hash_off
                    try:
                        res = drgn.Object(prog, "struct ldlm_resource", address=res_addr)
                        n = res.lr_name.name
                        res_info = {
                            "address": f"0x{res_addr:x}",
                            "name": [f"0x{n[i].value_():x}" for i in range(4)],
                            "refcount": res.lr_refcount.counter.value_(),
                            "granted_locks": [],
                            "waiting_locks": [],
                        }

                        # Collect granted locks
                        if not list_empty(res.lr_granted.address_of_()):
                            for lock in list_for_each_entry(
                                "struct ldlm_lock", res.lr_granted.address_of_(), "l_res_link"
                            ):
                                res_info["granted_locks"].append(
                                    _lock_to_dict(lock)
                                )

                        # Collect waiting locks
                        if not list_empty(res.lr_waiting.address_of_()):
                            for lock in list_for_each_entry(
                                "struct ldlm_lock", res.lr_waiting.address_of_(), "l_res_link"
                            ):
                                res_info["waiting_locks"].append(
                                    _lock_to_dict(lock)
                                )

                        resources.append(res_info)
                    except (drgn.FaultError, drgn.ObjectAbsentError):
                        continue

                ns_info["resources"] = resources

            namespaces.append(ns_info)

    if ns_addr:
        ns = drgn.Object(prog, "struct ldlm_namespace", address=ns_addr)
        name = lh.obd_name(ns.ns_obd[0]) if ns.ns_obd.value_() != 0 else "<unknown>"
        namespaces.append({
            "address": f"0x{ns_addr:x}",
            "name": name,
            "side": "",
        })
    else:
        collect_ns("ldlm_srv_namespace_list", "server")
        collect_ns("ldlm_cli_active_namespace_list", "client")
        collect_ns("ldlm_cli_inactive_namespace_list", "inactive")

    return {"analysis": "ldlm_locks", "namespaces": namespaces}


def _lock_to_dict(lock):
    """Convert an ldlm_lock to a JSON-friendly dict."""
    try:
        try:
            refcount = lock.l_handle.h_ref.refs.counter.value_()
        except AttributeError:
            try:
                refcount = lock.l_refc.counter.value_()
            except AttributeError:
                refcount = -1

        return {
            "address": f"0x{_obj_addr(lock):x}",
            "cookie": f"0x{lock.l_handle.h_cookie.value_():x}",
            "refcount": refcount,
            "pid": lock.l_pid.value_(),
            "req_mode": lh.lockmode2str(lock.l_req_mode.value_()),
            "granted_mode": lh.lockmode2str(lock.l_granted_mode.value_()),
            "readers": lock.l_readers.value_(),
            "writers": lock.l_writers.value_(),
            "flags": f"0x{lock.l_flags.value_():x}",
        }
    except (drgn.FaultError, drgn.ObjectAbsentError):
        return {"address": "<corrupted>"}


def main():
    try:
        from .lustre_analyze import load_program
    except ImportError:
        from lustre_analyze import load_program

    parser = argparse.ArgumentParser(
        description="Dumps lists of granted and waiting ldlm locks for each namespace.",
    )
    parser.add_argument("--vmcore", required=True)
    parser.add_argument("--vmlinux", required=True)
    parser.add_argument("--mod-dir", default=None)
    parser.add_argument("--debug-dir", default=None)
    parser.add_argument("-n", dest="nflag", action="store_true",
                        help="Print only namespace info")
    parser.add_argument("--text", action="store_true", help="Text output (default is JSON)")
    parser.add_argument("--pretty", action="store_true",
                        help="Pretty-print JSON (also set LUSTRE_DRGN_PRETTY=1)")
    parser.add_argument("ns_addr", nargs="?", default=None, type=lambda x: int(x, 0))
    args = parser.parse_args()

    prog = load_program(args.vmcore, args.vmlinux, args.mod_dir, args.debug_dir)

    if args.text:
        dump_locks_text(prog, args.ns_addr, args.nflag)
    else:
        result = get_locks_json(prog, args.ns_addr, args.nflag)
        lh.json_output(result, args)


if __name__ == "__main__":
    main()
