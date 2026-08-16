from __future__ import annotations

import json
import logging
import random
import re
import secrets
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .auth import (
    DEVICE_COOKIE,
    cookie_kwargs,
    get_current_user,
    hash_password,
    hash_token,
    login_conflict,
    new_session_token,
    throttle,
    verify_password,
)
from .config import (
    ADMIN_NAME,
    ADMIN_PASSWORD,
    ADMIN_PHONE,
    GEMINI_API_KEY,
    SESSION_COOKIE_NAME,
    STATIC_DIR,
    TEMPLATES_DIR,
)
from .countries import COUNTRIES, DEFAULT_COUNTRY
from .database import (
    active_session_for_user,
    admin_exists,
    clear_sim_exercises,
    create_session,
    create_user,
    delete_keyword,
    delete_session_by_token,
    delete_user,
    get_ai_exercise,
    get_sim_exercise,
    get_user_by_phone,
    init_db,
    is_healthy,
    latest_ai_exercise,
    list_attempts,
    list_keywords,
    list_users,
    part_stats,
    passed_exercise_ids,
    record_attempt,
    reset_progress,
    revoke_sessions_for_user,
    save_ai_exercise,
    save_keyword,
    save_sim_exercise,
    set_user_password,
    stats,
)
from .exercises import (
    get_exercise,
    get_exercises,
    get_progression,
    is_generated,
    is_unlocked,
    part_meta,
)
from .gemini import generate_authentic_exercise, generate_report
from .grading import grade_part1, grade_part2, grade_part3, grade_part4
from .models import Exercise

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
)
logger = logging.getLogger("italian-test")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


class LoginRequired(Exception):
    pass


class Forbidden(Exception):
    pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if ADMIN_PHONE and ADMIN_PASSWORD and not admin_exists():
        create_user(
            _norm_phone(ADMIN_PHONE),
            hash_password(ADMIN_PASSWORD),
            ADMIN_NAME,
            role="admin",
        )
        logger.info("admin user created from env")
    logger.info("database ready")
    yield


