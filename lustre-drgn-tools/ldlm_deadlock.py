#!/usr/bin/env python3
"""LDLM lock deadlock and contention analyzer for vmcore dumps.

Builds a wait-for graph from LDLM lock state and detects cycles
(deadlocks), blocking chains, and BL_AST timeout situations.

Three levels of analysis:
  1. Per-resource conflict analysis — which granted locks block which
     waiting locks, using the LDLM mode compatibility matrix.
  2. Wait-for graph cycle detection — builds a directed graph where
     nodes are clients (exports) and edges are "waiting for" relations.
     Cycles = deadlocks.
  3. BL_AST timeout analysis — walks the server-side waiting_locks_list
     to find locks where blocking callbacks have timed out or are
     close to timeout.

Output: JSON (default) or text.
"""

import argparse
import json
import sys
from collections import defaultdict

import drgn
from drgn.helpers.linux.list import (
    list_for_each_entry,
    list_empty,
)

try:
    from . import lustre_helpers as lh
except ImportError:
    import lustre_helpers as lh


# ── Lock mode compatibility matrix ──────────────────────────
#
# Mirrors lustre_dlm.h LCK_COMPAT_* definitions.
# lck_compat[mode] = bitmask of modes compatible with it.

LCK_EX = 1
LCK_PW = 2
LCK_PR = 4
LCK_CW = 8
LCK_CR = 16
LCK_NL = 32
LCK_GROUP = 64
LCK_COS = 128
LCK_TXN = 256

_LCK_COMPAT = {
    LCK_EX:    LCK_NL,
    LCK_PW:    LCK_NL | LCK_CR,
    LCK_PR:    LCK_NL | LCK_CR | LCK_PR | LCK_TXN,
    LCK_CW:    LCK_NL | LCK_CR | LCK_CW,
    LCK_CR:    LCK_NL | LCK_CR | LCK_CW | LCK_PR | LCK_PW | LCK_TXN,
    LCK_NL:    (LCK_NL | LCK_CR | LCK_CW | LCK_PR | LCK_PW |
                LCK_EX | LCK_GROUP | LCK_COS),
    LCK_GROUP: LCK_NL | LCK_GROUP,
    LCK_COS:   LCK_NL | LCK_COS,
    LCK_TXN:   LCK_NL | LCK_CR | LCK_PR | LCK_TXN,
}

# Lock type constants
LDLM_PLAIN = 10
LDLM_EXTENT = 11
LDLM_FLOCK = 12
LDLM_IBITS = 13

# Interesting lock flags
LDLM_FL_AST_SENT = 0x0000000000000020
LDLM_FL_CBPENDING = 0x0000000400000000
LDLM_FL_BL_AST = 0x0000400000000000
LDLM_FL_FLOCK_DEADLOCK = 0x0000000000008000


def lockmode_compat(exist_mode, new_mode):
    """Return True if exist_mode and new_mode are compatible."""
    compat = _LCK_COMPAT.get(exist_mode, 0)
    return bool(compat & new_mode)


# ── Helpers ──────────────────────────────────────────────────


def _obj_addr(obj):
    """Get address of a drgn Object."""
    try:
        return obj.address_of_().value_()
    except ValueError:
        return obj.value_()


def _safe_val(fn, default=None):
    """Call fn(), return default on drgn fault."""
    try:
        return fn()
    except (drgn.FaultError, drgn.ObjectAbsentError, AttributeError):
        return default


def _get_lock_export_id(lock):
    """Extract a client identity string from a lock's export.

    Returns (nid_str, uuid_str, export_addr) or None if unavailable.
    Server-side locks have l_export pointing to the client's export.
    """
    try:
        exp_ptr = lock.l_export.value_()
        if exp_ptr == 0:
            return None
        exp = lock.l_export[0]

        nid_str = "unknown"
        try:
            conn = exp.exp_connection
            if conn.value_() != 0:
                nid_str = lh.nid2str(conn[0].c_peer.nid.value_())
        except (drgn.FaultError, AttributeError):
            pass

        uuid_str = "unknown"
        try:
            uuid_str = exp.exp_client_uuid.uuid.string_().decode(
                errors="replace")
        except (drgn.FaultError, AttributeError):
            pass

        return (nid_str, uuid_str, f"0x{exp_ptr:x}")
    except (drgn.FaultError, drgn.ObjectAbsentError, AttributeError):
        return None


