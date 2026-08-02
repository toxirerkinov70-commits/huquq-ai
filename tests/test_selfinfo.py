"""Telling a question about one's own plan apart from a question about the law.

"Tarif" means both a subscription and, in the Labour Code, a wage grading system.
Asking about "mening tarifim" once returned article 250 of the Labour Code: correctly
cited, and the wrong question answered.
"""

import pytest

from backend.app.services import plans
from backend.app.services.selfinfo import account_answer, is_account_question


@pytest.mark.parametrize(
    "question",
    [
        "Mening tarifim haqida gapirib ber",
        "tarifim qanday",
        "Mening hisobim haqida ayting",
        "Bugun qancha savol qoldi?",
        "Nechta savol qoldi",
        "obunam qachon tugaydi",
        "kunlik cheklovim qancha",
        "Мой тариф какой?",
        "сколько вопросов осталось",
        "моя подписка",
    ],
)
def test_questions_about_the_account_are_recognised(question):
    assert is_account_question(question) is True


@pytest.mark.parametrize(
    "question",
    [
        "Mehnat kodeksida tarif tizimi nima?",
        "Tarif setkasi qanday tuziladi?",
        "250-moddada nima deyilgan?",
        "Ish haqi tarif stavkasi qanday belgilanadi",
        "Что такое тарифная сетка?",
        "Тарифные разряды в трудовом кодексе",
    ],
)
def test_legal_questions_about_tariffs_still_go_to_the_corpus(question):
    assert is_account_question(question) is False


def test_a_long_message_is_not_treated_as_an_account_question():
    long_one = "Mening tarifim " + "x" * 300
    assert is_account_question(long_one) is False


def test_the_answer_states_the_plan_and_what_is_left():
    plan = plans.get("free")
    quota = {"used_today": 2, "daily_limit": 5, "remaining": 3}
    answer = account_answer({}, plan, quota, "tarifim qanday")

    assert plan.name in answer
    assert "5" in answer and "2" in answer and "3" in answer
    assert "Sozlamalar" in answer


def test_an_unlimited_plan_says_so_rather_than_showing_a_count():
    owner = plans.get("owner")
    quota = {"used_today": 40, "daily_limit": 0, "remaining": -1}
    answer = account_answer({}, owner, quota, "mening tarifim")

    assert "cheksiz" in answer.lower()
    assert "-1" not in answer


def test_the_expiry_is_shown_when_there_is_one():
    plan = plans.get("standart")
    quota = {"used_today": 0, "daily_limit": 50, "remaining": 50}
    answer = account_answer({"plan_expires_at": "2026-10-30T00:00:00"}, plan, quota, "tarifim")
    assert "2026-10-30" in answer


def test_the_answer_follows_the_language_of_the_question():
    plan = plans.get("free")
    quota = {"used_today": 1, "daily_limit": 5, "remaining": 4}
    assert "Ваш тариф" in account_answer({}, plan, quota, "какой у меня тариф?")
    assert "Sizning tarifingiz" in account_answer({}, plan, quota, "mening tarifim")


# --- through the API --------------------------------------------------------


def test_the_chat_answers_from_the_account_without_a_model_call(client, ready_auth):
    response = client.post(
        "/api/chat",
        json={"question": "Mening tarifim haqida gapirib ber", "stream": False},
        headers=ready_auth,
    )
    assert response.status_code == 200
    data = response.json()
    assert "Bepul" in data["answer"]
    # nothing was retrieved, so nothing may be presented as a legal source
    assert data["sources"] == []
    # and it did not cost a question from the daily allowance
    assert client.get("/api/quota", headers=ready_auth).json()["used_today"] == 0


def test_it_survives_the_daily_limit_being_spent(client, ready_auth):
    from backend.app.db import sqlite
    from backend.app.services import auth as auth_service

    user_id = auth_service.verify_token(ready_auth["Authorization"][7:])
    for _ in range(5):
        sqlite.record_usage(user_id, "/api/chat", "question")

    # a legal question is refused, but asking what is left must still work
    assert client.post(
        "/api/chat", json={"question": "Meros qanday taqsimlanadi?"}, headers=ready_auth
    ).status_code == 429
    answer = client.post(
        "/api/chat", json={"question": "qancha savol qoldi?", "stream": False}, headers=ready_auth
    )
    assert answer.status_code == 200
    assert "0" in answer.json()["answer"]
