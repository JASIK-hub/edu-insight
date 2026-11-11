import unittest

from pydantic import ValidationError

from app.contracts import OptimizeRequest, TopicMetric, TopicsOut
from app.curriculum.service import optimize


class OptimizerHalfHourTests(unittest.TestCase):
    def setUp(self):
        self.topics = TopicsOut(dataset_id=1, weak_threshold=0.6, topics=[
            TopicMetric(topic="Algebra", mastery=.4, sample_size=10, student_count=10, is_weak=True),
            TopicMetric(topic="Geometry", mastery=.6, sample_size=10, student_count=10, is_weak=False),
            TopicMetric(topic="Probability", mastery=.8, sample_size=10, student_count=10, is_weak=False),
        ])

    def test_half_hour_transfer_preserves_budget_and_locks(self):
        result = optimize(OptimizeRequest(dataset_id=1,
            current_hours={"Algebra": 4.5, "Geometry": 5.5, "Probability": 8},
            minimum_hours=2, max_change_per_topic=4, locked_topics=["Geometry"]), self.topics)
        rows = {row.topic: row for row in result.allocations}
        self.assertEqual(result.total_hours, 18)
        self.assertEqual(sum(row.recommended_hours for row in result.allocations), 18)
        self.assertEqual(rows["Geometry"].recommended_hours, 5.5)
        self.assertEqual(rows["Algebra"].recommended_hours, 8.5)
        self.assertEqual(rows["Probability"].recommended_hours, 4)
        self.assertEqual(rows["Algebra"].change, 4)

    def test_invalid_quarter_hours_and_unknown_locks_rejected(self):
        with self.assertRaises(ValidationError):
            OptimizeRequest(current_hours={"Algebra": 4.25})
        with self.assertRaises(ValidationError):
            OptimizeRequest(current_hours={"Algebra": 4}, locked_topics=["Unknown"])


if __name__ == "__main__":
    unittest.main()
