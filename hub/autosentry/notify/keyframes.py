"""Keyframe persistence for the audit log (FR-15).

When an event is logged, the frame that produced it is written to disk as a JPEG so an
operator can later see *what the camera saw*, not just the textual assessment. This is pure
audit metadata on the **non-critical** path (pillar 1): image encoding is best-effort and
fully isolated — a failed write (missing codec, bad frame, full disk) degrades to "no
keyframe" and never blocks or breaks the alarm or the event row.

`cv2` is imported lazily inside the writer so the dependency is only touched when a real
frame is actually persisted (tests inject a fake writer and never import it).
"""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger("autosentry.notify")


def write_keyframe(image: Any, path: str) -> bool:
    """Encode `image` (a BGR ndarray) to `path` as JPEG. Returns True on success.

    Best-effort: any failure is logged and reported as False so the caller can record an
    empty keyframe list rather than propagating an exception onto the alarm path.
    """
    try:
        import cv2  # lazy: only when a real frame is persisted

        os.makedirs(os.path.dirname(path), exist_ok=True)
        return bool(cv2.imwrite(path, image))
    except Exception as e:  # missing codec / bad frame / full disk — never fatal (pillar 1)
        log.warning("keyframe write failed (%s): %s", path, e)
        return False
