"""Security verification tests — pillar 5, SR-3 (secret hygiene) + SR-4 (attack surface).

These pin the self-defense invariants as code so they cannot silently regress. They are the
V-Model right-arm activities for SR-3 (Inspection) and SR-4 (Analysis), made reproducible in
CI rather than performed once by hand:

- **SR-3:** the mesh HMAC key is loaded from the environment with *no* committed default and
  *no* key field on any config model; the repo's ignore rules exclude secret artifacts and
  `config.yaml` carries only the env-var *name*, never key material.
- **SR-4:** the detection→alarm critical path (capture, detection, reasoning, state, alarm,
  comms) exposes no inbound network listener; the only inbound surface is the opt-in
  dashboard, which binds loopback by default and lives off the critical path.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from autosentry.comms.gateway import MeshGateway
from autosentry.config import CommsConfig, Settings

_REPO = Path(__file__).resolve().parents[2]
# Packages that make up the detection→alarm critical path (CLAUDE.md §2, pillar 1).
_CRITICAL_PKGS = ["capture", "detection", "reasoning", "state", "alarm", "comms"]


# --- SR-3: secret hygiene -------------------------------------------------------------
def test_mesh_key_loads_from_env_with_no_committed_default(monkeypatch):
    monkeypatch.delenv("AUTOSENTRY_MESH_KEY", raising=False)
    gw = MeshGateway(CommsConfig())
    # No env, no committed fallback ⇒ a hard, loud failure — never a silent default key.
    with pytest.raises(RuntimeError):
        gw._get_key()


def test_mesh_key_uses_the_env_value_when_set(monkeypatch):
    monkeypatch.setenv("AUTOSENTRY_MESH_KEY", "unit-test-key")
    gw = MeshGateway(CommsConfig())
    assert gw._get_key() == b"unit-test-key"


def test_comms_config_holds_only_the_env_var_name_not_a_key():
    cfg = CommsConfig()
    assert cfg.key_env == "AUTOSENTRY_MESH_KEY"  # the *name*, not a secret
    assert not hasattr(cfg, "key")  # no field that could carry key material


def test_config_yaml_contains_no_key_material():
    text = (_REPO / "hub" / "autosentry" / "config.yaml").read_text()
    assert "key_env:" in text  # only the env-var name is referenced
    # No `key: <value>` assignment anywhere in the shipped config.
    assert re.search(r"^\s*key\s*:", text, re.MULTILINE) is None


def test_gitignore_excludes_secret_artifacts():
    gi = (_REPO / ".gitignore").read_text()
    for pattern in (".env", "*.key", "*.pem", "secrets/", "node_keys.yaml"):
        assert pattern in gi, f"missing .gitignore rule for {pattern}"


# --- SR-4: critical-path attack surface -----------------------------------------------
def test_dashboard_is_opt_in_and_binds_loopback_by_default():
    s = Settings()
    assert s.dashboard.enabled is False  # off unless an operator opts in (FR-17)
    assert s.dashboard.host == "127.0.0.1"  # loopback — not exposed to the network


def test_critical_path_exposes_no_inbound_network_listener():
    pkg_root = _REPO / "hub" / "autosentry"
    listeners = ("HTTPServer", "serve_forever", "socketserver", ".bind(")
    offenders: list[str] = []
    for pkg in _CRITICAL_PKGS:
        for py in (pkg_root / pkg).rglob("*.py"):
            text = py.read_text()
            for token in listeners:
                if token in text:
                    offenders.append(f"{py.relative_to(pkg_root)}: {token}")
    assert not offenders, f"inbound listener on the critical path (SR-4): {offenders}"
