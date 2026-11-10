"""Framework-independent entry point for analytics consumers."""

from __future__ import annotations

import pandas as pd

from app.engines.analytics import AnalyticsInput, analytics_report
from app.engines.analytics.engine import AnalyticsReport


def build_analytics_report(
    assessments: pd.DataFrame,
    topics: pd.DataFrame | None = None,
    textbooks: pd.DataFrame | None = None,
    *,
    min_sample: int = 10,
) -> AnalyticsReport:
    """Compute a complete report from catalog and assessment snapshots."""
    if min_sample < 1:
        raise ValueError("min_sample must be positive")
    return analytics_report(AnalyticsInput(assessments, topics, textbooks), min_sample=min_sample)
