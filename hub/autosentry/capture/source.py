"""Camera sources (ICD-1).

Auto-detect/connect to a camera and yield Frames with zone + timestamp, reconnecting on
loss (FR-1, FR-2, FMEA F1). OpenCV is imported lazily so the package imports without the
vision extra; the capture object is also injectable so the reconnect/sequencing logic is
unit-testable without a real camera.

STATUS: M1 — frame loop + reconnect implemented; cv2 lazy-loaded.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from typing import Protocol

from autosentry.contracts import Frame


class Capture(Protocol):
    """Minimal cv2.VideoCapture surface we depend on (keeps the seam testable)."""

    def read(self) -> tuple[bool, object]: ...
    def release(self) -> None: ...
    def isOpened(self) -> bool: ...


class CameraSource(Protocol):
    """A source of frames for one zone."""

    zone: str

    def frames(self) -> Iterator[Frame]: ...
    def close(self) -> None: ...


def _open_cv2(source: str, width: int, height: int, fps: int) -> Capture:
    """Default capture factory: lazy-import cv2 and open a UVC/CSI/RTSP source."""
    import cv2  # heavy, lazy

    cap = cv2.VideoCapture(int(source) if source.isdigit() else source)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)
    return cap


class OpenCVCamera:
    """OpenCV/GStreamer-backed camera (USB/CSI/RTSP)."""

    def __init__(
        self,
        source: str,
        zone: str,
        width: int = 1920,
        height: int = 1080,
        fps: int = 15,
        timeout_s: float = 5.0,
        open_fn: Callable[[str, int, int, int], Capture] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.source = source
        self.zone = zone
        self.width = width
        self.height = height
        self.fps = fps
        self.timeout_s = timeout_s
        self._open = open_fn or _open_cv2
        self._clock = clock
        self._cap: Capture | None = None
        self._closed = False
        self.reconnects = 0

    def _open_capture(self) -> Capture:
        return self._open(self.source, self.width, self.height, self.fps)

    def frames(self) -> Iterator[Frame]:
        """Yield frames until closed; reconnect internally on transient loss (FMEA F1).

        Never gives up silently: on read failure it keeps retrying past `timeout_s`,
        reopening the device, so a flaky camera degrades loudly (the caller's frame
        watchdog escalates), not silently.
        """
        self._cap = self._open_capture()
        seq = 0
        last_ok = self._clock()
        while not self._closed:
            ok, image = self._cap.read()
            now = self._clock()
            if not ok or image is None:
                if now - last_ok >= self.timeout_s:
                    self._reconnect()
                    last_ok = self._clock()
                continue
            last_ok = now
            yield Frame(zone=self.zone, ts=time.time(), image=image, seq=seq)
            seq += 1
        self._release()

    def probe(self) -> bool:
        """Single open+read attempt for the preflight self-test (OS-8).

        Unlike `frames()`, this never enters the resilient retry loop — it opens once, reads
        one frame, releases, and returns whether a frame came through. Bounded, never hangs.
        """
        cap: Capture | None = None
        try:
            cap = self._open_capture()
            ok, image = cap.read()
            return bool(ok and image is not None)
        except Exception:
            return False
        finally:
            if cap is not None:
                cap.release()

    def _reconnect(self) -> None:
        self.reconnects += 1
        self._release()
        self._cap = self._open_capture()

    def _release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def close(self) -> None:
        self._closed = True


def list_cameras(max_index: int = 8) -> list[int]:
    """Probe device indices 0..max_index-1 and return those that open (FR-1 autodetect).

    Best-effort; returns [] if OpenCV isn't installed (the package still imports).
    """
    try:
        import cv2
    except ImportError:
        return []
    found: list[int] = []
    for i in range(max_index):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            found.append(i)
        cap.release()
    return found
