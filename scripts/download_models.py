#!/usr/bin/env python3
"""Provision AutoSentry's local AI models (FR-18; docs/VISION_PIPELINE.md, docs/VOICE_AGENT.md).

Fetches every model the active config needs — the stage-1 YOLO detector, the stage-2 VLM and
voice LLM (pulled into the local Ollama server), the faster-whisper STT model, and the Piper
TTS voice — into the local `models/` cache. Idempotent: already-present models are skipped.
After a successful run the hub loads every model offline (pillar 1).

Usage:
  python scripts/download_models.py                 # fetch whatever is missing
  python scripts/download_models.py --config cfg.yaml
  python scripts/download_models.py --force         # re-fetch even if present
  python scripts/download_models.py --list          # show targets + status, fetch nothing
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "hub"))

from autosentry.config import load_settings  # noqa: E402
from autosentry.models import ensure_present, targets  # noqa: E402

_DEFAULT_CONFIG = os.path.join(
    os.path.dirname(__file__), "..", "hub", "autosentry", "config.yaml"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="download_models", description=__doc__)
    parser.add_argument("--config", default=_DEFAULT_CONFIG, help="path to config.yaml")
    parser.add_argument("--force", action="store_true", help="re-fetch even if present")
    parser.add_argument("--list", action="store_true", help="list targets, fetch nothing")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = load_settings(args.config)

    if args.list:
        for t in targets(settings):
            print(f"  [{t.kind:7}] {t.label} -> {t.ref}")
        return 0

    print(f"Provisioning models into {settings.models.dir}/ (force={args.force}) ...")
    results = ensure_present(settings, force=args.force)
    for r in results:
        mark = {"present": "·", "fetched": "✓", "missing": "!", "error": "✗"}.get(r.status, "?")
        suffix = f"  ({r.info})" if r.info else ""
        print(f"  {mark} {r.status:8} {r.label}{suffix}")

    failed = [r for r in results if r.status == "error"]
    if failed:
        print(f"\n{len(failed)} model(s) failed to provision.", file=sys.stderr)
        return 1
    print("\nAll required models are present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
