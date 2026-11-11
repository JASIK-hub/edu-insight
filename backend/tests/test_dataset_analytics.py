import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.storage.database import Base, get_session
from app.storage import models  # noqa: F401


CSV = ("student_id,topic,textbook,score,max_score,assessment_date,class_id,grade\n"
       "s1,Algebra,Book A,4,10,2026-01-01,7A,7\n"
       "s2,Algebra,Book B,8,10,2026-01-01,7A,7\n"
       "s1,Geometry,Book A,6,10,2026-01-02,7A,7\n"
       "s3,Geometry,Book B,3,5,,,8\n")


class DatasetAnalyticsTests(unittest.TestCase):
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

    def test_upload_then_chart_analytics(self):
        uploaded = self.client.post("/api/datasets/upload", files={
            "file": ("synthetic.csv", CSV.encode(), "text/csv")})
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        dataset_id = uploaded.json()["dataset_id"]
        response = self.client.get(f"/api/datasets/{dataset_id}/analytics")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["overview"], {"total_students": 3, "total_observations": 4, "average_score": 60.0,
                                            "total_topics": 2, "critical_topics": 0})
        self.assertEqual(body["topic_mastery"], [
            {"topic": "Algebra", "score": 60.0, "student_count": 2, "sample_size": 2, "below_target_count": 1},
            {"topic": "Geometry", "score": 60.0, "student_count": 2, "sample_size": 2, "below_target_count": 2}])
        self.assertEqual(body["student_average_distribution"], [
            {"score_range": "<60", "students_count": 1},
            {"score_range": "60–74", "students_count": 1},
            {"score_range": "75–84", "students_count": 1},
            {"score_range": "≥85", "students_count": 0},
        ])
        self.assertEqual(body["performance_trend"], [
            {"assessment_date": "2026-01-01", "score": 60.0, "student_count": 2},
            {"assessment_date": "2026-01-02", "score": 60.0, "student_count": 1}])
        self.assertEqual(body["available_filters"], {
            "grades": [7, 8], "subjects": [], "textbooks": ["Book A", "Book B"],
            "topics": ["Algebra", "Geometry"]})
        self.assertEqual(body["topic_performance"], [])
        self.assertEqual(len(body["textbook_comparison"]), 4)
        self.assertTrue(body["data_quality_warnings"])

        filtered = self.client.get(f"/api/datasets/{dataset_id}/analytics?grade=8")
        self.assertEqual(filtered.json()["overview"]["total_students"], 1)
        self.assertEqual(filtered.json()["overview"]["total_observations"], 1)
        self.assertEqual(filtered.json()["overview"]["average_score"], 60.0)
        self.assertEqual(sum(row["students_count"] for row in filtered.json()["student_average_distribution"]), 1)

    def test_missing_dataset(self):
        self.assertEqual(self.client.get("/api/datasets/999/analytics").status_code, 404)


if __name__ == "__main__":
    unittest.main()