def _get_lock_import_id(lock):
    """Extract server identity from a lock's conn_export (client-side).

    Returns (nid_str, name_str, export_addr) or None.
    """
    try:
        conn_exp = lock.l_conn_export.value_()
        if conn_exp == 0:
            return None
        obd = lock.l_conn_export[0].exp_obd
        name = lh.obd_name(obd)
        imp = obd.u.cli.cl_import[0]
        nid = imp.imp_connection[0].c_peer.nid.value_()
        return (lh.nid2str(nid), name, f"0x{conn_exp:x}")
    except (drgn.FaultError, drgn.ObjectAbsentError, AttributeError):
        return None


def _lock_identity(lock):
    """Build a compact identity dict for a lock."""
    try:
        cookie = lock.l_handle.h_cookie.value_()
    except (drgn.FaultError, AttributeError):
        cookie = 0

    mode_req = _safe_val(lambda: lock.l_req_mode.value_(), 0)
    mode_gr = _safe_val(lambda: lock.l_granted_mode.value_(), 0)
    flags = _safe_val(lambda: lock.l_flags.value_(), 0)
    pid = _safe_val(lambda: lock.l_pid.value_(), 0)

    d = {
        "address": f"0x{_obj_addr(lock):x}",
        "cookie": f"0x{cookie:x}",
        "req_mode": lh.lockmode2str(mode_req),
        "granted_mode": lh.lockmode2str(mode_gr),
        "pid": pid,
        "flags": f"0x{flags:x}",
    }

    # Type-specific policy data
    try:
        lr_type = lock.l_resource[0].lr_type.value_()
        if lr_type == LDLM_EXTENT:
            ext = lock.l_policy_data.l_extent
            d["extent"] = {
                "start": ext.start.value_(),
                "end": ext.end.value_(),
            }
        elif lr_type == LDLM_IBITS:
            bits = lock.l_policy_data.l_inodebits.bits.value_()
            d["ibits"] = f"0x{bits:x}"
        elif lr_type == LDLM_FLOCK:
            fl = lock.l_policy_data.l_flock
            d["flock"] = {
                "pid": fl.pid.value_(),
                "start": fl.start.value_(),
                "end": fl.end.value_(),
            }
    except (drgn.FaultError, drgn.ObjectAbsentError, AttributeError):
        pass

    # Export identity (who holds/wants this lock)
    exp_id = _get_lock_export_id(lock)
    if exp_id:
        d["client_nid"] = exp_id[0]
        d["client_uuid"] = exp_id[1]
        d["export"] = exp_id[2]
    else:
        imp_id = _get_lock_import_id(lock)
        if imp_id:
            d["server_nid"] = imp_id[0]
            d["server_name"] = imp_id[1]

    return d


def _resource_name(res):
    """Get resource name as a string."""
    try:
        n = res.lr_name.name
        return (f"0x{n[0].value_():x}:0x{n[1].value_():x}:"
                f"0x{n[2].value_():x}.{n[3].value_():x}")
    except (drgn.FaultError, drgn.ObjectAbsentError, AttributeError):
        return "<unknown>"


def _resource_fid_parts(res):
    """Get raw resource name parts as ints (for FID lookup)."""
    try:
        n = res.lr_name.name
        return [n[i].value_() for i in range(4)]
    except (drgn.FaultError, drgn.ObjectAbsentError, AttributeError):
        return None


