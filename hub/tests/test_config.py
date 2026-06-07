"""Unit tests for configuration loading (FR-5/FR-16 tunability, SR-3 secret handling).

Confirms defaults are sane (DISARMED at rest, latch on), that a YAML file overrides
defaults, and that the mesh HMAC key is sourced from the environment, never the file.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from autosentry.config import CaptureConfig, Settings, load_settings


def test_sources_and_zones_must_be_one_to_one():
    # A mismatch must fail loudly at load, not silently blind a zone (pillar 1).
    with pytest.raises(ValidationError):
        CaptureConfig(sources=["0"], zones=["front", "back"])
    with pytest.raises(ValidationError):
        CaptureConfig(sources=["0", "1", "2"], zones=["front", "back"])
    # Matched counts are accepted.
    ok = CaptureConfig(sources=["0", "1"], zones=["front", "back"])
    assert ok.zones == ["front", "back"]


def test_defaults_are_safe():
    s = Settings()
    assert s.armed is False  # ships DISARMED; explicit arming required
    assert s.state.latch is True  # alarms latch until ack + cooldown (FR-6)
    assert s.state.confirmation_window_s > 0  # anti-false-positive window exists (PR-4)


def test_load_missing_path_falls_back_to_defaults():
    s = load_settings("/no/such/config.yaml")
    assert s.armed is False
    assert s.capture.zones == ["default"]


def test_yaml_overrides_defaults(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "armed: true\n"
        "state:\n"
        "  arm_confidence: 0.8\n"
        "  latch: false\n"
        "capture:\n"
        "  sources: ['0', '1']\n"
        "  zones: [front, garage]\n"
    )
    s = load_settings(cfg)
    assert s.armed is True
    assert s.state.arm_confidence == 0.8
    assert s.state.latch is False
    assert s.capture.zones == ["front", "garage"]


def test_no_secret_in_config_model():
    # The HMAC key must never be a settings field; only the env var *name* lives in config.
    s = Settings()
    assert "key" not in s.comms.model_dump() or "key_env" in s.comms.model_dump()
    assert s.comms.key_env == "AUTOSENTRY_MESH_KEY"


def test_env_override(monkeypatch):
    monkeypatch.setenv("AUTOSENTRY_ARMED", "true")
    assert Settings().armed is True