app = FastAPI(
    title="IMPAROMA",
    description="Pratica di lettura per la certificazione PLIDA B1.",
    version="1.1.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.middleware("http")
async def ensure_device_id(request: Request, call_next):
    """Every device (browser/PWA) gets a long-lived device_id cookie.

    The id is computed before the route runs and exposed via request.state so
    that login binds the session to the same device even on the first request.
    """
    device = request.cookies.get(DEVICE_COOKIE)
    if not device:
        device = secrets.token_urlsafe(16)
        request.state.device_id = device
        response = await call_next(request)
        response.set_cookie(
            DEVICE_COOKIE, device, max_age=10 * 365 * 24 * 3600, **cookie_kwargs()
        )
        return response
    request.state.device_id = device
    return await call_next(request)


@app.exception_handler(LoginRequired)
async def _login_required(request: Request, exc: LoginRequired):
    return RedirectResponse(url="/login", status_code=303)


@app.exception_handler(Forbidden)
async def _forbidden(request: Request, exc: Forbidden):
    return RedirectResponse(url="/practice", status_code=303)


def _norm_phone(phone: str) -> str:
    """Normalize a phone number: keep digits and a single leading '+'."""
    s = re.sub(r"[\s\-().]", "", phone or "").strip()
    if not s:
        return ""
    if s[0] != "+":
        s = "+" + s
    return s


def _auth(request: Request) -> dict:
    user = get_current_user(request)
    if user is None:
        raise LoginRequired()
    return user


def _auth_admin(request: Request) -> dict:
    user = _auth(request)
    if user["role"] != "admin":
        raise Forbidden()
    return user


def _render(request: Request, template: str, status_code: int = 200, **context):
    user = get_current_user(request)
    context.setdefault("request", request)
    context.setdefault("current_user", user)
    context.setdefault("is_admin", bool(user and user["role"] == "admin"))
    return templates.TemplateResponse(request, template, context, status_code=status_code)


# ---------------------------------------------------------------------------
# Auth pages
# ---------------------------------------------------------------------------


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if get_current_user(request) is not None:
        return RedirectResponse(url="/practice", status_code=303)
    return _render(request, "login.html", countries=COUNTRIES, default_country=DEFAULT_COUNTRY)


@app.post("/login", response_class=HTMLResponse)
async def login(request: Request):
    if get_current_user(request) is not None:
        return RedirectResponse(url="/practice", status_code=303)

    form = await request.form()
    country = (form.get("country", "") or DEFAULT_COUNTRY).strip()
    local_phone = (form.get("phone", "") or "").strip()
    phone = _norm_phone(country + local_phone)
    password = form.get("password", "")
    host = request.client.host if request.client else "?"
    throttle_key = f"{phone}|{host}"

    error = None
    if throttle.blocked(throttle_key):
        error = "Troppi tentativi. Riprova tra qualche minuto."
    else:
        user = get_user_by_phone(phone) if phone else None
        if user is None or not user["active"] or not verify_password(password, user["password_hash"]):
            throttle.record_fail(throttle_key)
            error = "Telefono o password non corretti."
        else:
            device = getattr(request.state, "device_id", request.cookies.get(DEVICE_COOKIE, ""))
            if login_conflict(user["id"], device):
                error = (
                    "Questo profilo è già connesso su un altro dispositivo. "
                    "Esci da lì oppure chiedi all'amministratore di disconnetterlo."
                )
            else:
                throttle.reset(throttle_key)
                token = new_session_token()
                create_session(user["id"], hash_token(token), device)
                response = RedirectResponse(url="/practice", status_code=303)
                response.set_cookie(SESSION_COOKIE_NAME, token, **cookie_kwargs())
                return response

    return _render(
        request,
        "login.html",
        error=error,
        phone=local_phone,
        country=country or DEFAULT_COUNTRY,
        countries=COUNTRIES,
        default_country=DEFAULT_COUNTRY,
        status_code=401,
    )


@app.post("/logout", response_class=HTMLResponse)
async def logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        delete_session_by_token(hash_token(token))
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return response


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if get_current_user(request) is None:
        return RedirectResponse(url="/login", status_code=303)
    return RedirectResponse(url="/practice")


@app.get("/practice", response_class=HTMLResponse)
async def practice(request: Request):
    _auth(request)
    return _render(
        request,
        "practice.html",
        active_tab="practice",
        parts=part_meta(),
    )


@app.get("/profile", response_class=HTMLResponse)
async def profile(request: Request):
    user = _auth(request)
    session = active_session_for_user(user["id"])
    return _render(
        request,
        "profile.html",
        active_tab="profile",
        user=user,
        session=session,
        stats=stats(user["id"]),
    )


@app.get("/practice/{part}", response_class=HTMLResponse)
async def practice_part(request: Request, part: int):
    user = _auth(request)
    meta = _part_meta_or_404(part)
    passed = passed_exercise_ids(user["id"])
    chain = get_progression(part)

    state = []
    for idx, ex in enumerate(chain):
        unlocked = idx == 0 or chain[idx - 1].id in passed or ex.id in passed
        state.append({"ex": ex, "unlocked": unlocked, "passed": ex.id in passed})

    done = sum(1 for s in state if s["passed"])
    total = len(chain)

    ai_card = None
    if total and done == total:
        ai_ex = current_ai_exercise(part, passed, user["id"])
        if ai_ex:
            ai_card = {"ex": ai_ex, "passed": ai_ex.id in passed}

    return _render(
        request,
        "practice_part.html",
        active_tab="practice",
        part=meta,
        state=state,
        ai_card=ai_card,
        has_api_key=bool(GEMINI_API_KEY),
        done=done,
        total=total,
        parts=part_meta(),
    )


@app.get("/exercise/{exercise_id}", response_class=HTMLResponse)
async def exercise_page(request: Request, exercise_id: str):
    user = _auth(request)
    ex = _get_exercise(exercise_id, user["id"])
    if not ex:
        raise HTTPException(status_code=404, detail="esercizio non trovato")
    passed = passed_exercise_ids(user["id"])
    if is_generated(ex):
        if not _part_complete(ex.part, passed):
            return RedirectResponse(url=f"/practice/{ex.part}", status_code=303)
    elif not is_unlocked(ex.part, ex.id, passed):
        return RedirectResponse(url=f"/practice/{ex.part}", status_code=303)
    return _render(
        request,
        "exercise.html",
        active_tab="practice",
        ex=ex,
        parts=part_meta(),
    )


@app.get("/simulation", response_class=HTMLResponse)
async def simulation_picker(request: Request):
    _auth(request)
    return _render(
        request,
        "simulation_picker.html",
        active_tab="simulation",
        has_api_key=bool(GEMINI_API_KEY),
    )


@app.get("/simulation/{mode}", response_class=HTMLResponse)
async def simulation(request: Request, mode: str):
    user = _auth(request)
    if mode not in _SIM_MODES:
        raise HTTPException(status_code=404, detail="modalità non trovata")
    needs_ai = mode in ("mixed", "ai")
    if needs_ai and not GEMINI_API_KEY:
        return RedirectResponse(url="/simulation", status_code=303)

    clear_sim_exercises(user["id"])
    exercises: list[Exercise] = []
    fallbacks = 0

    for part in (1, 2, 3, 4):
        if mode == "real":
            exercises.append(_random_real(part))
        elif mode == "ai":
            ex = _generate_sim_ai(part, user["id"])
            if ex is None:
                ex = _random_real(part)
                fallbacks += 1
            exercises.append(ex)
        else:  # mixed
            use_ai = random.random() < 0.5
            if use_ai:
                ex = _generate_sim_ai(part, user["id"])
                if ex is None:
                    ex = _random_real(part)
                    fallbacks += 1
                exercises.append(ex)
            else:
                exercises.append(_random_real(part))

    if mode == "mixed":
        gen_flags = [is_generated(ex) for ex in exercises]
        if not any(gen_flags):
            for p in (2, 3, 4):
                ex = _generate_sim_ai(p, user["id"])
                if ex is not None:
                    exercises[p - 1] = ex
                    break
        elif all(gen_flags):
            exercises[0] = _random_real(1)

    return _render(
        request,
        "simulation.html",
        active_tab="simulation",
        exercises=exercises,
        mode=mode,
        mode_label=_SIM_MODES[mode],
        has_api_key=bool(GEMINI_API_KEY),
        fallbacks=fallbacks,
    )


@app.get("/vocab", response_class=HTMLResponse)
async def vocab_page(request: Request):
    user = _auth(request)
    return _render(
        request,
        "vocab.html",
        active_tab="vocab",
        keywords=list_keywords(user["id"]),
        stats=stats(user["id"]),
    )


@app.get("/progress", response_class=HTMLResponse)
async def progress_page(request: Request):
    user = _auth(request)
    return _render(
        request,
        "progress.html",
        active_tab="progress",
        attempts=list_attempts(user["id"]),
        stats=stats(user["id"]),
    )


@app.get("/api/health", response_class=JSONResponse)
async def api_health():
    return {"ok": True, "db": is_healthy()}


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    _auth_admin(request)
    return _render_admin(request, error="", notice="")


def _render_admin(request: Request, error: str = "", notice: str = "") -> HTMLResponse:
    users = list_users()
    sessions = {u["id"]: active_session_for_user(u["id"]) for u in users}
    return _render(
        request,
        "admin.html",
        active_tab="admin",
        users=users,
        sessions=sessions,
        error=error,
        notice=notice,
        has_api_key=bool(GEMINI_API_KEY),
        countries=COUNTRIES,
        default_country=DEFAULT_COUNTRY,
    )


@app.post("/admin/users", response_class=HTMLResponse)
async def admin_create_user(request: Request):
    _auth_admin(request)
    form = await request.form()
    country = (form.get("country", "") or DEFAULT_COUNTRY).strip()
    phone = _norm_phone(country + form.get("phone", ""))
    name = form.get("name", "").strip()
    password = form.get("password", "")
    if not phone or not password:
        return _render_admin(request, error="Compila telefono e password.")
    if len(password) < 6:
        return _render_admin(request, error="La password deve avere almeno 6 caratteri.")
    if get_user_by_phone(phone):
        return _render_admin(request, error=f"Esiste già un utente con il numero {phone}.")
    create_user(phone, hash_password(password), name)
    return _render_admin(request, notice=f"Utente {phone} creato.")


@app.post("/admin/users/{user_id}/password", response_class=HTMLResponse)
async def admin_reset_password(request: Request, user_id: int):
    _auth_admin(request)
    form = await request.form()
    password = form.get("password", "")
    if len(password) < 6:
        return _render_admin(request, error="La password deve avere almeno 6 caratteri.")
    set_user_password(user_id, hash_password(password))
    return _render_admin(request, notice="Password aggiornata.")


@app.post("/admin/users/{user_id}/revoke", response_class=HTMLResponse)
async def admin_revoke(request: Request, user_id: int):
    _auth_admin(request)
    revoke_sessions_for_user(user_id)
    return _render_admin(request, notice="Dispositivo disconnesso.")


@app.post("/admin/users/{user_id}/delete", response_class=HTMLResponse)
async def admin_delete_user(request: Request, user_id: int):
    admin = _auth_admin(request)
    if admin["id"] == user_id:
        return _render_admin(request, error="Non puoi eliminare il tuo stesso account.")
    delete_user(user_id)
    return _render_admin(request, notice="Utente eliminato.")


# ---------------------------------------------------------------------------
# Practice grading (htmx partials)
# ---------------------------------------------------------------------------


@app.post("/answer", response_class=HTMLResponse)
async def answer_part1(request: Request):
    user = _auth(request)
    form = await request.form()
    exercise_id = form.get("exercise_id", "")
    answer = form.get("answer", "")
    ex = _get_exercise(exercise_id, user["id"])
    if not ex or ex.part != 1:
        raise HTTPException(status_code=404, detail="esercizio non trovato")
    result = grade_part1(ex, answer)
    record_attempt(user["id"], ex.id, ex.part, 1 if result["correct"] else 0, 1)
    passed = result["correct"]
    passed_set = passed_exercise_ids(user["id"])
    next_ex = _next_exercise(ex, passed_set, user["id"]) if passed else None
    return _render(
        request,
        "partials/feedback_p1.html",
        ex=ex,
        result=result,
        passed=passed,
        next_ex=next_ex,
        completed_part=bool(passed and next_ex is None and not is_generated(ex)),
    )


@app.post("/verify/{part}", response_class=HTMLResponse)
async def verify_part(request: Request, part: int):
    user = _auth(request)
    form = await request.form()
    exercise_id = form.get("exercise_id", "")
    answers = {k: v for k, v in form.items() if k != "exercise_id" and v}
    ex = _get_exercise(exercise_id, user["id"])
    if not ex or ex.part != part:
        raise HTTPException(status_code=404, detail="esercizio non trovato")

    if part == 2:
        result = grade_part2(ex, answers)
        partial = "partials/feedback_p2.html"
    elif part == 3:
        result = grade_part3(ex, answers)
        partial = "partials/feedback_p3.html"
    elif part == 4:
        result = grade_part4(ex, answers)
        partial = "partials/feedback_p4.html"
    else:
        raise HTTPException(status_code=400, detail="parte non valida")

    record_attempt(user["id"], ex.id, ex.part, result["correct"], result["total"])
    passed = result["all_correct"]
    passed_set = passed_exercise_ids(user["id"])
    next_ex = _next_exercise(ex, passed_set, user["id"]) if passed else None
    return _render(
        request,
        partial,
        ex=ex,
        result=result,
        passed=passed,
        next_ex=next_ex,
        completed_part=bool(passed and next_ex is None and not is_generated(ex)),
    )


@app.post("/simulation/grade", response_class=HTMLResponse)
async def simulation_grade(request: Request):
    user = _auth(request)
    body = await request.json()
    session = body.get("session", [])
    graded: list[dict] = []
    total_correct = 0
    total_questions = 0
    for item in session:
        exercise_id = item.get("exercise_id", "")
        answers = item.get("answers", {}) or {}
        ex = _get_exercise(exercise_id, user["id"])
        if not ex:
            continue
        if ex.part == 1:
            res = grade_part1(ex, answers.get("answer", ""))
            correct = 1 if res["correct"] else 0
            total = 1
            graded.append({"ex": ex, "part": 1, "result": res, "correct": correct, "total": total})
        elif ex.part == 2:
            res = grade_part2(ex, answers)
            graded.append({"ex": ex, "part": 2, "result": res, "correct": res["correct"], "total": res["total"]})
            correct, total = res["correct"], res["total"]
        elif ex.part == 3:
            res = grade_part3(ex, answers)
            graded.append({"ex": ex, "part": 3, "result": res, "correct": res["correct"], "total": res["total"]})
            correct, total = res["correct"], res["total"]
        elif ex.part == 4:
            res = grade_part4(ex, answers)
            graded.append({"ex": ex, "part": 4, "result": res, "correct": res["correct"], "total": res["total"]})
            correct, total = res["correct"], res["total"]
        else:
            continue
        total_correct += correct
        total_questions += total

    record_attempt(user["id"], "simulazione", 0, total_correct, total_questions)
    percent = round((total_correct / total_questions) * 100) if total_questions else 0
    mode = body.get("mode", "real")
    if mode not in _SIM_MODES:
        mode = "real"
    return _render(
        request,
        "partials/sim_results.html",
        graded=graded,
        total_correct=total_correct,
        total_questions=total_questions,
        percent=percent,
        mode=mode,
        mode_label=_SIM_MODES[mode],
    )


# ---------------------------------------------------------------------------
# Progress / AI report
# ---------------------------------------------------------------------------


@app.post("/progress/reset", response_class=HTMLResponse)
async def progress_reset(request: Request):
    user = _auth(request)
    reset_progress(user["id"])
    return RedirectResponse(url="/practice", status_code=303)


@app.post("/ai/report", response_class=HTMLResponse)
async def ai_report(request: Request):
    user = _auth(request)
    per_part = part_stats(user["id"])
    keywords = list_keywords(user["id"])

    stats_lines = "\n".join(
        f"- Parte {p['part']}: {p['correct']} corrette su {p['total']} ({p['percent']}%), "
        f"{p['attempts']} tentativi"
        for p in per_part
    )
    vocab_lines = "\n".join(
        f"- {k['term']}: {k['definition']}" for k in keywords[:15]
    )

    mode = "ai"
    try:
        report = generate_report(stats_lines or "nessun esercizio completato", vocab_lines or "nessun termine salvato")
    except Exception as exc:  # noqa: BLE001
        logger.warning("ai report unavailable, using local summary: %s", exc)
        report = _local_report(per_part, keywords)
        mode = "local"

    return _render(
        request,
        "partials/ai_report.html",
        report=report,
        mode=mode,
        has_api_key=bool(GEMINI_API_KEY),
    )


def _local_report(per_part: list[dict], keywords: list[dict]) -> str:
    """Rule-based Italian summary used when the AI is unavailable."""
    if not per_part:
        text = (
            "Non hai ancora completato nessun esercizio, quindi non ci sono dati per un'analisi. "
            "Inizia un percorso di Allenamento: ogni esercizio superato sblocca il successivo!"
        )
    else:
        strengths = [p for p in per_part if p["percent"] >= 70]
        improve = [p for p in per_part if 0 < p["percent"] <= 60]
        in_progress = [p for p in per_part if 60 < p["percent"] < 70]

        text = "Ecco un riepilogo dei tuoi progressi:\n"
        if strengths:
            text += "\nCosa stai facendo bene: "
            text += " e ".join(
                f"Parte {p['part']} ({p['percent']}% di risposte corrette)" for p in strengths
            ) + ". Continua così!"
        if improve:
            text += "\n\nCosa migliorare: "
            text += " e ".join(
                f"Parte {p['part']} ({p['percent']}%)" for p in improve
            ) + ". Rileggi i testi con attenzione e usa la 'Spiegazione' dopo ogni risposta."
        if in_progress:
            text += "\n\nStai migliorando nelle parti: " + ", ".join(
                f"Parte {p['part']} ({p['percent']}%)" for p in in_progress
            ) + ". Un altro piccolo sforzo e saranno un punto di forza!"

    if not keywords:
        text += (
            "\n\nConsiglio: tocca '💡 Parole Chiave' negli esercizi e salva i termini difficili: "
            "il tuo vocabolario personale ti aiuterà molto nel ripasso."
        )
    else:
        text += (
            f"\n\nHai salvato {len(keywords)} termini nel tuo vocabolario. "
            "Rileggili prima della simulazione: il lessico è la chiave della comprensione."
        )
    return text


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


@app.post("/vocab/save", response_class=HTMLResponse)
async def vocab_save(request: Request):
    user = _auth(request)
    form = await request.form()
    term = form.get("term", "").strip()
    definition = form.get("definition", "").strip()
    exercise_id = form.get("exercise_id", "")
    part = int(form.get("part", 0) or 0)
    if not term:
        raise HTTPException(status_code=400, detail="termine mancante")
    save_keyword(user["id"], term, definition, exercise_id, part)
    return _render(
        request,
        "partials/vocab_saved.html",
        term=term,
        count=len(list_keywords(user["id"])),
    )


@app.post("/vocab/delete/{keyword_id}", response_class=HTMLResponse)
async def vocab_delete(request: Request, keyword_id: int):
    user = _auth(request)
    delete_keyword(user["id"], keyword_id)
    return _render(
        request,
        "vocab.html",
        active_tab="vocab",
        keywords=list_keywords(user["id"]),
        stats=stats(user["id"]),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _part_meta_or_404(part: int) -> dict:
    for meta in part_meta():
        if meta["part"] == part:
            return meta
    raise HTTPException(status_code=404, detail="parte non trovata")


def _get_exercise(exercise_id: str, user_id: int) -> Optional[Exercise]:
    """Resolve an exercise from the seed data, the user's AI progression or
    their transient simulation exercises."""
    ex = get_exercise(exercise_id)
    if ex:
        return ex
    for row in (get_ai_exercise(user_id, exercise_id), get_sim_exercise(user_id, exercise_id)):
        if row:
            try:
                return Exercise.model_validate(json.loads(row["payload"]))
            except Exception:  # noqa: BLE001
                continue
    return None


_SIM_MODES = {
    "real": "Solo esercizi reali",
    "mixed": "Reale + IA",
    "ai": "Tutto IA",
}


def _random_real(part: int) -> Exercise:
    chain = get_progression(part)
    return random.choice(chain) if chain else get_exercises(part)[0]


def _generate_sim_ai(part: int, user_id: int) -> Optional[Exercise]:
    """Generate and persist one AI exercise for a simulation. Returns None on failure."""
    try:
        ex = generate_authentic_exercise(part)
        save_sim_exercise(user_id, part, ex.id, ex.model_dump_json())
        return ex
    except Exception as exc:  # noqa: BLE001
        logger.warning("simulation AI generation failed (part %s): %s", part, exc)
        return None


def _part_complete(part: int, passed: set[str]) -> bool:
    """True when every seed exercise of the part has been passed."""
    chain = get_progression(part)
    return bool(chain) and all(ex.id in passed for ex in chain)


def current_ai_exercise(part: int, passed: set[str], user_id: int) -> Optional[Exercise]:
    """Return the current (un-passed) AI exercise for a user/part, generating and
    storing a fresh one when the previous has been passed or none exists."""
    if not GEMINI_API_KEY:
        return None

    latest = latest_ai_exercise(user_id, part)
    if latest:
        try:
            ex = Exercise.model_validate(json.loads(latest["payload"]))
        except Exception:  # noqa: BLE001
            ex = None
        if ex is not None and ex.id not in passed:
            return ex

    try:
        ex = generate_authentic_exercise(part)
        save_ai_exercise(user_id, part, ex.id, ex.model_dump_json())
        return ex
    except Exception as exc:  # noqa: BLE001
        logger.warning("failed to generate AI exercise for part %s: %s", part, exc)
        return None


def _next_exercise(ex: Exercise, passed: set[str], user_id: int) -> Optional[Exercise]:
    """Next exercise after a pass:
    - seed exercise -> following seed, or the first AI exercise after the last one
    - AI exercise -> the next freshly generated AI exercise
    """
    if is_generated(ex):
        if _part_complete(ex.part, passed):
            return current_ai_exercise(ex.part, passed, user_id)
        return None

    chain = get_progression(ex.part)
    try:
        idx = [i.id for i in chain].index(ex.id)
    except ValueError:
        return None
    if idx + 1 < len(chain):
        return chain[idx + 1]
    if _part_complete(ex.part, passed):
        return current_ai_exercise(ex.part, passed, user_id)
    return None


@app.exception_handler(404)
async def _not_found(request: Request, exc: HTTPException):
    if request.url.path.startswith("/api/"):
        return JSONResponse(status_code=404, content={"detail": exc.detail or "not found"})
    if get_current_user(request) is None:
        return RedirectResponse(url="/login", status_code=303)
    return _render(request, "practice.html", active_tab="practice", parts=part_meta(), status_code=404)
