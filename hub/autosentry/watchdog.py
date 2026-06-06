"""Software watchdog — the SW half of the HW+SW watchdog (RR-1, FMEA F4).

The hub runs under systemd with `WatchdogSec` set (deploy/autosentry.service). systemd
expects a periodic `WATCHDOG=1` liveness datagram on $NOTIFY_SOCKET; if the main loop
hangs and the pings stop, systemd kills and restarts the service — a hung pipeline can
never sit silently blind (pillar 1: degrade loudly, never silently).

Pure stdlib and fully testable: the socket send is injectable, and with no $NOTIFY_SOCKET
(any dev/test machine) every call is a no-op. The loop pings on each frame; the throttle
keeps that cheap regardless of frame rate.
"""

from __future__ import annotations

import os
import socket
import time
from collections.abc import Callable


def _sd_notify(state: str) -> None:
    """Send one sd_notify datagram to $NOTIFY_SOCKET; no-op if not under systemd."""
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    if addr.startswith("@"):  # abstract namespace socket
        addr = "\0" + addr[1:]
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
        sock.connect(addr)
        sock.sendall(state.encode())


class Watchdog:
    """Throttled sd_notify liveness pinger driven by the main loop."""

    def __init__(
        self,
        interval_s: float,
        clock: Callable[[], float] = time.monotonic,
        notify: Callable[[str], None] = _sd_notify,
    ) -> None:
        self._interval = interval_s
        self._clock = clock
        self._notify = notify
        self._last = float("-inf")

    def ready(self) -> None:
        """Tell systemd the service finished starting (Type=notify)."""
        self._notify("READY=1")

    def ping(self, now: float | None = None) -> bool:
        """Send a liveness ping if a full interval has elapsed. Returns True if it pinged."""
        now = self._clock() if now is None else now
        if now - self._last < self._interval:
            return False
        self._last = now
        self._notify("WATCHDOG=1")
        return True
