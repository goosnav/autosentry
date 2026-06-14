"""Configuration (pydantic-settings + config.yaml).

All tunable thresholds live here so sensitivity can change without touching logic
(requirements FR-5, FR-16). Secrets (e.g. the mesh HMAC key) are NOT stored in the
repo — they load from environment or an out-of-tree path (see docs/SECURITY.md, SR-3).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class CaptureConfig(BaseModel):
    sources: list[str] = ["0"]  # device index, /dev path, or rtsp URL per zone
    zones: list[str] = ["default"]
    width: int = 1920
    height: int = 1080
    fps: int = 15
    timeout_s: float = 5.0  # no-frame -> reconnect + DEGRADED (FMEA F1)

    @model_validator(mode="after")
    def _sources_match_zones(self) -> CaptureConfig:
        # sources↔zones are strictly 1:1 (one camera per zone, FR-16). Fail loudly at load
        # rather than letting a mismatch silently drop a camera or leave a zone blind — a
        # blind zone on a security system is exactly the silent failure pillar 1 forbids.
        if len(self.sources) != len(self.zones):
            raise ValueError(
                f"capture.sources ({len(self.sources)}) and capture.zones "
                f"({len(self.zones)}) must be 1:1 — each zone needs exactly one source"
            )
        return self


class DetectionConfig(BaseModel):
    model: str = "yolov8n.pt"
    weapon_model: str | None = None  # fine-tuned head (docs/VISION_PIPELINE.md §6)
    models_dir: str = "models"  # local weight cache (set from ModelsConfig.dir); runs offline
    conf_person: float = 0.4
    conf_weapon: float = 0.5
    device: str = "auto"  # auto | cuda | cpu | tensorrt
    # Tracker (ByteTrack on Jetson; portable IoU tracker for dev). FR-3.
    track_iou: float = 0.3  # min IoU to associate a detection with an existing track
    track_max_age: int = 30  # frames a track survives unmatched before it's dropped
    track_history: int = 30  # bbox history kept per track (for approach/loiter signals)


class TriggerConfig(BaseModel):
    loiter_s: float = 20.0
    approach_px_s: float = 120.0
    approach_window_s: float = 2.0  # measure approach speed over this recent window, not lifetime
    restricted_zones: list[str] = []
    restricted_hours: list[int] = []  # hours (0-23) considered restricted


class ReasoningConfig(BaseModel):
    backend: str = "ollama"  # ollama | llamacpp
    model: str = "qwen2-vl:2b"
    endpoint: str = "http://127.0.0.1:11434"
    timeout_s: float = 4.0  # hard timeout -> conservative fallback (FMEA F6)
    keyframes: int = 3


class StateConfig(BaseModel):
    watch_timeout_s: float = 30.0
    arm_confidence: float = 0.6  # stage-2 confidence to enter THREAT
    confirmation_window_s: float = 1.5  # THREAT must persist this long -> ALARM (PR-2)
    cooldown_s: float = 60.0  # quiet period before ALARM auto-relaxes after clear
    latch: bool = True  # ALARM stays until threat gone AND owner ack (FR-6)


class AlarmConfig(BaseModel):
    siren_gpio: int | None = None
    strobe_gpio: int | None = None
    audio_device: str | None = None
    latch: bool = True  # ALARM stays until threat gone AND owner ack (FR-6)


class CommsConfig(BaseModel):
    enabled: bool = False  # open the radio link + broadcast on ALARM (needs hardware); M3
    port: str = "/dev/ttyUSB0"
    baud: int = 115200
    net_id: int = 1
    hub_addr: int = 0
    hb_interval_s: float = 5.0
    hb_miss_max: int = 3  # missed heartbeats -> offline / fail-safe (FR-9, PR-7)
    retries: int = 3
    broadcast_repeats: int = 3
    key_env: str = "AUTOSENTRY_MESH_KEY"  # HMAC key loaded from env, never committed (SR-3)


class VoiceConfig(BaseModel):
    enabled: bool = True
    stt_model: str = "small"
    llm_model: str = "qwen2.5:3b"
    llm_endpoint: str = "http://127.0.0.1:11434"
    tts_voice: str = "en_US-amy-medium"
    max_reply_tokens: int = 80
    turn_timeout_s: float = 3.0  # voice is non-critical; never blocks alarm (FMEA F15)
    models_dir: str = "models"  # local STT/TTS cache (set from ModelsConfig.dir)


class NotifyConfig(BaseModel):
    enabled: bool = False
    endpoint: str | None = None
    queue_path: str = "events.db"
    keyframe_dir: str = "keyframes"  # where triggering-frame images are persisted (FR-15)


class ModelsConfig(BaseModel):
    """Local AI-model provisioning (FR-18). Models are fetched once if missing, then run
    fully offline (pillar 1, pillar 4 — on-device). Disable auto_download for air-gapped
    boxes provisioned out-of-band via `scripts/download_models.py`."""

    auto_download: bool = True  # fetch any missing model on startup (needs network ONCE)
    dir: str = "models"  # local cache; weights are git-ignored and run offline thereafter
    # Source bases (tunable so a mirror / pinned release can replace the public default).
    yolo_assets_base: str = "https://github.com/ultralytics/assets/releases/download/v8.3.0"
    piper_voices_base: str = "https://huggingface.co/rhasspy/piper-voices/resolve/main"


class WatchdogConfig(BaseModel):
    sw_timeout_s: float = 10.0  # missed liveness tick -> restart pipeline (RR-1, FMEA F4)


class DashboardConfig(BaseModel):
    enabled: bool = False  # opt-in local operator UI; never on the critical path (FR-17)
    host: str = "127.0.0.1"  # loopback by default — not exposed to the network
    port: int = 8088
    event_limit: int = 50  # most-recent events returned to the UI


class Settings(BaseSettings):
    """Top-level settings. Loaded from config.yaml, overridable by AUTOSENTRY_* env vars."""

    model_config = SettingsConfigDict(env_prefix="AUTOSENTRY_", env_nested_delimiter="__")

    armed: bool = False  # default DISARMED; explicit arming required
    capture: CaptureConfig = Field(default_factory=CaptureConfig)
    detection: DetectionConfig = Field(default_factory=DetectionConfig)
    trigger: TriggerConfig = Field(default_factory=TriggerConfig)
    reasoning: ReasoningConfig = Field(default_factory=ReasoningConfig)
    state: StateConfig = Field(default_factory=StateConfig)
    alarm: AlarmConfig = Field(default_factory=AlarmConfig)
    comms: CommsConfig = Field(default_factory=CommsConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    notify: NotifyConfig = Field(default_factory=NotifyConfig)
    watchdog: WatchdogConfig = Field(default_factory=WatchdogConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)

    @model_validator(mode="after")
    def _propagate_models_dir(self) -> Settings:
        """ModelsConfig.dir is the single source of truth for where weights live; mirror it
        into the subsystems that load model files so the provisioner and the backends agree."""
        self.detection.models_dir = self.models.dir
        self.voice.models_dir = self.models.dir
        return self


def load_settings(path: str | Path | None = None) -> Settings:
    """Load settings from a YAML file (defaults applied for any missing keys)."""
    data: dict = {}
    if path is not None:
        p = Path(path)
        if p.exists():
            data = yaml.safe_load(p.read_text()) or {}
    return Settings(**data)
