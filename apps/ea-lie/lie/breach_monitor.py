"""Breach monitor — listens to EA-FCI / EA-DIS / EA-PIP events,
generates notice + evidence summary + LINE notification via qwen3-8b on-prem.
"""
from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))
from lmstudio_client import PRIMARY_MODEL, chat_complete  # noqa: E402

logger = logging.getLogger(__name__)

LINE_NOTIFY_URL = "https://notify-api.line.me/api/notify"


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
    line_sent: bool
    notice_generated: bool


class BreachMonitor:
    """Process breach events from EA-FCI/EA-DIS/EA-PIP and dispatch responses."""

    def __init__(
        self,
        line_token: str = "",
        lmstudio_base: str = "http://localhost:1234",
    ) -> None:
        self._line_token = line_token
        self._lmstudio_base = lmstudio_base

    def process_event(
        self,
        event: BreachEvent,
        obligations: Optional[list[dict[str, Any]]] = None,
    ) -> BreachResponse:
        """Main entry: generate notice + evidence + LINE."""
        notice = self._generate_notice(event, obligations or [])
        evidence = self._compile_evidence(event)
        line_sent = self._send_line(event, notice)

        return BreachResponse(
            contract_id=event.contract_id,
            notice_text=notice,
            evidence_summary=evidence,
            line_sent=line_sent,
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

    def _send_line(self, event: BreachEvent, notice: str) -> bool:
        if not self._line_token:
            logger.warning("LINE token not set; skipping notification")
            return False

        message = (
            f"\n[EA-LIE BREACH ALERT]\n"
            f"Contract : {event.contract_id}\n"
            f"Source   : {event.source.value}\n"
            f"Type     : {event.event_type}\n"
            f"Action   : Review breach notice immediately — legal response required."
        )
        try:
            resp = httpx.post(
                LINE_NOTIFY_URL,
                headers={"Authorization": f"Bearer {self._line_token}"},
                data={"message": message},
                timeout=10.0,
            )
            success = resp.status_code == 200
            if not success:
                logger.error("LINE notify failed: status=%s", resp.status_code)
            return success
        except Exception as exc:
            logger.error("LINE notify error: %s", exc)
            return False
