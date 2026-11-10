import json
import logging

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field

from app.config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_ENABLED, OPENAI_MAX_RETRIES, OPENAI_MODEL, OPENAI_TIMEOUT
from app.contracts import ExplainOut, ExplainRequest

logger = logging.getLogger(__name__)
_BLOCKED = {"student_id", "student_ids", "student_name", "student_names", "name", "names", "email", "emails", "phone", "phones", "csv", "raw_csv", "records", "students", "individual_records"}


class GeneratedExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    explanation: str = Field(min_length=1)


def _safe_facts(value, depth=0):
    if depth > 8:
        raise ValueError("facts are too deeply nested")
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key.lower() in _BLOCKED or any(word in key.lower() for word in ("email", "phone", "student_id", "raw_")):
                raise ValueError("facts contain individual or raw student data")
            result[key] = _safe_facts(item, depth + 1)
        return result
    if isinstance(value, list):
        if len(value) > 100:
            raise ValueError("facts contain too many entries")
        return [_safe_facts(item, depth + 1) for item in value]
    return value


def _fallback(request: ExplainRequest, facts: dict) -> ExplainOut:
    labels = {
        "en": ("Computed educational results", "These are descriptive results or scenario estimates; they do not establish causation."),
        "ru": ("Рассчитанные образовательные показатели", "Это описательные результаты или оценки сценария; они не доказывают причинно-следственную связь."),
        "kk": ("Есептелген білім беру көрсеткіштері", "Бұл сипаттамалық нәтижелер немесе сценарий бағалары; олар себеп-салдар байланысын дәлелдемейді."),
    }
    title, caveat = labels.get(request.locale.lower().split("-")[0], labels["en"])
    return ExplainOut(explanation=f"{title} ({request.kind}): {json.dumps(facts, ensure_ascii=False, sort_keys=True)}. {caveat}", source="fallback", model=None)


async def explain(request: ExplainRequest) -> ExplainOut:
    facts = _safe_facts(request.facts)
    if not OPENAI_ENABLED or not OPENAI_API_KEY:
        return _fallback(request, facts)
    try:
        client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL,
                             timeout=OPENAI_TIMEOUT, max_retries=OPENAI_MAX_RETRIES)
        response = await client.responses.create(
            model=OPENAI_MODEL,
            instructions=(
                "Explain supplied aggregate educational results in the requested language (English, Russian, or Kazakh). "
                "Use only supplied facts. Do not add metrics, calculate scores, change allocations, or claim causation. "
                "Textbook comparisons are descriptive associations. Simulations are scenario estimates. "
                "Return a JSON object with one nonempty string field named explanation."
            ),
            input=json.dumps({"locale": request.locale, "kind": request.kind, "facts": facts}, ensure_ascii=False),
            text={"format": {"type": "json_schema", "name": "educational_explanation", "strict": True,
                             "schema": {"type": "object", "properties": {"explanation": {"type": "string"}},
                                        "required": ["explanation"], "additionalProperties": False}}},
        )
        parsed = GeneratedExplanation.model_validate_json(response.output_text)
        source = "openrouter" if OPENAI_BASE_URL.rstrip("/") == "https://openrouter.ai/api/v1" else "openai"
        return ExplainOut(explanation=parsed.explanation, source=source, model=OPENAI_MODEL)
    except Exception:
        logger.warning("Explanation provider unavailable; using fallback")
        return _fallback(request, facts)
