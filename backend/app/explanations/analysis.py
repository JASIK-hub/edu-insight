"""The backend owns every fact; AI can only choose a vetted action code."""

import json
import logging
from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict

from app.config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_ENABLED, OPENAI_MAX_RETRIES, OPENAI_MODEL, OPENAI_TIMEOUT
from app.contracts import (AnalysisCurriculum, AnalysisEvidence, AnalysisFinding,
    AnalysisHourExplanation, AnalysisRecommendation, AnalysisRequest, AnalysisSummary,
    AnalysisTextbook, AnalysisTopic, EduInsightAnalysisResponse, OptimizeOut,
    OverviewOut, TextbooksOut, TopicsOut)
from app.explanations.service import _safe_facts

logger = logging.getLogger(__name__)
ActionCode = Literal["review_materials", "diagnose_gaps", "align_assessment"]


class ActionChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic_ref: str
    action_code: ActionCode


class ActionChoices(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actions: list[ActionChoice]


WORDS = {
    "ru": {
        "title": "Успеваемость по темам", "weak_summary": "Темы с низким освоением требуют внимания.",
        "good_summary": "Слабых тем в предоставленных данных не выявлено.", "empty": "Данных для выводов недостаточно.",
        "mastery": "Уровень освоения", "records": "Оценочных записей", "students": "Учащихся",
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
        "mastery": "Mastery", "records": "Assessment records", "students": "Students", "weak": "Mastery is below the threshold",
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
        "mastery": "Меңгеру деңгейі", "records": "Бағалау жазбалары", "students": "Оқушылар", "weak": "Меңгеру деңгейі шектен төмен",
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


def _build_report(request: AnalysisRequest, overview: OverviewOut, topics: TopicsOut,
                  textbooks: TextbooksOut, optimization: OptimizeOut | None,
                  quality: dict, actions: dict[str, ActionCode]) -> EduInsightAnalysisResponse:
    w = WORDS[request.language]
    weak = [item for item in topics.topics if item.is_weak]
    findings = [AnalysisFinding(
        id=f"finding_{i:03d}", title=item.topic,
        description=(f"{w['mastery']}: {item.mastery}; {w['records']}: {item.sample_size}; "
                     f"{w['students']}: {item.student_count}. "
                     + w["weak_detail"].format(threshold=topics.weak_threshold) + " "
                     + w["topic_scope"].format(records=item.sample_size, students=item.student_count)),
        severity="high", topic=item.topic,
        evidence=[AnalysisEvidence(metric="mastery", value=item.mastery, unit="ratio"),
                  AnalysisEvidence(metric="sample_size", value=item.sample_size, unit="records")],
    ) for i, item in enumerate(weak, 1)]
    topic_analysis = [AnalysisTopic(
        topic=item.topic, status="needs_attention" if item.is_weak else "satisfactory",
        interpretation=(f"{w['mastery']}: {item.mastery}; {w['records']}: {item.sample_size}; "
                        f"{w['students']}: {item.student_count}. "
                        + w["weak_detail" if item.is_weak else "good_detail"].format(threshold=topics.weak_threshold)
                        + " " + w["topic_scope"].format(records=item.sample_size, students=item.student_count)),
        main_concern=w["weak"] if item.is_weak else None,
    ) for item in topics.topics]
    textbook_analysis = [AnalysisTextbook(
        textbook=item.textbook,
        observation=(f"{w['mastery']}: {item.mastery}; {w['records']}: {item.sample_size}; "
                     f"{w['students']}: {item.student_count}. "
                     + w["textbook_detail"].format(topics=item.topic_count)),
        limitations=[w["textbook_limit"]],
    ) for item in textbooks.textbooks]
    hours = [] if optimization is None else [AnalysisHourExplanation(
        topic=item.topic, current_hours=item.current_hours,
        recommended_hours=item.recommended_hours,
        reason=(f"{w['hour_reason']} {w['mastery']}: {item.mastery}; {w['priority']}: {item.priority}. "
                + w["hour_detail"].format(current=item.current_hours,
                    recommended=item.recommended_hours, change=item.change)),
    ) for item in optimization.allocations]
    recommendations = []
    for i, item in enumerate(weak, 1):
        title, action = w["actions"][actions.get(item.topic, "diagnose_gaps")]
        recommendations.append(AnalysisRecommendation(
            id=f"rec_{i:03d}", title=title, priority="high",
            action=action + " " + w["action_detail"],
            related_topics=[item.topic],
            evidence=[f"{item.topic}: {w['mastery']} {item.mastery}; {w['records']} {item.sample_size}; "
                      f"{w['students']} {item.student_count}."],
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
    ) + " " + w["scope"].format(records=overview.observation_count,
        students=overview.student_count, topics=overview.topic_count,
        mastery=overview.overall_mastery)
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
                  textbooks: TextbooksOut) -> EduInsightAnalysisResponse:
    quality = _safe_facts(request.data_quality)
    weak = [item for item in topics.topics if item.is_weak]
    actions: dict[str, ActionCode] = {}
    if weak and OPENAI_ENABLED and OPENAI_API_KEY:
        topic_refs = {f"t{index}": item.topic for index, item in enumerate(weak, 1)}
        payload = {"weak_topics": [{"topic_ref": f"t{index}", "mastery": item.mastery,
                   "sample_size": item.sample_size} for index, item in enumerate(weak, 1)],
                   "allowed_action_codes": ["review_materials", "diagnose_gaps", "align_assessment"]}
        try:
            client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL,
                                 timeout=OPENAI_TIMEOUT, max_retries=OPENAI_MAX_RETRIES)
            response = await client.responses.create(
                model=OPENAI_MODEL,
                instructions=("Choose one allowed action_code for each weak topic. "
                              "Use only supplied opaque topic_ref values. "
                              "Return only JSON. Do not create topics, metrics, hours, or prose."),
                input=json.dumps(payload, ensure_ascii=False),
                text={"format": {"type": "json_schema", "name": "EduInsightActionChoices",
                                 "strict": True, "schema": ActionChoices.model_json_schema()}},
            )
            selected = ActionChoices.model_validate_json(response.output_text)
            if len(selected.actions) == len(topic_refs) and {item.topic_ref for item in selected.actions} == set(topic_refs):
                actions = {topic_refs[item.topic_ref]: item.action_code for item in selected.actions}
            else:
                logger.warning("AI action choices did not match weak topics; using defaults")
        except Exception as exc:
            logger.warning("AI action selection unavailable (%s); using defaults", type(exc).__name__)
    return _build_report(request, overview, topics, textbooks, request.optimization, quality, actions)
