import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.storage.database import Base, get_session
from app.storage import models  # noqa: F401


class SubjectReportTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:",
                                    connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        sessions = sessionmaker(self.engine)

        def get_test_session():
            with sessions() as session:
                yield session

        app.dependency_overrides[get_session] = get_test_session
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.engine.dispose()

    def test_subject_filter_and_report_percent(self):
        csv = ("student_id,subject,topic,textbook,score,max_score\n"
               "s1,Math,Introduction,Book A,4,10\n"
               "s2,Math,Introduction,Book A,5,10\n"
               "s1,History,Introduction,Book B,9,10\n"
               "s2,History,Introduction,Book B,10,10\n")
        uploaded = self.client.post("/api/datasets/upload", files={"file": ("subjects.csv", csv.encode())})
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        dataset_id = uploaded.json()["dataset_id"]
        dashboard = self.client.get(f"/api/datasets/{dataset_id}/analytics")
        self.assertEqual(dashboard.json()["available_filters"]["subjects"], ["History", "Math"])
        math = self.client.get(f"/api/datasets/{dataset_id}/analytics?subject=Math").json()
        self.assertEqual(math["overview"]["total_observations"], 2)
        self.assertEqual(math["overview"]["average_score"], 45)
        self.assertEqual(self.client.get(f"/api/analytics/overview?dataset_id={dataset_id}&subject=Math").json()["overall_mastery"], 0.45)
        with patch("app.explanations.analysis.OPENAI_ENABLED", False):
            report = self.client.post("/api/recommendations/analyze", json={"dataset_id": dataset_id, "subject": "Math"})
        self.assertEqual(report.status_code, 200, report.text)
        self.assertIn("45%", report.json()["executive_summary"]["summary"])
        self.assertNotIn("0.45", report.json()["executive_summary"]["summary"])
        self.assertEqual(len(report.json()["recommendations"]), 1)
        with patch("app.explanations.analysis.OPENAI_ENABLED", False):
            history = self.client.post("/api/recommendations/analyze", json={"dataset_id": dataset_id, "subject": "History"})
        self.assertEqual(history.status_code, 200, history.text)
        self.assertIn("95%", history.json()["executive_summary"]["summary"])
        self.assertEqual(history.json()["recommendations"], [])

    def test_item_responses_require_subject_when_ambiguous(self):
        csv = ("student_id,subject,topic,textbook,score,max_score\n"
               "s1,Math,Introduction,Book A,4,10\n"
               "s1,History,Introduction,Book B,9,10\n")
        dataset_id = self.client.post("/api/datasets/upload", files={"file": ("subjects.csv", csv.encode())}).json()["dataset_id"]
        path = f"/api/datasets/{dataset_id}/items/upload"
        ambiguous = b"student_id,topic,skill,item_id,is_correct\ns1,Introduction,Basics,q1,0\n"
        self.assertEqual(self.client.post(path, files={"file": ("items.csv", ambiguous)}).status_code, 422)
        explicit = b"student_id,subject,topic,skill,item_id,is_correct\ns1,Math,Introduction,Basics,q1,0\n"
        self.assertEqual(self.client.post(path, files={"file": ("items.csv", explicit)}).status_code, 200)
        math = self.client.get(f"/api/datasets/{dataset_id}/skills?subject=Math").json()
        history = self.client.get(f"/api/datasets/{dataset_id}/skills?subject=History").json()
        self.assertEqual(math["skills"][0]["subject"], "Math")
        self.assertEqual(history["skills"], [])


if __name__ == "__main__":
    unittest.main()
