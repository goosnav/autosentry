"""Preflight self-test (OS-8, production QA gate).

`autosentry --selftest` runs a non-destructive readiness check on a unit and exits 0 only if
every *critical* check passes — the single command the production QA gate and field service
run before declaring a unit good (docs/PRODUCTION_PROVISIONING.md §2). It never arms anything
and never sounds the siren; it only inspects configuration, secrets, models, and the camera.

The check logic is pure and unit-tested with injected probes (no camera, no network, no
models); `main()` wires in the real probes.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from autosentry.config import Settings


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""
    critical: bool = True  # a non-critical failure warns but does not fail the unit


# A camera probe takes a source string and returns (opened_ok, human_detail).
CameraProbe = Callable[[str], tuple[bool, str]]
# A models probe returns (all_present, human_detail).
ModelsProbe = Callable[[], tuple[bool, str]]


def _default_camera_probe(source: str) -> tuple[bool, str]:
    """Open the camera and grab one frame (lazy cv2 via OpenCVCamera); best-effort."""
    try:
        from autosentry.capture import OpenCVCamera

        ok = OpenCVCamera(source=source, zone="selftest").probe()
        return (ok, "frame captured" if ok else "no frame / device unavailable")
    except Exception as e:  # missing device / no cv2 / bad source
        return (False, f"open failed: {e}")


def _default_models_probe(settings: Settings) -> tuple[bool, str]:
    """Report-only presence check of every required model (never fetches)."""
    try:
        from autosentry.models import ensure_present

        report = ensure_present(settings, report_only=True)
        missing = [r.label for r in report if r.status != "present"]
        if missing:
            return (False, "missing: " + ", ".join(missing))
        return (True, f"{len(report)} model(s) present")
    except Exception as e:
        return (False, f"check failed: {e}")


def run_selftest(
    settings: Settings,
    *,
    env: Mapping[str, str] | None = None,
    camera_probe: CameraProbe | None = None,
    models_probe: ModelsProbe | None = None,
) -> list[CheckResult]:
    """Run the preflight checks and return their results (pure; probes are injectable)."""
    env = os.environ if env is None else env
    camera_probe = camera_probe or _default_camera_probe
    models_probe = models_probe or (lambda: _default_models_probe(settings))

    results: list[CheckResult] = []

    # Config loaded + sources/zones 1:1 (the model validator already enforced this on load).
    n = len(settings.capture.zones)
    zones = ", ".join(settings.capture.zones)
    results.append(CheckResult("config", n >= 1, f"{n} zone(s): {zones}"))

    # Mesh key present (critical only when the radio link is enabled, SR-3).
    if settings.comms.enabled:
        key = env.get(settings.comms.key_env)
        results.append(
            CheckResult(
                "mesh_key",
                bool(key),
                "set" if key else f"{settings.comms.key_env} not set",
            )
        )

    # Models provisioned (FR-18).
    ok, detail = models_probe()
    results.append(CheckResult("models", ok, detail))

    # Every camera opens and yields a frame (FR-1). One result per zone.
    for source, zone in zip(settings.capture.sources, settings.capture.zones, strict=True):
        cam_ok, cam_detail = camera_probe(source)
        results.append(CheckResult(f"camera:{zone}", cam_ok, cam_detail))

    # Weapon model configured — non-critical (the unit runs, but can't detect weapons).
    has_weapon = settings.detection.weapon_model is not None
    results.append(
        CheckResult(
            "weapon_model",
            has_weapon,
            "configured" if has_weapon else "UNSET — stage-1 weapon detection disabled",
            critical=False,
        )
    )

    return results


def passed(results: list[CheckResult]) -> bool:
    """A unit passes only if every *critical* check is ok."""
    return all(r.ok for r in results if r.critical)


def format_report(results: list[CheckResult]) -> str:
    lines = ["AutoSentry preflight self-test:"]
    for r in results:
        mark = "PASS" if r.ok else ("WARN" if not r.critical else "FAIL")
        lines.append(f"  [{mark}] {r.name}: {r.detail}")
    lines.append("RESULT: " + ("READY" if passed(results) else "NOT READY — fix FAILs above"))
    return "\n".join(lines)
