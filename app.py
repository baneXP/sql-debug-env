"""
app.py — FastAPI server for sql-debug-env.

Exposes the three OpenEnv-required endpoints:
  POST /reset  — start a new episode, return initial observation
  POST /step   — submit an action, return StepResult
  GET  /state  — return current environment state
  GET  /health — health check
  GET  /tasks  — list available tasks

Run locally:
  uvicorn app:app --host 0.0.0.0 --port 7860
"""

import os
import random
import uuid
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from models import ResetResult, SqlAction, SqlObservation, StateResponse, StepResult
from tasks import grade_action, sample_task, TASK_REGISTRY

app = FastAPI(
    title="SQL Debug Environment",
    description=(
        "OpenEnv-compliant environment for training AI agents to debug SQL queries. "
        "Three tasks of increasing difficulty: classify_issue (easy), fix_query (medium), "
        "full_review (hard)."
    ),
    version="1.0.0",
)

# ── In-memory session store ───────────────────────────────────────────────────
# Maps session_id -> session state dict.
# For HF Space single-instance evaluation a single global session suffices;
# we still key by session_id for correctness.

_sessions: Dict[str, Dict[str, Any]] = {}
_DEFAULT_TASK = os.getenv("SQL_DEBUG_TASK", "classify_issue")


def _new_session(task_name: str, seed: Optional[int] = None) -> Dict[str, Any]:
    rng = random.Random(seed)
    task_data = sample_task(task_name, rng)
    session_id = str(uuid.uuid4())
    return {
        "session_id": session_id,
        "task_name": task_name,
        "task_data": task_data,
        "step": 0,
        "max_steps": task_data["max_steps"],
        "done": False,
        "best_reward": 0.0,
        "last_reward": 0.0,
        "last_feedback": None,
    }


def _build_observation(session: Dict[str, Any]) -> SqlObservation:
    td = session["task_data"]
    return SqlObservation(
        query_id=td["id"],
        task_name=session["task_name"],
        task_description=td["task_description"],
        sql_query=td["sql_query"],
        schema_context=td["schema_context"],
        step=session["step"],
        max_steps=session["max_steps"],
        feedback=session.get("last_feedback"),
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/reset")
async def reset(request: Request) -> JSONResponse:
    """Start a new episode. Accepts optional JSON: {task_name, seed, session_id}."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    task_name = body.get("task_name", _DEFAULT_TASK)
    seed = body.get("seed", None)

    if task_name not in TASK_REGISTRY:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown task '{task_name}'. Valid: {list(TASK_REGISTRY.keys())}",
        )

    session = _new_session(task_name, seed)
    _sessions[session["session_id"]] = session

    obs = _build_observation(session)
    result = ResetResult(
        observation=obs,
        done=False,
        reward=0.0,
        info={
            "session_id": session["session_id"],
            "task": task_name,
            "difficulty": TASK_REGISTRY[task_name]["difficulty"],
        },
    )
    return JSONResponse(content=result.model_dump(), status_code=200)


@app.post("/step")
async def step(request: Request) -> JSONResponse:
    """Submit an action and advance the episode."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    # Support session_id or fall back to most-recent session
    session_id = body.get("session_id")
    if session_id and session_id in _sessions:
        session = _sessions[session_id]
    elif _sessions:
        # Most recently created session (last key)
        session = list(_sessions.values())[-1]
    else:
        raise HTTPException(status_code=400, detail="No active session. Call /reset first.")

    if session["done"]:
        obs = _build_observation(session)
        return JSONResponse(
            content=StepResult(
                observation=obs,
                reward=session["last_reward"],
                done=True,
                info={"message": "Episode already done. Call /reset to start a new one."},
            ).model_dump(),
            status_code=200,
        )

    # Parse action
    action_content = body.get("content") or body.get("action", {}).get("content", "")
    if not action_content:
        raise HTTPException(status_code=400, detail="Missing 'content' field in request body.")

    action = SqlAction(content=action_content)

    # Advance step counter
    session["step"] += 1

    # Grade
    reward, feedback = grade_action(action.content, session["task_data"])

    # Update session
    session["last_reward"] = reward
    session["last_feedback"] = feedback
    if reward > session["best_reward"]:
        session["best_reward"] = reward

    # Termination: done when max_steps reached or perfect score
    done = (session["step"] >= session["max_steps"]) or (reward >= 1.0)
    session["done"] = done

    obs = _build_observation(session)
    result = StepResult(
        observation=obs,
        reward=reward,
        done=done,
        info={
            "session_id": session["session_id"],
            "feedback": feedback,
            "best_reward": session["best_reward"],
            "step": session["step"],
        },
    )
    return JSONResponse(content=result.model_dump(), status_code=200)


@app.get("/state")
async def state(session_id: Optional[str] = None) -> JSONResponse:
    """Return current episode state."""
    if session_id and session_id in _sessions:
        session = _sessions[session_id]
    elif _sessions:
        session = list(_sessions.values())[-1]
    else:
        raise HTTPException(status_code=404, detail="No active session.")

    resp = StateResponse(
        task_name=session["task_name"],
        query_id=session["task_data"]["id"],
        step=session["step"],
        max_steps=session["max_steps"],
        done=session["done"],
        best_reward=session["best_reward"],
        session_id=session["session_id"],
    )
    return JSONResponse(content=resp.model_dump(), status_code=200)


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "env": "sql-debug-env", "version": "1.0.0"}, status_code=200)


@app.get("/tasks")
async def list_tasks() -> JSONResponse:
    tasks_info = {
        name: {
            "difficulty": meta["difficulty"],
            "max_steps": meta["max_steps"],
            "num_scenarios": len(meta["data"]),
        }
        for name, meta in TASK_REGISTRY.items()
    }
    return JSONResponse({"tasks": tasks_info}, status_code=200)


# ── Exception handler ─────────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": str(exc), "type": type(exc).__name__},
    )
