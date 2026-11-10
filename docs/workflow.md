# CSV to report workflow

The browser makes two requests. The CSV is parsed and stored in Neon; only opaque topic references, mastery ratios, and sample sizes can reach OpenRouter. Student IDs, topic and textbook text, assessment rows, and raw CSV bytes never enter the model request.

## 1. Upload

`POST /api/datasets/upload` with multipart form field `file` containing a UTF-8 CSV:

```csv
student_id,topic,textbook,score,max_score
s1,Algebra,Book A,4,10
s2,Algebra,Book B,6,10
s1,Geometry,Book A,9,10
```

Example HTTP 200 body (the ID and timestamp depend on the database):

```json
{"id":4,"dataset_id":4,"filename":"sample.csv","row_count":3,"created_at":"2026-11-10T10:38:50Z","status":"uploaded"}
```

The existing `id`, filename, row count, and timestamp remain. `dataset_id` is a stable alias for `id`. An invalid CSV returns 422 and creates no dataset.

## 2. Analyze

`POST /api/recommendations/analyze` with JSON:

```json
{"dataset_id":4,"language":"ru"}
```

The response is the existing `EduInsightAnalysisResponse` JSON contract. Example from the CSV above (text is deterministic unless an approved AI action is selected):

```json
{
  "executive_summary":{"title":"Успеваемость по темам","summary":"Темы с низким освоением требуют внимания.","overall_status":"needs_attention","key_findings_count":1},
  "key_findings":[{"id":"finding_001","title":"Algebra","description":"Уровень освоения: 0.5; Оценочных записей: 2.","severity":"high","topic":"Algebra","evidence":[{"metric":"mastery","value":0.5,"unit":"ratio"},{"metric":"sample_size","value":2,"unit":"records"}]}],
  "topic_analysis":[{"topic":"Algebra","status":"needs_attention","interpretation":"Уровень освоения: 0.5; Оценочных записей: 2.","main_concern":"Освоение ниже заданного порога"},{"topic":"Geometry","status":"satisfactory","interpretation":"Уровень освоения: 0.9; Оценочных записей: 1.","main_concern":null}],
  "textbook_analysis":[{"textbook":"Book B","observation":"Уровень освоения: 0.6; Оценочных записей: 1; Учащихся: 1.","confidence":"limited","limitations":["Наблюдаемые различия не доказывают преимущество учебника: возможны отбор учащихся и различия в исходной подготовке."]},{"textbook":"Book A","observation":"Уровень освоения: 0.65; Оценочных записей: 2; Учащихся: 1.","confidence":"limited","limitations":["Наблюдаемые различия не доказывают преимущество учебника: возможны отбор учащихся и различия в исходной подготовке."]}],
  "curriculum_explanation":{"summary":"Распределение часов не предоставлено.","total_hours_preserved":null,"topic_explanations":[]},
  "recommendations":[{"id":"rec_001","title":"Выявить пробелы","priority":"high","action":"Разобрать ошибки по теме и определить понятия, требующие повторного объяснения.","related_topics":["Algebra"],"evidence":["Algebra: Уровень освоения 0.5; Оценочных записей 2."]}],
  "limitations":["Наблюдаемые различия не доказывают преимущество учебника: возможны отбор учащихся и различия в исходной подготовке.","Распределение часов не предоставлено."],
  "data_quality_warnings":[],
  "generated_language":"ru"
}
```

Pass an `optimization` response from `POST /api/curriculum/optimize` to include backend-calculated allocations. The analysis endpoint checks that dataset, topics, mastery, and hour totals match before storing a report.

## States, retrieval, and retries

`GET /api/datasets/4/status` returns:

```json
{"dataset_id":4,"status":"completed","report_id":7}
```

States are `uploaded` after CSV persistence, `processing` during analysis, `completed` after report persistence, and `failed` after an unexpected analysis error. OpenRouter errors use deterministic recommendations and still complete the report. A duplicate request while processing returns HTTP 409 with `{"detail":{"status":"processing","dataset_id":4}}`. Retry the same body after completion to receive the saved report without another model call. A failed request may be retried; it reuses its report row. Processing reservations older than `ANALYSIS_STALE_SECONDS` may be retried after a server interruption.

`GET /api/datasets/4/report` returns a `StoredReportOut` object with `id`, `dataset_id`, `status`, `created_at`, and `report`. Its `report` property contains the exact analysis JSON shown above. While processing, this endpoint returns 409; without a completed report, it returns 404.

Frontend request sequence:

```javascript
const form = new FormData();
form.append("file", file);
const uploaded = await fetch("/api/datasets/upload", { method: "POST", body: form }).then(r => r.json());
const analyze = () => fetch("/api/recommendations/analyze", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ dataset_id: uploaded.dataset_id, language: "ru" })
});
let response = await analyze();
if (response.status === 409) {
  for (let attempt = 0; attempt < 30; attempt++) {
    const state = await fetch(`/api/datasets/${uploaded.dataset_id}/status`).then(r => r.json());
    if (state.status !== "processing") {
      response = await analyze(); // Ensures this request gets its own matching report.
      break;
    }
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
}
if (response.status === 409) throw new Error("Analysis is still processing");
if (!response.ok) throw new Error(`Analysis failed: ${response.status}`);
const report = await response.json();
```

If analysis returns 409, poll `/status` until processing ends and repeat the same analysis request. That repeat returns the cached matching report, or starts the requested report if a different analysis was processing. Handle `failed` by allowing a retry and showing the server error. The backend never sends raw CSV or personal student data to OpenRouter.
