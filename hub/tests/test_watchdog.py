"""Unit tests for the software watchdog (RR-1).

The watchdog is the SW half of the HW+SW supervision: it must ping at a steady cadence
while the loop is alive, and — crucially — stop pinging the moment the loop stalls, so
systemd kills and restarts a hung hub instead of letting it sit blind.
"""

from __future__ import annotations

from autosentry.watchdog import Watchdog


def _wd(interval=10.0):
    sent: list[str] = []
    clock = {"t": 0.0}
    wd = Watchdog(interval, clock=lambda: clock["t"], notify=sent.append)
    return wd, sent, clock


def test_ready_notifies_systemd():
    wd, sent, _ = _wd()
    wd.ready()
    assert sent == ["READY=1"]


def test_first_ping_fires_then_throttles():
    wd, sent, clock = _wd(interval=10.0)
    assert wd.ping() is True  # t=0, first ping always fires
    assert sent == ["WATCHDOG=1"]
    clock["t"] = 5.0
    assert wd.ping() is False  # within the interval -> throttled
    assert len(sent) == 1
    clock["t"] = 10.0
    assert wd.ping() is True  # interval elapsed -> ping again
    assert len(sent) == 2


def test_stalled_loop_stops_pinging():
    # If the loop hangs, ping() is never called again, so no further WATCHDOG=1 is sent
    # and systemd's WatchdogSec fires. We model the hang as "clock advances, no ping call".
    wd, sent, clock = _wd(interval=10.0)
    wd.ping()
    clock["t"] = 1000.0  # time passes but the hung loop never calls ping()
    assert sent == ["WATCHDOG=1"]  # exactly one ping -> systemd will restart us


def test_notify_is_noop_without_socket(monkeypatch):
    # Default _sd_notify must be a silent no-op off systemd (any dev/test box).
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    Watchdog(10.0).ping()  # must not raise
