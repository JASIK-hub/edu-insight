from datetime import datetime
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class HealthOut(BaseModel):
    status: Literal["ok"] = "ok"
    database: Literal["ok", "unavailable"]


class DatasetOut(BaseModel):
    id: int
    dataset_id: int
    filename: str
    row_count: int
    created_at: datetime
    status: Literal["uploaded", "processing", "completed", "failed"]


class DatasetListOut(BaseModel):
    datasets: list[DatasetOut]


class OverviewOut(BaseModel):
    dataset_id: int | None
    observation_count: int
    student_count: int
    topic_count: int
    textbook_count: int
    overall_mastery: float | None


class TopicMetric(BaseModel):
    topic: str
    mastery: float
    sample_size: int
    student_count: int
    is_weak: bool


class TopicsOut(BaseModel):
    dataset_id: int | None
    weak_threshold: float
    topics: list[TopicMetric]


class TextbookMetric(BaseModel):
    textbook: str
    mastery: float
    sample_size: int
    student_count: int
    topic_count: int


class TextbooksOut(BaseModel):
    dataset_id: int | None
    textbooks: list[TextbookMetric]


class DashboardOverview(BaseModel):
    total_students: int
    total_observations: int
    average_score: float | None
    total_topics: int
    critical_topics: int


class TopicMasteryPoint(BaseModel):
    topic: str
    score: float
    student_count: int
    sample_size: int
    below_target_count: int


class PerformanceTrendPoint(BaseModel):
    assessment_date: str
    score: float
    student_count: int


class ScoreDistributionPoint(BaseModel):
    score_range: str
    students_count: int


class StudentAverageDistributionPoint(BaseModel):
    score_range: str
    students_count: int


class TextbookComparisonPoint(BaseModel):
    textbook: str
    topic: str
    average_score: float
    student_count: int


class TopicPerformancePoint(BaseModel):
    topic: str
    correct_answers: int
    incorrect_answers: int


class DashboardFilters(BaseModel):
    grades: list[int]
    subjects: list[str]
    textbooks: list[str]
    topics: list[str]


class DatasetAnalyticsOut(BaseModel):
    dataset_id: int
    generated_at: datetime
    overview: DashboardOverview
    topic_mastery: list[TopicMasteryPoint]
    performance_trend: list[PerformanceTrendPoint]
    score_distribution: list[ScoreDistributionPoint]
    student_average_distribution: list[StudentAverageDistributionPoint]
    textbook_comparison: list[TextbookComparisonPoint]
    topic_performance: list[TopicPerformancePoint]
    data_quality_warnings: list[str]
    available_filters: DashboardFilters


class ItemImportOut(BaseModel):
    dataset_id: int
    row_count: int
    skill_count: int


class SkillMetric(BaseModel):
    subject: str | None = None
    topic: str
    skill: str
    correct_answers: int
    incorrect_answers: int
    student_count: int
    item_count: int
    accuracy_percent: float
    status: Literal["insufficient_data", "needs_attention", "on_target"]
    suggested_action: str


class SkillAnalyticsOut(BaseModel):
    dataset_id: int
    item_response_count: int
    skills: list[SkillMetric]


class OptimizeRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{
        "dataset_id": 3,
        "current_hours": {"Algebra": 8, "Geometry": 6},
        "minimum_hours": 3,
        "max_change_per_topic": 4,
        "weak_threshold": 0.6,
    }]})

    dataset_id: int | None = None
    subject: str | None = None
    grade: int | None = None
    textbook: str | None = None
    topic: str | None = None
    current_hours: dict[str, float] = Field(min_length=1)
    minimum_hours: float = Field(default=1, ge=0)
    max_change_per_topic: float = Field(default=4, ge=0)
    weak_threshold: float = Field(default=.6, ge=0, le=1)
    locked_topics: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_hours(self):
        if any(not name.strip() or not math.isfinite(hours) or hours < 0 or hours * 2 != round(hours * 2)
               for name, hours in self.current_hours.items()):
            raise ValueError("topic names must be nonempty and hours must be nonnegative half-hour increments")
        if any(not math.isfinite(value) or value * 2 != round(value * 2)
               for value in (self.minimum_hours, self.max_change_per_topic)):
            raise ValueError("planning limits must use half-hour increments")
        if len(set(self.locked_topics)) != len(self.locked_topics) or not set(self.locked_topics).issubset(self.current_hours):
            raise ValueError("locked_topics must be unique topics in current_hours")
        if any(self.current_hours[name] < self.minimum_hours for name in self.locked_topics):
            raise ValueError("locked topics must meet minimum_hours")
        if sum(self.current_hours.values()) < self.minimum_hours * len(self.current_hours):
            raise ValueError("total hours cannot meet minimum_hours")
        return self


