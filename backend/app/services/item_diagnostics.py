"""Import item-level answers and summarize verified skill gaps."""

import csv
import io
from collections import defaultdict

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.contracts import ItemImportOut, SkillAnalyticsOut, SkillMetric
from app.storage.models import Assessment, Dataset, ItemResponse

REQUIRED = {"student_id", "topic", "skill", "item_id", "is_correct"}
TRUE_VALUES = {"1", "true", "yes"}
FALSE_VALUES = {"0", "false", "no"}


def _parse(content: bytes) -> list[dict[str, object]]:
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV must be UTF-8") from exc
    if not decoded.strip():
        raise ValueError("CSV is empty")
    try:
        reader = csv.DictReader(io.StringIO(decoded, newline=""), strict=True)
        if reader.fieldnames is None or set(reader.fieldnames) not in (REQUIRED, REQUIRED | {"subject"}) or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError(f"CSV headers must contain {', '.join(sorted(REQUIRED))}; subject is optional")
        rows: list[dict[str, object]] = []
        seen: set[tuple[str, str | None, str, str]] = set()
        item_skills: dict[tuple[str | None, str], tuple[str, str]] = {}
        for line, row in enumerate(reader, start=2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"row {line}: incorrect column count")
            values = {field: (row[field] or "").strip() for field in REQUIRED}
            subject = (row.get("subject") or "").strip() or None
            if subject is not None and len(subject) > 255:
                raise ValueError(f"row {line}: subject must be at most 255 characters")
            if any(not values[field] or len(values[field]) > 255 for field in REQUIRED):
                raise ValueError(f"row {line}: fields must be nonempty and at most 255 characters")
            truth = values["is_correct"].lower()
            if truth not in TRUE_VALUES | FALSE_VALUES:
                raise ValueError(f"row {line}: is_correct must be 1 or 0")
            key = (values["student_id"], subject, values["topic"], values["item_id"])
            if key in seen:
                raise ValueError(f"row {line}: duplicate student/topic/item response")
            seen.add(key)
            item_key = (subject, values["item_id"])
            topic_skill = (values["topic"], values["skill"])
            if item_key in item_skills and item_skills[item_key] != topic_skill:
                raise ValueError(f"row {line}: item_id must have one topic and skill")
            item_skills[item_key] = topic_skill
            rows.append({**{field: values[field] for field in REQUIRED - {"is_correct"}}, "subject": subject,
                         "is_correct": truth in TRUE_VALUES})
    except csv.Error as exc:
        raise ValueError(f"malformed CSV: {exc}") from exc
    if not rows:
        raise ValueError("CSV has no item responses")
    return rows


def import_item_responses(session: Session, dataset_id: int, content: bytes) -> ItemImportOut:
    if session.get(Dataset, dataset_id) is None:
        raise LookupError("Dataset not found")
    rows = _parse(content)
    known = set(session.execute(select(Assessment.student_id, Assessment.topic, Assessment.subject)
                                .where(Assessment.dataset_id == dataset_id)).all())
    for line, row in enumerate(rows, start=2):
        matches = {subject for student, topic, subject in known
                   if student == row["student_id"] and topic == row["topic"]}
        if not matches:
            raise ValueError(f"row {line}: student_id and topic must match the selected dataset")
        if row["subject"] is None:
            if len(matches) > 1:
                raise ValueError(f"row {line}: subject is required because this student and topic occur in multiple subjects")
            row["subject"] = next(iter(matches))
        elif row["subject"] not in matches:
            raise ValueError(f"row {line}: subject must match the selected dataset")
    try:
        session.execute(delete(ItemResponse).where(ItemResponse.dataset_id == dataset_id))
        session.add_all(ItemResponse(dataset_id=dataset_id, **row) for row in rows)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return ItemImportOut(dataset_id=dataset_id, row_count=len(rows),
                         skill_count=len({(row["subject"], row["topic"], row["skill"]) for row in rows}))


def skill_analytics(session: Session, dataset_id: int, topic: str | None = None,
                    subject: str | None = None) -> SkillAnalyticsOut:
    if session.get(Dataset, dataset_id) is None:
        raise LookupError("Dataset not found")
    query = select(ItemResponse).where(ItemResponse.dataset_id == dataset_id)
    if topic is not None:
        query = query.where(ItemResponse.topic == topic)
    if subject is not None:
        query = query.where(ItemResponse.subject == subject)
    rows = session.scalars(query).all()
    groups: dict[tuple[str | None, str, str], list[ItemResponse]] = defaultdict(list)
    for row in rows:
        groups[(row.subject, row.topic, row.skill)].append(row)
    skills = []
    for (subject_name, topic_name, skill), group in sorted(groups.items(), key=lambda item: (item[0][0] or "", item[0][1], item[0][2])):
        correct = sum(row.is_correct for row in group)
        students = len({row.student_id for row in group})
        accuracy = round(correct / len(group) * 100, 2)
        if students < 5:
            status = "insufficient_data"
            action = "Проверьте навык дополнительными заданиями: выборка меньше пяти учащихся."
        elif accuracy < 75:
            status = "needs_attention"
            action = "Разберите типичные ошибки и проведите короткую повторную диагностику этого навыка."
        else:
            status = "on_target"
            action = "Продолжайте практику и проверяйте сохранение результата в следующих работах."
        skills.append(SkillMetric(subject=subject_name, topic=topic_name, skill=skill, correct_answers=correct,
                                  incorrect_answers=len(group) - correct, student_count=students,
                                  item_count=len({row.item_id for row in group}),
                                  accuracy_percent=accuracy, status=status, suggested_action=action))
    return SkillAnalyticsOut(dataset_id=dataset_id, item_response_count=len(rows), skills=skills)