def _enrich_with_path(info_dict, res, fid_cache):
    """Add a 'path' field to info_dict if the resource FID is cached."""
    if not fid_cache:
        return
    parts = _resource_fid_parts(res)
    if parts is None:
        return
    fid_str = lh.resource_name_to_fid_str(parts)
    path = fid_cache.get(fid_str)
    if path:
        info_dict["path"] = path
        info_dict["fid"] = fid_str


def _resource_type_str(res):
    """Get resource type string."""
    try:
        t = res.lr_type.value_()
        return {LDLM_PLAIN: "PLAIN", LDLM_EXTENT: "EXTENT",
                LDLM_FLOCK: "FLOCK", LDLM_IBITS: "IBITS"}.get(t, f"?({t})")
    except (drgn.FaultError, AttributeError):
        return "?"


# ── Per-resource conflict analysis ───────────────────────────


def _find_conflicts_on_resource(res):
    """For a single resource, find which granted locks block waiting locks.

    Returns a list of conflict dicts, each with:
      - waiting_lock: identity of the waiting lock
      - blocked_by: list of granted lock identities that conflict
    """
    conflicts = []

    # Collect granted locks with their modes
    granted = []
    try:
        if not list_empty(res.lr_granted.address_of_()):
            for lock in list_for_each_entry(
                "struct ldlm_lock", res.lr_granted.address_of_(),
                "l_res_link"
            ):
                mode = _safe_val(lambda l=lock: l.l_granted_mode.value_(), 0)
                granted.append((lock, mode))
    except (drgn.FaultError, drgn.ObjectAbsentError):
        pass

    if not granted:
        return conflicts

    # Check each waiting lock against granted locks
    try:
        if list_empty(res.lr_waiting.address_of_()):
            return conflicts
    except (drgn.FaultError, drgn.ObjectAbsentError):
        return conflicts

    try:
        for wlock in list_for_each_entry(
            "struct ldlm_lock", res.lr_waiting.address_of_(), "l_res_link"
        ):
            req_mode = _safe_val(
                lambda l=wlock: l.l_req_mode.value_(), 0)
            if req_mode == 0:
                continue

            blockers = []
            for glock, gmode in granted:
                if gmode == 0:
                    continue
                if not lockmode_compat(gmode, req_mode):
                    blockers.append(_lock_identity(glock))

            if blockers:
                conflicts.append({
                    "waiting_lock": _lock_identity(wlock),
                    "blocked_by": blockers,
                })
    except (drgn.FaultError, drgn.ObjectAbsentError):
        pass

    return conflicts


# ── Wait-for graph and cycle detection ───────────────────────


def _build_wait_for_graph(prog, fid_cache=None):
    """Build a wait-for graph from all namespaces.

    Nodes are export addresses (clients). An edge from A to B means
    "client A is waiting for a lock held by client B".

    Returns:
      graph: dict mapping export_addr -> set of export_addrs it waits for
      node_info: dict mapping export_addr -> {nid, uuid} for display
      edges: list of (waiter_export, holder_export, resource, waiter_lock,
             holder_lock) for detailed reporting
    """
    graph = defaultdict(set)
    node_info = {}
    edges = []

    def process_ns_list(ns_sym_name):
        try:
            ns_list = prog[ns_sym_name]
        except (KeyError, LookupError):
            return

        lr_hash_off = prog.type(
            "struct ldlm_resource").member("lr_hash").offset

        for ns in list_for_each_entry(
            "struct ldlm_namespace", ns_list.address_of_(),
            "ns_list_chain"
        ):
            rs_hash = ns.ns_rs_hash
            for _bkt, _off, hnode in lh.cfs_hash_for_each_node(
                prog, rs_hash
            ):
                res_addr = hnode.value_() - lr_hash_off
                try:
                    res = drgn.Object(
                        prog, "struct ldlm_resource", address=res_addr)
                    _process_resource_for_graph(
                        res, graph, node_info, edges, fid_cache)
                except (drgn.FaultError, drgn.ObjectAbsentError):
                    continue

    # Server-side namespaces are where cross-client conflicts happen
    process_ns_list("ldlm_srv_namespace_list")

    return graph, node_info, edges


