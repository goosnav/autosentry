"""Default voice transports (FR-11). Lazy-imported by VoiceAgent so the package imports
without the `voice` extra (faster-whisper, httpx, piper) or any running model. Not
unit-tested — exercised against live local models during M5 bring-up on the Jetson
(docs/VOICE_AGENT.md §2). Each call enforces the per-turn timeout so a hung model can
never stall the dialogue task (FMEA F15).
"""

from __future__ import annotations

import os
import subprocess
from typing import Any

from autosentry.config import VoiceConfig


class WhisperSTT:
    """faster-whisper (CTranslate2) speech-to-text. `audio` is a path or PCM ndarray."""

    def __init__(self, config: VoiceConfig) -> None:
        self.cfg = config
        self._model: Any = None

    def transcribe(self, audio: object) -> str:
        from faster_whisper import WhisperModel  # heavy/optional, lazy

        if self._model is None:
            # Load from the local cache the provisioner populated (FR-18); faster-whisper
            # still fetches into download_root on a cache miss if it was skipped.
            self._model = WhisperModel(
                self.cfg.stt_model, download_root=os.path.join(self.cfg.models_dir, "whisper")
            )
        segments, _ = self._model.transcribe(audio)
        return " ".join(seg.text for seg in segments).strip()


class OllamaLLM:
    """POSTs the persona + grounded prompt to a local Ollama /api/chat endpoint."""

    def __init__(self, config: VoiceConfig) -> None:
        self.cfg = config

    def generate(self, system: str, user: str, max_tokens: int) -> str:
        import httpx  # heavy/optional, lazy

        payload = {
            "model": self.cfg.llm_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        resp = httpx.post(
            f"{self.cfg.llm_endpoint}/api/chat",
            json=payload,
            timeout=self.cfg.turn_timeout_s,
        )
        resp.raise_for_status()
        return str(resp.json().get("message", {}).get("content", ""))


class PiperTTS:
    """Pipes text to the Piper CLI, which renders + plays it on the local speaker."""

    def __init__(self, config: VoiceConfig) -> None:
        self.cfg = config

    def speak(self, text: str) -> None:
        subprocess.run(
            ["piper", "--model", self._voice_model(), "--output-raw"],
            input=text.encode(),
            timeout=self.cfg.turn_timeout_s,
            check=True,
        )

    def _voice_model(self) -> str:
        """Use the provisioned voice .onnx under models_dir if present; else the bare id so
        a system-installed Piper voice still resolves (FR-18)."""
        local = os.path.join(self.cfg.models_dir, "piper", f"{self.cfg.tts_voice}.onnx")
        return local if os.path.exists(local) else self.cfg.tts_voice
