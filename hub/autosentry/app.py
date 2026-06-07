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
import os
import threading
import time
from pathlib import Path

from autosentry.alarm import AlarmController
from autosentry.capture import OpenCVCamera
from autosentry.comms.gateway import MeshGateway
from autosentry.config import Settings, load_settings
from autosentry.contracts import (
    Action,
    AlarmCommand,
    AuthorityRecommendation,
    Frame,
    Level,
    NodeStatus,
    ThreatAssessment,
    ThreatState,
)
from autosentry.detection import Detector, TriggerEvaluator
from autosentry.detection.triggers import PERSON_CLASS
from autosentry.notify import Notifier
from autosentry.notify.keyframes import write_keyframe
from autosentry.reasoning import Assessor
from autosentry.state import StateInputs, StateMachine
from autosentry.voice import VoiceAgent
from autosentry.watchdog import Watchdog

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
        # Best-effort keyframe encoder (FR-15); injectable so tests avoid the cv2 dependency.
        self._keyframe_writer = write_keyframe
        # Later-milestone subsystems, constructed now behind their interfaces.
        self.mesh = MeshGateway(settings.comms)
        self.voice = VoiceAgent(settings.voice) if settings.voice.enabled else None
        # M4 power/reliability: liveness watchdog, arming policy, degraded-mode tracking.
        self.watchdog = Watchdog(settings.watchdog.sw_timeout_s)
        # Per-zone arming (FR-14). `armed: true` arms every zone at boot; default disarmed.
        self.armed_zones: set[str] = set(self.zones) if settings.armed else set()
        self.test_mode = False  # OS-8: exercise the chain without latching the real siren
        self.degraded: dict[str, str] = {}  # subsystem -> reason; non-empty = DEGRADED (RR-4)
        # M6: authority-contact recommendations awaiting explicit owner confirmation (SE-5).
        self.pending_authority: list[AuthorityRecommendation] = []

    # --- operator controls (FR-14) ----------------------------------------------------
    def arm(self, zone: str | None = None) -> None:
        """Arm one zone, or every zone when zone is None."""
        self.armed_zones |= {zone} if zone is not None else set(self.zones)

    def disarm(self, zone: str | None = None) -> None:
        """Disarm one zone, or every zone when zone is None."""
        self.armed_zones -= {zone} if zone is not None else set(self.zones)

    def set_test_mode(self, on: bool) -> None:
        self.test_mode = on

    def panic(self, zone: str, now: float | None = None) -> ThreatState:
        """Manual owner override: force ALARM now and actuate, armed or not (FR-14)."""
        now = time.monotonic() if now is None else now
        machine = self.machines[zone]
        before = machine.level
        state = machine.update(StateInputs(panic=True), now=now)
        actions = self._actuate(zone, before, state.level, panic=True)
        log.warning("zone=%s PANIC -> %s", zone, state.level.value)
        self.notifier.log_event(state, None, actions)
        return state

    # --- health / power (RR-4, FR-10) -------------------------------------------------
    def power_alerts(self) -> list[NodeStatus]:
        """Nodes that are offline (tamper/jam) or running on battery — never ignored."""
        return self.mesh.offline_nodes() + self.mesh.on_battery_nodes()

    def health(self) -> dict[str, object]:
        """Operational status for supervision/dashboards (RR-4, FR-10)."""
        return {
            "armed_zones": sorted(self.armed_zones),
            "test_mode": self.test_mode,
            "degraded": dict(self.degraded),
            "offline_nodes": [n.node_id for n in self.mesh.offline_nodes()],
            "on_battery_nodes": [n.node_id for n in self.mesh.on_battery_nodes()],
        }

    def _degrade(self, subsystem: str, reason: str) -> None:
        if self.degraded.get(subsystem) != reason:
            log.error("DEGRADED %s: %s", subsystem, reason)  # loud, never silent (pillar 1)
        self.degraded[subsystem] = reason

    def _recover(self, subsystem: str) -> None:
        if self.degraded.pop(subsystem, None) is not None:
            log.info("recovered %s", subsystem)

    def step(self, zone: str, frame: Frame) -> ThreatState:
        """Process one frame for a zone and return the resulting threat state (M1+M2).

        Orchestration: detect+track -> trigger policy -> [stage-2 on trigger] -> state
        machine -> local alarm + audit log. Stage-2 runs only when stage-1 fires (it is
        expensive); a single armed frame still cannot latch ALARM — the machine requires
        the assessment to persist across the confirmation window (PR-4, pillar 3).
        """
        detector = self.detectors[zone]
        machine = self.machines[zone]
        try:
            tracks = detector.track(frame)
            self._recover("vision")
        except Exception as e:  # camera/model fault — degrade loudly, don't crash (RR-4)
            self._degrade("vision", f"detect failed: {e}")
            return machine.state()
        trig = self.triggers.evaluate(tracks, zone, frame.ts)
        assessment = None
        if trig.fired:
            try:
                assessment = self.assessor.assess(tracks, [frame.image], zone, frame.ts)
                self._recover("reasoning")
            except Exception as e:
                # A stage-2 fault yields no assessment, so the machine can't reach THREAT —
                # degrading never manufactures a false ALARM (pillar 3, RR-4).
                self._degrade("reasoning", f"assess failed: {e}")
        inputs = StateInputs(
            track_present=any(t.cls == PERSON_CLASS for t in tracks),
            stage1_trigger=trig.fired,
            assessment=assessment,
        )
        before = machine.level
        state = machine.update(inputs, now=frame.ts)
        if state.level != before:
            actions = self._actuate(zone, before, state.level, assessment=assessment)
            log.info(
                "zone=%s %s -> %s (%s)%s",
                zone,
                before.value,
                state.level.value,
                state.reason,
                f" trigger={trig.reason}" if trig.reason else "",
            )
            # Persist the triggering frame so the audit row shows what the camera saw (FR-15).
            keyframes = self._save_keyframe(zone, frame) if trig.fired else []
            self.notifier.log_event(state, assessment, actions, keyframes)  # FR-15
            if state.level == Level.ALARM:
                self._notify_owner(state, assessment)  # FR-13, best-effort
        return state

    def _save_keyframe(self, zone: str, frame: Frame) -> list[str]:
        """Encode the event's frame to disk for the audit log (FR-15); best-effort.

        Strictly off the critical path (pillar 1): a failed encode logs and returns no
        keyframe rather than disturbing the alarm or the event row.
        """
        if frame.image is None:
            return []
        fname = f"{zone}-{frame.seq}-{frame.ts:.3f}.jpg"
        path = os.path.join(self.settings.notify.keyframe_dir, fname)
        try:
            if self._keyframe_writer(frame.image, path):
                return [path]
        except Exception as e:  # never let audit-image capture break the pipeline
            log.warning("keyframe capture failed for zone=%s: %s", zone, e)
        return []

    def _actuate(
        self,
        zone: str,
        before: Level,
        now_level: Level,
        *,
        panic: bool = False,
        assessment: ThreatAssessment | None = None,
    ) -> list[str]:
        """Drive the local alarm + mesh + voice on ALARM entry/exit, report the actions.

        Arming gates physical response: a disarmed zone still reaches ALARM in the log but
        sounds nothing. Test mode pulses the siren without latching (OS-8). A manual panic
        overrides both — the owner pressed the button, so it always fires (FR-6/7/14).

        Ordering encodes the pillars: the local siren latches first, then mesh, then voice.
        Each later actuator is best-effort and wrapped, so a dead radio or a hung LLM can
        never block or silence the local alarm (pillar 1) and voice is purely additive,
        never a precondition (FR-12, SE-1).
        """
        actions: list[str] = []
        if now_level == Level.ALARM:
            if self.test_mode and not panic:
                self.alarm.apply(AlarmCommand(action=Action.TEST, zone=zone))
                return ["test_pulse"]  # no latch (FR-14)
            if not (panic or zone in self.armed_zones):
                return ["suppressed_disarmed"]  # monitored + logged, but not sounded
            self.alarm.trigger(zone)
            actions.append("local_alarm")
            if self.settings.comms.enabled:
                try:
                    zone_id = self.zones.index(zone) if zone in self.zones else 0
                    self.mesh.broadcast_alarm(level=list(Level).index(now_level), zone_id=zone_id)
                    actions.append("mesh_alarm")
                    self._recover("mesh")
                except Exception as e:  # mesh fault must not block the local siren (pillar 1)
                    self._degrade("mesh", f"broadcast failed: {e}")
            if self._engage_voice(zone, assessment):
                actions.append("voice_engaged")
            self._recommend_authority(zone, now_level)  # SE-5: human-confirm gated
            actions.append("authority_recommended")
        elif before == Level.ALARM:
            self.alarm.clear(zone)
            actions.append("alarm_cleared")
        return actions

    def _engage_voice(self, zone: str, assessment: ThreatAssessment | None) -> bool:
        """Open the de-escalation dialogue, grounded in the live assessment (FR-11/12).

        Runs only after the siren has already latched, so a voice failure degrades loudly
        but never gates the alarm (FR-12, FMEA F15). Disabled voice or a missing assessment
        (e.g. a manual panic with no vision) simply skips engagement.
        """
        if self.voice is None or assessment is None:
            return False
        try:
            turn = self.voice.greet(assessment)
            log.info("zone=%s voice: %s", zone, turn.text)
            self._recover("voice")
            return True
        except Exception as e:  # a hung/broken voice agent must not affect the alarm
            self._degrade("voice", f"voice failed: {e}")
            return False

    def _notify_owner(self, state: ThreatState, assessment: ThreatAssessment | None) -> None:
        """Queue an owner push (FR-13). Off the critical path: a failure degrades, never gates.

        The notifier persists durably and flushes when online; an internet outage just leaves
        the push queued (OS-5), so this call cannot delay or silence the local alarm (pillar 1).
        """
        try:
            self.notifier.notify(state, assessment)
            self._recover("notify")
        except Exception as e:
            self._degrade("notify", f"notify failed: {e}")

    # --- SE-5 emergency escalation (human-in-the-loop) --------------------------------
    def _recommend_authority(self, zone: str, level: Level) -> AuthorityRecommendation:
        """Surface a contact-authorities recommendation; never auto-dials in v1 (SE-5).

        The recommendation is queued unconfirmed and announced; only an explicit
        `confirm_authority_contact` (a human action) may mark it confirmed, keeping a person
        in the loop on the highest-consequence escalation (docs/SAFETY_ETHICS_LEGAL.md §6).
        """
        rec = AuthorityRecommendation(
            zone=zone,
            threat_level=level.value,
            reason="confirmed threat reached ALARM",
            ts=time.monotonic(),
        )
        self.pending_authority.append(rec)
        log.warning(
            "zone=%s AUTHORITY CONTACT RECOMMENDED — awaiting owner confirmation (SE-5)", zone
        )
        return rec

    def confirm_authority_contact(self, rec: AuthorityRecommendation) -> bool:
        """Record an explicit human confirmation of a non-recoverable escalation (SE-5).

        This is the only path that may mark a recommendation confirmed. v1 still does not
        auto-contact emergency services — confirmation authorizes the owner's own action and
        is logged for audit.
        """
        rec.confirmed = True
        log.warning("zone=%s authority contact CONFIRMED by owner (SE-5)", rec.zone)
        return True

    def run(self) -> int:
        """Drive every configured camera through the pipeline until interrupted (FR-2, FR-16).

        Each zone gets its own capture + worker thread, so cameras are independent: a stall
        or reconnect on one zone never blocks another, and the per-zone detectors/state
        machines keep track IDs and threat levels from colliding across zones (FR-16).
        """
        sources = self.settings.capture.sources
        if not sources:
            raise SystemExit("no capture sources configured")
        self._ensure_models()  # fetch any missing local models before the loop (FR-18)
        cap = self.settings.capture
        cams = [
            OpenCVCamera(
                source=src,
                zone=zone,
                width=cap.width,
                height=cap.height,
                fps=cap.fps,
                timeout_s=cap.timeout_s,
            )
            for src, zone in zip(sources, self.zones, strict=False)
        ]
        self.watchdog.ready()  # tell systemd we're up (RR-1)
        dashboard = self._start_dashboard()  # non-critical operator UI (FR-17)
        stop = threading.Event()
        workers = [
            threading.Thread(
                target=self._run_camera, args=(cam, stop), name=f"zone-{cam.zone}", daemon=True
            )
            for cam in cams
        ]
        try:
            for w in workers:
                w.start()
            while any(w.is_alive() for w in workers):
                for w in workers:
                    w.join(timeout=0.5)
        except KeyboardInterrupt:
            log.info("shutting down")
        finally:
            stop.set()
            for cam in cams:
                cam.close()
            if dashboard is not None:
                dashboard.shutdown()
        return 0

    def _ensure_models(self) -> None:
        """Provision local models at boot, off the steady-state critical path (FR-18).

        Runs once before the camera loop starts, never inside `step()`, so a model download
        can't stall the detection→alarm path (pillar 1). A fetch failure degrades loudly: the
        affected backend will then fail its own load and surface DEGRADED, never silently.
        """
        if not self.settings.models.auto_download:
            return
        try:
            from autosentry.models import ensure_present

            errors = []
            for r in ensure_present(self.settings):
                if r.status == "error":
                    errors.append(r.label)
                elif r.status == "fetched":
                    log.info("provisioned model: %s", r.label)
            if errors:
                self._degrade("models", f"could not provision: {', '.join(errors)}")
            else:
                self._recover("models")
        except Exception as e:  # provisioning must never stop the hub from coming up
            self._degrade("models", f"provisioning failed: {e}")

    def _start_dashboard(self):
        """Start the opt-in operator dashboard (FR-17); a failure here never gates the loop.

        Off the critical path by construction: it only reads Hub state and routes to the
        operator controls a human already has. If it can't bind, we log and run headless.
        """
        if not self.settings.dashboard.enabled:
            return None
        try:
            from autosentry.dashboard.server import start_dashboard
            from autosentry.dashboard.service import DashboardService

            service = DashboardService(self, event_limit=self.settings.dashboard.event_limit)
            server, _ = start_dashboard(
                service, self.settings.dashboard.host, self.settings.dashboard.port
            )
            return server
        except Exception as e:  # never let the UI stop the pipeline (pillar 1)
            self._degrade("dashboard", f"dashboard start failed: {e}")
            return None

    def _run_camera(self, cam: OpenCVCamera, stop: threading.Event) -> None:
        """Per-zone worker: pull frames and step the pipeline until stopped (FR-16)."""
        log.info(
            "AutoSentry zone=%s source=%s armed=%s",
            cam.zone,
            cam.source,
            cam.zone in self.armed_zones,
        )
        for frame in cam.frames():
            if stop.is_set():
                break
            self.step(cam.zone, frame)
            self.watchdog.ping()  # liveness; a hung loop stops pinging -> restart (RR-1)


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
