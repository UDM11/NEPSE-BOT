"""Performance metrics collection and reporting."""

from __future__ import annotations

import statistics
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncIterator, Iterator


@dataclass
class LatencyRecord:
    """Single latency measurement."""

    metric_name: str
    latency_ms: float
    symbol: str | None = None
    metadata: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class MetricsCollector:
    """Collect and aggregate latency metrics."""

    def __init__(self, max_samples: int = 10_000):
        self._samples: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=max_samples)
        )
        self._records: deque[LatencyRecord] = deque(maxlen=max_samples)
        self._counters: dict[str, int] = defaultdict(int)

    def record_latency(
        self,
        metric_name: str,
        latency_ms: float,
        symbol: str | None = None,
        **metadata,
    ) -> None:
        self._samples[metric_name].append(latency_ms)
        self._records.append(
            LatencyRecord(metric_name, latency_ms, symbol, metadata)
        )

    def increment(self, counter_name: str, amount: int = 1) -> None:
        self._counters[counter_name] += amount

    @contextmanager
    def measure(self, metric_name: str, symbol: str | None = None, **metadata) -> Iterator[None]:
        """Sync context manager for latency measurement."""
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            self.record_latency(metric_name, elapsed_ms, symbol, **metadata)

    @asynccontextmanager
    async def measure_async(
        self, metric_name: str, symbol: str | None = None, **metadata
    ) -> AsyncIterator[None]:
        """Async context manager for latency measurement."""
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            self.record_latency(metric_name, elapsed_ms, symbol, **metadata)

    def get_stats(self, metric_name: str) -> dict[str, float]:
        samples = list(self._samples.get(metric_name, []))
        if not samples:
            return {"count": 0, "min": 0, "max": 0, "mean": 0, "p50": 0, "p95": 0, "p99": 0}
        sorted_samples = sorted(samples)
        n = len(sorted_samples)

        def percentile(p: float) -> float:
            idx = int(n * p / 100)
            return sorted_samples[min(idx, n - 1)]

        return {
            "count": n,
            "min": min(sorted_samples),
            "max": max(sorted_samples),
            "mean": statistics.mean(sorted_samples),
            "p50": percentile(50),
            "p95": percentile(95),
            "p99": percentile(99),
        }

    def get_all_stats(self) -> dict[str, dict[str, float]]:
        return {name: self.get_stats(name) for name in self._samples}

    def get_counters(self) -> dict[str, int]:
        return dict(self._counters)

    def get_recent_records(self, limit: int = 100) -> list[dict]:
        return [
            {
                "metric_name": r.metric_name,
                "latency_ms": r.latency_ms,
                "symbol": r.symbol,
                "metadata": r.metadata,
                "timestamp": r.timestamp.isoformat(),
            }
            for r in list(self._records)[-limit:]
        ]

    def generate_report(self) -> dict:
        """Generate comprehensive metrics report."""
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "latency": self.get_all_stats(),
            "counters": self.get_counters(),
            "key_metrics": {
                "detection": self.get_stats("detection_latency"),
                "decision": self.get_stats("decision_latency"),
                "order_submission": self.get_stats("order_submission_latency"),
                "execution": self.get_stats("execution_latency"),
                "end_to_end": self.get_stats("end_to_end_latency"),
            },
        }


# Global metrics instance
metrics = MetricsCollector()
