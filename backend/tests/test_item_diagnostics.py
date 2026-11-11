import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.storage.database import Base, get_session
from app.storage import models  # noqa: F401


class ItemDiagnosticsTests(unittest.TestCase):
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
        csv = "student_id,topic,textbook,score,max_score\n" + "".join(
            f"s{i},Algebra,Book A,5,10\n" for i in range(1, 6))
        response = self.client.post("/api/datasets/upload", files={"file": ("assessments.csv", csv.encode())})
        self.assertEqual(response.status_code, 200, response.text)
        self.dataset_id = response.json()["dataset_id"]

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.engine.dispose()

    def test_upload_and_skill_recommendation(self):
        before = self.client.get(f"/api/datasets/{self.dataset_id}/skills")
        self.assertEqual(before.json(), {"dataset_id": self.dataset_id, "item_response_count": 0, "skills": []})
        csv = "student_id,topic,skill,item_id,is_correct\n" + "".join(
            f"s{i},Algebra,Linear equations,q1,{int(i == 1)}\n" for i in range(1, 6))
        uploaded = self.client.post(f"/api/datasets/{self.dataset_id}/items/upload",
                                    files={"file": ("items.csv", csv.encode())})
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        self.assertEqual(uploaded.json(), {"dataset_id": self.dataset_id, "row_count": 5, "skill_count": 1})
        body = self.client.get(f"/api/datasets/{self.dataset_id}/skills?topic=Algebra").json()
        self.assertEqual(body["item_response_count"], 5)
        self.assertEqual(body["skills"][0]["correct_answers"], 1)
        self.assertEqual(body["skills"][0]["incorrect_answers"], 4)
        self.assertEqual(body["skills"][0]["student_count"], 5)
        self.assertEqual(body["skills"][0]["accuracy_percent"], 20)
        self.assertEqual(body["skills"][0]["status"], "needs_attention")

    def test_report_refreshes_after_item_upload_and_names_measured_skill(self):
        request = {"dataset_id": self.dataset_id, "language": "ru"}
        with patch("app.explanations.analysis.OPENAI_ENABLED", False):
            before = self.client.post("/api/recommendations/analyze", json=request)
        self.assertEqual(before.status_code, 200, before.text)
        self.assertIn("не загружены", before.json()["key_findings"][0]["description"])
        csv = "student_id,topic,skill,item_id,is_correct\n" + "".join(
            f"s{i},Algebra,Linear equations,q1,{int(i == 1)}\n" for i in range(1, 6))
        uploaded = self.client.post(f"/api/datasets/{self.dataset_id}/items/upload",
                                    files={"file": ("items.csv", csv.encode())})
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        with patch("app.explanations.analysis.OPENAI_ENABLED", False):
            after = self.client.post("/api/recommendations/analyze", json=request)
        self.assertEqual(after.status_code, 200, after.text)
        report = after.json()
        self.assertIn("Linear equations", report["key_findings"][0]["description"])
        self.assertIn("1 из 5", report["key_findings"][0]["description"])
        self.assertEqual(report["key_findings"][0]["evidence"][2],
                         {"metric": "skill_accuracy", "value": 20.0, "unit": "percent"})
        self.assertIn("Linear equations", report["recommendations"][0]["action"])

    def test_invalid_upload_does_not_replace_existing_answers(self):
        valid = b"student_id,topic,skill,item_id,is_correct\ns1,Algebra,Linear equations,q1,1\n"
        path = f"/api/datasets/{self.dataset_id}/items/upload"
        self.assertEqual(self.client.post(path, files={"file": ("items.csv", valid)}).status_code, 200)
        invalid = valid + b"unknown,Algebra,Linear equations,q2,0\n"
        response = self.client.post(path, files={"file": ("items.csv", invalid)})
        self.assertEqual(response.status_code, 422)
        body = self.client.get(f"/api/datasets/{self.dataset_id}/skills").json()
        self.assertEqual(body["item_response_count"], 1)
        self.assertEqual(body["skills"][0]["status"], "insufficient_data")

    def test_item_cannot_change_skill_between_students(self):
        csv = ("student_id,topic,skill,item_id,is_correct\n"
               "s1,Algebra,Linear equations,q1,1\n"
               "s2,Algebra,Fractions,q1,0\n")
        response = self.client.post(f"/api/datasets/{self.dataset_id}/items/upload",
                                    files={"file": ("items.csv", csv.encode())})
        self.assertEqual(response.status_code, 422)
        self.assertIn("one topic and skill", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
