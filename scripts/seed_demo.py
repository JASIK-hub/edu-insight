"""Generate reproducible, explicitly synthetic educational data."""

import io
import random
from datetime import date, timedelta

from app.repositories import session_factory
from app.services.dataset_service import import_dataset


def main():
    rng = random.Random(20261110)
    subjects = {
        "Mathematics": ["Fractions", "Algebra", "Geometry", "Statistics"],
        "Science": ["Ecology", "Forces", "Energy", "Cells"],
        "Language": ["Reading", "Writing", "Grammar", "Literature"],
    }
    lines = ["student_id,classroom,grade,subject,topic,textbook,score,max_score,assessment_date"]
    for grade in (5, 6, 7, 8, 9):
        for room in ("A", "B", "C", "D"):
            for student_number in range(1, 31):
                student_id = f"SYN-{grade}{room}-{student_number:03d}"
                for subject, topics in subjects.items():
                    for topic in rng.sample(topics, 2):
                        score = rng.randint(5, 20)
                        day = date(2026, 9, 1) + timedelta(days=rng.randint(0, 60))
                        lines.append(f"{student_id},{grade}{room},{grade},{subject},{topic},Synthetic {subject} Grade {grade},{score},20,{day.isoformat()}")
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    with session_factory()() as session:
        result = import_dataset(session, io.BytesIO(payload), "SYNTHETIC_demo.csv", "SYNTHETIC EduInsight Demo School", synthetic=True)
    if not result.ok:
        raise RuntimeError(f"Seed failed: {result.errors}")
    print(f"Synthetic dataset {result.dataset_id}: 600 students, {result.imported_rows} assessment rows")


if __name__ == "__main__":
    main()
