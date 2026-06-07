"""Operator dashboard service (FR-17) — the testable core behind the local web UI.

This is a thin, side-effect-light read/control surface over a running `Hub`. It does no
I/O of its own (no sockets); the HTTP adapter in `server.py` maps requests onto these
methods. Keeping the logic here means the dashboard's behavior is unit-tested directly
against a Hub, with no network in the loop.

The dashboard is **non-critical** (pillar 1): it only reads Hub state and invokes the same
operator controls a human already has (FR-14, SE-5). It never sits on the detection→alarm
path, so a dashboard fault cannot affect detection, alarm, mesh, or notification.
"""

import json
from typing import Any

from autosentry.app import Hub
from autosentry.contracts import Level

_LEVEL_RANK = {lvl.value: i for i, lvl in enumerate(Level)}


class DashboardService:
    """Read/control facade over a Hub for the local operator UI (FR-17)."""

    def __init__(self, hub: Hub, event_limit: int = 50) -> None:
        self.hub = hub
        self.event_limit = event_limit

    # --- reads -------------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        """A single snapshot the UI can poll: per-zone state, health, pending queues."""
        latest = self._latest_assessments()
        zones = []
        for zone in self.hub.zones:
            st = self.hub.machines[zone].state()
            zones.append(
                {
                    "zone": zone,
                    "level": st.level.value,
                    "since": st.since,
                    "reason": st.reason,
                    "armed": zone in self.hub.armed_zones,
                    "assessment": latest.get(zone),
                }
            )
        health = self.hub.health()
        system_level = max(
            (str(z["level"]) for z in zones),
            key=lambda lv: _LEVEL_RANK.get(lv, 0),
            default="NORMAL",
        )
        return {
            "system_level": system_level,
            "armed_count": len(self.hub.armed_zones),
            "zone_count": len(self.hub.zones),
            "zones": zones,
            "test_mode": self.hub.test_mode,
            "degraded": health["degraded"],
            "nodes": self._node_health(),
            "offline_nodes": health["offline_nodes"],
            "on_battery_nodes": health["on_battery_nodes"],
            "pending_notifications": self.hub.notifier.pending(),
            "pending_authority": [
                {
                    "index": i,
                    "zone": rec.zone,
                    "threat_level": rec.threat_level,
                    "reason": rec.reason,
                    "ts": rec.ts,
                    "confirmed": rec.confirmed,
                }
                for i, rec in enumerate(self.hub.pending_authority)
            ],
        }

    def _latest_assessments(self) -> dict[str, dict[str, Any]]:
        """Most-recent stage-2 assessment per zone, distilled for the UI (weapon/intent/conf)."""
        out: dict[str, dict[str, Any]] = {}
        for ev in self.hub.notifier.events():  # oldest-first; later rows overwrite
            raw = ev.get("assessment")
            if not raw:
                continue
            try:
                a = json.loads(raw)
            except (ValueError, TypeError):
                continue
            out[ev["zone"]] = {
                "armed": a.get("armed"),
                "weapon_type": a.get("weapon_type"),
                "intent": a.get("intent"),
                "confidence": a.get("confidence"),
                "description": a.get("description"),
            }
        return out

    def _node_health(self) -> list[dict[str, Any]]:
        """Per-node mesh health for the UI (FR-8/FR-10). Empty until the radio link is up."""
        nodes = {}
        for n in self.hub.mesh.offline_nodes():
            nodes[n.node_id] = {"node_id": n.node_id, "online": False, "on_battery": n.on_battery,
                                "battery_mv": n.battery_mv}
        for n in self.hub.mesh.on_battery_nodes():
            nodes.setdefault(n.node_id, {"node_id": n.node_id, "online": n.online,
                                         "on_battery": True, "battery_mv": n.battery_mv})
        return sorted(nodes.values(), key=lambda d: d["node_id"])

    def events(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Most-recent audit events for the UI, newest first (FR-15)."""
        limit = self.event_limit if limit is None else limit
        return self.hub.notifier.recent_events(limit)  # newest-first, bounded in SQL

    # --- controls (the same operator actions a human already has) ----------------------
    def arm(self, zone: str | None = None) -> dict[str, Any]:
        self._check_zone(zone)
        self.hub.arm(zone)
        return self.status()

    def disarm(self, zone: str | None = None) -> dict[str, Any]:
        self._check_zone(zone)
        self.hub.disarm(zone)
        return self.status()

    def set_test_mode(self, on: bool) -> dict[str, Any]:
        self.hub.set_test_mode(on)
        return self.status()

    def panic(self, zone: str) -> dict[str, Any]:
        self._check_zone(zone)
        self.hub.panic(zone)
        return self.status()

    def confirm_authority(self, index: int) -> dict[str, Any]:
        """Confirm one pending authority-contact recommendation by index (SE-5).

        This is an explicit human action routed straight to the Hub's only confirm path;
        the dashboard never auto-confirms.
        """
        recs = self.hub.pending_authority
        if not 0 <= index < len(recs):
            raise KeyError(f"no pending authority recommendation at index {index}")
        self.hub.confirm_authority_contact(recs[index])
        return self.status()

    def _check_zone(self, zone: str | None) -> None:
        if zone is not None and zone not in self.hub.zones:
            raise KeyError(f"unknown zone: {zone}")
