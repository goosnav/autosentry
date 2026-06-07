"""Default owner-push transport (FR-13, ICD-6). Lazy-imported by Notifier so the package
imports without httpx and so the critical path never depends on a network client. Posts a
notification to the configured HTTPS endpoint; any transport error is raised so the caller
keeps the item queued for the next flush (OS-5). Not unit-tested — exercised against a real
push endpoint during M6 bring-up.
"""

from __future__ import annotations

from dataclasses import asdict

from autosentry.config import NotifyConfig
from autosentry.contracts import Notification


class HttpNotifySender:
    """POSTs a Notification as JSON to the owner's push endpoint over HTTPS."""

    def __init__(self, config: NotifyConfig) -> None:
        self.cfg = config

    def send(self, note: Notification) -> None:
        if not self.cfg.endpoint:
            raise RuntimeError("no notify endpoint configured")
        import httpx  # heavy/optional, lazy

        resp = httpx.post(self.cfg.endpoint, json=asdict(note), timeout=5.0)
        resp.raise_for_status()
