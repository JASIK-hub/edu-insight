# API contract (v1)

JSON fields are snake_case. All success bodies are exact Pydantic v2 models in `backend/app/contracts.py`. Errors use FastAPI `{ "detail": ... }`. Query `dataset_id` is optional on analytics GETs; omitted means newest dataset. Unknown IDs return 404. No datasets means empty analytics outputs.

| Method/path | Request | 200 response |
|---|---|---|
| `GET /api/health` | none | `HealthOut` |
| `POST /api/datasets/upload` | multipart `file` CSV | `DatasetOut` (`id` retained, plus `dataset_id` and `status`) |
| `GET /api/datasets` | none | `DatasetListOut` |
| `GET /api/datasets/{dataset_id}/status` | none | `DatasetStatusOut` |
| `GET /api/datasets/{dataset_id}/report` | none | `StoredReportOut` |
| `GET /api/datasets/{dataset_id}/analytics` | optional query `grade?: int`, `subject?: str`, `textbook?: str`, `topic?: str` | `DatasetAnalyticsOut` |
| `GET /api/analytics/overview` | query `dataset_id?: int` | `OverviewOut` |
| `GET /api/analytics/topics` | query `dataset_id?: int`, `weak_threshold?: float` (0–1, default .6) | `TopicsOut` |
| `GET /api/analytics/textbooks` | query `dataset_id?: int` | `TextbooksOut` |
| `POST /api/curriculum/optimize` | `OptimizeRequest` JSON | `OptimizeOut` |
| `POST /api/curriculum/simulate` | `SimulateRequest` JSON | `SimulateOut` |
| `POST /api/recommendations/explain` | `ExplainRequest` JSON | `ExplainOut` |
| `POST /api/recommendations/analyze` | `AnalysisRequest` JSON | `EduInsightAnalysisResponse` |

`OptimizeRequest`: `dataset_id?: int`, `current_hours: dict[str,int]`, `minimum_hours: int=1`, `max_change_per_topic: int=4`, `weak_threshold: float=.6`. Hours >= 0; at least one topic; constraints >= 0. Every named topic must exist in selected dataset. `OptimizeOut`: `dataset_id?: int`, `total_hours: int`, `allocations: list[HourAllocation]`, `method: str`. `HourAllocation`: `topic`, `current_hours`, `recommended_hours`, `change`, `mastery`, `priority` (all numbers except topic; hour fields integers).

`SimulateRequest`: `dataset_id?: int`, `current_hours: dict[str,int]`, `proposed_hours: dict[str,int]`, `sensitivity: float=.15` (0–1). Both maps have identical keys, nonnegative integer values, and positive total current hours. `SimulateOut`: `dataset_id?: int`, `projections: list[TopicProjection]`, `overall_before: float`, `overall_after: float`, `assumption: str`. `TopicProjection`: `topic`, `current_hours`, `proposed_hours`, `mastery_before`, `mastery_after`, `delta`.

`ExplainRequest`: `kind: "analytics" | "optimization" | "simulation"`, `facts: dict[str, JsonValue]`, `locale: str="en"`. Facts must be computed output supplied by caller; text must not introduce new scores. `ExplainOut`: `explanation: str`, `source: "openai" | "openrouter" | "fallback"`, `model: str | null`.

`AnalysisRequest`: `dataset_id?: int`, `language: "en" | "ru" | "kk" = "ru"`, `school_context?: str`, `optimization?: OptimizeOut`, `data_quality: dict[str, JsonValue] = {}`. The backend loads overview, topic, and textbook metrics for the selected dataset. `EduInsightAnalysisResponse` has exactly `executive_summary`, `key_findings`, `topic_analysis`, `textbook_analysis`, `curriculum_explanation`, `recommendations`, `limitations`, `data_quality_warnings`, and `generated_language`. Nested fields follow the Pydantic models in `backend/app/contracts.py`. The backend constructs all metrics, evidence, textbook observations, and hour allocations. AI may select only approved action codes for weak topics; invalid choices are ignored. `school_context` is accepted for compatibility but is not sent to AI or used to alter the report.

