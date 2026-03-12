#!/usr/bin/env python3
"""Stripe layout reconstructor for Lustre vmcore analysis.

Iterates all cached Lustre inodes and extracts their stripe layout
information -- both LOV (file data striping) and LMV (directory
striping).

Authors: Claude (Anthropic), for lustre-drgn-tools.
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


# ── Magic constants ──────────────────────────────────────────

LOV_MAGIC_MAGIC = 0x0BD0
LOV_MAGIC_V1 = 0x0BD10000 | LOV_MAGIC_MAGIC
LOV_MAGIC_V3 = 0x0BD30000 | LOV_MAGIC_MAGIC
LOV_MAGIC_COMP_V1 = 0x0BD60000 | LOV_MAGIC_MAGIC
LOV_MAGIC_FOREIGN = 0x0BD70000 | LOV_MAGIC_MAGIC

LMV_MAGIC_V1 = 0x0CD20CD0
LMV_MAGIC = LMV_MAGIC_V1

LOV_MAGIC_NAMES = {
    LOV_MAGIC_V1: "LOV_MAGIC_V1",
    LOV_MAGIC_V3: "LOV_MAGIC_V3",
    LOV_MAGIC_COMP_V1: "LOV_MAGIC_COMP_V1",
    LOV_MAGIC_FOREIGN: "LOV_MAGIC_FOREIGN",
}

LMV_MAGIC_NAMES = {
    LMV_MAGIC_V1: "LMV_MAGIC",
}

# ── Pattern constants ────────────────────────────────────────

LOV_PATTERN_RAID0 = 0x001
LOV_PATTERN_MDT = 0x100
LOV_PATTERN_OVERSTRIPING = 0x200
LOV_PATTERN_FOREIGN = 0x400
LOV_PATTERN_COMPRESS = 0x800

PATTERN_NAMES = {
    0x000: "NONE",
    0x001: "RAID0",
    0x002: "RAID1",
    0x004: "PARITY",
    0x100: "MDT",
}


def pattern2str(pat):
    """Convert a stripe pattern value to a human-readable string."""
    base = pat & 0xFFFF
    parts = []
    for bit, name in PATTERN_NAMES.items():
        if bit and (base & bit):
            parts.append(name)
    if base & LOV_PATTERN_OVERSTRIPING:
        parts.append("OVERSTRIPING")
    if base & LOV_PATTERN_COMPRESS:
        parts.append("COMPRESS")
    if not parts:
        if base == 0:
            return "NONE"
        return f"0x{base:x}"
    return "|".join(parts)


# ── LMV hash types ──────────────────────────────────────────

LMV_HASH_TYPE_MASK = 0x0000FFFF

LMV_HASH_NAMES = {
    0: "unknown",
    1: "all_chars",
    2: "fnv_1a_64",
    3: "crush",
    4: "crush2",
}


def hash_type2str(ht):
    """Convert LMV hash type to string."""
    base = ht & LMV_HASH_TYPE_MASK
    name = LMV_HASH_NAMES.get(base, f"unknown({base})")
    flags = ht & ~LMV_HASH_TYPE_MASK
    if flags:
        name += f"|flags=0x{flags:x}"
    return name


# ── FID formatting ───────────────────────────────────────────

def fid2str(fid):
    """Format a lu_fid struct as a string."""
    try:
        seq = fid.f_seq.value_()
        oid = fid.f_oid.value_()
        ver = fid.f_ver.value_()
        return f"[0x{seq:x}:0x{oid:x}:0x{ver:x}]"
    except (drgn.FaultError, AttributeError):
        return "[?:?:?]"


def ostid2str(oi):
    """Format an ost_id (via its embedded FID) as a string."""
    try:
        fid = oi.oi_fid
        return fid2str(fid)
    except (drgn.FaultError, AttributeError):
        try:
            oid = oi.oi.oi_id.value_()
            seq = oi.oi.oi_seq.value_()
            return f"0x{seq:x}:0x{oid:x}"
        except (drgn.FaultError, AttributeError):
            return "?"


# ── Inode path resolution ───────────────────────────────────

def resolve_inode_path(inode):
    """Try to resolve a path from an inode's dentry cache.

    Walks d_parent chain from the first dentry in i_dentry hlist.
    Returns None if no dentry is cached.
    """
    try:
        # i_dentry is an hlist_head
        first = inode.i_dentry.first
        if first.value_() == 0:
            return None

        # The dentry is linked via d_u.d_alias (hlist_node)
        dentry_type = inode.prog_.type("struct dentry")
        d_u_offset = dentry_type.member("d_u").offset
        dentry_addr = first.value_() - d_u_offset
        dentry = drgn.Object(inode.prog_, "struct dentry", address=dentry_addr)

        parts = []
        seen = set()
        cur = dentry
        for _ in range(256):  # max depth guard
            addr = cur.address_of_().value_()
            if addr in seen:
                break
            seen.add(addr)

            name = cur.d_name.name.string_().decode(errors="replace")
            if name == "/":
                break
            parts.append(name)

            parent_ptr = cur.d_parent.value_()
            if parent_ptr == 0 or parent_ptr == addr:
                break
            cur = cur.d_parent[0]

        if parts:
            parts.reverse()
            return "/" + "/".join(parts)
    except (drgn.FaultError, AttributeError, drgn.ObjectAbsentError):
        pass
    return None


# ── Lustre superblock discovery ──────────────────────────────

def find_lustre_superblocks(prog):
    """Find all Lustre superblocks by walking the kernel super_blocks list.

    Returns list of (super_block, ll_sb_info) tuples.
    """
    results = []
    try:
        sb_list = prog["super_blocks"]
    except (KeyError, LookupError):
        return results

    for sb in list_for_each_entry(
        "struct super_block", sb_list.address_of_(), "s_list"
    ):
        try:
            type_ptr = sb.s_type.value_()
            if type_ptr == 0:
                continue
            name = sb.s_type[0].name.string_().decode(errors="replace")
            if name != "lustre":
                continue

            # Get ll_sb_info via s_fs_info -> lustre_sb_info -> lsi_llsbi
            fs_info_ptr = sb.s_fs_info.value_()
            if fs_info_ptr == 0:
                continue
            lsi = drgn.Object(
                prog, "struct lustre_sb_info", address=fs_info_ptr
            )
            sbi_ptr = lsi.lsi_llsbi.value_()
            if sbi_ptr == 0:
                continue
            sbi = drgn.Object(prog, "struct ll_sb_info", address=sbi_ptr)
            results.append((sb, sbi))
        except (drgn.FaultError, AttributeError, drgn.ObjectAbsentError):
            continue

    return results


# ── LOV layout extraction ───────────────────────────────────

def extract_lov_layout(prog, lsm):
    """Extract file stripe layout from a lov_stripe_md pointer.

    Returns a dict describing the layout, or None on failure.
    """
    try:
        lsm_ptr = lsm.value_()
        if lsm_ptr == 0:
            return None
        lsm_obj = lsm[0]
    except (drgn.FaultError, AttributeError):
        return None

    try:
        magic = lsm_obj.lsm_magic.value_()
        layout_gen = lsm_obj.lsm_layout_gen.value_()
        mirror_count = lsm_obj.lsm_mirror_count.value_()
        entry_count = lsm_obj.lsm_entry_count.value_()
    except (drgn.FaultError, AttributeError):
        return None

    magic_name = LOV_MAGIC_NAMES.get(magic, f"0x{magic:x}")

    if magic == LOV_MAGIC_FOREIGN:
        return {
            "magic": magic_name,
            "layout_gen": layout_gen,
            "mirror_count": mirror_count,
            "components": [],
            "note": "foreign layout",
        }

    components = []
    # Sanity bound on entry_count
    if entry_count > 1024:
        entry_count = 0

    for i in range(entry_count):
        try:
            entry_ptr = lsm_obj.lsm_entries[i].value_()
            if entry_ptr == 0:
                continue
            entry = lsm_obj.lsm_entries[i][0]
            comp = _extract_lsm_entry(prog, entry, i)
            if comp is not None:
                components.append(comp)
        except (drgn.FaultError, AttributeError, drgn.ObjectAbsentError):
            continue

    return {
        "magic": magic_name,
        "layout_gen": layout_gen,
        "mirror_count": mirror_count,
        "components": components,
    }


def _extract_lsm_entry(prog, entry, idx):
    """Extract one lov_stripe_md_entry as a dict."""
    try:
        lsme_id = entry.lsme_id.value_()
        lsme_magic = entry.lsme_magic.value_()
        lsme_flags = entry.lsme_flags.value_()
        lsme_pattern = entry.lsme_pattern.value_()

        # Check for foreign entry
        if lsme_magic == LOV_MAGIC_FOREIGN:
            return {
                "id": lsme_id,
                "magic": "LOV_MAGIC_FOREIGN",
                "flags": f"0x{lsme_flags:x}",
                "pattern": pattern2str(lsme_pattern),
                "note": "foreign component",
            }

        ext_start = entry.lsme_extent.e_start.value_()
        ext_end = entry.lsme_extent.e_end.value_()
        stripe_size = entry.lsme_stripe_size.value_()
        stripe_count = entry.lsme_stripe_count.value_()
        pool_name = ""
        try:
            pool_name = entry.lsme_pool_name.string_().decode(errors="replace")
        except (drgn.FaultError, AttributeError):
            pass

        stripes = []
        # Sanity limit on stripe_count
        sc = min(stripe_count, 2000)
        for j in range(sc):
            try:
                oinfo_ptr = entry.lsme_oinfo[j].value_()
                if oinfo_ptr == 0:
                    continue
                oinfo = entry.lsme_oinfo[j][0]
                ost_idx = oinfo.loi_ost_idx.value_()
                obj_id = ostid2str(oinfo.loi_oi)
                stripes.append({
                    "ost_idx": ost_idx,
                    "object_id": obj_id,
                })
            except (drgn.FaultError, AttributeError, drgn.ObjectAbsentError):
                continue

        return {
            "id": lsme_id,
            "extent": {
                "start": ext_start,
                "end": ext_end,
            },
            "pattern": pattern2str(lsme_pattern),
            "stripe_size": stripe_size,
            "stripe_count": stripe_count,
            "pool": pool_name,
            "flags": f"0x{lsme_flags:x}",
            "stripes": stripes,
        }
    except (drgn.FaultError, AttributeError, drgn.ObjectAbsentError):
        return None


# ── LMV layout extraction ───────────────────────────────────

def extract_lmv_layout(prog, lso_ptr):
    """Extract directory stripe layout from an lmv_stripe_object pointer.

    Returns a dict describing the layout, or None on failure.
    """
    try:
        if lso_ptr.value_() == 0:
            return None
        lso = lso_ptr[0]
        lsm = lso.lso_lsm
    except (drgn.FaultError, AttributeError):
        return None

    try:
        magic = lsm.lsm_md_magic.value_()
        stripe_count = lsm.lsm_md_stripe_count.value_()
        master_mdt = lsm.lsm_md_master_mdt_index.value_()
        hash_type = lsm.lsm_md_hash_type.value_()
        pool_name = ""
        try:
            pool_name = lsm.lsm_md_pool_name.string_().decode(
                errors="replace"
            )
        except (drgn.FaultError, AttributeError):
            pass
    except (drgn.FaultError, AttributeError):
        return None

    magic_name = LMV_MAGIC_NAMES.get(magic, f"0x{magic:x}")

    if magic != LMV_MAGIC:
        return {
            "magic": magic_name,
            "stripe_count": stripe_count,
            "master_mdt": master_mdt,
            "hash_type": hash_type2str(hash_type),
            "stripes": [],
        }

    stripes = []
    sc = min(stripe_count, 2000)
    for i in range(sc):
        try:
            oinfo = lsm.lsm_md_oinfo[i]
            mdt_idx = oinfo.lmo_mds.value_()
            fid = fid2str(oinfo.lmo_fid)
            stripes.append({
                "mdt_idx": mdt_idx,
                "fid": fid,
            })
        except (drgn.FaultError, AttributeError, drgn.ObjectAbsentError):
            continue

    return {
        "magic": magic_name,
        "stripe_count": stripe_count,
        "master_mdt": master_mdt,
        "hash_type": hash_type2str(hash_type),
        "pool": pool_name,
        "stripes": stripes,
    }


# ── LOV object discovery ────────────────────────────────────

def get_lov_stripe_md(prog, lli):
    """Get the lov_stripe_md from ll_inode_info via lli_clob.

    Path: lli_clob (cl_object*) -> container_of to lov_object -> lo_lsm.
    """
    try:
        clob_ptr = lli.lli_clob.value_()
        if clob_ptr == 0:
            return None

        # cl_object is embedded as lo_cl in lov_object.
        # lov_object = container_of(cl_object, struct lov_object, lo_cl)
        lo_cl_offset = prog.type("struct lov_object").member("lo_cl").offset
        lov_addr = clob_ptr - lo_cl_offset

        lov_obj = drgn.Object(prog, "struct lov_object", address=lov_addr)
        lo_lsm = lov_obj.lo_lsm
        return lo_lsm
    except (drgn.FaultError, AttributeError, drgn.ObjectAbsentError,
            LookupError):
        return None


# ── Main iteration ───────────────────────────────────────────

def get_stripe_layouts(prog, max_inodes=10000):
    """Iterate cached Lustre inodes and extract stripe layouts.

    Returns a result dict with file_layouts, dir_layouts, and summary.
    """
    file_layouts = []
    dir_layouts = []
    layout_type_counts = {}
    total_inodes = 0
    skipped = 0

    superblocks = find_lustre_superblocks(prog)
    if not superblocks:
        return {
            "analysis": "stripe_layouts",
            "error": "No Lustre superblocks found",
            "file_layouts": [],
            "dir_layouts": [],
            "summary": {
                "total_files_with_layout": 0,
                "total_dirs_with_layout": 0,
                "layout_types": {},
            },
        }

    # Get the offset of lli_vfs_inode within ll_inode_info
    try:
        lli_vfs_inode_off = prog.type("struct ll_inode_info").member(
            "lli_vfs_inode"
        ).offset
    except LookupError:
        return {
            "analysis": "stripe_layouts",
            "error": "Cannot find struct ll_inode_info type",
            "file_layouts": [],
            "dir_layouts": [],
            "summary": {
                "total_files_with_layout": 0,
                "total_dirs_with_layout": 0,
                "layout_types": {},
            },
        }

    for sb, sbi in superblocks:
        if total_inodes >= max_inodes:
            break

        # Walk super_block->s_inodes list
        try:
            if list_empty(sb.s_inodes.address_of_()):
                continue
        except (drgn.FaultError, AttributeError):
            continue

        for inode in list_for_each_entry(
            "struct inode", sb.s_inodes.address_of_(), "i_sb_list"
        ):
            if total_inodes >= max_inodes:
                break
            total_inodes += 1

            try:
                inode_addr = inode.address_of_().value_()
                # container_of: ll_inode_info from inode
                lli_addr = inode_addr - lli_vfs_inode_off
                lli = drgn.Object(
                    prog, "struct ll_inode_info", address=lli_addr
                )

                # Verify magic
                magic = lli.lli_inode_magic.value_()
                if magic != 0x111d0de5:
                    skipped += 1
                    continue

                fid_str = fid2str(lli.lli_fid)
                path = resolve_inode_path(inode)

                # Check inode mode to determine file vs directory
                i_mode = inode.i_mode.value_()
                is_dir = (i_mode & 0o170000) == 0o040000
                is_reg = (i_mode & 0o170000) == 0o100000

                if is_dir:
                    # Directory: check for LMV layout
                    try:
                        lso_ptr = lli.lli_lsm_obj
                        lmv_info = extract_lmv_layout(prog, lso_ptr)
                        if lmv_info is not None:
                            entry = {
                                "fid": fid_str,
                                "inode_addr": f"0x{inode_addr:x}",
                            }
                            if path:
                                entry["path"] = path
                            entry.update(lmv_info)
                            dir_layouts.append(entry)

                            magic_name = lmv_info.get("magic", "?")
                            layout_type_counts[magic_name] = (
                                layout_type_counts.get(magic_name, 0) + 1
                            )
                    except (drgn.FaultError, AttributeError,
                            drgn.ObjectAbsentError):
                        pass

                if is_reg or not is_dir:
                    # Regular file (or symlink, etc): check LOV layout
                    lo_lsm = get_lov_stripe_md(prog, lli)
                    if lo_lsm is not None:
                        lov_info = extract_lov_layout(prog, lo_lsm)
                        if lov_info is not None:
                            entry = {
                                "fid": fid_str,
                                "inode_addr": f"0x{inode_addr:x}",
                            }
                            if path:
                                entry["path"] = path
                            entry.update(lov_info)
                            file_layouts.append(entry)

                            magic_name = lov_info.get("magic", "?")
                            layout_type_counts[magic_name] = (
                                layout_type_counts.get(magic_name, 0) + 1
                            )

            except (drgn.FaultError, AttributeError,
                    drgn.ObjectAbsentError):
                skipped += 1
                continue

    return {
        "analysis": "stripe_layouts",
        "file_layouts": file_layouts,
        "dir_layouts": dir_layouts,
        "summary": {
            "total_inodes_scanned": total_inodes,
            "skipped": skipped,
            "total_files_with_layout": len(file_layouts),
            "total_dirs_with_layout": len(dir_layouts),
            "layout_types": layout_type_counts,
            "superblocks_found": len(superblocks),
        },
    }


# ── Text output ──────────────────────────────────────────────

def print_layouts_text(result):
    """Print stripe layouts in human-readable text format."""
    summary = result.get("summary", {})
    print("=" * 72)
    print("Lustre Stripe Layout Analysis")
    print("=" * 72)
    print(f"Superblocks found:     {summary.get('superblocks_found', 0)}")
    print(f"Inodes scanned:        {summary.get('total_inodes_scanned', 0)}")
    print(f"Skipped (bad magic):   {summary.get('skipped', 0)}")
    print(f"Files with layout:     {summary.get('total_files_with_layout', 0)}")
    print(f"Dirs with layout:      {summary.get('total_dirs_with_layout', 0)}")
    lt = summary.get("layout_types", {})
    if lt:
        print(f"Layout types:          {lt}")
    print()

    if result.get("error"):
        print(f"ERROR: {result['error']}")
        return

    # File layouts
    file_layouts = result.get("file_layouts", [])
    if file_layouts:
        print("-" * 72)
        print("FILE LAYOUTS")
        print("-" * 72)
        for fl in file_layouts:
            path = fl.get("path", "<unknown>")
            fid = fl.get("fid", "?")
            magic = fl.get("magic", "?")
            layout_gen = fl.get("layout_gen", "?")
            mirror_count = fl.get("mirror_count", 0)
            print(f"\n  FID: {fid}  Inode: {fl.get('inode_addr', '?')}")
            if path != "<unknown>":
                print(f"  Path: {path}")
            print(f"  Magic: {magic}  Layout Gen: {layout_gen}"
                  f"  Mirrors: {mirror_count}")

            for comp in fl.get("components", []):
                ext = comp.get("extent", {})
                ext_s = ext.get("start", "?")
                ext_e = ext.get("end", "?")
                if isinstance(ext_e, int) and ext_e == 0xFFFFFFFFFFFFFFFF:
                    ext_e_str = "EOF"
                else:
                    ext_e_str = str(ext_e)
                print(f"    Component {comp.get('id', '?')}: "
                      f"[{ext_s}-{ext_e_str}] "
                      f"pattern={comp.get('pattern', '?')} "
                      f"stripe_size={comp.get('stripe_size', '?')} "
                      f"stripe_count={comp.get('stripe_count', '?')} "
                      f"flags={comp.get('flags', '?')}")
                pool = comp.get("pool", "")
                if pool:
                    print(f"      Pool: {pool}")
                for s in comp.get("stripes", []):
                    print(f"      OST {s.get('ost_idx', '?')}: "
                          f"objid={s.get('object_id', '?')}")

    # Directory layouts
    dir_layouts = result.get("dir_layouts", [])
    if dir_layouts:
        print()
        print("-" * 72)
        print("DIRECTORY LAYOUTS")
        print("-" * 72)
        for dl in dir_layouts:
            path = dl.get("path", "<unknown>")
            fid = dl.get("fid", "?")
            magic = dl.get("magic", "?")
            print(f"\n  FID: {fid}  Inode: {dl.get('inode_addr', '?')}")
            if path != "<unknown>":
                print(f"  Path: {path}")
            print(f"  Magic: {magic}  "
                  f"Stripe Count: {dl.get('stripe_count', '?')}  "
                  f"Master MDT: {dl.get('master_mdt', '?')}  "
                  f"Hash: {dl.get('hash_type', '?')}")
            pool = dl.get("pool", "")
            if pool:
                print(f"  Pool: {pool}")
            for s in dl.get("stripes", []):
                print(f"    MDT {s.get('mdt_idx', '?')}: "
                      f"fid={s.get('fid', '?')}")

    print()
    print("=" * 72)


# ── CLI entry point ──────────────────────────────────────────

def main():
    try:
        from .lustre_analyze import load_program
    except ImportError:
        from lustre_analyze import load_program

    parser = argparse.ArgumentParser(
        description="Extract Lustre file and directory stripe layouts "
                    "from a vmcore.",
    )
    parser.add_argument("--vmcore", required=True,
                        help="Path to vmcore file")
    parser.add_argument("--vmlinux", required=True,
                        help="Path to vmlinux (debug kernel)")
    parser.add_argument("--mod-dir", default=None,
                        help="Directory containing Lustre .ko files")
    parser.add_argument("--debug-dir", default=None,
                        help="Directory containing .ko.debug files")
    parser.add_argument("--text", action="store_true",
                        help="Text output (default is JSON)")
    parser.add_argument("--pretty", action="store_true",
                        help="Pretty-print JSON "
                             "(also set LUSTRE_DRGN_PRETTY=1)")
    parser.add_argument("--max-inodes", type=int, default=10000,
                        help="Maximum inodes to scan (default: 10000)")
    args = parser.parse_args()

    prog = load_program(
        args.vmcore, args.vmlinux, args.mod_dir, args.debug_dir
    )

    result = get_stripe_layouts(prog, max_inodes=args.max_inodes)

    if args.text:
        print_layouts_text(result)
    else:
        lh.json_output(result, args)


if __name__ == "__main__":
    main()
