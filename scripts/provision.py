#!/usr/bin/env python3
"""Provisioning helper (SR-3): generate the per-deployment mesh key and hub env file.

One AutoSentry property shares a single HMAC key across its hub and all alarm nodes. That key
is a secret: it is never committed, never stored in config.yaml, and lives only in the hub's
environment (`/etc/autosentry/mesh.env`) and in each node's flash. This tool makes a
fresh key and writes the hub side; `scripts/provision_node.sh` flashes the node side with the
same key. See docs/PRODUCTION_PROVISIONING.md.

Keys are URL-safe tokens (alphanumeric + -_), so they pass cleanly through a shell and a C
string literal at flash time without escaping surprises.

Usage:
  python scripts/provision.py new-key                       # print a fresh key
  python scripts/provision.py hub-env --key K [--out PATH]   # write AUTOSENTRY_MESH_KEY=K
  python scripts/provision.py node-flags --key K --addr N    # print the pio build flags
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys

DEFAULT_ENV = "/etc/autosentry/mesh.env"
PLACEHOLDER = "REPLACE_AT_PROVISIONING"


def new_key(nbytes: int = 32) -> str:
    """A fresh URL-safe mesh key (>= 256 bits of entropy by default)."""
    return secrets.token_urlsafe(nbytes)


def _validate(key: str) -> None:
    if not key or key == PLACEHOLDER:
        raise SystemExit("refusing to provision the placeholder / empty key (SR-3)")


def write_hub_env(key: str, out: str) -> None:
    _validate(key)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    # Write atomically with 0600 perms so the key is never world-readable.
    tmp = f"{out}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(f"AUTOSENTRY_MESH_KEY={key}\n")
    os.replace(tmp, out)
    os.chmod(out, 0o600)
    print(f"wrote {out} (mode 600) — keep this secret; back it up to add nodes later")


def node_flags(key: str, addr: int) -> str:
    """The PlatformIO build flags that flash a node with this key + address."""
    _validate(key)
    if addr < 1:
        raise SystemExit("node address must be >= 1 (0 is the hub)")
    # The macro must expand to a C string literal; URL-safe keys need no further escaping.
    return f'-DNODE_ADDR={addr} -DAUTOSENTRY_MESH_KEY=\\"{key}\\"'


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="AutoSentry provisioning helper (SR-3)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_new = sub.add_parser("new-key", help="print a fresh mesh key")
    p_new.add_argument("--bytes", type=int, default=32, help="entropy bytes (default 32)")

    p_env = sub.add_parser("hub-env", help="write the hub's AUTOSENTRY_MESH_KEY env file")
    p_env.add_argument("--key", required=True)
    p_env.add_argument("--out", default=DEFAULT_ENV)

    p_flags = sub.add_parser("node-flags", help="print PlatformIO build flags for a node")
    p_flags.add_argument("--key", required=True)
    p_flags.add_argument("--addr", type=int, required=True)

    args = ap.parse_args(argv)
    if args.cmd == "new-key":
        print(new_key(args.bytes))
    elif args.cmd == "hub-env":
        write_hub_env(args.key, args.out)
    elif args.cmd == "node-flags":
        print(node_flags(args.key, args.addr))
    return 0


if __name__ == "__main__":
    sys.exit(main())