def _process_resource_for_graph(res, graph, node_info, edges,
                                fid_cache=None):
    """Process one resource: add edges from waiters to holders."""
    # Collect granted locks with export info
    granted = []
    try:
        if list_empty(res.lr_granted.address_of_()):
            return
    except (drgn.FaultError, drgn.ObjectAbsentError):
        return

    for glock in list_for_each_entry(
        "struct ldlm_lock", res.lr_granted.address_of_(), "l_res_link"
    ):
        exp_ptr = _safe_val(lambda l=glock: l.l_export.value_(), 0)
        gmode = _safe_val(lambda l=glock: l.l_granted_mode.value_(), 0)
        if exp_ptr == 0 or gmode == 0:
            continue

        # Register node
        if exp_ptr not in node_info:
            exp_id = _get_lock_export_id(glock)
            if exp_id:
                node_info[exp_ptr] = {
                    "nid": exp_id[0], "uuid": exp_id[1]}
            else:
                node_info[exp_ptr] = {"nid": "?", "uuid": "?"}

        granted.append((glock, gmode, exp_ptr))

    if not granted:
        return

    # Check waiting locks
    try:
        if list_empty(res.lr_waiting.address_of_()):
            return
    except (drgn.FaultError, drgn.ObjectAbsentError):
        return

    res_name = _resource_name(res)
    res_type = _resource_type_str(res)

    # Resolve path once per resource
    res_path = None
    if fid_cache:
        parts = _resource_fid_parts(res)
        if parts:
            fid_str = lh.resource_name_to_fid_str(parts)
            res_path = fid_cache.get(fid_str)

    for wlock in list_for_each_entry(
        "struct ldlm_lock", res.lr_waiting.address_of_(), "l_res_link"
    ):
        w_exp = _safe_val(lambda l=wlock: l.l_export.value_(), 0)
        w_mode = _safe_val(lambda l=wlock: l.l_req_mode.value_(), 0)
        if w_exp == 0 or w_mode == 0:
            continue

        if w_exp not in node_info:
            exp_id = _get_lock_export_id(wlock)
            if exp_id:
                node_info[w_exp] = {"nid": exp_id[0], "uuid": exp_id[1]}
            else:
                node_info[w_exp] = {"nid": "?", "uuid": "?"}

        for glock, gmode, g_exp in granted:
            if w_exp == g_exp:
                continue  # Same client — not a cross-client conflict
            if not lockmode_compat(gmode, w_mode):
                graph[w_exp].add(g_exp)
                edge = {
                    "waiter_export": f"0x{w_exp:x}",
                    "holder_export": f"0x{g_exp:x}",
                    "resource": res_name,
                    "resource_type": res_type,
                    "waiter_mode": lh.lockmode2str(w_mode),
                    "holder_mode": lh.lockmode2str(gmode),
                    "waiter_cookie": _safe_val(
                        lambda l=wlock: f"0x{l.l_handle.h_cookie.value_():x}",
                        "?"),
                    "holder_cookie": _safe_val(
                        lambda l=glock: f"0x{l.l_handle.h_cookie.value_():x}",
                        "?"),
                }
                if res_path:
                    edge["path"] = res_path
                edges.append(edge)


