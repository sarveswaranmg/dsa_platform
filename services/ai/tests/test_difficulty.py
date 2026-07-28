import uuid

from httpx import AsyncClient

from app.difficulty.rules import DEFAULT_DIFFICULTY


async def test_first_signal_starts_from_default_difficulty(client: AsyncClient) -> None:
    session_id = uuid.uuid4()
    response = await client.post(
        "/internal/difficulty/signal",
        json={
            "session_id": str(session_id),
            "question_version_id": str(uuid.uuid4()),
            "time_elapsed_pct": 0.1,
            "verdict": "AC",
            "complexity_hint": "optimal",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["difficulty"] == DEFAULT_DIFFICULTY + 1.0
    assert body["difficulty_band"] == "hard"


async def test_state_persists_across_signals_for_the_same_session(
    client: AsyncClient,
) -> None:
    session_id = uuid.uuid4()
    body = {
        "session_id": str(session_id),
        "question_version_id": str(uuid.uuid4()),
        "time_elapsed_pct": 0.1,
        "verdict": "AC",
        "complexity_hint": "suboptimal",
    }
    first = (await client.post("/internal/difficulty/signal", json=body)).json()
    assert first["difficulty"] == DEFAULT_DIFFICULTY + 0.5

    second = (await client.post("/internal/difficulty/signal", json=body)).json()
    assert second["difficulty"] == DEFAULT_DIFFICULTY + 1.0


async def test_different_sessions_do_not_interfere(client: AsyncClient) -> None:
    body_a = {
        "session_id": str(uuid.uuid4()),
        "question_version_id": str(uuid.uuid4()),
        "time_elapsed_pct": 0.1,
        "verdict": "AC",
        "complexity_hint": "optimal",
    }
    body_b = {
        "session_id": str(uuid.uuid4()),
        "question_version_id": str(uuid.uuid4()),
        "time_elapsed_pct": 0.9,
        "verdict": "WA",
        "complexity_hint": None,
    }
    result_a = (await client.post("/internal/difficulty/signal", json=body_a)).json()
    result_b = (await client.post("/internal/difficulty/signal", json=body_b)).json()
    assert result_a["difficulty"] == DEFAULT_DIFFICULTY + 1.0
    assert result_b["difficulty"] == DEFAULT_DIFFICULTY - 1.0


async def test_no_auth_required(client: AsyncClient) -> None:
    # Internal endpoint — trusted-network-only, blocked at the gateway edge;
    # unlike examiner-plane routes this must work with no Authorization header.
    response = await client.post(
        "/internal/difficulty/signal",
        json={
            "session_id": str(uuid.uuid4()),
            "question_version_id": str(uuid.uuid4()),
            "time_elapsed_pct": 0.1,
            "verdict": "AC",
        },
    )
    assert response.status_code == 200
