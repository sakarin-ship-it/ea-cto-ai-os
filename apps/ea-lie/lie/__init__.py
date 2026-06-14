"""EA-LIE — Legal Intelligence Engine (schema: lie)."""
from .breach_monitor import BreachEvent, BreachMonitor, BreachResponse, EventSource
from .clauses import ALL_MANDATORY_CLAUSES, MANDATORY_CLAUSE_IDS, MANDATORY_CLAUSE_TAGS
from .contract_drafter import ContractDrafter, ContractType, DraftResult
from .fidic_timebar import FIDICDeadline, FIDICEdition, FIDICTimebar, TimerAlert
from .nda_generator import NDAGenerator, NDAParams, NDAType
from .obligation_tracker import Obligation, ObligationTracker, ScheduledAlert
from .redline_generator import WATERMARK_TEXT, RedlineChange, RedlineGenerator
from .review_engine import RAGStatus, ReviewEngine, ReviewerLevel, ReviewResult

__all__ = [
    "NDAGenerator", "NDAParams", "NDAType",
    "ContractDrafter", "ContractType", "DraftResult",
    "ReviewEngine", "ReviewResult", "RAGStatus", "ReviewerLevel",
    "RedlineGenerator", "RedlineChange", "WATERMARK_TEXT",
    "ObligationTracker", "Obligation", "ScheduledAlert",
    "FIDICTimebar", "FIDICEdition", "FIDICDeadline", "TimerAlert",
    "BreachMonitor", "BreachEvent", "BreachResponse", "EventSource",
    "ALL_MANDATORY_CLAUSES", "MANDATORY_CLAUSE_IDS", "MANDATORY_CLAUSE_TAGS",
]
