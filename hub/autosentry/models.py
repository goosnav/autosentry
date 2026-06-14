"""Local AI-model provisioning (FR-18).

AutoSentry runs every model on-device (pillars 1 + 4): the fast YOLO detector, the stage-2
VLM, and the voice STT/LLM/TTS. This module makes the box self-provisioning — on startup it
enumerates the models the current config needs, checks which are already present, and fetches
only the missing ones. After the first (networked) fetch the weights live under `models/`
(git-ignored) and the system runs fully offline forever after, so model download never sits
on the steady-state detection→alarm path (pillar 1).

The enumeration (`targets`) and the present/fetch decision (`ensure_present`) are pure and
unit-tested with fakes; the actual network/disk fetchers are injected so no test touches the
network. `scripts/download_models.py` is the explicit CLI entry; `Hub.run()` calls
`ensure_present` at boot when `models.auto_download` is set.
"""

from __future__ import annotations

import logging
import os
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from autosentry.config import Settings

log = logging.getLogger("autosentry.models")


@dataclass
class ModelTarget:
    """One model the running config requires, plus how to obtain it if missing."""

    label: str  # human-readable, for logs/report
    kind: str  # "file" | "ollama" | "whisper"
    ref: str  # file: local path · ollama: model tag · whisper: model name
    url: str | None = None  # file kind: download source
    endpoint: str | None = None  # ollama kind: server base URL
    root: str | None = None  # whisper kind: download_root dir
    extra: list[tuple[str, str]] = field(default_factory=list)  # file: (url, dest) sidecars


@dataclass
class ProvisionResult:
    label: str
    status: str  # "present" | "fetched" | "missing" | "error"
    info: str = ""


class OllamaClient(Protocol):
    """Minimal Ollama control surface: which models are pulled, and pull a missing one."""

    def tags(self) -> set[str]: ...
    def pull(self, model: str) -> None: ...


def _piper_voice_relpath(voice: str) -> str:
    """Map a Piper voice id to its repo path, e.g. en_US-amy-medium ->
    en/en_US/amy/medium/en_US-amy-medium (rhasspy/piper-voices layout)."""
    lang_region, name, quality = voice.split("-", 2)
    lang = lang_region.split("_")[0]
    return f"{lang}/{lang_region}/{name}/{quality}/{voice}"


def targets(s: Settings) -> list[ModelTarget]:
    """Enumerate the models the current settings require (pure)."""
    m = s.models
    out: list[ModelTarget] = []

    det = s.detection.model
    out.append(
        ModelTarget(
            label=f"YOLO detector ({det})",
            kind="file",
            ref=os.path.join(m.dir, det),
            url=f"{m.yolo_assets_base}/{det}",
        )
    )
    if s.detection.weapon_model:
        wm = s.detection.weapon_model
        out.append(
            ModelTarget(
                label=f"YOLO weapon head ({wm})",
                kind="file",
                ref=os.path.join(m.dir, wm),
                url=f"{m.yolo_assets_base}/{wm}",
            )
        )

    out.append(
        ModelTarget(
            label=f"VLM ({s.reasoning.model})",
            kind="ollama",
            ref=s.reasoning.model,
            endpoint=s.reasoning.endpoint,
        )
    )

    if s.voice.enabled:
        out.append(
            ModelTarget(
                label=f"voice LLM ({s.voice.llm_model})",
                kind="ollama",
                ref=s.voice.llm_model,
                endpoint=s.voice.llm_endpoint,
            )
        )
        out.append(
            ModelTarget(
                label=f"Whisper STT ({s.voice.stt_model})",
                kind="whisper",
                ref=s.voice.stt_model,
                root=os.path.join(m.dir, "whisper"),
            )
        )
        voice = s.voice.tts_voice
        base = f"{m.piper_voices_base}/{_piper_voice_relpath(voice)}"
        onnx = os.path.join(m.dir, "piper", f"{voice}.onnx")
        out.append(
            ModelTarget(
                label=f"Piper TTS ({voice})",
                kind="file",
                ref=onnx,
                url=f"{base}.onnx",
                extra=[(f"{base}.onnx.json", f"{onnx}.json")],
            )
        )
    return out


