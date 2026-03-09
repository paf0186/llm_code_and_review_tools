"""drgn-based Lustre vmcore analysis scripts.

These scripts use drgn (https://github.com/osandov/drgn) to
programmatically analyze kernel crash dumps with full access to
Lustre data structures, local variables, and typed Python objects.

Unlike the crash wrapper (which drives crash via subprocess and
parses text), drgn scripts access memory and types directly as
a Python library — no text parsing, no sentinels, no subprocess.
"""
