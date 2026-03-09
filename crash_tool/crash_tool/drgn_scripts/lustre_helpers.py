"""Lustre helper functions for drgn — port of epython lustrelib.py.

Provides utilities for navigating Lustre data structures in vmcore
files: NID formatting, OBD device access, cfs_hash traversal,
rb-tree iteration, and linked list helpers.

Original: contrib/debug_tools/epython_scripts/lustrelib.py
Authors: Ann Koehler (Cray Inc.), ported to drgn by Claude.
"""

import drgn
from drgn.helpers.linux.list import (
    hlist_for_each_entry,
    list_for_each_entry,
    list_empty,
)


# ── NID formatting ────────────────────────────────────────────


LNET_NID_ANY = 0xFFFFFFFFFFFFFFFF

SOCKLND = 2
PTLLND = 4
O2IBLND = 5
GNILND = 13
KFILND = 14


def lnet_nidaddr(nid: int) -> int:
    return nid & 0xFFFFFFFF


def lnet_nidnet(nid: int) -> int:
    return (nid >> 32) & 0xFFFFFFFF


def lnet_nettyp(net: int) -> int:
    return (net >> 16) & 0xFFFF


def lnet_netnum(net: int) -> int:
    return net & 0xFFFF


def nid2str(nid: int) -> str:
    """Convert a numeric NID to a string like '10.0.0.1@o2ib0'."""
    if nid == LNET_NID_ANY:
        return "LNET_NID_ANY"

    addr = lnet_nidaddr(nid)
    net = lnet_nidnet(nid)
    lnd = lnet_nettyp(net)
    nnum = lnet_netnum(net)

    ip = "{}.{}.{}.{}".format(
        (addr >> 24) & 0xFF,
        (addr >> 16) & 0xFF,
        (addr >> 8) & 0xFF,
        addr & 0xFF,
    )

    lnd_names = {
        SOCKLND: "tcp",
        O2IBLND: "o2ib",
        PTLLND: "ptl",
        GNILND: "gni",
        KFILND: "kfi",
    }

    if lnd in lnd_names:
        s = f"{ip}@{lnd_names[lnd]}" if lnd in (SOCKLND, O2IBLND) else f"{addr}@{lnd_names[lnd]}"
        if nnum != 0:
            s += str(nnum)
        return s

    return f"{addr}@unknown{lnd}"


# ── OBD device access ────────────────────────────────────────


def get_obd_devices(prog: drgn.Program) -> list:
    """Return list of (index, obd_device Object) for all active devices."""
    sym = prog.symbol("obd_devs")
    arr = drgn.Object(
        prog,
        prog.type("struct obd_device *[8192]"),
        address=sym.address,
    )

    devices = []
    for i in range(8192):
        try:
            ptr = arr[i].value_()
            if ptr == 0:
                continue
            obd = drgn.Object(prog, "struct obd_device", address=ptr)
            devices.append((i, obd))
        except drgn.FaultError:
            continue

    return devices


def obd_name(obd: drgn.Object) -> str:
    """Get OBD device name."""
    return obd.obd_name.string_().decode(errors="replace")


def obd_uuid(obd: drgn.Object) -> str:
    """Get OBD device UUID."""
    return obd.obd_uuid.uuid.string_().decode(errors="replace")


def obd2nidstr(obd: drgn.Object) -> str:
    """Get NID string for an OBD device's import connection."""
    try:
        imp = obd.u.cli.cl_import[0]
        if imp.imp_invalid:
            return "LNET_NID_ANY"
        conn = imp.imp_connection
        if conn.value_() == 0:
            return "LNET_NID_ANY"
        nid = conn[0].c_peer.nid.value_()
        return nid2str(nid)
    except (drgn.FaultError, AttributeError):
        return "LNET_NID_ANY"


# ── cfs_hash traversal ────────────────────────────────────────


CFS_HASH_ADD_TAIL = 1 << 4
CFS_HASH_DEPTH = 1 << 12
CFS_HASH_TYPE_MASK = CFS_HASH_ADD_TAIL | CFS_HASH_DEPTH


def cfs_hash_nbkt(hsh: drgn.Object) -> int:
    return 1 << (hsh.hs_cur_bits.value_() - hsh.hs_bkt_bits.value_())


def cfs_hash_bkt_nhlist(hsh: drgn.Object) -> int:
    return 1 << hsh.hs_bkt_bits.value_()


def cfs_hash_for_each_node(prog: drgn.Program, hsh: drgn.Object):
    """Iterate over all hlist_node entries in a cfs_hash.

    Yields (bucket_index, offset, hlist_node) tuples.
    """
    hs_type = hsh.hs_flags.value_() & CFS_HASH_TYPE_MASK

    # Determine the head struct and field name based on hash type
    type_info = {
        0: ("struct cfs_hash_head", "hh_head"),
        CFS_HASH_DEPTH: ("struct cfs_hash_head_dep", "hd_head"),
        CFS_HASH_ADD_TAIL: ("struct cfs_hash_dhead", "dh_head"),
        CFS_HASH_DEPTH | CFS_HASH_ADD_TAIL: ("struct cfs_hash_dhead_dep", "dd_head"),
    }

    if hs_type not in type_info:
        return

    dt_struct, hd_field = type_info[hs_type]

    nbkt = cfs_hash_nbkt(hsh)
    nhlist = cfs_hash_bkt_nhlist(hsh)

    for bkt_idx in range(nbkt):
        bkt_ptr = hsh.hs_buckets[bkt_idx]
        if bkt_ptr.value_() == 0:
            continue

        for offset in range(nhlist):
            try:
                # Navigate to the head structure
                hsb_head_off = prog.type("struct cfs_hash_bucket").member("hsb_head").offset
                dt_size = prog.type(dt_struct).size
                head_addr = bkt_ptr.value_() + hsb_head_off + offset * dt_size

                head = drgn.Object(prog, dt_struct, address=head_addr)
                hd_off = prog.type(dt_struct).member(hd_field).offset
                hlist = drgn.Object(
                    prog, "struct hlist_head",
                    address=head_addr + hd_off,
                )

                # Walk the hlist
                node = hlist.first
                while node.value_() != 0:
                    yield bkt_idx, offset, node
                    try:
                        node = node[0].next
                    except drgn.FaultError:
                        break

            except (drgn.FaultError, drgn.ObjectAbsentError):
                continue


