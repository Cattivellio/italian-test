from __future__ import annotations

import json
from pathlib import Path

from .config import EXERCISES_DIR
from .models import Exercise

_CACHE: dict[str, list[Exercise]] = {}


def _load_part(part: int) -> list[Exercise]:
    path: Path = EXERCISES_DIR / f"p{part}.json"
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        raw_list = json.load(fh)
    if not isinstance(raw_list, list):
        raw_list = [raw_list]
    return [Exercise.model_validate(item) for item in raw_list]


def get_exercises(part: int) -> list[Exercise]:
    if part not in _CACHE:
        _CACHE[part] = _load_part(part)
    return _CACHE[part]


def get_exercise(exercise_id: str) -> Exercise | None:
    for part in (1, 2, 3, 4):
        for ex in get_exercises(part):
            if ex.id == exercise_id:
                return ex
    return None


def all_exercises() -> list[Exercise]:
    out: list[Exercise] = []
    for part in (1, 2, 3, 4):
        out.extend(get_exercises(part))
    return out


def part_meta() -> list[dict]:
    return [
        {
            "part": 1,
            "title": "Testi brevi e comprensione globale",
            "short": "Testi brevi",
            "description": "Avvisi, annunci, ricette e recensioni con domande a scelta multipla (A/B/C/D).",
            "icon": "📄",
        },
        {
            "part": 2,
            "title": "Abbinamento / Corrispondenza",
            "short": "Abbinamento",
            "description": "Abbina ogni profilo all'annuncio (A–G) più adatto.",
            "icon": "🔗",
        },
        {
            "part": 3,
            "title": "Completamento del testo",
            "short": "Completamento",
            "description": "Completa il testo scegliendo la frase giusta per ogni lacuna numerata.",
            "icon": "✏️",
        },
        {
            "part": 4,
            "title": "Notizie e titoli di giornale",
            "short": "Titoli",
            "description": "Abbina ogni notizia breve al titolo di giornale più adatto.",
            "icon": "📰",
        },
    ]


def is_generated(exercise: Exercise) -> bool:
    """True for AI-generated exercises (gen-*), which are not part of the seed chain."""
    return exercise.id.startswith("gen-")


def get_progression(part: int) -> list[Exercise]:
    """The fixed seed chain (real exam order) used for the unlock progression.

    Returns only the exercises loaded from the seed file, in their original order,
    excluding any AI-generated items that were added to the session cache.
    """
    seed = _load_part(part)
    return [ex for ex in seed if not is_generated(ex)]


def is_unlocked(part: int, exercise_id: str, passed: set[str]) -> bool:
    """An exercise is unlocked if it's the first of its chain, the previous one is
    passed, or it has already been passed itself."""
    chain = get_progression(part)
    for idx, ex in enumerate(chain):
        if ex.id == exercise_id:
            if idx == 0:
                return True
            return chain[idx - 1].id in passed or ex.id in passed
    # Generated / unknown exercises are always accessible.
    return True
