from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import httpx

from .config import GEMINI_API_KEY, GEMINI_MODEL
from .exercises import get_progression
from .models import Exercise

logger = logging.getLogger("italian-test")

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
GENERATE_TIMEOUT = 60.0
MAX_RETRIES = 3

# Instruction block shared by all parts. UI-facing text is Italian; code is English.
_BASE_INSTRUCTIONS = """You are an expert Italian language teacher specializing in the PLIDA B1 exam.
Create authentic Italian reading-comprehension exercises at B1 level (CEFR), as close as possible
to the real exam papers shown below in the EXAMPLES.

Rules:
- ALL text, questions, options, explanations and keyword definitions MUST be in Italian.
- The content must be realistic, clear and appropriate for adult learners (avvisi, annunci, ricette, recensioni, notizie, piccoli testi informativi), exactly like the EXAMPLES.
- Match the EXAMPLES in: register, text length, option length, question phrasing and how distractors are written (plausible but clearly wrong).
- The vocabulary difficulty must be B1: everyday, concrete words.
- Exactly one option must be clearly correct; the others must be plausible but clearly wrong.
- The 'explanation' must be in Italian, brief, and must quote the exact sentence in the passage that justifies the answer.
- 'keywords' must contain 2 to 4 difficult B1-level terms found in the text, with a short Italian definition (simple words).
- Return ONLY valid JSON. No markdown fences, no comments, no trailing text.
"""

_PART_SCHEMAS: dict[int, str] = {
    1: """PART 1 — Testi brevi e comprensione globale.
Return a JSON object with EXACTLY this shape (field names fixed):
{
  "id": "gen-p1-XXX", "part": 1,
  "title": "<short title in Italian>",
  "topic": "<topic in Italian>",
  "text": "<a short practical text of 40-80 words in Italian: avviso, annuncio, ricetta, recensione, comunicazione>",
  "question": "<question in Italian, e.g. 'Questo testo…', 'Secondo il testo…', 'L'avviso informa che…'>",
  "options": [ {"key": "A", "text": "..."}, {"key": "B", "text": "..."}, {"key": "C", "text": "..."}, {"key": "D", "text": "..."} ],
  "correctAnswer": "<A|B|C|D>",
  "explanation": "<Italian explanation quoting the justifying sentence from the text>",
  "keywords": [ {"term": "...", "definition": "..."} ]
}""",
    2: """PART 2 — Abbinamento / Corrispondenza.
Create 4 profiles (numbered 7, 8, 9, 10) of people looking for something, and 7 ads (keys A to G). Two ads are extra (distractors).
Return a JSON object with EXACTLY this shape:
{
  "id": "gen-p2-XXX", "part": 2,
  "title": "<Italian title>",
  "instructions": "<Italian instructions>",
  "example": "<text of the example person's request> → A",
  "profiles": [ {"number": 7, "text": "«Cerco …»"}, ... four profiles ... ],
  "ads": [ {"key": "A", "text": "<ad text>"}, ... seven ads ... ],
  "solution": {"7": "A", "8": "D", "9": "E", "10": "B"},
  "explanation": {"7": "<brief Italian explanation quoting the matching clue>", ...},
  "keywords": [ {"term": "...", "definition": "..."} ]
}
Each profile must match exactly one ad; every ad key used in 'solution' must exist in 'ads'.""",
    3: """PART 3 — Completamento del testo con lacune.
Create a coherent Italian passage with 3 numbered blanks (numbers 11, 12, 13). Each blank is filled by a missing sentence chosen from ONE shared set of 6 sentences (keys A to F); two sentences are extra (not used).
Return a JSON object with EXACTLY this shape:
{
  "id": "gen-p3-XXX", "part": 3,
  "title": "<Italian title>",
  "instructions": "<Italian instructions>",
  "intro": "<optional short Italian introduction of 1-2 lines>",
  "segments": [ {"type": "text", "content": "<passage part>"}, {"type": "blank", "number": 11}, ... ],
  "blanks": [ {"number": 11, "options": [ {"key": "A", "text": "..."}, ... six options (same set for all blanks) ... ], "correct": "F"}, ... three blanks ... ],
  "explanation": {"11": "<Italian explanation>", ...},
  "keywords": [ {"term": "...", "definition": "..."} ]
}
The 'segments' array must interleave text pieces and blanks in reading order; concatenating text parts must form a natural passage where each blank slot holds exactly one of its options.""",
    4: """PART 4 — Notizie e titoli di giornale.
Create 5 short Italian news blurbs (numbered 14, 15, 16, 17, 18, each 25-50 words) and 9 newspaper headlines (keys A to I). Three headlines are extra (distractors).
Return a JSON object with EXACTLY this shape:
{
  "id": "gen-p4-XXX", "part": 4,
  "title": "<Italian title>",
  "instructions": "<Italian instructions>",
  "example": "<text of the example news blurb> → A",
  "news": [ {"number": 14, "text": "<news blurb in Italian>"}, ... five news ... ],
  "headlines": [ {"key": "A", "text": "<headline>"}, ... nine headlines ... ],
  "solution": {"14": "C", "15": "G", ...},
  "explanation": {"14": "<brief Italian explanation>", ...},
  "keywords": [ {"term": "...", "definition": "..."} ]
}
Every headline key used in 'solution' must exist in 'headlines'.""",
}


