"""ICD-7 — the typed data contracts that cross module boundaries.

These are the *only* types allowed to pass between subsystems (requirement IR-4).
Loose dicts across a seam are a defect. See docs/INTERFACES.md (ICD-7).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from pydantic import BaseModel, Field


class Level(str, Enum):
    """Threat state-machine levels (docs/ARCHITECTURE.md §4)."""

    NORMAL = "NORMAL"
    WATCH = "WATCH"
    SUSPECT = "SUSPECT"
    THREAT = "THREAT"
    ALARM = "ALARM"


class Action(str, Enum):
    """Local alarm actions (ICD-4)."""

    ARM = "ARM"
    TRIGGER = "TRIGGER"
    CLEAR = "CLEAR"
    TEST = "TEST"


class MsgType(str, Enum):
    """LoRa mesh message types (ICD-3 / docs/COMMS_PROTOCOL.md)."""

    ALARM = "ALARM"
    ACK = "ACK"
    HEARTBEAT = "HEARTBEAT"
    HEARTBEAT_ACK = "HEARTBEAT_ACK"
    STATUS = "STATUS"
    CONFIG = "CONFIG"
    TEST = "TEST"


@dataclass(frozen=True)
class BBox:
    """Axis-aligned bounding box in pixel coords."""

    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2.0

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2.0


@dataclass
class Frame:
    """A captured frame with provenance (ICD-1). `image` is an HxWx3 ndarray."""

    zone: str
    ts: float
    image: object  # numpy.ndarray; kept as object to avoid importing numpy here
    seq: int


@dataclass
class Detection:
    """A single stage-1 detection (FR-3)."""

    cls: str  # e.g. person, handgun, rifle, knife
    conf: float
    bbox: BBox
    ts: float


@dataclass
class Track:
    """A subject tracked across frames by ByteTrack (FR-3)."""

    track_id: int
    cls: str
    bbox: BBox
    first_ts: float
    last_ts: float
    history: list[BBox] = field(default_factory=list)
    # Per-bbox capture timestamps, parallel to `history` (history_ts[i] is when history[i]
    # was seen). Lets the trigger policy measure *recent* motion over a time window instead
    # of a lifetime average, so a loiter-then-sprint can't hide under the threshold (FR-3).
    history_ts: list[float] = field(default_factory=list)


class ThreatAssessment(BaseModel):
    """Stage-2 VLM output — schema-validated (FR-4, FMEA F7).

    Pydantic enforces the contract so a malformed/hallucinated model response is
    rejected before it can influence the state machine.
    """

    armed: bool
    weapon_type: str | None = None
    intent: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
    description: str = ""
    zone: str
    ts: float


@dataclass
class ThreatState:
    """Current threat level for a zone (FR-5)."""

    level: Level
    zone: str
    since: float
    reason: str


@dataclass
class AlarmCommand:
    """Command to the local alarm peripherals (ICD-4)."""

    action: Action
    zone: str


@dataclass
class MeshMessage:
    """An application-level mesh message; serialized to the wire by comms.protocol (ICD-3)."""

    type: MsgType
    dst: int
    payload: bytes
    counter: int


@dataclass
class NodeStatus:
    """Hub-side view of an alarm node's health (FR-8, FR-10)."""

    node_id: int
    online: bool
    battery_mv: int
    on_battery: bool
    last_seen: float


@dataclass
class VoiceTurn:
    """One turn of the de-escalation dialogue, with its grounding vision context (FR-11)."""

    role: str  # "subject" | "agent"
    text: str
    vision_context: ThreatAssessment | None
    ts: float


@dataclass
class Notification:
    """Owner push payload (ICD-6, FR-13). Best-effort, never in the alarm critical path."""

    event_id: int
    zone: str
    ts: float
    threat_level: str
    assessment_summary: str
    keyframe_ref: str | None = None


@dataclass
class AuthorityRecommendation:
    """A recommendation to contact authorities, gated on human confirmation (SE-5).

    AutoSentry never auto-contacts emergency services in v1; this record is surfaced to the
    owner and only `confirmed` by an explicit human action — keeping a human in the loop on
    the highest-consequence, non-recoverable escalation (docs/SAFETY_ETHICS_LEGAL.md §6).
    """

    zone: str
    threat_level: str
    reason: str
    ts: float
    confirmed: bool = False
