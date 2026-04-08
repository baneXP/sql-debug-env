"""
inference.py — Baseline inference script for sql-debug-env
===================================================================
Mandatory environment variables:
  API_BASE_URL   LLM API endpoint (default: HuggingFace router)
  MODEL_NAME     Model identifier  (default: Qwen2.5-72B-Instruct)
  HF_TOKEN       HuggingFace / LLM API key
  IMAGE_NAME     Docker image name (if using from_docker_image)
  SQL_DEBUG_URL  Direct server URL  (optional; skips Docker if set)

Output format (required by OpenEnv evaluator):
  [START] task=<task> env=sql-debug-env model=<model>
  [STEP]  step=<n> action=<action_str> reward=<0.00> done=<true|false> error=<msg|null>
  [END]   success=<true|false> steps=<n> score=<score> rewards=<r1,r2,...>
"""

import asyncio
import os
import textwrap
from typing import List, Optional

from openai import OpenAI

from env import SqlDebugAction, SqlDebugEnv

# ── Configuration ─────────────────────────────────────────────────────────────
IMAGE_NAME   = os.getenv("IMAGE_NAME", "sql-debug-env:latest")
SQL_DEBUG_URL = os.getenv("SQL_DEBUG_URL", "")          # set this for HF Space runs
API_KEY      = os.getenv("HF_TOKEN") or os.getenv("API_KEY", "")
API_BASE_URL = os.getenv("API_BASE_URL", "https://router.huggingface.co/v1")
MODEL_NAME   = os.getenv("MODEL_NAME", "Qwen/Qwen2.5-72B-Instruct")
BENCHMARK    = "sql-debug-env"

MAX_STEPS_OVERRIDE = None   # None = use env's max_steps per task
TEMPERATURE  = 0.3          # low temp for deterministic SQL tasks
MAX_TOKENS   = 512
SUCCESS_THRESHOLD = 0.5     # score >= 0.5 counts as success

# Tasks to evaluate (runs sequentially, one episode each)
TASKS_TO_RUN = ["classify_issue", "fix_query", "full_review"]

# ── Logging helpers ───────────────────────────────────────────────────────────

def log_start(task: str, env: str, model: str) -> None:
    print(f"[START] task={task} env={env} model={model}", flush=True)


def log_step(step: int, action: str, reward: float, done: bool, error: Optional[str]) -> None:
    # Sanitize action: collapse newlines to spaces for single-line output
    safe_action = action.replace("\n", " ").replace("\r", "").strip()
    # Truncate long actions for log readability
    if len(safe_action) > 200:
        safe_action = safe_action[:197] + "..."
    error_val = error if error else "null"
    print(
        f"[STEP] step={step} action={safe_action!r} "
        f"reward={reward:.2f} done={str(done).lower()} error={error_val}",
        flush=True,
    )


def log_end(success: bool, steps: int, score: float, rewards: List[float]) -> None:
    rewards_str = ",".join(f"{r:.2f}" for r in rewards)
    print(
        f"[END] success={str(success).lower()} steps={steps} "
        f"score={score:.3f} rewards={rewards_str}",
        flush=True,
    )

# ── Prompt builders ───────────────────────────────────────────────────────────

SYSTEM_PROMPT = textwrap.dedent("""
You are an expert database engineer and SQL code reviewer.
You will be given SQL queries to analyze. Depending on the task:

- classify_issue: Output one of these labels clearly in your response:
  select_star, sql_injection, cartesian_product, missing_index, n_plus_one
  Then briefly explain your reasoning.

- fix_query: Provide a corrected SQL query that fixes the described issue.
  Show the fixed query clearly, then explain what you changed.

- full_review: List ALL issues found, provide a complete fixed query,
  and explain each fix and its impact.

Be concise, precise, and always include the relevant SQL in your response.
""").strip()


def build_prompt(obs_data: dict, feedback: Optional[str]) -> str:
    parts = [
        f"TASK: {obs_data['task_name']}",
        f"INSTRUCTIONS: {obs_data['task_description']}",
        "",
        "SCHEMA:",
        obs_data["schema_context"],
        "",
        "SQL QUERY:",
        obs_data["sql_query"],
    ]
    if feedback:
        parts += ["", f"PREVIOUS FEEDBACK: {feedback}"]
    parts += ["", "Your response:"]
    return "\n".join(parts)


def get_agent_response(
    client: OpenAI,
    obs_data: dict,
    feedback: Optional[str],
) -> str:
    user_prompt = build_prompt(obs_data, feedback)
    try:
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            stream=False,
        )
        text = (completion.choices[0].message.content or "").strip()
        return text if text else "select_star"
    except Exception as exc:
        print(f"[DEBUG] LLM request failed: {exc}", flush=True)
        return "select_star"  # safe fallback for easy task


# ── Episode runner ────────────────────────────────────────────────────────────

async def run_episode(
    env: SqlDebugEnv,
    client: OpenAI,
    task_name: str,
) -> None:
    """Run a single episode for the given task and emit [START]/[STEP]/[END] logs."""
    rewards: List[float] = []
    steps_taken = 0
    score = 0.0
    success = False

    log_start(task=task_name, env=BENCHMARK, model=MODEL_NAME)

    try:
        reset_result = await env.reset(task_name=task_name)
        obs = reset_result.observation
        feedback: Optional[str] = None

        max_steps = obs.max_steps
        done = reset_result.done

        for step_num in range(1, max_steps + 1):
            if done:
                break

            # Build observation dict for prompt
            obs_data = {
                "task_name": obs.task_name,
                "task_description": obs.task_description,
                "sql_query": obs.sql_query,
                "schema_context": obs.schema_context,
            }

            # Get agent action
            response = get_agent_response(client, obs_data, feedback)

            # Submit to environment
            step_result = await env.step(SqlDebugAction(content=response))

            reward = step_result.reward or 0.0
            done   = step_result.done
            error  = None

            rewards.append(reward)
            steps_taken = step_num
            feedback = step_result.info.get("feedback")

            log_step(
                step=step_num,
                action=response,
                reward=reward,
                done=done,
                error=error,
            )

            obs = step_result.observation

            if done:
                break

        # Score = best reward achieved across all steps (normalized)
        score = max(rewards) if rewards else 0.0
        score = min(max(score, 0.0), 1.0)
        success = score >= SUCCESS_THRESHOLD

    except Exception as exc:
        print(f"[DEBUG] Episode error: {exc}", flush=True)

    finally:
        log_end(success=success, steps=steps_taken, score=score, rewards=rewards)


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    client = OpenAI(base_url=API_BASE_URL, api_key=API_KEY)

    for task_name in TASKS_TO_RUN:
        # Connect to environment
        if SQL_DEBUG_URL:
            env = await SqlDebugEnv.from_url(SQL_DEBUG_URL)
        else:
            env = await SqlDebugEnv.from_docker_image(IMAGE_NAME)

        try:
            await run_episode(env, client, task_name)
        finally:
            try:
                await env.close()
            except Exception as e:
                print(f"[DEBUG] env.close() error: {e}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
