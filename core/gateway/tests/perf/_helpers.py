"""Latency-percentile helpers for perf tests.

Pure helpers — no I/O. Implements percentile computation via linear
interpolation between order statistics so we don't depend on numpy.
"""

from __future__ import annotations


def _percentile(sorted_samples: list[float], q: float) -> float:
    """Linear-interpolation percentile. ``q`` is in [0, 100]."""
    if not sorted_samples:
        raise ValueError("cannot compute percentile of empty sample")
    if len(sorted_samples) == 1:
        return sorted_samples[0]

    # Numpy-equivalent "linear" method: rank = (n - 1) * q / 100.
    rank = (len(sorted_samples) - 1) * (q / 100.0)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_samples) - 1)
    frac = rank - lo
    return sorted_samples[lo] * (1.0 - frac) + sorted_samples[hi] * frac


def percentiles(samples: list[float]) -> dict[str, float]:
    """Return p50/p95/p99 plus min/max/mean for an unordered sample list."""
    if not samples:
        raise ValueError("samples must be non-empty")
    ordered = sorted(samples)
    return {
        "min": ordered[0],
        "max": ordered[-1],
        "mean": sum(ordered) / len(ordered),
        "p50": _percentile(ordered, 50.0),
        "p95": _percentile(ordered, 95.0),
        "p99": _percentile(ordered, 99.0),
    }


def format_percentiles(label: str, stats: dict[str, float]) -> str:
    """Render a one-line summary in milliseconds."""
    return (
        f"{label}: "
        f"min={stats['min'] * 1000:.1f}ms "
        f"p50={stats['p50'] * 1000:.1f}ms "
        f"p95={stats['p95'] * 1000:.1f}ms "
        f"p99={stats['p99'] * 1000:.1f}ms "
        f"max={stats['max'] * 1000:.1f}ms "
        f"mean={stats['mean'] * 1000:.1f}ms"
    )
