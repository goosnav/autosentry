"""Unit tests for the preflight self-test (OS-8; selftest.py).

The check logic runs against injected probes — no camera, no models, no network. Pins: a
clean unit reads READY (exit 0); a missing camera or model or mesh key is a critical FAIL
(exit 1); an unset weapon model only WARNs (non-critical).
"""

from __future__ import annotations

from autosentry.config import CaptureConfig, CommsConfig, DetectionConfig, Settings
from autosentry.selftest import format_report, passed, run_selftest


def _settings(**kw) -> Settings:
    s = Settings()
    s.capture = CaptureConfig(sources=["0"], zones=["front"])
    s.detection = DetectionConfig(weapon_model="models/weapons.pt")
    s.comms = CommsConfig(enabled=False)
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def _CAM_OK(src):
    return (True, "frame captured")


def _CAM_BAD(src):
    return (False, "no frame")


def _MODELS_OK():
    return (True, "3 model(s) present")


def _MODELS_BAD():
    return (False, "missing: VLM (qwen2-vl:2b)")


def test_clean_unit_is_ready():
    res = run_selftest(_settings(), camera_probe=_CAM_OK, models_probe=_MODELS_OK)
    assert passed(res) is True
    assert "READY" in format_report(res)


def test_missing_camera_fails():
    res = run_selftest(_settings(), camera_probe=_CAM_BAD, models_probe=_MODELS_OK)
    assert passed(res) is False
    cam = next(r for r in res if r.name == "camera:front")
    assert cam.ok is False and cam.critical is True


def test_missing_model_fails():
    res = run_selftest(_settings(), camera_probe=_CAM_OK, models_probe=_MODELS_BAD)
    assert passed(res) is False


def test_unset_weapon_model_only_warns():
    s = _settings()
    s.detection = DetectionConfig(weapon_model=None)
    res = run_selftest(s, camera_probe=_CAM_OK, models_probe=_MODELS_OK)
    weapon = next(r for r in res if r.name == "weapon_model")
    assert weapon.ok is False and weapon.critical is False
    assert passed(res) is True  # non-critical -> unit still READY


def test_mesh_key_checked_only_when_comms_enabled():
    # comms disabled -> no mesh_key check at all
    res = run_selftest(_settings(), camera_probe=_CAM_OK, models_probe=_MODELS_OK)
    assert not any(r.name == "mesh_key" for r in res)
    # comms enabled, key absent -> critical FAIL
    s = _settings(comms=CommsConfig(enabled=True))
    res = run_selftest(s, env={}, camera_probe=_CAM_OK, models_probe=_MODELS_OK)
    key = next(r for r in res if r.name == "mesh_key")
    assert key.ok is False
    assert passed(res) is False
    # comms enabled, key present -> ok
    res = run_selftest(
        s, env={"AUTOSENTRY_MESH_KEY": "k"}, camera_probe=_CAM_OK, models_probe=_MODELS_OK
    )
    assert next(r for r in res if r.name == "mesh_key").ok is True


def test_camera_probe_runs_per_zone():
    s = _settings(capture=CaptureConfig(sources=["0", "1"], zones=["front", "back"]))
    res = run_selftest(s, camera_probe=_CAM_OK, models_probe=_MODELS_OK)
    cams = [r for r in res if r.name.startswith("camera:")]
    assert {c.name for c in cams} == {"camera:front", "camera:back"}
