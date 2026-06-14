"""Unit tests for the provisioning helper (SR-3; scripts/provision.py).

Pins the secret-handling contract: keys are high-entropy and shell/C-safe, the placeholder
and empty keys are refused, the hub env file is written 0600, and node build flags carry the
address + key in the form the firmware expects.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

from provision import new_key, node_flags, write_hub_env  # noqa: E402


def test_new_key_is_unique_and_url_safe():
    a, b = new_key(), new_key()
    assert a != b  # fresh randomness each call
    assert len(a) >= 32
    assert all(c.isalnum() or c in "-_" for c in a)  # shell- and C-string-safe


def test_node_flags_carry_addr_and_key():
    flags = node_flags("abc123", 4)
    assert "-DNODE_ADDR=4" in flags
    assert 'AUTOSENTRY_MESH_KEY=\\"abc123\\"' in flags


def test_node_flags_reject_placeholder_and_bad_addr():
    with pytest.raises(SystemExit):
        node_flags("REPLACE_AT_PROVISIONING", 1)
    with pytest.raises(SystemExit):
        node_flags("realkey", 0)  # 0 is the hub address, nodes are >= 1


def test_hub_env_is_written_0600(tmp_path):
    out = tmp_path / "mesh.env"
    write_hub_env("s3cret-key", str(out))
    assert out.read_text() == "AUTOSENTRY_MESH_KEY=s3cret-key\n"
    assert (out.stat().st_mode & 0o777) == 0o600  # not world-readable


def test_hub_env_refuses_placeholder(tmp_path):
    with pytest.raises(SystemExit):
        write_hub_env("REPLACE_AT_PROVISIONING", str(tmp_path / "mesh.env"))
