"""
server/app.py — SQL Debug Environment server.
OpenEnv-compliant FastAPI app with all required endpoints.
"""

import os
import random
import uuid
from typing import Any, Dict, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

# Allow running from project root or server/ directory
import sys
from pathlib import Path
_here = Path(__file__).parent
_root = _here.parent
for p in [str(_here), str(_root)]:
    if p not in sys.path:
        sys.path.insert(0, p)

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


# ── Core OpenEnv endpoints ─────────────────────────────────────────────────────

@app.post("/reset")
async def reset(request: Request) -> JSONResponse:
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
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    session_id = body.get("session_id")
    if session_id and session_id in _sessions:
        session = _sessions[session_id]
    elif _sessions:
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

    action_content = body.get("content") or body.get("action", {}).get("content", "")
    if not action_content:
        raise HTTPException(status_code=400, detail="Missing 'content' field.")

    action = SqlAction(content=action_content)
    session["step"] += 1

    reward, feedback = grade_action(action.content, session["task_data"])

    session["last_reward"] = reward
    session["last_feedback"] = feedback
    if reward > session["best_reward"]:
        session["best_reward"] = reward

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


# ── Required OpenEnv spec endpoints ───────────────────────────────────────────

@app.get("/health")
async def health() -> JSONResponse:
    # Must return {"status": "healthy"} for openenv validate
    return JSONResponse(
        {"status": "healthy", "env": "sql-debug-env", "version": "1.0.0"},
        status_code=200,
    )


@app.get("/metadata")
async def metadata() -> JSONResponse:
    return JSONResponse({
        "name": "sql-debug-env",
        "description": (
            "Real-world SQL query debugging environment. An AI agent reviews SQL queries "
            "for security vulnerabilities, performance issues, and correctness errors. "
            "Three tasks: classify_issue (easy), fix_query (medium), full_review (hard)."
        ),
        "version": "1.0.0",
        "tasks": list(TASK_REGISTRY.keys()),
        "author": "Satyam Sharma",
    }, status_code=200)


@app.get("/schema")
async def schema() -> JSONResponse:
    return JSONResponse({
        "action": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Agent's text response to the SQL debugging task",
                }
            },
            "required": ["content"],
        },
        "observation": {
            "type": "object",
            "properties": {
                "query_id":         {"type": "string"},
                "task_name":        {"type": "string"},
                "task_description": {"type": "string"},
                "sql_query":        {"type": "string"},
                "schema_context":   {"type": "string"},
                "step":             {"type": "integer"},
                "max_steps":        {"type": "integer"},
                "feedback":         {"type": ["string", "null"]},
            },
            "required": ["query_id", "task_name", "sql_query", "schema_context", "step", "max_steps"],
        },
        "state": {
            "type": "object",
            "properties": {
                "task_name":    {"type": "string"},
                "query_id":     {"type": "string"},
                "step":         {"type": "integer"},
                "max_steps":    {"type": "integer"},
                "done":         {"type": "boolean"},
                "best_reward":  {"type": "number"},
                "session_id":   {"type": "string"},
            },
        },
    }, status_code=200)


@app.post("/mcp")
async def mcp(request: Request) -> JSONResponse:
    """JSON-RPC 2.0 endpoint for MCP compatibility."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    method = body.get("method", "")
    req_id = body.get("id", 1)

    if method == "tools/list":
        result = {
            "tools": [
                {
                    "name": "reset",
                    "description": "Start a new SQL debugging episode",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "task_name": {"type": "string"},
                            "seed": {"type": "integer"},
                        },
                    },
                },
                {
                    "name": "step",
                    "description": "Submit an action to the SQL debugging environment",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string"},
                            "session_id": {"type": "string"},
                        },
                        "required": ["content"],
                    },
                },
            ]
        }
    else:
        result = {"message": "sql-debug-env MCP endpoint", "method": method}

    return JSONResponse(
        {"jsonrpc": "2.0", "id": req_id, "result": result},
        status_code=200,
    )


@app.get("/tasks")
async def list_tasks() -> JSONResponse:
    return JSONResponse({
        "tasks": {
            name: {
                "difficulty": meta["difficulty"],
                "max_steps": meta["max_steps"],
                "num_scenarios": len(meta["data"]),
            }
            for name, meta in TASK_REGISTRY.items()
        }
    }, status_code=200)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": str(exc), "type": type(exc).__name__},
    )


# ── Entry point (required by openenv validate) ────────────────────────────────

def main() -> None:
    """Main entry point for openenv serve / uv run server."""
    port = int(os.getenv("PORT", "7860"))
    uvicorn.run("server.app:app", host="0.0.0.0", port=port, workers=1)


if __name__ == "__main__":
    main()