class HourAllocation(BaseModel):
    topic: str
    current_hours: float
    recommended_hours: float
    change: float
    mastery: float
    priority: float


class OptimizeOut(BaseModel):
    dataset_id: int | None
    total_hours: float
    allocations: list[HourAllocation]
    method: str


class SimulateRequest(BaseModel):
    dataset_id: int | None = None
    current_hours: dict[str, int] = Field(min_length=1)
    proposed_hours: dict[str, int] = Field(min_length=1)
    sensitivity: float = Field(default=.15, ge=0, le=1)

    @model_validator(mode="after")
    def validate_hours(self):
        if self.current_hours.keys() != self.proposed_hours.keys():
            raise ValueError("current_hours and proposed_hours must have identical topics")
        if any(not name.strip() or hours < 0 for name, hours in self.current_hours.items()):
            raise ValueError("topic names must be nonempty and hours nonnegative")
        if any(hours < 0 for hours in self.proposed_hours.values()):
            raise ValueError("proposed hours must be nonnegative")
        if sum(self.current_hours.values()) <= 0:
            raise ValueError("total current hours must be positive")
        return self


class TopicProjection(BaseModel):
    topic: str
    current_hours: int
    proposed_hours: int
    mastery_before: float
    mastery_after: float
    delta: float


class SimulateOut(BaseModel):
    dataset_id: int | None
    projections: list[TopicProjection]
    overall_before: float
    overall_after: float
    assumption: str


class ExplainRequest(BaseModel):
    kind: Literal["analytics", "optimization", "simulation"]
    facts: dict[str, JsonValue]
    locale: str = "en"


class ExplainOut(BaseModel):
    explanation: str
    source: Literal["openai", "openrouter", "fallback"]
    model: str | None


class AnalysisRequest(BaseModel):
    dataset_id: int | None = None
    subject: str | None = Field(default=None, max_length=255)
    language: Literal["en", "ru", "kk"] = "ru"
    school_context: str | None = Field(default=None, max_length=2000)
    optimization: OptimizeOut | None = None
    data_quality: dict[str, JsonValue] = Field(default_factory=dict)


class AnalysisEvidence(BaseModel):
    metric: str
    value: JsonValue
    unit: str | None = None


class AnalysisFinding(BaseModel):
    id: str
    title: str
    description: str
    severity: Literal["critical", "high", "medium", "low", "info"]
    topic: str | None = None
    evidence: list[AnalysisEvidence]


class AnalysisTopic(BaseModel):
    topic: str
    status: Literal["critical", "needs_attention", "satisfactory"]
    interpretation: str
    main_concern: str | None = None


class AnalysisTextbook(BaseModel):
    textbook: str
    observation: str
    confidence: Literal["limited", "moderate"] = "limited"
    limitations: list[str]


class AnalysisHourExplanation(BaseModel):
    topic: str
    current_hours: float
    recommended_hours: float
    reason: str


class AnalysisCurriculum(BaseModel):
    summary: str
    total_hours_preserved: bool | None
    topic_explanations: list[AnalysisHourExplanation]


class AnalysisRecommendation(BaseModel):
    id: str
    title: str
    priority: Literal["high", "medium", "low"]
    action: str
    related_topics: list[str]
    evidence: list[str]


class AnalysisSummary(BaseModel):
    title: str
    summary: str
    overall_status: Literal["needs_attention", "satisfactory", "insufficient_data"]
    key_findings_count: int


class EduInsightAnalysisResponse(BaseModel):
    executive_summary: AnalysisSummary
    key_findings: list[AnalysisFinding]
    topic_analysis: list[AnalysisTopic]
    textbook_analysis: list[AnalysisTextbook]
    curriculum_explanation: AnalysisCurriculum
    recommendations: list[AnalysisRecommendation]
    limitations: list[str]
    data_quality_warnings: list[str]
    generated_language: Literal["en", "ru", "kk"]


class DatasetStatusOut(BaseModel):
    dataset_id: int
    status: Literal["uploaded", "processing", "completed", "failed"]
    report_id: int | None


class StoredReportOut(BaseModel):
    id: int
    dataset_id: int
    status: Literal["completed"]
    report: EduInsightAnalysisResponse
    created_at: datetime