The report text is expanded by the backend with sample sizes, topic interpretation, textbook cautions, hour changes, and practical actions. OpenRouter still returns only validated action codes; it does not write the report or change factual fields. A previously completed report is cached for the same analysis request; upload a new dataset to generate a report from new data.

`HealthOut`: `status: "ok"`, `database: "ok" | "unavailable"`. `DatasetOut`: `id`, `dataset_id` (equal to `id`), `filename`, `row_count`, `created_at` ISO datetime, `status: "uploaded" | "processing" | "completed" | "failed"`. `DatasetListOut`: `datasets`. `DatasetStatusOut`: `dataset_id`, `status`, `report_id?: int`. `StoredReportOut`: `id`, `dataset_id`, `status: "completed"`, `report: EduInsightAnalysisResponse`, `created_at`. `OverviewOut`: `dataset_id?: int`, `observation_count`, `student_count`, `topic_count`, `textbook_count`, `overall_mastery: float | null`. `TopicsOut`: `dataset_id?: int`, `weak_threshold`, `topics: list[TopicMetric]`. `TopicMetric`: `topic`, `mastery`, `sample_size`, `student_count`, `is_weak`. `TextbooksOut`: `dataset_id?: int`, `textbooks: list[TextbookMetric]`. `TextbookMetric`: `textbook`, `mastery`, `sample_size`, `student_count`, `topic_count`.

## Dataset dashboard analytics

`GET /api/datasets/{dataset_id}/analytics` reads persisted assessment rows and computes chart data using Pandas. Unknown dataset IDs return 404. Filters select assessment rows before calculating KPIs and chart series. `available_filters` always describes the full dataset. All score fields are percentages from 0 to 100, calculated as `100 * sum(score) / sum(max_score)` for the relevant group and rounded to two decimal places. `critical_topics` counts topics with a score below 60%. Student counts are distinct student IDs within each group. Trend points use assessment dates; undated rows are excluded from that series. Score ranges are `(0,20]`, `(20,40]`, `(40,60]`, `(60,80]`, `(80,100]` (zero belongs to the first range), with empty bins omitted. A student with assessments in different bins can be counted in multiple bins. `topic_performance` is empty because assessment points do not provide correct/incorrect answer counts. The current upload schema has no subject field, so `subjects` is empty and a subject filter returns no observations with a warning. Missing series use `[]`; `average_score` is `null` for no matching observations.

Example after uploading four observations (`4/10`, `8/10`, `6/10`, `3/5`) for three distinct students:

```json
{
  "dataset_id": 1,
  "generated_at": "2026-01-03T12:00:00Z",
  "overview": {"total_students": 3, "average_score": 60.0, "total_topics": 2, "critical_topics": 0},
  "topic_mastery": [
    {"topic": "Algebra", "score": 60.0, "student_count": 2},
    {"topic": "Geometry", "score": 60.0, "student_count": 2}
  ],
  "performance_trend": [
    {"assessment_date": "2026-01-01", "score": 60.0, "student_count": 2},
    {"assessment_date": "2026-01-02", "score": 60.0, "student_count": 1}
  ],
  "score_distribution": [
    {"score_range": "20-40", "students_count": 1},
    {"score_range": "40-60", "students_count": 2},
    {"score_range": "60-80", "students_count": 1}
  ],
  "textbook_comparison": [
    {"textbook": "Book A", "topic": "Algebra", "average_score": 40.0, "student_count": 1},
    {"textbook": "Book A", "topic": "Geometry", "average_score": 60.0, "student_count": 1},
    {"textbook": "Book B", "topic": "Algebra", "average_score": 80.0, "student_count": 1},
    {"textbook": "Book B", "topic": "Geometry", "average_score": 60.0, "student_count": 1}
  ],
  "topic_performance": [],
  "data_quality_warnings": [
    "Subject is not stored in the current CSV schema; subject filtering is unavailable.",
    "Answer counts are not stored; topic_performance is unavailable.",
    "Excluded 1 undated records from performance_trend.",
    "A student may appear in multiple score ranges when they have multiple assessments."
  ],
  "available_filters": {"grades": [7, 8], "subjects": [], "textbooks": ["Book A", "Book B"], "topics": ["Algebra", "Geometry"]}
}
```