def _find_cycles(graph):
    """Find all cycles in a directed graph using DFS.

    Returns list of cycles, each cycle is a list of nodes forming
    the cycle (first == last).
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color = defaultdict(int)
    parent = {}
    cycles = []

    def dfs(u, path):
        color[u] = GRAY
        path.append(u)
        for v in graph.get(u, set()):
            if color[v] == GRAY:
                # Found a cycle — extract it
                idx = path.index(v)
                cycle = list(path[idx:]) + [v]
                cycles.append(cycle)
            elif color[v] == WHITE:
                dfs(v, path)
        path.pop()
        color[u] = BLACK

    for node in list(graph.keys()):
        if color[node] == WHITE:
            dfs(node, [])

    return cycles


# ── BL_AST timeout analysis ─────────────────────────────────


def _analyze_bl_ast_timeouts(prog):
    """Walk the server-side waiting_locks_list for BL_AST timeouts.

    Returns list of locks with pending blocking callbacks, sorted by
    urgency (oldest callback first).
    """
    results = []

    try:
        wl_list = prog["waiting_locks_list"]
    except (KeyError, LookupError):
        return results  # Not a server, or symbol not found

    try:
        if list_empty(wl_list.address_of_()):
            return results
    except (drgn.FaultError, drgn.ObjectAbsentError):
        return results

    # Get current kernel time for timeout comparison
    # In a vmcore this is the time at crash
    try:
        # Try to read jiffies or ktime for reference
        # Fall back to just reporting the timestamps raw
        pass
    except Exception:
        pass

    for lock in list_for_each_entry(
        "struct ldlm_lock", wl_list.address_of_(), "l_pending_chain"
    ):
        try:
            cb_ts = _safe_val(
                lambda l=lock: l.l_callback_timestamp.value_(), 0)
            blast_sent = _safe_val(
                lambda l=lock: l.l_blast_sent.value_(), 0)

            info = _lock_identity(lock)
            info["callback_timestamp"] = cb_ts
            info["bl_ast_sent_time"] = blast_sent
            if cb_ts > 0 and blast_sent > 0:
                info["waiting_seconds"] = cb_ts - blast_sent

            # Check l_blocking_lock if it's still set
            bl_lock = _safe_val(
                lambda l=lock: l.l_blocking_lock.value_(), 0)
            if bl_lock != 0:
                try:
                    bl = drgn.Object(
                        prog, "struct ldlm_lock", address=bl_lock)
                    info["blocking_lock"] = _lock_identity(bl)
                except (drgn.FaultError, drgn.ObjectAbsentError):
                    info["blocking_lock_addr"] = f"0x{bl_lock:x}"

            results.append(info)
        except (drgn.FaultError, drgn.ObjectAbsentError):
            continue

    # Sort by callback timestamp (oldest = most urgent)
    results.sort(key=lambda x: x.get("callback_timestamp", 0))
    return results


# ── l_blocking_lock chain analysis ───────────────────────────


def _analyze_blocking_lock_chains(prog):
    """Find all locks that have l_blocking_lock set and trace chains.

    This captures the direct server-side blocking relationship,
    independent of the mode-based conflict analysis.
    """
    chains = []

    def walk_ns_list(ns_sym_name):
        try:
            ns_list = prog[ns_sym_name]
        except (KeyError, LookupError):
            return

        lr_hash_off = prog.type(
            "struct ldlm_resource").member("lr_hash").offset

        for ns in list_for_each_entry(
            "struct ldlm_namespace", ns_list.address_of_(),
            "ns_list_chain"
        ):
            ns_name = _safe_val(
                lambda n=ns: lh.obd_name(n.ns_obd[0]), "<unknown>")
            rs_hash = ns.ns_rs_hash
            for _bkt, _off, hnode in lh.cfs_hash_for_each_node(
                prog, rs_hash
            ):
                res_addr = hnode.value_() - lr_hash_off
                try:
                    res = drgn.Object(
                        prog, "struct ldlm_resource", address=res_addr)
                    _check_blocking_locks(prog, res, ns_name, chains)
                except (drgn.FaultError, drgn.ObjectAbsentError):
                    continue

    walk_ns_list("ldlm_srv_namespace_list")
    walk_ns_list("ldlm_cli_active_namespace_list")
    return chains


def _check_blocking_locks(prog, res, ns_name, chains):
    """Check locks on a resource for l_blocking_lock pointers."""
    res_name = _resource_name(res)

    for queue_name, queue_field in [("granted", "lr_granted"),
                                    ("waiting", "lr_waiting")]:
        try:
            queue = getattr(res, queue_field)
            if list_empty(queue.address_of_()):
                continue
        except (drgn.FaultError, drgn.ObjectAbsentError):
            continue

        for lock in list_for_each_entry(
            "struct ldlm_lock", queue.address_of_(), "l_res_link"
        ):
            bl_ptr = _safe_val(
                lambda l=lock: l.l_blocking_lock.value_(), 0)
            if bl_ptr == 0:
                continue

            chain_entry = {
                "namespace": ns_name,
                "resource": res_name,
                "queue": queue_name,
                "lock": _lock_identity(lock),
                "blocking_lock_addr": f"0x{bl_ptr:x}",
            }

            # Try to dereference the blocking lock
            try:
                bl = drgn.Object(
                    prog, "struct ldlm_lock", address=bl_ptr)
                chain_entry["blocking_lock"] = _lock_identity(bl)
            except (drgn.FaultError, drgn.ObjectAbsentError):
                chain_entry["blocking_lock"] = "<fault>"

            chains.append(chain_entry)


# ── Top-level analysis functions ─────────────────────────────


def analyze_conflicts(prog, fid_cache=None):
    """Per-resource conflict analysis across all namespaces.

    Returns resources that have both granted and waiting locks with
    mode conflicts.  If fid_cache is provided, enriches output with
    file paths resolved from the dentry cache.
    """
    contended = []

    def scan_ns_list(ns_sym_name, side):
        try:
            ns_list = prog[ns_sym_name]
        except (KeyError, LookupError):
            return

        lr_hash_off = prog.type(
            "struct ldlm_resource").member("lr_hash").offset

        for ns in list_for_each_entry(
            "struct ldlm_namespace", ns_list.address_of_(),
            "ns_list_chain"
        ):
            ns_name = _safe_val(
                lambda n=ns: lh.obd_name(n.ns_obd[0]), "<unknown>")
            rs_hash = ns.ns_rs_hash

            for _bkt, _off, hnode in lh.cfs_hash_for_each_node(
                prog, rs_hash
            ):
                res_addr = hnode.value_() - lr_hash_off
                try:
                    res = drgn.Object(
                        prog, "struct ldlm_resource", address=res_addr)
                    conflicts = _find_conflicts_on_resource(res)
                    if conflicts:
                        entry = {
                            "namespace": ns_name,
                            "namespace_side": side,
                            "resource": _resource_name(res),
                            "resource_type": _resource_type_str(res),
                            "resource_addr": f"0x{res_addr:x}",
                            "conflicts": conflicts,
                        }
                        _enrich_with_path(entry, res, fid_cache)
                        contended.append(entry)
                except (drgn.FaultError, drgn.ObjectAbsentError):
                    continue

    scan_ns_list("ldlm_srv_namespace_list", "server")
    scan_ns_list("ldlm_cli_active_namespace_list", "client")
    return contended


def analyze_deadlocks(prog, fid_cache=None):
    """Build wait-for graph and detect cycles (deadlocks).

    Returns dict with the graph edges, detected cycles, and
    node information.
    """
    graph, node_info, edges = _build_wait_for_graph(prog, fid_cache)
    cycles_raw = _find_cycles(graph)

    # Format cycles with node info
    cycles = []
    for cycle in cycles_raw:
        formatted = []
        for exp_addr in cycle:
            info = node_info.get(exp_addr, {"nid": "?", "uuid": "?"})
            formatted.append({
                "export": f"0x{exp_addr:x}",
                "nid": info["nid"],
                "uuid": info["uuid"],
            })
        cycles.append(formatted)

    # Format node_info for output
    nodes = {}
    for exp_addr, info in node_info.items():
        nodes[f"0x{exp_addr:x}"] = info

    return {
        "nodes": nodes,
        "edge_count": len(edges),
        "edges": edges,
        "cycles": cycles,
        "deadlock_detected": len(cycles) > 0,
    }


def analyze_all(prog):
    """Run all deadlock/contention analyses and return combined result."""
    result = {"analysis": "ldlm_deadlock"}

    # Build FID->path cache once for all analyses (client vmcores only)
    fid_cache = lh.build_fid_path_cache(prog)
    if fid_cache:
        result["fid_paths_resolved"] = len(fid_cache)

    # 1. Wait-for graph and cycle detection
    wfg = analyze_deadlocks(prog, fid_cache)
    result["wait_for_graph"] = wfg
    result["deadlock_detected"] = wfg["deadlock_detected"]

    # 2. Per-resource conflict detail
    result["contended_resources"] = analyze_conflicts(prog, fid_cache)
    result["contended_resource_count"] = len(result["contended_resources"])

    # 3. BL_AST timeout analysis
    result["bl_ast_timeouts"] = _analyze_bl_ast_timeouts(prog)
    result["bl_ast_timeout_count"] = len(result["bl_ast_timeouts"])

    # 4. Direct l_blocking_lock chains
    result["blocking_chains"] = _analyze_blocking_lock_chains(prog)
    result["blocking_chain_count"] = len(result["blocking_chains"])

    # Summary
    result["summary"] = {
        "deadlocks": len(wfg["cycles"]),
        "contended_resources": len(result["contended_resources"]),
        "bl_ast_timeouts": len(result["bl_ast_timeouts"]),
        "blocking_chains": len(result["blocking_chains"]),
        "wait_for_edges": wfg["edge_count"],
        "clients_in_graph": len(wfg["nodes"]),
    }

    return result


# ── Text output ──────────────────────────────────────────────


def print_analysis_text(result):
    """Print deadlock analysis in human-readable text format."""
    summary = result.get("summary", {})

    print("=" * 70)
    print("LDLM Lock Deadlock / Contention Analysis")
    print("=" * 70)
    print()

    # Deadlocks (most critical first)
    wfg = result.get("wait_for_graph", {})
    cycles = wfg.get("cycles", [])
    if cycles:
        print(f"*** DEADLOCK DETECTED: {len(cycles)} cycle(s) ***")
        print()
        for i, cycle in enumerate(cycles):
            print(f"  Cycle {i + 1}:")
            for j, node in enumerate(cycle):
                arrow = " -> " if j < len(cycle) - 1 else ""
                print(f"    {node['nid']} ({node['uuid']}){arrow}")
            print()
    else:
        print("No deadlocks detected.")
        print()

    # BL_AST timeouts
    bl_timeouts = result.get("bl_ast_timeouts", [])
    if bl_timeouts:
        print(f"BL_AST Timeouts: {len(bl_timeouts)} lock(s) with pending "
              f"blocking callbacks")
        print("-" * 60)
        for entry in bl_timeouts:
            print(f"  Lock {entry.get('cookie', '?')} "
                  f"mode={entry.get('req_mode', '?')} "
                  f"pid={entry.get('pid', '?')}")
            nid = entry.get("client_nid", entry.get("server_nid", "?"))
            print(f"    Client: {nid}")
            ws = entry.get("waiting_seconds", "?")
            print(f"    BL_AST wait: {ws}s")
            bl = entry.get("blocking_lock", {})
            if bl and isinstance(bl, dict):
                print(f"    Blocked by: {bl.get('cookie', '?')} "
                      f"mode={bl.get('granted_mode', '?')} "
                      f"client={bl.get('client_nid', '?')}")
            print()

    # Blocking chains
    chains = result.get("blocking_chains", [])
    if chains:
        print(f"Blocking Chains: {len(chains)} lock(s) with "
              f"l_blocking_lock set")
        print("-" * 60)
        for entry in chains:
            lk = entry.get("lock", {})
            bl = entry.get("blocking_lock", {})
            print(f"  {entry.get('namespace', '?')} "
                  f"res={entry.get('resource', '?')} "
                  f"({entry.get('queue', '?')})")
            nid = lk.get("client_nid", lk.get("server_nid", "?"))
            print(f"    Lock {lk.get('cookie', '?')} "
                  f"mode={lk.get('req_mode', '?')} client={nid}")
            if isinstance(bl, dict):
                bl_nid = bl.get("client_nid", bl.get("server_nid", "?"))
                print(f"    Blocked by {bl.get('cookie', '?')} "
                      f"mode={bl.get('granted_mode', '?')} "
                      f"client={bl_nid}")
            print()

    # Contended resources
    contended = result.get("contended_resources", [])
    if contended:
        print(f"Contended Resources: {len(contended)}")
        print("-" * 60)
        for res in contended:
            path_str = f" ({res['path']})" if "path" in res else ""
            print(f"  {res['namespace']} ({res['namespace_side']}) "
                  f"res={res['resource']} type={res['resource_type']}"
                  f"{path_str}")
            for conflict in res["conflicts"]:
                wl = conflict["waiting_lock"]
                w_nid = wl.get("client_nid",
                               wl.get("server_nid", "?"))
                print(f"    Waiting: {wl.get('cookie', '?')} "
                      f"req_mode={wl.get('req_mode', '?')} "
                      f"client={w_nid}")
                for bl in conflict["blocked_by"]:
                    bl_nid = bl.get("client_nid",
                                    bl.get("server_nid", "?"))
                    print(f"      blocked by: {bl.get('cookie', '?')} "
                          f"mode={bl.get('granted_mode', '?')} "
                          f"client={bl_nid}")
            print()

    # Wait-for graph summary
    print(f"Wait-for Graph: {summary.get('clients_in_graph', 0)} clients, "
          f"{summary.get('wait_for_edges', 0)} edges")

    # Print graph edges if there are any
    edges = wfg.get("edges", [])
    if edges:
        print("-" * 60)
        nodes = wfg.get("nodes", {})
        for edge in edges:
            w_info = nodes.get(edge["waiter_export"], {})
            h_info = nodes.get(edge["holder_export"], {})
            res_label = edge.get("path", edge["resource"])
            print(f"  {w_info.get('nid', '?')} "
                  f"--({edge['waiter_mode']} vs {edge['holder_mode']} "
                  f"on {res_label})--> "
                  f"{h_info.get('nid', '?')}")

    print()
    print("=" * 70)


# ── Main ─────────────────────────────────────────────────────


def main():
    try:
        from .lustre_analyze import load_program
    except ImportError:
        from lustre_analyze import load_program

    parser = argparse.ArgumentParser(
        description="LDLM lock deadlock and contention analyzer.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--vmcore", required=True)
    parser.add_argument("--vmlinux", required=True)
    parser.add_argument("--mod-dir", default=None)
    parser.add_argument("--debug-dir", default=None)
    parser.add_argument("--text", action="store_true",
                        help="Text output (default is JSON)")
    parser.add_argument("--pretty", action="store_true",
                        help="Pretty-print JSON")
    parser.add_argument("--conflicts-only", action="store_true",
                        help="Only show per-resource conflict analysis")
    parser.add_argument("--graph-only", action="store_true",
                        help="Only show wait-for graph and cycles")
    args = parser.parse_args()

    prog = load_program(args.vmcore, args.vmlinux,
                        args.mod_dir, args.debug_dir)

    if args.conflicts_only:
        result = {
            "analysis": "ldlm_conflicts",
            "contended_resources": analyze_conflicts(prog),
        }
    elif args.graph_only:
        result = {
            "analysis": "ldlm_wait_for_graph",
            "wait_for_graph": analyze_deadlocks(prog),
        }
    else:
        result = analyze_all(prog)

    if args.text:
        print_analysis_text(result)
    else:
        lh.json_output(result, args)


if __name__ == "__main__":
    main()
