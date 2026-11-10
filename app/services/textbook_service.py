"""Framework-independent textbook comparison service."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.engines.analytics import AnalyticsInput, textbook_comparison


def compare_textbooks(
    assessments: pd.DataFrame,
    topics: pd.DataFrame | None = None,
    textbooks: pd.DataFrame | None = None,
    *,
    min_sample: int = 10,
    imbalance_ratio: float = 2.0,
) -> list[dict[str, Any]]:
    """Return descriptive textbook groups, including sample and quality indicators."""
    if min_sample < 1 or imbalance_ratio <= 1:
        raise ValueError("min_sample must be positive and imbalance_ratio must exceed 1")
    return textbook_comparison(AnalyticsInput(assessments, topics, textbooks),
                               min_sample=min_sample, imbalance_ratio=imbalance_ratio)
