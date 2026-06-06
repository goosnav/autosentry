"""Unit tests for OpenCVCamera frame loop + reconnect (FR-1/2, FMEA F1).

Uses a fake capture and a manual clock so the reconnect-on-loss behavior is deterministic
and needs no real camera.
"""

from __future__ import annotations

from itertools import islice

from autosentry.capture.source import OpenCVCamera


class FakeCapture:
    def __init__(self, script: list[tuple[bool, object]]) -> None:
        self._script = list(script)
        self.released = False

    def read(self) -> tuple[bool, object]:
        if self._script:
            return self._script.pop(0)
        return (False, None)

    def release(self) -> None:
        self.released = True

    def isOpened(self) -> bool:
        return True


def test_yields_frames_with_incrementing_seq():
    cap = FakeCapture([(True, "img0"), (True, "img1"), (True, "img2")])
    cam = OpenCVCamera("0", "front", open_fn=lambda *a: cap)
    frames = list(islice(cam.frames(), 3))
    assert [f.seq for f in frames] == [0, 1, 2]
    assert [f.image for f in frames] == ["img0", "img1", "img2"]
    assert all(f.zone == "front" for f in frames)


def test_reconnects_after_timeout_and_recovers():
    caps = [
        FakeCapture([(False, None), (False, None)]),  # dead camera
        FakeCapture([(True, "img0"), (True, "img1")]),  # replacement after reconnect
    ]
    clock = {"t": 0.0}

    def tick() -> float:
        clock["t"] += 1.0
        return clock["t"]

    cam = OpenCVCamera(
        "0", "front", timeout_s=2.0, open_fn=lambda *a: caps.pop(0), clock=tick
    )
    frames = list(islice(cam.frames(), 2))
    assert cam.reconnects == 1
    assert [f.image for f in frames] == ["img0", "img1"]
    assert caps == []  # both captures were consumed (initial + reconnect)


def test_close_stops_iteration():
    cap = FakeCapture([(True, "img0"), (True, "img1"), (True, "img2"), (True, "img3")])
    cam = OpenCVCamera("0", "front", open_fn=lambda *a: cap)
    gen = cam.frames()
    assert next(gen).seq == 0
    cam.close()
    assert list(gen) == []  # closed -> generator finishes
    assert cap.released