# ── Red-black tree helpers ────────────────────────────────────


def rb_first(root: drgn.Object):
    """Get the first (leftmost) node in an rb-tree."""
    n = root.rb_node
    if n.value_() == 0:
        return None
    while n[0].rb_left.value_() != 0:
        n = n[0].rb_left
    return n


def rb_next(prog: drgn.Program, node: drgn.Object):
    """Get the next node in rb-tree order."""
    # parent is encoded in __rb_parent_color with low bits as color
    parent_color = node[0].__rb_parent_color.value_() if hasattr(node[0], '__rb_parent_color') else 0

    def rb_parent(n):
        pc = n[0].__rb_parent_color.value_()
        addr = pc & ~3
        if addr == 0:
            return None
        return drgn.Object(prog, "struct rb_node *",
                           value=addr).read_()

    # If right child exists, go right then all the way left
    if node[0].rb_right.value_() != 0:
        node = node[0].rb_right
        while node[0].rb_left.value_() != 0:
            node = node[0].rb_left
        return node

    # Otherwise go up until we come from a left child
    parent = rb_parent(node)
    while parent is not None and node.value_() == parent[0].rb_right.value_():
        node = parent
        parent = rb_parent(node)

    return parent


# ── LDLM lock mode helpers ───────────────────────────────────


LDLM_LOCK_MODES = {
    0: "--",
    1: "EX",
    2: "PW",
    4: "PR",
    8: "CW",
    16: "CR",
    32: "NL",
    64: "GROUP",
}


def lockmode2str(mode: int) -> str:
    return LDLM_LOCK_MODES.get(mode, f"??({mode})")


# ── RPC opcode helpers ────────────────────────────────────────


# Common Lustre RPC opcodes
RPC_OPCODES = {
    1: "OST_REPLY",
    2: "OST_GETATTR",
    3: "OST_SETATTR",
    4: "OST_READ",
    5: "OST_WRITE",
    6: "OST_CREATE",
    7: "OST_DESTROY",
    8: "OST_GET_INFO",
    9: "OST_CONNECT",
    10: "OST_DISCONNECT",
    11: "OST_PUNCH",
    12: "OST_OPEN",
    13: "OST_CLOSE",
    14: "OST_STATFS",
    16: "OST_SYNC",
    17: "OST_SET_INFO",
    18: "OST_QUOTACHECK",
    19: "OST_QUOTACTL",
    20: "OST_QUOTA_ADJUST_QUNIT",
    21: "OST_LADVISE",
    22: "OST_FALLOCATE",
    23: "OST_SEEK",
    33: "MDS_GETATTR",
    34: "MDS_GETATTR_NAME",
    35: "MDS_CLOSE",
    36: "MDS_REINT",
    37: "MDS_READPAGE",
    38: "MDS_CONNECT",
    39: "MDS_DISCONNECT",
    40: "MDS_GET_ROOT",
    41: "MDS_STATFS",
    42: "MDS_PIN",
    43: "MDS_UNPIN",
    44: "MDS_SYNC",
    45: "MDS_DONE_WRITING",
    46: "MDS_SET_INFO",
    47: "MDS_QUOTACHECK",
    48: "MDS_QUOTACTL",
    49: "MDS_GETXATTR",
    50: "MDS_SWAP_LAYOUTS",
    51: "MDS_RMFID",
    52: "MDS_BATCH",
    101: "LDLM_ENQUEUE",
    102: "LDLM_CONVERT",
    103: "LDLM_CANCEL",
    104: "LDLM_BL_CALLBACK",
    105: "LDLM_CP_CALLBACK",
    106: "LDLM_GL_CALLBACK",
    107: "LDLM_SET_INFO",
    400: "MGS_CONNECT",
    401: "MGS_DISCONNECT",
    402: "MGS_EXCEPTION",
    403: "MGS_TARGET_REG",
    404: "MGS_TARGET_DEL",
    405: "MGS_SET_INFO",
    406: "MGS_CONFIG_READ",
    501: "OBD_PING",
    502: "OBD_LOG_CANCEL",
    503: "OBD_QC_CALLBACK",
    504: "OBD_IDX_READ",
    506: "LLOG_ORIGIN_HANDLE_CREATE",
    507: "LLOG_ORIGIN_HANDLE_NEXT_BLOCK",
    508: "LLOG_ORIGIN_HANDLE_READ_HEADER",
    510: "LLOG_ORIGIN_HANDLE_CLOSE",
    513: "LLOG_CATINFO",
    601: "SEQ_QUERY",
    700: "SEC_CTX_INIT",
    701: "SEC_CTX_INIT_CONT",
    702: "SEC_CTX_FINI",
    801: "FLD_QUERY",
    802: "FLD_READ",
    900: "OUT_UPDATE",
    1000: "LFSCK_NOTIFY",
    1001: "LFSCK_QUERY",
}


def opc2str(opc: int) -> str:
    return RPC_OPCODES.get(opc, f"UNKNOWN({opc})")
