"""Unit tests for local model provisioning (FR-18; models.py).

AutoSentry must self-provision its models on first boot and then run them entirely offline
(pillars 1 + 4). These pin the present/fetch decision with injected fake fetchers — no
network, no real weights: a present model is never re-fetched, a missing one is, disabling
auto_download reports-without-fetching (air-gapped provisioning), force re-fetches, the
Ollama path checks the server's tag list, and one bad target can't abort the rest.
"""

from __future__ import annotations

import os

from autosentry.config import Settings
from autosentry.models import ensure_present, targets


class FakeOllama:
    """Stand-in for the local Ollama server: a fixed tag set + a record of pulls."""

    def __init__(self, present: set[str]):
        self.present = set(present)
        self.pulled: list[str] = []

    def __call__(self, endpoint: str) -> FakeOllama:  # used as ollama_factory
        return self

    def tags(self) -> set[str]:
        return set(self.present)

    def pull(self, model: str) -> None:
        self.pulled.append(model)
        self.present.add(model)


class Recorder:
    """Records (url/model, dest/root) fetches and creates the destination so a later
    presence check sees the file/dir as materialized."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def file(self, url: str, dest: str) -> None:
        self.calls.append((url, dest))
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(b"x")

    def whisper(self, model: str, root: str) -> None:
        self.calls.append((model, root))
        os.makedirs(root, exist_ok=True)
        with open(os.path.join(root, "model.bin"), "wb") as fh:
            fh.write(b"x")


def _settings(tmp_path, **kw) -> Settings:
    s = Settings()
    s.models.dir = str(tmp_path / "models")
    s.detection.models_dir = s.models.dir  # mirror (model_validator already did, but explicit)
    s.voice.models_dir = s.models.dir
    for k, v in kw.items():
        setattr(s.models, k, v)
    return s


def _run(s, ollama, rec, **kw):
    return ensure_present(
        s, ollama_factory=ollama, fetch_file=rec.file, fetch_whisper=rec.whisper, **kw
    )


def test_targets_cover_detector_vlm_and_voice(tmp_path):
    s = _settings(tmp_path)
    labels = [t.label for t in targets(s)]
    kinds = {t.kind for t in targets(s)}
    assert any("YOLO detector" in x for x in labels)
    assert any("VLM" in x for x in labels)
    assert any("Whisper" in x for x in labels)
    assert any("Piper" in x for x in labels)
    assert kinds == {"file", "ollama", "whisper"}


def test_missing_models_are_fetched(tmp_path):
    s = _settings(tmp_path)
    ollama = FakeOllama(present=set())  # nothing pulled yet
    rec = Recorder()
    results = _run(s, ollama, rec)
    assert {r.status for r in results} == {"fetched"}
    # both ollama models pulled, files written for yolo + piper(.onnx + .json) + whisper
    assert set(ollama.pulled) == {s.reasoning.model, s.voice.llm_model}
    assert any("yolov8n.pt" in dest for _, dest in rec.calls)
    assert any(dest.endswith(".onnx.json") for _, dest in rec.calls)


def test_present_models_are_not_refetched(tmp_path):
    s = _settings(tmp_path)
    ollama = FakeOllama(present={s.reasoning.model, s.voice.llm_model})
    rec = Recorder()
    _run(s, ollama, rec)  # first pass materializes the files
    ollama.pulled.clear()
    rec2 = Recorder()
    results = _run(s, ollama, rec2)
    assert {r.status for r in results} == {"present"}
    assert ollama.pulled == []
    assert rec2.calls == []  # nothing downloaded the second time


def test_auto_download_off_reports_missing_without_fetching(tmp_path):
    s = _settings(tmp_path, auto_download=False)
    ollama = FakeOllama(present=set())
    rec = Recorder()
    results = _run(s, ollama, rec)
    assert {r.status for r in results} == {"missing"}
    assert ollama.pulled == []
    assert rec.calls == []  # air-gapped: nothing fetched


def test_force_refetches_even_when_present(tmp_path):
    s = _settings(tmp_path)
    ollama = FakeOllama(present={s.reasoning.model, s.voice.llm_model})
    rec = Recorder()
    _run(s, ollama, rec)  # materialize
    ollama.pulled.clear()
    rec2 = Recorder()
    results = _run(s, ollama, rec2, force=True)
    assert {r.status for r in results} == {"fetched"}
    assert set(ollama.pulled) == {s.reasoning.model, s.voice.llm_model}
    assert rec2.calls  # re-downloaded despite presence


def test_voice_disabled_drops_voice_targets(tmp_path):
    s = _settings(tmp_path)
    s.voice.enabled = False
    labels = [t.label for t in targets(s)]
    assert not any("Whisper" in x or "Piper" in x or "voice LLM" in x for x in labels)
    assert any("VLM" in x for x in labels)  # detector + VLM remain


def test_one_failure_is_isolated(tmp_path):
    s = _settings(tmp_path)
    ollama = FakeOllama(present=set())
    rec = Recorder()

    def flaky(url: str, dest: str) -> None:
        if dest.endswith("yolov8n.pt"):
            raise RuntimeError("mirror down")
        rec.file(url, dest)

    results = ensure_present(
        s, ollama_factory=ollama, fetch_file=flaky, fetch_whisper=rec.whisper
    )
    by_status: dict[str, int] = {}
    for r in results:
        by_status[r.status] = by_status.get(r.status, 0) + 1
    assert by_status.get("error") == 1  # only the YOLO target failed
    assert by_status.get("fetched", 0) >= 1  # the rest still provisioned
    assert set(ollama.pulled) == {s.reasoning.model, s.voice.llm_model}