def _example_json(ex: Exercise) -> str:
    """Serialize a real seed exercise into a compact prompt example."""
    return json.dumps(ex.model_dump(), ensure_ascii=False, indent=2)


def _build_prompt(part: int, topic: str, count: int) -> str:
    schema = _PART_SCHEMAS.get(part)
    if not schema:
        raise ValueError(f"unsupported part: {part}")
    examples = get_progression(part)[:2]
    examples_block = "\n\n".join(_example_json(ex) for ex in examples)
    topic_line = f"\nSuggested topic (optional): {topic}" if topic else ""
    count_line = f"\nGenerate {count} exercise(s). If count > 1, return a JSON ARRAY of objects, each matching the shape below."
    return (
        _BASE_INSTRUCTIONS
        + f"\n\nREAL EXAMPLES (imitate their style, length and difficulty):\n{examples_block}"
        + topic_line
        + count_line
        + "\n\n"
        + schema
    )


def generate_exercises(part: int, topic: str = "", count: int = 1) -> list[Exercise]:
    """Call Gemini Flash and return validated Exercise objects."""
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY non configurata")

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": _build_prompt(part, topic, count)}],
            }
        ],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 8192,
            "responseMimeType": "application/json",
        },
    }

    url = f"{API_BASE}/models/{GEMINI_MODEL}:generateContent"
    params = {"key": GEMINI_API_KEY}

    with httpx.Client(timeout=GENERATE_TIMEOUT) as client:
        resp = client.post(url, params=params, json=payload)
        if resp.status_code != 200:
            detail = resp.text[:500]
            logger.error("gemini request failed: %s %s", resp.status_code, detail)
            raise RuntimeError(f"Errore dal generatore IA ({resp.status_code})")
        data = resp.json()

    text = _extract_text(data)
    raw = json.loads(text)

    items = raw if isinstance(raw, list) else [raw]
    if not isinstance(raw, list) and count > 1:
        items = [raw]

    exercises: list[Exercise] = []
    for item in items[:count]:
        exercises.append(Exercise.model_validate(item))
    return exercises


