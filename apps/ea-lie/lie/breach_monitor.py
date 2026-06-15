"""Breach monitor — listens to EA-FCI / EA-DIS / EA-PIP events,
generates notice + evidence summary + iMessage alert via qwen3-8b on-prem.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))
from lmstudio_client import PRIMARY_MODEL, chat_complete  # noqa: E402

logger = logging.getLogger(__name__)


class EventSource(str, Enum):
    EA_FCI = "EA-FCI"
    EA_DIS = "EA-DIS"
    EA_PIP = "EA-PIP"


@dataclass
class BreachEvent:
    source: EventSource
    contract_id: str
    event_type: str
    description: str
    evidence_urls: list[str] = field(default_factory=list)
    timestamp: Optional[datetime] = None

    def __post_init__(self) -> None:
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)


@dataclass
class BreachResponse:
    contract_id: str
    notice_text: str
    evidence_summary: str
    alert_sent: bool
    notice_generated: bool


class BreachMonitor:
    """Process breach events from EA-FCI/EA-DIS/EA-PIP and dispatch responses."""

    def __init__(
        self,
        imessage_recipient: Optional[str] = None,
        lmstudio_base: str = "http://localhost:1234",
    ) -> None:
        # None → read from env; "" → explicitly no recipient (used in tests to suppress)
        self._recipient = (
            imessage_recipient
            if imessage_recipient is not None
            else os.getenv("ALERT_IMESSAGE_RECIPIENT", "")
        )
        self._lmstudio_base = lmstudio_base

    def process_event(
        self,
        event: BreachEvent,
        obligations: Optional[list[dict[str, Any]]] = None,
    ) -> BreachResponse:
        """Main entry: generate notice + evidence + iMessage alert."""
        notice = self._generate_notice(event, obligations or [])
        evidence = self._compile_evidence(event)
        alert_sent = self._send_imessage(event, notice)

        return BreachResponse(
            contract_id=event.contract_id,
            notice_text=notice,
            evidence_summary=evidence,
            alert_sent=alert_sent,
            notice_generated=bool(notice and not notice.startswith("[FAILED")),
        )

    # ------------------------------------------------------------------

    def _generate_notice(
        self, event: BreachEvent, obligations: list[dict[str, Any]]
    ) -> str:
        affected = json.dumps(obligations[:5], ensure_ascii=False)
        prompt = (
            f"You are a Thai contract lawyer.  Draft a formal breach notice letter (EN/TH bilingual).\n\n"
            f"Contract ID: {event.contract_id}\n"
            f"Source system: {event.source.value}\n"
            f"Event type: {event.event_type}\n"
            f"Description: {event.description}\n"
            f"Affected obligations: {affected}\n\n"
            f"The notice must: (1) identify the breach precisely; "
            f"(2) cite the relevant contract clause(s); "
            f"(3) state required remediation steps; "
            f"(4) set a cure period (standard 14 days unless otherwise specified); "
            f"(5) reserve all rights including those under CCC Art.213.\n"
            f"Output the notice text only."
        )
        try:
            return chat_complete(prompt, model=PRIMARY_MODEL)
        except Exception as exc:
            logger.error("qwen3 breach notice failed: %s", exc)
            return f"[FAILED: notice generation error for contract {event.contract_id}]"

    def _compile_evidence(self, event: BreachEvent) -> str:
        ts = event.timestamp.isoformat() if event.timestamp else "N/A"
        lines = [
            "BREACH EVENT EVIDENCE SUMMARY",
            f"Contract ID : {event.contract_id}",
            f"Source      : {event.source.value}",
            f"Event type  : {event.event_type}",
            f"Timestamp   : {ts}",
            f"Description : {event.description}",
            f"Evidence ({len(event.evidence_urls)} item(s)):",
        ]
        for url in event.evidence_urls:
            lines.append(f"  • {url}")
        return "\n".join(lines)

    def _send_imessage(self, event: BreachEvent, notice: str) -> bool:
        if not self._recipient:
            logger.warning("iMessage recipient not configured; skipping alert")
            return False

        message = (
            f"[EA-LIE BREACH ALERT]\n"
            f"Contract : {event.contract_id}\n"
            f"Source   : {event.source.value}\n"
            f"Type     : {event.event_type}\n"
            f"Action   : Review breach notice immediately — legal response required."
        )
        script = (
            'tell application "Messages"\n'
            f"  send {json.dumps(message)} to buddy {json.dumps(self._recipient)}"
            ' of service "iMessage"\n'
            "end tell"
        )
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                timeout=15.0,
            )
            if result.returncode != 0:
                logger.error("iMessage send failed: %s", result.stderr.decode())
            return result.returncode == 0
        except Exception as exc:
            logger.error("iMessage send error: %s", exc)
            return False