def _download_file(url: str, dest: str) -> None:
    """Fetch a single file to dest atomically (download to .part, then rename)."""
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    tmp = f"{dest}.part"
    log.info("downloading %s -> %s", url, dest)
    # Bounded connect/read timeout: provisioning runs at boot, so a stalled mirror must
    # surface as a URLError (caught per-target in ensure_present) rather than hang startup
    # forever — a silent boot hang is exactly the failure pillar 1 forbids (FR-18).
    with urllib.request.urlopen(url, timeout=30) as resp, open(tmp, "wb") as fh:  # noqa: S310
        while chunk := resp.read(1 << 16):
            fh.write(chunk)
    os.replace(tmp, dest)


def _download_whisper(model: str, root: str) -> None:
    """Materialize a faster-whisper model into root (downloads from HF on first call)."""
    os.makedirs(root, exist_ok=True)
    from faster_whisper import WhisperModel  # heavy/optional, lazy

    WhisperModel(model, download_root=root)


class _HttpOllamaClient:
    """Default OllamaClient over the local server's HTTP API (httpx, lazy)."""

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint

    def tags(self) -> set[str]:
        import httpx  # heavy/optional, lazy

        resp = httpx.get(f"{self.endpoint}/api/tags", timeout=5.0)
        resp.raise_for_status()
        return {m["name"] for m in resp.json().get("models", [])}

    def pull(self, model: str) -> None:
        import httpx  # heavy/optional, lazy

        log.info("ollama pull %s (this can take a while)", model)
        with httpx.stream(
            "POST", f"{self.endpoint}/api/pull", json={"name": model}, timeout=None
        ) as resp:
            resp.raise_for_status()
            for _ in resp.iter_lines():  # drain the progress stream to completion
                pass


def ensure_present(
    s: Settings,
    *,
    ollama_factory: Callable[[str], OllamaClient] | None = None,
    fetch_file: Callable[[str, str], None] | None = None,
    fetch_whisper: Callable[[str, str], None] | None = None,
    force: bool = False,
    report_only: bool = False,
) -> list[ProvisionResult]:
    """Ensure every required model is present, fetching the missing ones (FR-18).

    Idempotent: present models are left untouched unless `force`. When `auto_download` is off
    a missing model is reported (status "missing") rather than fetched — useful for air-gapped
    provisioning. `report_only` checks presence and never fetches regardless of config (used by
    the preflight self-test). Each target is isolated: one failure is recorded and the rest
    still proceed, so a single bad mirror can't abort the whole provisioning pass.
    """
    ollama_factory = ollama_factory or _HttpOllamaClient
    fetch_file = fetch_file or _download_file
    fetch_whisper = fetch_whisper or _download_whisper
    auto = False if report_only else (s.models.auto_download or force)

    results: list[ProvisionResult] = []
    for t in targets(s):
        try:
            results.append(
                _ensure_one(t, auto, force, ollama_factory, fetch_file, fetch_whisper)
            )
        except Exception as e:  # never let one model abort provisioning the others
            log.error("provisioning %s failed: %s", t.label, e)
            results.append(ProvisionResult(t.label, "error", str(e)))
    return results


def _ensure_one(
    t: ModelTarget,
    auto: bool,
    force: bool,
    ollama_factory: Callable[[str], OllamaClient],
    fetch_file: Callable[[str, str], None],
    fetch_whisper: Callable[[str, str], None],
) -> ProvisionResult:
    if t.kind == "ollama":
        client = ollama_factory(t.endpoint or "")
        present = t.ref in client.tags()
        if present and not force:
            return ProvisionResult(t.label, "present")
        if not auto:
            return ProvisionResult(t.label, "missing", "auto_download off")
        client.pull(t.ref)
        return ProvisionResult(t.label, "fetched")

    if t.kind == "whisper":
        root = t.root or "."
        present = False
        if os.path.isdir(root):
            with os.scandir(root) as entries:
                present = any(entries)  # closes the iterator (no FD leak)
        if present and not force:
            return ProvisionResult(t.label, "present")
        if not auto:
            return ProvisionResult(t.label, "missing", "auto_download off")
        fetch_whisper(t.ref, root)
        return ProvisionResult(t.label, "fetched")

    # file kind (+ sidecars)
    present = os.path.exists(t.ref) and all(os.path.exists(p) for _, p in t.extra)
    if present and not force:
        return ProvisionResult(t.label, "present")
    if not auto:
        return ProvisionResult(t.label, "missing", "auto_download off")
    assert t.url is not None
    fetch_file(t.url, t.ref)
    for url, dest in t.extra:
        fetch_file(url, dest)
    return ProvisionResult(t.label, "fetched")