def validate_generated(ex: Exercise) -> bool:
    """Semantic checks to ensure a generated exercise looks like a real exam item."""
    try:
        if ex.part == 1:
            if len(ex.options) != 4 or not ex.text or not ex.question:
                return False
            keys = {o.key for o in ex.options}
            if ex.correctAnswer not in keys:
                return False
            if not ex.explanation or len(ex.text) < 30:
                return False
            return True

        if ex.part == 2:
            if len(ex.profiles) != 4 or len(ex.ads) != 7 or not ex.example:
                return False
            ad_keys = {a.key for a in ex.ads}
            for p in ex.profiles:
                sol = ex.solution.get(str(p.number))
                if sol not in ad_keys or str(p.number) not in ex.explanation:
                    return False
            return True

        if ex.part == 3:
            if len(ex.blanks) != 3 or not ex.segments:
                return False
            blank_numbers = {b.number for b in ex.blanks}
            seg_numbers = {s.number for s in ex.segments if s.type == "blank"}
            if blank_numbers != seg_numbers:
                return False
            option_set = None
            for b in ex.blanks:
                if len(b.options) != 6 or [o.key for o in b.options] != list("ABCDEF"):
                    return False
                if b.correct not in {o.key for o in b.options}:
                    return False
                if str(b.number) not in ex.explanation:
                    return False
                current_set = json.dumps([o.text for o in b.options], ensure_ascii=False)
                if option_set is None:
                    option_set = current_set
                elif option_set != current_set:
                    return False
            return True

        if ex.part == 4:
            if len(ex.news) != 5 or len(ex.headlines) != 9 or not ex.example:
                return False
            hl_keys = {h.key for h in ex.headlines}
            for n in ex.news:
                sol = ex.solution.get(str(n.number))
                if sol not in hl_keys or str(n.number) not in ex.explanation:
                    return False
            return True
    except Exception:  # noqa: BLE001
        return False
    return False


def generate_authentic_exercise(part: int) -> Exercise:
    """Generate one authentic exercise, validating and retrying up to MAX_RETRIES."""
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            ex = generate_exercises(part=part, count=1)[0]
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning("generation attempt %d failed: %s", attempt + 1, exc)
            continue
        if validate_generated(ex):
            ex.id = f"gen-p{part}-{uuid.uuid4().hex[:10]}"
            return ex
        logger.warning("generated exercise failed validation (attempt %d)", attempt + 1)
        last_error = ValueError("l'esercizio generato non rispetta il formato d'esame")
    raise RuntimeError(str(last_error) or "impossibile generare un esercizio valido")


def generate_report(stats_text: str, vocab_text: str) -> str:
    """Call Gemini Flash and return a plain-text Italian progress assessment."""
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY non configurata")

    prompt = (
        "You are an experienced Italian language tutor for the PLIDA B1 exam.\n"
        "Based on the statistics below, write a SHORT assessment in ITALIAN (max ~160 words) "
        "divided into three short sections: 'Cosa stai facendo bene', 'Cosa migliorare' and "
        "'Consigli pratici'. Be encouraging, concrete and B1-friendly.\n"
        "Write ONLY the assessment text in Italian. No markdown, no headers like '##'.\n\n"
        "STATISTICHE DI PRECISIONE PER PARTE (corrette/totali e percentuale):\n"
        + (stats_text or "(nessun esercizio completato finora)")
        + "\n\nVOCABOLARIO SALVATO (termini chiave che l'utente ha raccolto):\n"
        + (vocab_text or "(nessun termine salvato)")
    )

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1024},
    }
    url = f"{API_BASE}/models/{GEMINI_MODEL}:generateContent"
    params = {"key": GEMINI_API_KEY}

    with httpx.Client(timeout=GENERATE_TIMEOUT) as client:
        resp = client.post(url, params=params, json=payload)
        if resp.status_code != 200:
            detail = resp.text[:500]
            logger.error("gemini report failed: %s %s", resp.status_code, detail)
            raise RuntimeError(f"Errore nell'analisi IA ({resp.status_code})")
        data = resp.json()

    return _extract_text(data)


def _extract_text(data: dict[str, Any]) -> str:
    try:
        candidates = data.get("candidates", [])
        parts = candidates[0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts).strip()
    except Exception as exc:  # noqa: BLE001
        logger.error("failed to extract gemini text: %s", exc)
        raise RuntimeError("Risposta IA non valida")
