"""Readiness check data model and topic builder.

Defines the topic health contract: which topics MUST be publishing
for a given robot/task/world combination, and the result types for
reporting health status.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class TopicCheck:
    """A single topic to verify."""

    topic: str
    msg_type: str
    required: bool = True
    timeout: float = 10.0


@dataclass(frozen=True)
class TopicResult:
    """Outcome of checking one topic."""

    topic: str
    publishing: bool
    latency_ms: float | None
    error: str | None = None


@dataclass
class ReadinessReport:
    """Aggregate readiness result."""

    connected: bool
    topics: list[TopicResult]
    timestamp: datetime
    checks: list[TopicCheck] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        """True if connected and all required topics are publishing."""
        if not self.connected:
            return False
        required_topics = {c.topic for c in self.checks if c.required}
        for result in self.topics:
            if result.topic in required_topics and not result.publishing:
                return False
        return True

    @property
    def failed(self) -> list[TopicResult]:
        """Topics that failed the check (required and not publishing)."""
        required_topics = {c.topic for c in self.checks if c.required}
        return [r for r in self.topics if r.topic in required_topics and not r.publishing]

    def summary(self) -> str:
        """Human-readable one-liner."""
        total = len(self.topics)
        healthy = sum(1 for r in self.topics if r.publishing)
        if healthy == total:
            return f"{healthy}/{total} topics OK"
        missing = [r.topic for r in self.failed]
        return f"{healthy}/{total} topics — {', '.join(missing)} MISSING"
