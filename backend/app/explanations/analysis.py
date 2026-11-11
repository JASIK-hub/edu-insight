"""Backend owns facts; AI may propose bounded teaching steps as hypotheses."""

import asyncio
import json
import logging
from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict

from app.config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_ENABLED, OPENAI_MAX_RETRIES, OPENAI_MODEL, OPENAI_TIMEOUT
from app.contracts import (AnalysisCurriculum, AnalysisEvidence, AnalysisFinding,
    AnalysisHourExplanation, AnalysisRecommendation, AnalysisRequest, AnalysisSummary,
    AnalysisTextbook, AnalysisTopic, EduInsightAnalysisResponse, OptimizeOut,
    OverviewOut, SkillMetric, TextbooksOut, TopicsOut)
from app.explanations.service import _safe_facts

logger = logging.getLogger(__name__)
ActionCode = Literal["review_materials", "diagnose_gaps", "align_assessment"]


class ActionChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic_ref: str
    action_code: ActionCode
    focus_areas: list[str]
    classroom_step: str
    check_task: str


class ActionChoices(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actions: list[ActionChoice]


WORDS = {
    "ru": {
        "title": "Успеваемость по темам", "weak_summary": "Темы с низким освоением требуют внимания.",
        "good_summary": "Слабых тем в предоставленных данных не выявлено.", "empty": "Данных для выводов недостаточно.",
        "mastery": "Уровень освоения", "records": "Оценочных записей", "students": "Учащихся", "subject": "Предмет",
        "weak": "Освоение ниже заданного порога", "textbook_limit": "Наблюдаемые различия не доказывают преимущество учебника: возможны отбор учащихся и различия в исходной подготовке.",
        "no_hours": "Распределение часов не предоставлено.", "hours": "Показано рассчитанное backend распределение часов с сохранением общего бюджета.",
        "hour_reason": "Основание: измеренное освоение и рассчитанный приоритет.", "no_data": "Оценочные записи отсутствуют.",
        "quality": "Предупреждение о качестве данных", "priority": "Приоритет",
        "scope": "В выборке {records} оценочных записей от {students} учащихся по {topics} темам. Общее освоение по набранным и возможным баллам: {mastery}.",
        "weak_detail": "Тема находится ниже порога освоения {threshold}. Это сигнал для проверки конкретных затруднений, а не доказательство причины низкого результата.",
        "good_detail": "Тема не находится ниже порога освоения {threshold}. Следует сохранить наблюдение за результатами следующих оцениваний.",
        "topic_scope": "Показатель основан на {records} оценочных записях {students} учащихся. Результат описывает эту выборку и не показывает, какие именно задания вызвали затруднения.",
        "textbook_detail": "Показатель относится к {topics} темам в этой выборке. Сравнивать учебники следует с учётом размера групп и исходной подготовки учащихся.",
        "hour_detail": "Текущее число часов: {current}; рекомендованное: {recommended}; изменение: {change}. Общий бюджет часов сохранён; перераспределение рассчитано алгоритмом, а не моделью ИИ.",
        "action_detail": "Сначала изучить ошибки в оценочных работах по этой теме, затем выбрать адресное изменение объяснения или практики и проверить результат на следующем оценивании.",
        "sample_limit": "Наблюдаемые результаты относятся только к загруженным оценочным записям; они не доказывают причину различий или будущий эффект изменений.",
        "actions": {
            "review_materials": ("Пересмотреть материалы", "Сопоставить объяснения и упражнения по теме с заданиями оценивания."),
            "diagnose_gaps": ("Выявить пробелы", "Разобрать ошибки по теме и определить понятия, требующие повторного объяснения."),
            "align_assessment": ("Проверить оценивание", "Сопоставить задания по теме с учебными целями и проверить критерии оценивания."),
        },
    },
    "en": {
        "title": "Performance by topic", "weak_summary": "Weak topics need attention.", "good_summary": "No weak topics were identified.", "empty": "Insufficient data for conclusions.",
        "mastery": "Mastery", "records": "Assessment records", "students": "Students", "subject": "Subject", "weak": "Mastery is below the threshold",
        "textbook_limit": "Observed differences do not establish textbook superiority; selection and prior knowledge may differ.",
        "no_hours": "No hour allocation was supplied.", "hours": "The backend allocation preserves the total hours budget.",
        "hour_reason": "Based on measured mastery and computed priority.", "no_data": "No assessment records were supplied.",
        "quality": "Data quality warning", "priority": "Priority",
        "scope": "The sample contains {records} assessment records from {students} students across {topics} topics. Overall mastery by earned and possible points is {mastery}.",
        "weak_detail": "This topic is below the mastery threshold of {threshold}. This calls for reviewing specific learning gaps, but does not establish why the score is low.",
        "good_detail": "This topic is not below the mastery threshold of {threshold}. Continue monitoring future assessments.",
        "topic_scope": "The measure is based on {records} assessment records from {students} students. It describes this sample and does not identify which questions caused difficulty.",
        "textbook_detail": "This measure spans {topics} topics in the sample. Compare textbooks with attention to group sizes and students' prior knowledge.",
        "hour_detail": "Current hours: {current}; recommended hours: {recommended}; change: {change}. The total budget is preserved; the allocation was computed by the backend, not AI.",
        "action_detail": "First review errors in assessments for this topic, then choose a targeted change to instruction or practice and check the next assessment.",
        "sample_limit": "Observed results describe only uploaded assessment records; they do not establish causes or future effects.",
        "actions": {
            "review_materials": ("Review materials", "Compare explanations and exercises for this topic with assessment tasks."),
            "diagnose_gaps": ("Diagnose gaps", "Review errors in this topic and identify concepts needing another explanation."),
            "align_assessment": ("Check assessment", "Compare assessment tasks with learning objectives and review scoring criteria."),
        },
    },
    "kk": {
        "title": "Тақырыптар бойынша үлгерім", "weak_summary": "Меңгеруі төмен тақырыптар назар аударуды қажет етеді.", "good_summary": "Әлсіз тақырыптар анықталмады.", "empty": "Қорытынды жасауға дерек жеткіліксіз.",
        "mastery": "Меңгеру деңгейі", "records": "Бағалау жазбалары", "students": "Оқушылар", "subject": "Пән", "weak": "Меңгеру деңгейі шектен төмен",
        "textbook_limit": "Бақыланған айырмашылық оқулықтың артықшылығын дәлелдемейді; іріктеу мен бастапқы дайындық әртүрлі болуы мүмкін.",
        "no_hours": "Сағаттар бөлінісі берілмеген.", "hours": "Backend бөлген жалпы сағат көлемі сақталған.",
        "hour_reason": "Өлшенген меңгеру деңгейі мен есептелген басымдыққа негізделген.", "no_data": "Бағалау жазбалары жоқ.",
        "quality": "Дерек сапасы туралы ескерту", "priority": "Басымдық",
        "scope": "Іріктемеде {students} оқушының {topics} тақырып бойынша {records} бағалау жазбасы бар. Жиналған және мүмкін ұпайлар бойынша жалпы меңгеру: {mastery}.",
        "weak_detail": "Бұл тақырыптың меңгерілуі {threshold} шегінен төмен. Нақты қиындықтарды тексеру қажет, бірақ төмен нәтиженің себебі дәлелденбеген.",
        "good_detail": "Бұл тақырыптың меңгерілуі {threshold} шегінен төмен емес. Келесі бағалаулардың нәтижесін бақылаңыз.",
        "topic_scope": "Көрсеткіш {students} оқушының {records} бағалау жазбасына негізделген. Ол осы іріктемені сипаттайды, нақты қай тапсырма қиын болғанын көрсетпейді.",
        "textbook_detail": "Көрсеткіш іріктемедегі {topics} тақырыпты қамтиды. Оқулықтарды топ көлемі мен оқушылардың бастапқы дайындығын ескере отырып салыстырыңыз.",
        "hour_detail": "Қазіргі сағат: {current}; ұсынылған сағат: {recommended}; өзгеріс: {change}. Жалпы бюджет сақталған; бөліністі ИИ емес, backend есептеді.",
        "action_detail": "Алдымен осы тақырыптағы бағалау қателерін қарап, содан кейін түсіндіру не жаттығуға нақты өзгеріс енгізіп, келесі бағалауда тексеріңіз.",
        "sample_limit": "Бақыланған нәтиже тек жүктелген жазбаларды сипаттайды; себепті немесе болашақ әсерді дәлелдемейді.",
        "actions": {
            "review_materials": ("Материалдарды қайта қарау", "Тақырып түсіндірмелері мен жаттығуларын бағалау тапсырмаларымен салыстыру."),
            "diagnose_gaps": ("Олқылықтарды анықтау", "Тақырыптағы қателерді талдап, қайта түсіндіруді қажет ететін ұғымдарды анықтау."),
            "align_assessment": ("Бағалауды тексеру", "Тапсырмаларды оқу мақсаттарымен салыстырып, бағалау өлшемдерін тексеру."),
        },
    },
}


def _percent(value: float | None, language: str) -> str:
    if value is None:
        return "—"
    formatted = f"{value * 100:.1f}".rstrip("0").rstrip(".")
    return f"{formatted.replace('.', ',') if language in {'ru', 'kk'} else formatted}%"


def _measured_skill(topic: str, skills: list[SkillMetric]) -> SkillMetric | None:
    matches = [skill for skill in skills if skill.topic == topic and skill.student_count >= 5]
    return min(matches, key=lambda skill: (skill.accuracy_percent, -skill.student_count)) if matches else None


def _skill_sentence(skill: SkillMetric | None, language: str) -> str:
    if skill is None:
        return {"ru": "Ответы по заданиям для этой темы не загружены; конкретный пробел пока не измерен.",
                "en": "Item responses for this topic were not uploaded; a specific gap has not been measured.",
                "kk": "Бұл тақырып бойынша тапсырма жауаптары жүктелмеген; нақты олқылық әлі өлшенген жоқ."}[language]
    correct = skill.correct_answers
    total = skill.correct_answers + skill.incorrect_answers
    return {"ru": f"По навыку «{skill.skill}» верны {correct} из {total} ответов ({_percent(skill.accuracy_percent / 100, language)}); проверены {skill.student_count} учащихся.",
            "en": f"For the skill '{skill.skill}', {correct} of {total} answers were correct ({_percent(skill.accuracy_percent / 100, language)}) across {skill.student_count} students.",
            "kk": f"«{skill.skill}» дағдысы бойынша {total} жауаптың {correct}-і дұрыс ({_percent(skill.accuracy_percent / 100, language)}); {skill.student_count} оқушы тексерілді."}[language]


def _safe_choice(choice: ActionChoice) -> bool:
    return (1 <= len(choice.focus_areas) <= 3
            and len(set(choice.focus_areas)) == len(choice.focus_areas)
            and all(text.strip() and len(text) <= limit and not any(ch.isdigit() for ch in text) and "%" not in text
                    for text, limit in ([(focus, 120) for focus in choice.focus_areas]
                                        + [(choice.classroom_step, 300), (choice.check_task, 300)])))


def _focus_sentence(choice: ActionChoice | None, language: str) -> str:
    if choice is None:
        return ""
    areas = ", ".join(f"«{focus}»" for focus in choice.focus_areas)
    return {"ru": f" ИИ предлагает проверить: {areas}. Это варианты для диагностики, а не измеренные ошибки.",
            "en": f"AI suggests checking: {areas}. These are diagnostic ideas, not measured errors.",
            "kk": f"ЖИ тексеруді ұсынады: {areas}. Бұлар өлшенген қателер емес, диагностикаға арналған ұсыныстар."}[language]


def _build_report(request: AnalysisRequest, overview: OverviewOut, topics: TopicsOut,
                  textbooks: TextbooksOut, optimization: OptimizeOut | None,
                  quality: dict, actions: dict[str, ActionChoice],
                  skills: list[SkillMetric] | None = None) -> EduInsightAnalysisResponse:
    w = WORDS[request.language]
    skills = skills or []
    weak = [item for item in topics.topics if item.is_weak]
    findings = [AnalysisFinding(
        id=f"finding_{i:03d}", title=item.topic,
        description=(f"{w['mastery']}: {_percent(item.mastery, request.language)}; "
                     f"{w['records']}: {item.sample_size}; {w['students']}: {item.student_count}. "
                     f"{w['weak']} ({_percent(topics.weak_threshold, request.language)}). "
                     + _skill_sentence(_measured_skill(item.topic, skills), request.language)
                     + _focus_sentence(actions.get(item.topic), request.language)),
        severity="high", topic=item.topic,
        evidence=[AnalysisEvidence(metric="mastery", value=item.mastery, unit="ratio"),
                  AnalysisEvidence(metric="sample_size", value=item.sample_size, unit="records")]
                 + ([AnalysisEvidence(metric="skill_accuracy", value=_measured_skill(item.topic, skills).accuracy_percent, unit="percent"),
                     AnalysisEvidence(metric="incorrect_answers", value=_measured_skill(item.topic, skills).incorrect_answers, unit="answers")]
                    if _measured_skill(item.topic, skills) else []),
    ) for i, item in enumerate(weak, 1)]
    topic_analysis = [AnalysisTopic(
        topic=item.topic, status="needs_attention" if item.is_weak else "satisfactory",
        interpretation=(f"{w['mastery']}: {_percent(item.mastery, request.language)}; {w['records']}: {item.sample_size}; "
                        f"{w['students']}: {item.student_count}. "
                        + w["weak_detail" if item.is_weak else "good_detail"].format(threshold=_percent(topics.weak_threshold, request.language))
                        + " " + w["topic_scope"].format(records=item.sample_size, students=item.student_count)
                        + " " + _skill_sentence(_measured_skill(item.topic, skills), request.language)
                        + _focus_sentence(actions.get(item.topic), request.language)),
        main_concern=w["weak"] if item.is_weak else None,
    ) for item in topics.topics]
    textbook_analysis = [AnalysisTextbook(
        textbook=item.textbook,
        observation=(f"{w['mastery']}: {_percent(item.mastery, request.language)}; {w['records']}: {item.sample_size}; "
                     f"{w['students']}: {item.student_count}. "
                     + w["textbook_detail"].format(topics=item.topic_count)),
        limitations=[w["textbook_limit"]],
    ) for item in textbooks.textbooks]
    hours = [] if optimization is None else [AnalysisHourExplanation(
        topic=item.topic, current_hours=item.current_hours,
        recommended_hours=item.recommended_hours,
        reason=(f"{w['hour_reason']} {w['mastery']}: {_percent(item.mastery, request.language)}; {w['priority']}: {round(item.priority, 2)}. "
                + w["hour_detail"].format(current=item.current_hours,
                    recommended=item.recommended_hours, change=item.change)),
    ) for item in optimization.allocations]
    recommendations = []
    for i, item in enumerate(weak, 1):
        choice = actions.get(item.topic)
        title, action = w["actions"][choice.action_code if choice else "diagnose_gaps"]
        measured = _measured_skill(item.topic, skills)
        if choice:
            detail = _focus_sentence(choice, request.language).strip() + " " + ({
                "ru": f"На уроке: {choice.classroom_step} Проверка: {choice.check_task}",
                "en": f"In class: {choice.classroom_step} Check: {choice.check_task}",
                "kk": f"Сабақта: {choice.classroom_step} Тексеру: {choice.check_task}"}[request.language])
        elif measured:
            detail = ({"ru": f"Начните с навыка «{measured.skill}»: разберите одно типовое задание, затем дайте новое задание на тот же навык и сравните ответы.",
                       "en": f"Start with '{measured.skill}': review one representative item, then give a new item on the same skill and compare responses.",
                       "kk": f"«{measured.skill}» дағдысынан бастаңыз: бір үлгі тапсырманы талдап, сол дағдыға жаңа тапсырма беріп, жауаптарды салыстырыңыз."}[request.language])
        else:
            detail = w["action_detail"]
        recommendations.append(AnalysisRecommendation(
            id=f"rec_{i:03d}", title=title, priority="high",
            action=action + " " + detail,
            related_topics=[item.topic],
            evidence=[f"{item.topic}: {w['mastery']} {_percent(item.mastery, request.language)}; {w['records']} {item.sample_size}; "
                      f"{w['students']} {item.student_count}."] + ([_skill_sentence(measured, request.language)] if measured else []),
        ))
    limitations = [w["sample_limit"]]
    if textbooks.textbooks:
        limitations.append(w["textbook_limit"])
    if overview.observation_count == 0:
        limitations.append(w["no_data"])
    if optimization is None:
        limitations.append(w["no_hours"])
    summary = w["empty"] if overview.observation_count == 0 else (
        w["weak_summary"] if weak else w["good_summary"]
    ) + (f" {w['subject']}: {request.subject}." if request.subject else "") + " " + w["scope"].format(records=overview.observation_count,
        students=overview.student_count, topics=overview.topic_count,
        mastery=_percent(overview.overall_mastery, request.language))
    return EduInsightAnalysisResponse(
        executive_summary=AnalysisSummary(
            title=w["title"], summary=summary,
            overall_status="insufficient_data" if overview.observation_count == 0 else "needs_attention" if weak else "satisfactory",
            key_findings_count=len(findings)),
        key_findings=findings, topic_analysis=topic_analysis,
        textbook_analysis=textbook_analysis,
        curriculum_explanation=AnalysisCurriculum(
            summary=w["no_hours"] if optimization is None else w["hours"],
            total_hours_preserved=None if optimization is None else sum(item.recommended_hours for item in optimization.allocations) == optimization.total_hours,
            topic_explanations=hours),
        recommendations=recommendations, limitations=limitations,
        data_quality_warnings=[f"{w['quality']}: {key}" for key in quality],
        generated_language=request.language,
    )


async def analyze(request: AnalysisRequest, overview: OverviewOut, topics: TopicsOut,
                  textbooks: TextbooksOut, skills: list[SkillMetric] | None = None,
                  grades: list[int] | None = None) -> EduInsightAnalysisResponse:
    quality = _safe_facts(request.data_quality)
    skills = skills or []
    weak = [item for item in topics.topics if item.is_weak]
    actions: dict[str, ActionChoice] = {}
    if weak and OPENAI_ENABLED and OPENAI_API_KEY:
        topic_refs = {f"t{index}": item.topic for index, item in enumerate(weak, 1)}
        payload = {"subject": request.subject, "grades": grades or [], "language": request.language,
                   "weak_topics": [{"topic_ref": f"t{index}", "topic": item.topic,
                                    "mastery_percent": round(item.mastery * 100, 1),
                                    "sample_size": item.sample_size,
                                    "measured_skills": [{"skill": skill.skill,
                                                         "accuracy_percent": skill.accuracy_percent,
                                                         "correct_answers": skill.correct_answers,
                                                         "incorrect_answers": skill.incorrect_answers,
                                                         "student_count": skill.student_count}
                                                        for skill in sorted((s for s in skills if s.topic == item.topic and s.student_count >= 5),
                                                                            key=lambda s: s.accuracy_percent)[:3]]}
                                   for index, item in enumerate(weak, 1)],
                   "allowed_action_codes": ["review_materials", "diagnose_gaps", "align_assessment"]}
        try:
            client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL,
                                 timeout=OPENAI_TIMEOUT, max_retries=OPENAI_MAX_RETRIES)
            for attempt in range(2):
                try:
                    response = await asyncio.wait_for(client.responses.create(
                        model=OPENAI_MODEL,
                        instructions=("You are an educational assistant for teachers. For each weak topic, return exactly one action. "
                                      "Use the supplied topic_ref and one allowed action_code. Write focus_areas, classroom_step, and check_task in the requested language. "
                                      "The teacher may provide only a broad topic such as Algebra. Use your pedagogical knowledge to propose two or three distinct, plausible prerequisite or related subtopics in focus_areas, beyond merely repeating the uploaded topic. "
                                      "Respect the supplied subject and grade levels when available; do not suggest material clearly beyond that curriculum level. "
                                      "These are your own teaching hypotheses to test, not observed errors or established causes. "
                                      "When measured_skills are present, include the weakest measured skill among the focus areas and add relevant related areas. "
                                      "classroom_step must give a concrete brief teaching activity; check_task must give a concrete new diagnostic task. "
                                      "Do not claim a specific misconception or cause was observed unless it is directly in the supplied skill names and counts. "
                                      "Do not invent scores, sample sizes, hours, student identities, textbook effects, or learning gains. "
                                      "Do not put numbers or percentages in generated text fields. Return only JSON."),
                        input=json.dumps(payload, ensure_ascii=False),
                        text={"format": {"type": "json_schema", "name": "EduInsightActionChoices",
                                         "strict": True, "schema": ActionChoices.model_json_schema()}},
                    ), timeout=OPENAI_TIMEOUT + 5)
                    selected = ActionChoices.model_validate_json(response.output_text)
                    if (len(selected.actions) != len(topic_refs)
                            or {item.topic_ref for item in selected.actions} != set(topic_refs)
                            or not all(_safe_choice(item) for item in selected.actions)):
                        raise ValueError("AI suggestions did not match the requested topics or text limits")
                    actions = {topic_refs[item.topic_ref]: item for item in selected.actions}
                    break
                except Exception as exc:
                    if attempt == 1:
                        logger.warning("AI suggestions unavailable after retry (%s); using defaults", type(exc).__name__)
        except Exception as exc:
            logger.warning("AI action selection unavailable (%s); using defaults", type(exc).__name__)
    return _build_report(request, overview, topics, textbooks, request.optimization, quality, actions, skills)
