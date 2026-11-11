# EDU-Insight Backend

### From assessment CSVs to a teaching plan with a fixed hour budget.

The EDU-Insight API validates assessment uploads, computes performance by topic, and recommends how to redistribute the teaching hours an educator already has. A structured report connects the recommendation to the available evidence and its limitations.

**[Backend repository](https://github.com/JASIK-hub/edu-insight) · [API docs](https://edu-insight-bciy.onrender.com/docs) · [OpenAPI contract](https://github.com/vcffff/edu-insight/blob/main/openapi.json) · [Frontend](https://github.com/vcffff/edu-insight) · [Demo CSV](https://github.com/vcffff/edu-insight/blob/main/docs/samples/single-student.csv)**

## The problem

An overall assessment average can hide gaps in specific topics. Even when those gaps are visible, educators still have to decide where to move teaching time without exceeding the hours already allocated.

## How it works

| Step | Backend responsibility |
| --- | --- |
| **Upload** | Accept a UTF-8 CSV as multipart form data and expose the dataset ID and processing status. |
| **Analyze** | Calculate overview metrics, topic performance, trends, score distributions and textbook comparisons where the dataset supports them. |
| **Plan** | Use educator-supplied hours and topic mastery to propose a redistribution within the same total budget. |
| **Explain** | Return a structured report with findings, evidence, recommendations and limitations. The report can include the latest optimization result. |

Dashboard scores use percentages. The optimizer uses mastery ratios from **0 to 1**. For example, **60%** is **0.6** in an optimization request.

## API routes

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Check service health. |
| POST | `/api/datasets/upload` | Upload a CSV using multipart field `file`. |
| GET | `/api/datasets` | List datasets. |
| GET | `/api/datasets/{dataset_id}/status` | Check processing status. |
| GET | `/api/datasets/{dataset_id}/analytics` | Read analytics with optional `grade`, `subject`, `textbook` and `topic` filters. |
| GET | `/api/datasets/{dataset_id}/report` | Retrieve the stored report for a dataset. |
| POST | `/api/curriculum/optimize` | Calculate recommended teaching hours. |
| POST | `/api/recommendations/analyze` | Generate an evidence-led report for a dataset. |

## Run locally

**Requirements:** Python 3.12+ and PostgreSQL. The project provides a Neon configuration template.

From the repository root in PowerShell:

```powershell
cd backend
py -m pip install -r requirements.txt
Copy-Item .env.example .env
```

On macOS or Linux, use `python3` in place of `py` and `cp .env.example .env` to copy the template.

### Environment variables

Edit `backend/.env`. The tracked template is [`backend/.env.example`](https://github.com/JASIK-hub/edu-insight/blob/main/backend/.env.example). Set `DATABASE_URL` to your Neon direct connection URL and retain its SSL query parameters.

| Variable | Value or template default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | Neon direct connection URL | Stores datasets and reports. |
| `OPENAI_API_KEY` | Empty | Optional OpenRouter key. Without it, reports use the deterministic fallback. |
| `OPENAI_BASE_URL` | `https://openrouter.ai/api/v1` | Provider endpoint. |
| `OPENAI_MODEL` | `openrouter/free` | Model for optional recommendation action selection. |
| `OPENAI_ENABLED` | `true` | Set to `false` to explicitly disable provider calls. |
| `OPENAI_TIMEOUT` | `15` | Provider timeout in seconds. |
| `OPENAI_MAX_RETRIES` | `0` | Provider retry limit. |
| `ANALYSIS_STALE_SECONDS` | `120` | Report processing stale threshold in seconds. |
| `MAX_UPLOAD_BYTES` | `10485760` | CSV upload limit of 10 MiB. |
| `CORS_ORIGINS` | `http://localhost:3000,http://localhost:5173` | Comma-separated frontend origins. |

The backend loads `backend/.env` and gives process environment variables precedence. Keep the real connection URL and provider key out of version control. On Render, set secrets in the service environment.

From `backend/`, after configuring the database:

```powershell
py -m alembic upgrade head
py seed.py
py -m uvicorn app.main:app --reload
```

The seed script loads synthetic assessments for a demo. Open [Swagger UI](http://127.0.0.1:8000/docs) or check [the health endpoint](http://127.0.0.1:8000/api/health). To run the examples below against your local service, set `EDU_API_BASE=http://127.0.0.1:8000`.

Run the backend test suite from `backend/` with `py -m unittest discover -s tests -v`.

## Try the API

Download the [synthetic sample CSV](https://github.com/vcffff/edu-insight/blob/main/docs/samples/single-student.csv) as `single-student.csv`. You can run these requests in Bash or use the interactive API docs.

For subject-specific analysis, add `subject` to the assessment CSV. For example:

```csv
student_id,subject,topic,textbook,score,max_score,assessment_date,class_id,grade
s1,Математика,Дроби,Учебник А,6,10,2026-09-01,7А,7
s2,История,Древний мир,Учебник Б,8,10,2026-09-01,7А,7
```

Select the subject in Live API to filter topic charts and generate a report from that subject's rows. The optional item-response CSV also accepts `subject` and requires it when the same student and topic occur in multiple subjects.

```bash
EDU_API_BASE=https://edu-insight-bciy.onrender.com
curl --fail-with-body "$EDU_API_BASE/api/health"

curl --fail-with-body -X POST "$EDU_API_BASE/api/datasets/upload" \
  -F 'file=@single-student.csv;type=text/csv'
```

Set `EDU_DATASET_ID` to the integer returned by the upload. Check its status before requesting analytics.

```bash
EDU_DATASET_ID=3 # Replace 3 with the ID from your upload.
curl --fail-with-body "$EDU_API_BASE/api/datasets/$EDU_DATASET_ID/status"
curl --fail-with-body "$EDU_API_BASE/api/datasets/$EDU_DATASET_ID/analytics"
```

The sample contains one synthetic student and three assessments. The normalized scores are **20%**, **30%** and **20%**, giving an overall average of about **23.3%**. This is useful for verifying the workflow. School-wide conclusions require a representative dataset.

### Request a teaching plan

Send the current hours using the topic names from the dataset. This example starts with **18 hours** across three topics, allows a change of up to four hours per topic, and sets a minimum of two hours.

```bash
curl --fail-with-body -X POST "$EDU_API_BASE/api/curriculum/optimize" \
  -H 'Content-Type: application/json' \
  --data-binary @- <<JSON
{
  "dataset_id": $EDU_DATASET_ID,
  "current_hours": {"Algebra": 8, "Geometry": 6, "Statistics": 4},
  "minimum_hours": 2,
  "max_change_per_topic": 4,
  "weak_threshold": 0.6
}
JSON
```

Compare the current and recommended hours and check that the totals match. If the optimizer finds no eligible transfer, an unchanged allocation can be a valid result. For an explanation that includes the new plan, pass the returned optimization as `optimization` to `POST /api/recommendations/analyze`, together with the same `dataset_id` and `language: "ru"`.

## Architecture

| Layer | Responsibility |
| --- | --- |
| **HTTP API** | Python and FastAPI expose the CSV, analytics, optimization and report endpoints. |
| **Analytics** | Normalize assessment scores and aggregate the available evidence for the selected dataset. |
| **Curriculum optimizer** | Apply deterministic, mastery-based allocation rules to the educator's current hours and planning constraints. |
| **Reporting** | Build and store structured reports. OpenRouter can select approved recommendation actions, with a deterministic fallback. Numeric evidence comes from the analytics and optimizer. |

The frontend's **Live API** mode uses this contract. Its offline demo runs in the browser and is a separate data source.

## Responsible use and current scope

- Upload anonymized assessment data. The upload workflow does not automatically remove personal identifiers.
- Check sample size and comparability before interpreting textbook or school differences.
- Missing dates can limit trend data. Add an optional `subject` column to the assessment CSV to filter topics and generate reports for one subject. Raw scores and maximum scores do not necessarily describe counts of correct and incorrect answers.
- Recommendations support educator review. The API does not predict learning gains or publish a timetable.
- The documented contract has no authentication or plan-storage endpoints. Keep sensitive student records out of the demo deployment.

## Verification

1. Confirm that the health route responds and the sample upload yields a dataset ID.
2. Check status, then compare the analytics response with the expected sample scores.
3. Submit a current-hour allocation and check the returned total, per-topic minimum and change limits.
4. Generate a report for the same dataset and verify that it explains the plan and flags sample limitations.
