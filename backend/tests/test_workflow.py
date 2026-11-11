"""Focused HTTP and persistence checks; no external database or provider calls."""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.storage.database import Base, get_session
from app.storage.models import AnalysisReport
from app.storage.repository import analysis_request_hash, reserve_report
from app.contracts import AnalysisRequest
from app.storage import models  # registers all tables


CSV = (b"student_id,topic,textbook,score,max_score\n"
       b"s1,Algebra,Book A,4,10\n"
       b"s2,Algebra,Book B,6,10\n"
       b"s1,Geometry,Book A,9,10\n")


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:",
                                    connect_args={"check_same_thread": False},
                                    poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

        def test_session():
            with self.sessions() as session:
                yield session

        app.dependency_overrides[get_session] = test_session
        self.client = TestClient(app, raise_server_exceptions=False)
        self.ai_enabled = patch("app.explanations.analysis.OPENAI_ENABLED", False)
        self.ai_enabled.start()

    def tearDown(self):
        self.ai_enabled.stop()
        self.client.close()
        app.dependency_overrides.clear()
        self.engine.dispose()

    def upload(self):
        response = self.client.post("/api/datasets/upload",
                                    files={"file": ("sample.csv", CSV, "text/csv")})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def analyze(self, dataset_id):
        return self.client.post("/api/recommendations/analyze",
                                json={"dataset_id": dataset_id, "language": "ru"})

    def test_upload_analysis_and_saved_report(self):
        uploaded = self.upload()
        self.assertEqual(uploaded["dataset_id"], uploaded["id"])
        self.assertEqual(uploaded["status"], "uploaded")
        dataset_id = uploaded["dataset_id"]
        response = self.analyze(dataset_id)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["generated_language"], "ru")
        self.assertEqual(response.json()["key_findings"][0]["evidence"][0]["value"], .5)
        self.assertIn("оценочных записей", response.json()["executive_summary"]["summary"])
        self.assertIn("учащихся", response.json()["topic_analysis"][0]["interpretation"])
        self.assertIn("Следует", response.json()["topic_analysis"][1]["interpretation"])
        status = self.client.get(f"/api/datasets/{dataset_id}/status")
        self.assertEqual(status.json()["status"], "completed")
        report = self.client.get(f"/api/datasets/{dataset_id}/report")
        self.assertEqual(report.status_code, 200, report.text)
        self.assertEqual(report.json()["report"], response.json())

    def test_retry_reuses_one_report(self):
        dataset_id = self.upload()["dataset_id"]
        first = self.analyze(dataset_id)
        with patch("app.api.routes.analyze", side_effect=AssertionError("AI should not run twice")):
            second = self.analyze(dataset_id)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.json(), first.json())
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count(AnalysisReport.id))), 1)

    def test_processing_blocks_duplicate_request(self):
        dataset_id = self.upload()["dataset_id"]
        with self.sessions() as session:
            state, _ = reserve_report(session, dataset_id,
                analysis_request_hash(AnalysisRequest(dataset_id=dataset_id), dataset_id))
        self.assertEqual(state, "reserved")
        response = self.analyze(dataset_id)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.client.get(f"/api/datasets/{dataset_id}/status").json()["status"], "processing")
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count(AnalysisReport.id))), 1)

    def test_provider_failure_uses_fallback_and_completes(self):
        dataset_id = self.upload()["dataset_id"]
        class BrokenClient:
            def __init__(self, **kwargs):
                raise RuntimeError("provider unavailable")
        with patch("app.explanations.analysis.OPENAI_ENABLED", True), \
             patch("app.explanations.analysis.OPENAI_API_KEY", "fake"), \
             patch("app.explanations.analysis.AsyncOpenAI", BrokenClient):
            response = self.analyze(dataset_id)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get(f"/api/datasets/{dataset_id}/status").json()["status"], "completed")

    def test_invalid_ai_choice_cannot_change_facts(self):
        dataset_id = self.upload()["dataset_id"]
        class Responses:
            async def create(self, **kwargs):
                class Response:
                    output_text = '{"actions":[{"topic_ref":"unknown","action_code":"review_materials"}]}'
                return Response()
        class Client:
            def __init__(self, **kwargs):
                self.responses = Responses()
        with patch("app.explanations.analysis.OPENAI_ENABLED", True), \
             patch("app.explanations.analysis.OPENAI_API_KEY", "fake"), \
             patch("app.explanations.analysis.AsyncOpenAI", Client):
            response = self.analyze(dataset_id)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("Calculus", response.text)
        self.assertEqual(response.json()["key_findings"][0]["evidence"][0]["value"], .5)

    def test_provider_timeout_uses_fallback(self):
        dataset_id = self.upload()["dataset_id"]
        class Responses:
            async def create(self, **kwargs):
                raise TimeoutError("simulated timeout")
        class Client:
            def __init__(self, **kwargs):
                self.assert_timeout = kwargs["timeout"] > 0
                assert self.assert_timeout
                self.responses = Responses()
        with patch("app.explanations.analysis.OPENAI_ENABLED", True), \
             patch("app.explanations.analysis.OPENAI_API_KEY", "fake"), \
             patch("app.explanations.analysis.AsyncOpenAI", Client):
            response = self.analyze(dataset_id)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get(f"/api/datasets/{dataset_id}/status").json()["status"], "completed")

    def test_invalid_ai_response_retries_then_uses_own_subtopic_ideas(self):
        dataset_id = self.upload()["dataset_id"]
        calls = []
        class Responses:
            async def create(self, **kwargs):
                calls.append(kwargs)
                class Response:
                    output_text = ('{"actions":[{"topic_ref":"t1","action_code":"diagnose_gaps",'
                                   '"focus_areas":["basic operations","linear equations"],'
                                   '"classroom_step":"Work through an example together.",'
                                   '"check_task":"Give a new equation to solve."}]}' if len(calls) == 2 else '{"actions":[]}')
                return Response()
        class Client:
            def __init__(self, **kwargs):
                self.responses = Responses()
        with patch("app.explanations.analysis.OPENAI_ENABLED", True), \
             patch("app.explanations.analysis.OPENAI_API_KEY", "fake"), \
             patch("app.explanations.analysis.AsyncOpenAI", Client):
            response = self.analyze(dataset_id)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(calls), 2)
        self.assertIn("basic operations", response.json()["key_findings"][0]["description"])
        self.assertIn("new equation", response.json()["recommendations"][0]["action"])

    def test_provider_receives_only_aggregate_topic_data(self):
        dataset_id = self.upload()["dataset_id"]
        seen = {}
        class Responses:
            async def create(self, **kwargs):
                seen.update(kwargs)
                class Response:
                    output_text = '{"actions":[{"topic_ref":"t1","action_code":"review_materials","focus_areas":["basic operations","linear equations"],"classroom_step":"Model a worked example in pairs.","check_task":"Give one new equation to solve."}]}'
                return Response()
        class Client:
            def __init__(self, **kwargs):
                self.responses = Responses()
        with patch("app.explanations.analysis.OPENAI_ENABLED", True), \
             patch("app.explanations.analysis.OPENAI_API_KEY", "fake"), \
             patch("app.explanations.analysis.AsyncOpenAI", Client):
            response = self.analyze(dataset_id)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("review_materials", seen["input"])
        self.assertEqual(response.json()["recommendations"][0]["title"], "Пересмотреть материалы")
        self.assertNotIn("student_id", seen["input"])
        self.assertNotIn("s1", seen["input"])
        self.assertNotIn("Book A", seen["input"])
        self.assertIn("Algebra", seen["input"])
        self.assertIn("basic operations", response.json()["recommendations"][0]["action"])
        self.assertIn("linear equations", response.json()["key_findings"][0]["description"])

    def test_invalid_upload_does_not_create_dataset(self):
        response = self.client.post("/api/datasets/upload", files={
            "file": ("bad.csv", b"student_id,topic,textbook,score,max_score\ns1,A,B,11,10\n", "text/csv")})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.get("/api/datasets").json()["datasets"], [])

    def test_failed_analysis_can_retry_without_duplicate_row(self):
        dataset_id = self.upload()["dataset_id"]
        with patch("app.api.routes.analyze", side_effect=RuntimeError("unexpected")):
            failed = self.analyze(dataset_id)
        self.assertEqual(failed.status_code, 500)
        self.assertEqual(self.client.get(f"/api/datasets/{dataset_id}/status").json()["status"], "failed")
        success = self.analyze(dataset_id)
        self.assertEqual(success.status_code, 200, success.text)
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count(AnalysisReport.id))), 1)


if __name__ == "__main__":
    unittest.main()
