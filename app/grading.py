from __future__ import annotations

from .models import Exercise

# UI-facing text in Italian (user-facing only).

FEEDBACK_CORRECT = "✅ Corretto!"
FEEDBACK_WRONG = "❌ Non corretto."


def grade_part1(exercise: Exercise, answer: str) -> dict:
    correct = answer.strip().upper() == exercise.correctAnswer.strip().upper()
    selected = next((o for o in exercise.options if o.key.upper() == answer.strip().upper()), None)
    correct_option = next((o for o in exercise.options if o.key == exercise.correctAnswer), None)
    return {
        "correct": correct,
        "selected_key": selected.key if selected else answer,
        "selected_text": selected.text if selected else "",
        "correct_key": exercise.correctAnswer,
        "correct_text": correct_option.text if correct_option else "",
        "explanation": exercise.explanation,
    }


def grade_part2(exercise: Exercise, answers: dict[str, str]) -> dict:
    results = []
    correct_count = 0
    for profile in exercise.profiles:
        key = str(profile.number)
        chosen = (answers.get(key) or "").strip().upper()
        expected = (exercise.solution.get(key) or "").strip().upper()
        is_correct = chosen == expected
        if is_correct:
            correct_count += 1
        results.append(
            {
                "number": profile.number,
                "profile_text": profile.text,
                "chosen": chosen,
                "expected": expected,
                "correct": is_correct,
                "explanation": exercise.explanation.get(key, ""),
            }
        )
    total = len(exercise.profiles)
    all_correct = correct_count == total
    return {"results": results, "correct": correct_count, "total": total, "all_correct": all_correct}


def grade_part3(exercise: Exercise, answers: dict[str, str]) -> dict:
    results = []
    correct_count = 0
    for blank in exercise.blanks:
        key = str(blank.number)
        chosen = (answers.get(key) or "").strip().upper()
        expected = blank.correct.strip().upper()
        is_correct = chosen == expected
        if is_correct:
            correct_count += 1
        chosen_option = next((o for o in blank.options if o.key == chosen), None)
        results.append(
            {
                "number": blank.number,
                "chosen": chosen,
                "expected": expected,
                "correct": is_correct,
                "chosen_text": chosen_option.text if chosen_option else "",
                "explanation": exercise.explanation.get(key, ""),
            }
        )
    total = len(exercise.blanks)
    all_correct = correct_count == total
    return {"results": results, "correct": correct_count, "total": total, "all_correct": all_correct}


def grade_part4(exercise: Exercise, answers: dict[str, str]) -> dict:
    results = []
    correct_count = 0
    for item in exercise.news:
        key = str(item.number)
        chosen = (answers.get(key) or "").strip().upper()
        expected = (exercise.solution.get(key) or "").strip().upper()
        is_correct = chosen == expected
        if is_correct:
            correct_count += 1
        results.append(
            {
                "number": item.number,
                "news_text": item.text,
                "chosen": chosen,
                "expected": expected,
                "correct": is_correct,
                "explanation": exercise.explanation.get(key, ""),
            }
        )
    total = len(exercise.news)
    all_correct = correct_count == total
    return {"results": results, "correct": correct_count, "total": total, "all_correct": all_correct}
