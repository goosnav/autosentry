"""Ollama VLM transport (FR-4). Lazy-imported by Assessor so the package imports without
the `reason` extra (httpx) or a running model. Not unit-tested — exercised against a live
local VLM during M2 bring-up on the Jetson (docs/VISION_PIPELINE.md §4).
"""

from __future__ import annotations

import base64

from autosentry.config import ReasoningConfig


class OllamaBackend:
    """POSTs prompt + base64 keyframes to a local Ollama /api/generate endpoint."""

    def __init__(self, config: ReasoningConfig) -> None:
        self.cfg = config

    def generate(self, prompt: str, images: list[object]) -> str:
        import httpx  # heavy/optional, lazy

        payload = {
            "model": self.cfg.model,
            "prompt": prompt,
            "images": [self._encode(img) for img in images],
            "stream": False,
            "format": "json",
        }
        resp = httpx.post(
            f"{self.cfg.endpoint}/api/generate",
            json=payload,
            timeout=self.cfg.timeout_s,
        )
        resp.raise_for_status()
        return str(resp.json().get("response", ""))

    @staticmethod
    def _encode(image: object) -> str:
        """Encode a keyframe to base64. Accepts pre-encoded bytes or a JPEG-encodable frame."""
        if isinstance(image, (bytes, bytearray)):
            return base64.b64encode(bytes(image)).decode("ascii")
        import cv2  # heavy/optional, lazy

        ok, buf = cv2.imencode(".jpg", image)
        if not ok:
            raise ValueError("failed to JPEG-encode keyframe")
        return base64.b64encode(buf.tobytes()).decode("ascii")
