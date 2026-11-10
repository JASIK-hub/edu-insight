"""Deterministic, Pandas-based educational analytics."""

from .engine import (
    AnalyticsInput,
    analytics_report,
    data_quality,
    detect_difficult_topics,
    overview_analytics,
    textbook_comparison,
    topic_analytics,
)

__all__ = [
    "AnalyticsInput", "analytics_report", "data_quality", "detect_difficult_topics",
    "overview_analytics", "textbook_comparison", "topic_analytics",
]
