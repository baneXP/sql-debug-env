# SQL Debug Environment (`sql-debug-env`)

[![openenv](https://img.shields.io/badge/OpenEnv-compliant-green)](https://huggingface.co/openenv)

A **real-world OpenEnv environment** for training and evaluating AI agents on SQL query debugging, security review, and performance optimization. Simulates the daily workflow of a database engineer reviewing queries before production deployment.

---

## Motivation

SQL bugs cost engineering teams hours of debugging and can expose critical security vulnerabilities. This environment provides a structured benchmark for evaluating whether language models can reliably:
- Spot dangerous patterns (SQL injection, cartesian products)
- Propose correct fixes with proper parameterization
- Perform thorough multi-issue code reviews

---

## Observation Space

Each observation is a typed Pydantic model with the following fields:

| Field | Type | Description |
|---|---|---|
| `query_id` | `str` | Unique ID for the SQL scenario |
| `task_name` | `str` | `classify_issue` / `fix_query` / `full_review` |
| `task_description` | `str` | Natural-language instructions for the agent |
| `sql_query` | `str` | The SQL query under review |
| `schema_context` | `str` | Relevant table definitions |
| `step` | `int` | Current step (1-indexed) |
| `max_steps` | `int` | Max steps for this task type |
| `feedback` | `str?` | Grader feedback from previous step (null on step 1) |

---

## Action Space

Single `content` field — free-text response from the agent.

```json
{ "content": "The issue is sql_injection because the username is interpolated..." }
```

---

## Tasks

### Task 1 — `classify_issue` (Easy, 1 step)

The agent must identify the **primary issue type** in a SQL query.

**Valid labels:** `select_star`, `sql_injection`, `cartesian_product`, `missing_index`, `n_plus_one`

**Scoring:**
- `1.0` — Correct label present in response
- `0.5` — Correct concept described but wrong label word
- `0.0` — Wrong issue identified

**Baseline expected score:** ~0.65

---

### Task 2 — `fix_query` (Medium, 3 steps)

The agent must rewrite a broken/inefficient SQL query. Feedback is provided after each step, allowing iterative improvement.

**Scenarios include:**
- Cartesian product → add explicit JOIN condition
- SQL injection → use parameterized queries
- Function on indexed column → rewrite as date range
- Correlated subquery → extract to CTE

**Scoring:** Rubric-based — checks for required elements, absence of forbidden patterns, and valid SQL structure.

**Baseline expected score:** ~0.45

---

### Task 3 — `full_review` (Hard, 5 steps)

The agent performs a comprehensive review of a complex query with **multiple simultaneous issues**. Must: identify all issues, provide a corrected query, and explain each fix.

**Scoring:** Multi-criterion rubric across 5 weighted dimensions (issue identification, fix quality, explanation depth).

**Baseline expected score:** ~0.25

---

## Reward Function

- Rewards are **dense** (non-binary) — partial credit for partial correctness.
- Multi-step tasks: agent receives feedback after each step and can improve.
- Final episode score = `max(rewards_across_steps)` for medium/hard tasks.
- All rewards are in `[0.0, 1.0]`.

---

## Setup & Running

### Local (Docker)

```bash
# Build
docker build -t sql-debug-env:latest .

# Run server
docker run -p 7860:7860 sql-debug-env:latest

# Test
curl -X POST http://localhost:7860/reset \
  -H "Content-Type: application/json" \
  -d '{"task_name": "classify_issue"}'
```

### Running the Inference Script

```bash
pip install openai httpx pydantic

export HF_TOKEN=hf_your_token
export API_BASE_URL=https://router.huggingface.co/v1
export MODEL_NAME=Qwen/Qwen2.5-72B-Instruct
export SQL_DEBUG_URL=http://localhost:7860   # if server already running

python inference.py
```

### API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/reset` | `POST` | Start episode. Body: `{task_name?, seed?}` |
| `/step` | `POST` | Submit action. Body: `{content, session_id?}` |
| `/state` | `GET` | Current state. Query: `session_id?` |
| `/tasks` | `GET` | List all tasks |
| `/health` | `GET` | Health check |

---

## Baseline Scores

| Task | Difficulty | Avg Score (Qwen2.5-72B) |
|---|---|---|
| `classify_issue` | Easy | ~0.65 |
| `fix_query` | Medium | ~0.45 |
| `full_review` | Hard | ~0.25 |

---

## openenv.yaml

Metadata for `openenv validate` compliance — see `openenv.yaml` in the repo root.

---

## License

MIT
