"""Pure analytics functions. All returned values are JSON-compatible Python objects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict

import numpy as np
import pandas as pd


class Distribution(TypedDict):
    low: int
    developing: int
    mastered: int


class OverviewResult(TypedDict):
    total_students: int
    total_assessments: int
    valid_assessments: int
    average_normalized_mastery: float | None
    critical_topics: list[Any]
    total_textbooks: int
    assessment_coverage: float | None


class TopicResult(TypedDict):
    topic_id: Any
    average_mastery: float | None
    median_score: float | None
    student_count: int
    assessment_count: int
    error_rate: float | None
    performance_distribution: Distribution
    priority_indicator: float | None
    mastery_category: str
    curriculum_importance: float
    sufficient_sample: bool


class TextbookResult(TypedDict):
    grade: Any
    subject: Any
    topic_id: Any
    textbook_id: Any
    average_normalized_score: float | None
    student_count: int
    assessment_count: int
    score_distribution: Distribution
    baseline_adjusted_mean_gain: float | None
    baseline_paired_count: int
    warnings: list[str]


class QualityIssue(TypedDict, total=False):
    code: str
    field: str
    count: int
    topic_id: Any
    topic_ids: list[Any]
    textbook_id: Any
    grade: Any
    subject: Any


class AnalyticsReport(TypedDict):
    overview: OverviewResult
    topics: list[TopicResult]
    textbooks: list[TextbookResult]
    difficult_topics: list[TopicResult]
    data_quality: list[QualityIssue]


@dataclass(frozen=True)
class AnalyticsInput:
    """Assessments are one row per attempt; topics/textbooks are catalog rows.

    Required assessment columns: student_id, topic or topic_id, textbook or
    textbook_id, score, max_score. Optional: assessment_id, grade, subject,
    baseline_score, baseline_max_score. Catalogs are optional; topics may
    provide curriculum_importance (0..1).
    """

    assessments: pd.DataFrame
    topics: pd.DataFrame | None = None
    textbooks: pd.DataFrame | None = None


def _required(frame: pd.DataFrame, columns: set[str], name: str) -> None:
    missing = columns - set(frame.columns)
    if missing:
        raise ValueError(f"{name} missing required columns: {', '.join(sorted(missing))}")


def _prepare(data: AnalyticsInput) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    a = data.assessments.copy()
    # The v1 CSV stores names directly; richer callers may supply ID columns.
    if "topic_id" not in a and "topic" in a:
        a["topic_id"] = a["topic"]
    if "textbook_id" not in a and "textbook" in a:
        a["textbook_id"] = a["textbook"]
    if "assessment_id" not in a:
        a["assessment_id"] = range(len(a))
    _required(a, {"student_id", "topic_id", "textbook_id", "score", "max_score"}, "assessments")
    for optional in ("grade", "subject"):
        if optional not in a:
            a[optional] = None
    t = data.topics.copy() if data.topics is not None else pd.DataFrame({"topic_id": sorted(a.topic_id.dropna().unique(), key=str)})
    b = data.textbooks.copy() if data.textbooks is not None else pd.DataFrame({"textbook_id": sorted(a.textbook_id.dropna().unique(), key=str)})
    if "topic_id" not in t and "topic" in t:
        t = t.rename(columns={"topic": "topic_id"})
    if "textbook_id" not in b and "textbook" in b:
        b = b.rename(columns={"textbook": "textbook_id"})
    _required(a, {"assessment_id", "student_id", "topic_id", "textbook_id", "grade", "subject", "score", "max_score"}, "assessments")
    _required(t, {"topic_id"}, "topics")
    _required(b, {"textbook_id"}, "textbooks")
    if t.topic_id.isna().any() or b.textbook_id.isna().any() or t.topic_id.duplicated().any() or b.textbook_id.duplicated().any():
        raise ValueError("topic_id and textbook_id must be unique in their catalogs")
    for col in ("score", "max_score", "baseline_score", "baseline_max_score"):
        if col in a:
            a[col] = pd.to_numeric(a[col], errors="coerce")
    valid = np.isfinite(a.score) & np.isfinite(a.max_score) & a.max_score.gt(0) & a.score.ge(0) & a.score.le(a.max_score)
    a["normalized_score"] = (a.score / a.max_score).where(valid)
    if {"baseline_score", "baseline_max_score"} <= set(a):
        bv = np.isfinite(a.baseline_score) & np.isfinite(a.baseline_max_score) & a.baseline_max_score.gt(0) & a.baseline_score.ge(0) & a.baseline_score.le(a.baseline_max_score)
        a["normalized_baseline"] = (a.baseline_score / a.baseline_max_score).where(bv)
        a["baseline_gain"] = a.normalized_score - a.normalized_baseline
    else:
        a["normalized_baseline"] = np.nan
        a["baseline_gain"] = np.nan
    if "curriculum_importance" not in t:
        t["curriculum_importance"] = 0.5
    t["curriculum_importance"] = pd.to_numeric(t.curriculum_importance, errors="coerce").fillna(0.5).clip(0, 1)
    return a, t, b


def _distribution(scores: pd.Series) -> Distribution:
    s = scores.dropna()
    return {"low": int((s < .5).sum()), "developing": int(((s >= .5) & (s < .8)).sum()), "mastered": int((s >= .8).sum())}


def _category(value: float | None) -> str:
    return "unknown" if value is None else "low" if value < .5 else "developing" if value < .8 else "mastered"


def _mean(series: pd.Series) -> float | None:
    value = series.mean()
    return None if pd.isna(value) else float(value)


def _topic_rows(a: pd.DataFrame, t: pd.DataFrame, min_sample: int) -> list[TopicResult]:
    rows = []
    for topic in t.sort_values("topic_id", key=lambda s: s.astype(str)).to_dict("records"):
        group = a.loc[a.topic_id == topic["topic_id"]]
        scores = group.normalized_score.dropna()
        n = len(scores)
        avg = _mean(scores)
        error = None if n == 0 else float((scores < .5).mean())
        importance = float(topic["curriculum_importance"])
        # Priority is bounded [0,1]; low confidence is represented separately.
        priority = None if avg is None else float((1 - avg) * .6 + error * .25 + importance * .15)
        rows.append({"topic_id": topic["topic_id"], "average_mastery": avg,
                     "median_score": None if n == 0 else float(scores.median()),
                     "student_count": int(group.loc[group.normalized_score.notna(), "student_id"].nunique()),
                     "assessment_count": n, "error_rate": error,
                     "performance_distribution": _distribution(scores),
                     "priority_indicator": priority, "mastery_category": _category(avg),
                     "curriculum_importance": importance, "sufficient_sample": n >= min_sample})
    return rows


def topic_analytics(data: AnalyticsInput, *, min_sample: int = 10) -> list[TopicResult]:
    if min_sample < 1:
        raise ValueError("min_sample must be positive")
    a, t, _ = _prepare(data)
    return _topic_rows(a, t, min_sample)


def detect_difficult_topics(data: AnalyticsInput, *, min_sample: int = 10,
                            mastery_threshold: float = .6, error_threshold: float = .4,
                            importance_threshold: float = .5) -> list[TopicResult]:
    if not all(0 <= value <= 1 for value in (mastery_threshold, error_threshold, importance_threshold)):
        raise ValueError("difficulty thresholds must be within [0, 1]")
    return [r for r in topic_analytics(data, min_sample=min_sample)
            if r["sufficient_sample"] and r["average_mastery"] < mastery_threshold
            and r["error_rate"] >= error_threshold and r["curriculum_importance"] >= importance_threshold]


def overview_analytics(data: AnalyticsInput, *, min_sample: int = 10) -> OverviewResult:
    if min_sample < 1:
        raise ValueError("min_sample must be positive")
    a, t, b = _prepare(data)
    valid = a.loc[a.normalized_score.notna()]
    topics = _topic_rows(a, t, min_sample)
    return {"total_students": int(a.student_id.nunique()), "total_assessments": len(a),
            "valid_assessments": len(valid), "average_normalized_mastery": _mean(valid.normalized_score),
            "critical_topics": [r["topic_id"] for r in topics if r["sufficient_sample"] and r["average_mastery"] is not None and r["average_mastery"] < .5],
            "total_textbooks": len(b),
            "assessment_coverage": None if data.topics is None or len(t) == 0 else float(a.loc[a.topic_id.isin(t.topic_id), "topic_id"].nunique() / len(t))}


def textbook_comparison(data: AnalyticsInput, *, min_sample: int = 10,
                        imbalance_ratio: float = 2.0) -> list[TextbookResult]:
    if min_sample < 1 or not np.isfinite(imbalance_ratio) or imbalance_ratio <= 1:
        raise ValueError("min_sample must be positive and imbalance_ratio must be finite and exceed 1")
    a, t, b = _prepare(data)
    valid = a.loc[a.normalized_score.notna() & a.textbook_id.isin(b.textbook_id) & a.topic_id.isin(t.topic_id)]
    keys = ["grade", "subject", "topic_id", "textbook_id"]
    rows = []
    for key, group in valid.groupby(keys, dropna=False, sort=False):
        paired = group.baseline_gain.dropna()
        rows.append({k: (None if pd.isna(v) else v) for k, v in zip(keys, key)} | {"average_normalized_score": _mean(group.normalized_score),
                    "student_count": int(group.student_id.nunique()), "assessment_count": len(group),
                    "score_distribution": _distribution(group.normalized_score),
                    "baseline_adjusted_mean_gain": _mean(paired), "baseline_paired_count": len(paired),
                    "warnings": []})
    rows.sort(key=lambda row: tuple("" if row[k] is None else str(row[k]) for k in keys))
    for row in rows:
        peers = [x for x in rows if all(x[k] == row[k] for k in keys[:3])]
        counts = [x["assessment_count"] for x in peers]
        if row["assessment_count"] < min_sample:
            row["warnings"].append("insufficient_sample")
        if len(peers) > 1 and min(counts) > 0 and max(counts) / min(counts) >= imbalance_ratio:
            row["warnings"].append("unequal_textbook_groups")
        if "baseline_score" in a or "baseline_max_score" in a:
            if 0 < row["baseline_paired_count"] < row["assessment_count"]:
                row["warnings"].append("partial_baseline_coverage")
            if row["baseline_paired_count"] == 0:
                row["warnings"].append("no_paired_baseline")
    return rows


def data_quality(data: AnalyticsInput, *, min_sample: int = 10,
                 imbalance_ratio: float = 2.0) -> list[QualityIssue]:
    a, t, b = _prepare(data)
    issues: list[QualityIssue] = []
    for col in ["student_id", "topic_id", "textbook_id", "score", "max_score"]:
        count = int(a[col].isna().sum())
        if count:
            issues.append({"code": "missing_values", "field": col, "count": count})
    for col in ("assessment_id", "grade", "subject", "baseline_score", "baseline_max_score"):
        if col in data.assessments:
            count = int(a[col].isna().sum())
            if count:
                issues.append({"code": "missing_values", "field": col, "count": count})
    invalid = int(a.normalized_score.isna().sum())
    if invalid:
        issues.append({"code": "invalid_or_missing_score", "count": invalid})
    duplicates = int(a.assessment_id.notna().sum() - a.assessment_id.dropna().nunique())
    if "assessment_id" not in data.assessments:
        source_columns = [c for c in data.assessments.columns if c in a]
        duplicates = int(a.duplicated(subset=source_columns).sum())
    if duplicates:
        issues.append({"code": "duplicate_assessments", "count": duplicates})
    uncovered = t.loc[~t.topic_id.isin(a.topic_id), "topic_id"].tolist()
    if uncovered:
        issues.append({"code": "incomplete_topic_coverage", "topic_ids": uncovered, "count": len(uncovered)})
    for name, catalog, col in [("topic", t, "topic_id"), ("textbook", b, "textbook_id")]:
        unknown = int((a[col].notna() & ~a[col].isin(catalog[col])).sum())
        if unknown:
            issues.append({"code": f"unknown_{name}", "count": unknown})
    for row in _topic_rows(a, t, min_sample):
        if not row["sufficient_sample"]:
            issues.append({"code": "insufficient_topic_sample", "topic_id": row["topic_id"], "count": row["assessment_count"]})
    for row in textbook_comparison(data, min_sample=min_sample, imbalance_ratio=imbalance_ratio):
        for warning in row["warnings"]:
            if warning in {"insufficient_sample", "unequal_textbook_groups"}:
                issues.append({"code": warning, "grade": row["grade"], "subject": row["subject"],
                               "topic_id": row["topic_id"], "textbook_id": row["textbook_id"],
                               "count": row["assessment_count"]})
    return issues


def analytics_report(data: AnalyticsInput, *, min_sample: int = 10) -> AnalyticsReport:
    return {"overview": overview_analytics(data, min_sample=min_sample),
            "topics": topic_analytics(data, min_sample=min_sample),
            "textbooks": textbook_comparison(data, min_sample=min_sample),
            "difficult_topics": detect_difficult_topics(data, min_sample=min_sample),
            "data_quality": data_quality(data, min_sample=min_sample)}
