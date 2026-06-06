"""AutoSentry hub entrypoint — wires the subsystems into the pipeline (FR-2).

Data flow (ICD-7):

    capture -> detect -> tracker -> triggers -> [stage-2] -> state -> {alarm, mesh, voice, notify}

M1 implements the left half end to end: capture -> detect/track -> triggers -> state machine,
logging every level change. Stage-2 reasoning (M2) and the response actuators (M2/M3/M5/M6)
drop in behind their typed interfaces without disturbing this loop.

Run:
    autosentry --source 0                 # webcam index / device path / rtsp URL
    autosentry --config path/to/config.yaml
    python -m autosentry.app --source 0
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from autosentry.alarm import AlarmController
from autosentry.capture import OpenCVCamera
from autosentry.comms.gateway import MeshGateway
from autosentry.config import Settings, load_settings
from autosentry.contracts import Frame, Level, ThreatState
from autosentry.detection import Detector, TriggerEvaluator
from autosentry.detection.triggers import PERSON_CLASS
from autosentry.notify import Notifier
from autosentry.reasoning import Assessor
from autosentry.state import StateInputs, StateMachine
from autosentry.voice import VoiceAgent

_DEFAULT_CONFIG = Path(__file__).with_name("config.yaml")
log = logging.getLogger("autosentry")


class Hub:
    """Owns one instance of every subsystem and the per-zone pipeline state."""

    def __init__(
        self,
        settings: Settings,
        detector: Detector | None = None,
        assessor: Assessor | None = None,
        notifier: Notifier | None = None,
    ) -> None:
        self.settings = settings
        self.zones = settings.capture.zones
        # One detector (own tracker) per zone so track IDs don't collide across cameras.
        # An injected detector (tests) is shared across zones by design.
        self.detectors = {z: detector or Detector(settings.detection) for z in self.zones}
        self.triggers = TriggerEvaluator(settings.trigger)
        self.machines = {z: StateMachine(z, settings.state) for z in self.zones}
        # M2 subsystems: stage-2 reasoning, local alarm, and the always-on audit log.
        self.assessor = assessor or Assessor(settings.reasoning)
        self.alarm = AlarmController(settings.alarm)
        self.notifier = notifier or Notifier(settings.notify)  # FR-15 audit always runs
        # Later-milestone subsystems, constructed now behind their interfaces.
        self.mesh = MeshGateway(settings.comms)
        self.voice = VoiceAgent(settings.voice) if settings.voice.enabled else None

    def step(self, zone: str, frame: Frame) -> ThreatState:
        """Process one frame for a zone and return the resulting threat state (M1+M2).

        Orchestration: detect+track -> trigger policy -> [stage-2 on trigger] -> state
        machine -> local alarm + audit log. Stage-2 runs only when stage-1 fires (it is
        expensive); a single armed frame still cannot latch ALARM — the machine requires
        the assessment to persist across the confirmation window (PR-4, pillar 3).
        """
        detector = self.detectors[zone]
        machine = self.machines[zone]
        tracks = detector.track(frame)
        trig = self.triggers.evaluate(tracks, zone, frame.ts)
        assessment = (
            self.assessor.assess(tracks, [frame.image], zone, frame.ts) if trig.fired else None
        )
        inputs = StateInputs(
            track_present=any(t.cls == PERSON_CLASS for t in tracks),
            stage1_trigger=trig.fired,
            assessment=assessment,
        )
        before = machine.level
        state = machine.update(inputs, now=frame.ts)
        if state.level != before:
            actions = self._actuate(zone, before, state.level)
            log.info(
                "zone=%s %s -> %s (%s)%s",
                zone,
                before.value,
                state.level.value,
                state.reason,
                f" trigger={trig.reason}" if trig.reason else "",
            )
            self.notifier.log_event(state, assessment, actions)  # FR-15
        return state

    def _actuate(self, zone: str, before: Level, now_level: Level) -> list[str]:
        """Drive the local alarm + mesh on ALARM entry/exit, report the actions (FR-6/7)."""
        actions: list[str] = []
        if now_level == Level.ALARM:
            self.alarm.trigger(zone)
            actions.append("local_alarm")
            if self.settings.comms.enabled:
                zone_id = self.zones.index(zone) if zone in self.zones else 0
                self.mesh.broadcast_alarm(level=list(Level).index(now_level), zone_id=zone_id)
                actions.append("mesh_alarm")
        elif before == Level.ALARM:
            self.alarm.clear(zone)
            actions.append("alarm_cleared")
        return actions

    def run(self) -> int:
        """Drive the primary camera through the pipeline until interrupted (FR-2).

        Multi-camera concurrency is M6; M1 runs the first configured source live so the
        vision core can be exercised on the Jetson + webcam dev rig.
        """
        if not self.settings.capture.sources:
            raise SystemExit("no capture sources configured")
        zone = self.zones[0]
        cam = OpenCVCamera(
            source=self.settings.capture.sources[0],
            zone=zone,
            width=self.settings.capture.width,
            height=self.settings.capture.height,
            fps=self.settings.capture.fps,
            timeout_s=self.settings.capture.timeout_s,
        )
        log.info("AutoSentry M1 vision core: zone=%s source=%s", zone, cam.source)
        try:
            for frame in cam.frames():
                self.step(zone, frame)
        except KeyboardInterrupt:
            log.info("shutting down")
        finally:
            cam.close()
        return 0


def build_hub(config: str | Path | None = None) -> Hub:
    """Load settings and construct a fully-wired (but not yet running) hub."""
    return Hub(load_settings(config or _DEFAULT_CONFIG))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="autosentry", description="AutoSentry hub")
    parser.add_argument("--config", default=None, help="path to config.yaml")
    parser.add_argument("--source", default=None, help="override capture source (index/path/rtsp)")
    parser.add_argument("--zone", default=None, help="zone name for a single --source override")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    settings = load_settings(args.config or _DEFAULT_CONFIG)
    if args.source is not None:
        settings.capture.sources = [args.source]
        settings.capture.zones = [args.zone or "default"]

    return Hub(settings).run()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
