"""
inference.py — Baseline inference script for sql-debug-env
===================================================================
Mandatory environment variables:
  API_BASE_URL        LLM API endpoint (default: HuggingFace router)
  MODEL_NAME          Model identifier  (default: Qwen2.5-72B-Instruct)
  HF_TOKEN            HuggingFace / LLM API key
  IMAGE_NAME          Docker image name (if using docker mode)
  SQL_DEBUG_URL       Direct server URL — evaluator sets this to HF Space URL
"""

import asyncio
import os
import textwrap
import urllib.request
import json
import subprocess
import time
from typing import List, Optional

from openai import OpenAI

# ── Configuration ─────────────────────────────────────────────────────────────
IMAGE_NAME    = os.getenv("IMAGE_NAME", "sql-debug-env:latest")
SQL_DEBUG_URL = os.getenv("SQL_DEBUG_URL", "").rstrip("/")
API_KEY       = os.getenv("HF_TOKEN") or os.getenv("API_KEY", "hf_placeholder")
API_BASE_URL  = os.getenv("API_BASE_URL", "https://router.huggingface.co/v1")
MODEL_NAME    = os.getenv("MODEL_NAME", "Qwen/Qwen2.5-72B-Instruct")
BENCHMARK     = "sql-debug-env"
TEMPERATURE   = 0.3
MAX_TOKENS    = 512
SUCCESS_THRESHOLD = 0.5
TASKS_TO_RUN  = ["classify_issue", "fix_query", "full_review"]

# ── Inline HTTP client ────────────────────────────────────────────────────────
_BASE_URL: str = ""
_SESSION_ID: Optional[str] = None
_CONTAINER_PROC = None


def _http_post(path: str, body: dict) -> dict:
    url = f"{_BASE_URL}{path}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data,
          headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_get(path: str) -> dict:
    req = urllib.request.Request(f"{_BASE_URL}{path}", method="GET")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _start_docker(image: str, port: int = 7861) -> None:
    global _CONTAINER_PROC
    _CONTAINER_PROC = subprocess.Popen(
        ["docker", "run", "--rm", "-p", f"{port}:7860", image],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            _http_get("/health")
            return
        except Exception:
            time.sleep(1.0)
    raise RuntimeError("Docker container did not start within 30s")


def _stop_docker() -> None:
    global _CONTAINER_PROC
    if _CONTAINER_PROC:
        _CONTAINER_PROC.terminate()
        try:
            _CONTAINER_PROC.wait(timeout=10)
        except Exception:
            _CONTAINER_PROC.kill()
        _CONTAINER_PROC = None


def env_reset(task_name: str) -> dict:
    global _SESSION_ID
    result = _http_post("/reset", {"task_name": task_name})
    _SESSION_ID = result.get("info", {}).get("session_id")
    return result


def env_step(content: str) -> dict:
    body = {"content": content}
    if _SESSION_ID:
        body["session_id"] = _SESSION_ID
    return _http_post("/step", body)


# ── Logging ───────────────────────────────────────────────────────────────────

def log_start(task: str, env: str, model: str) -> None:
    print(f"[START] task={task} env={env} model={model}", flush=True)


def log_step(step: int, action: str, reward: float, done: bool, error: Optional[str]) -> None:
    safe = action.replace("\n", " ").replace("\r", "").strip()
    if len(safe) > 200:
        safe = safe[:197] + "..."
    err = error if error else "null"
    print(f"[STEP] step={step} action={safe!r} reward={reward:.2f} done={str(done).lower()} error={err}", flush=True)


def log_end(success: bool, steps: int, score: float, rewards: List[float]) -> None:
    rewards_str = ",".join(f"{r:.2f}" for r in rewards)
    print(f"[END] success={str(success).lower()} steps={steps} score={score:.3f} rewards={rewards_str}", flush=True)


# ── Prompts ───────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = textwrap.dedent("""
You are an expert database engineer and SQL code reviewer.
Depending on the task:
- classify_issue: Output one label: select_star, sql_injection,
  cartesian_product, missing_index, or n_plus_one. Explain briefly.
- fix_query: Rewrite the SQL to fix the issue. Show the fix and explain.
- full_review: List ALL issues, provide complete fixed query, explain each fix.
Be concise and always include SQL in your response.
""").strip()


def build_prompt(obs: dict, feedback: Optional[str]) -> str:
    parts = [
        f"TASK: {obs['task_name']}",
        f"INSTRUCTIONS: {obs['task_description']}",
        "", "SCHEMA:", obs["schema_context"],
        "", "SQL QUERY:", obs["sql_query"],
    ]
    if feedback:
        parts += ["", f"PREVIOUS FEEDBACK: {feedback}"]
    parts += ["", "Your response:"]
    return "\n".join(parts)


def get_agent_response(client, obs, feedback):
    try:
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_prompt(obs, feedback)},
            ],
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
        )
        text = (completion.choices[0].message.content or "").strip()
        return text if text else "SELECT * FROM users"
    except Exception as exc:
        print(f"[DEBUG] LLM failed: {exc}", flush=True)

        # 🔥 HARD FALLBACK (IMPORTANT)
        return "SELECT id, name FROM users"


# ── Episode runner ────────────────────────────────────────────────────────────

def run_episode(client: OpenAI, task_name: str) -> None:
    rewards: List[float] = []
    steps_taken = 0
    score = 0.0
    success = False

    log_start(task=task_name, env=BENCHMARK, model=MODEL_NAME)

    try:
        reset_data = env_reset(task_name)
        obs = reset_data.get("observation", {})
        if not obs:
            raise RuntimeError("Invalid reset response")
        done = reset_data.get("done", False)
        feedback: Optional[str] = None
        max_steps = obs["max_steps"]

        for step_num in range(1, max_steps + 1):
            if done:
                break

            response = get_agent_response(client, obs, feedback)

            try:
                step_data = env_step(response)
            except Exception as exc:
                print(f"[DEBUG] env_step error: {exc}", flush=True)
                log_step(step_num, response, 0.0, True, str(exc))
                rewards.append(0.0)
                steps_taken = step_num
                break

            reward   = float(step_data.get("reward") or 0.0)
            done     = bool(step_data.get("done", False))
            feedback = step_data.get("info", {}).get("feedback")
            obs      = step_data["observation"]

            rewards.append(reward)
            steps_taken = step_num
            log_step(step_num, response, reward, done, None)

            if done:
                break

        score = max(rewards) if rewards else 0.0
        score = min(max(score, 0.0), 1.0)
        success = score >= SUCCESS_THRESHOLD

    except Exception as exc:
        print(f"[DEBUG] Episode error: {exc}", flush=True)

    finally:
        log_end(success=success, steps=steps_taken, score=score, rewards=rewards)


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    global _BASE_URL

    if SQL_DEBUG_URL:
        _BASE_URL = SQL_DEBUG_URL
    else:
        port = 7861
        _BASE_URL = f"http://localhost:{port}"
        _start_docker(IMAGE_NAME, port)

    client = OpenAI(base_url=API_BASE_URL, api_key=API_KEY)

    try:
        for task_name in TASKS_TO_RUN:
            run_episode(client, task_name)
    finally:
        try:
            _stop_docker()
        except Exception as e:
            print(f"[DEBUG] env.close() error: {e}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
