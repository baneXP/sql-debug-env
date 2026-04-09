"""
tasks.py — Task definitions and graders for sql-debug-env.

Three task types:
  1. classify_issue  (easy)   — label the primary SQL issue
  2. fix_query       (medium) — rewrite the query to fix the issue
  3. full_review     (hard)   — find all issues, fix, and explain

Each task dict contains:
  - id, schema_context, sql_query
  - Task-specific grading metadata
"""

import random
from typing import Dict, List, Optional, Tuple


# ══════════════════════════════════════════════════════════════════════════════
#  EASY — classify_issue
# ══════════════════════════════════════════════════════════════════════════════

CLASSIFY_TASKS: List[Dict] = [
    {
        "id": "cls_001",
        "schema_context": (
            "Table: users (id INT PK, username VARCHAR(50), email VARCHAR(100), "
            "created_at TIMESTAMP)\n"
            "Table: orders (id INT PK, user_id INT FK, total DECIMAL(10,2), "
            "status VARCHAR(20), created_at TIMESTAMP)"
        ),
        "sql_query": (
            "SELECT *\n"
            "FROM users u, orders o\n"
            "WHERE u.id = 1"
        ),
        "label": "cartesian_product",
        "alt_keywords": ["cartesian", "cross join", "missing join condition", "cross product", "implicit join"],
    },
    {
        "id": "cls_002",
        "schema_context": (
            "Table: products (id INT PK, name VARCHAR(100), category VARCHAR(50), "
            "price DECIMAL(10,2), stock INT, description TEXT, weight DECIMAL)"
        ),
        "sql_query": (
            "SELECT *\n"
            "FROM products\n"
            "WHERE category = 'electronics'\n"
            "ORDER BY price ASC"
        ),
        "label": "select_star",
        "alt_keywords": ["select *", "wildcard", "all columns", "avoid star", "explicit columns"],
    },
    {
        "id": "cls_003",
        "schema_context": (
            "Table: users (id INT PK, username VARCHAR(50), email VARCHAR(100), "
            "password_hash VARCHAR(255), role VARCHAR(20))"
        ),
        "sql_query": (
            "query = \"SELECT id, email, role FROM users WHERE username = '\" "
            "+ username_input + \"'\""
        ),
        "label": "sql_injection",
        "alt_keywords": ["injection", "sqli", "concatenat", "unsanitized", "parameteriz", "prepared"],
    },
    {
        "id": "cls_004",
        "schema_context": (
            "Table: transactions (id INT PK, account_id INT INDEX, amount DECIMAL, "
            "created_at TIMESTAMP INDEX, merchant VARCHAR)\n"
            "Table: accounts (id INT PK, customer_id INT, balance DECIMAL)"
        ),
        "sql_query": (
            "SELECT t.id, t.amount, a.customer_id\n"
            "FROM transactions t\n"
            "JOIN accounts a ON t.account_id = a.id\n"
            "WHERE YEAR(t.created_at) = 2024\n"
            "  AND MONTH(t.created_at) = 3"
        ),
        "label": "missing_index",
        "alt_keywords": [
            "index", "full scan", "function wrap", "sargable", "non-sargable",
            "year(", "date_format", "can't use index", "wrapping", "function on column"
        ],
    },
    {
        "id": "cls_005",
        "schema_context": (
            "Table: orders (id INT PK, customer_id INT INDEX, status VARCHAR(20))\n"
            "Table: order_items (id INT PK, order_id INT FK INDEX, product_id INT, quantity INT)"
        ),
        "sql_query": (
            "-- Application pseudocode:\n"
            "-- pending_orders = db.query('SELECT id FROM orders WHERE status = ?', ['pending'])\n"
            "-- for order in pending_orders:\n"
            "--     items = db.query('SELECT * FROM order_items WHERE order_id = ?', [order.id])\n"
            "-- ^^^ Actual queries executed per row above ^^^"
        ),
        "label": "n_plus_one",
        "alt_keywords": ["n+1", "n plus one", "loop query", "multiple queries", "1+n", "per-row query"],
    },
    {
        "id": "cls_006",
        "schema_context": (
            "Table: employees (id INT PK, dept_id INT, name VARCHAR, salary DECIMAL)\n"
            "Table: departments (id INT PK, name VARCHAR, location VARCHAR)\n"
            "Table: projects (id INT PK, dept_id INT, budget DECIMAL)"
        ),
        "sql_query": (
            "SELECT e.name, d.name, p.budget\n"
            "FROM employees e, departments d, projects p"
        ),
        "label": "cartesian_product",
        "alt_keywords": ["cartesian", "cross join", "no join", "missing on", "3-way cross"],
    },
]


# ══════════════════════════════════════════════════════════════════════════════
#  MEDIUM — fix_query
# ══════════════════════════════════════════════════════════════════════════════

FIX_TASKS: List[Dict] = [
    {
        "id": "fix_001",
        "schema_context": (
            "Table: employees (id INT PK, name VARCHAR(100), dept_id INT, salary DECIMAL)\n"
            "Table: departments (id INT PK, name VARCHAR(100), budget DECIMAL, manager_id INT)"
        ),
        "sql_query": (
            "SELECT e.name, e.salary, d.name AS dept_name\n"
            "FROM employees e, departments d\n"
            "WHERE e.salary > 50000"
        ),
        "issue_description": "Missing JOIN condition between employees and departments causes a cartesian product.",
        "hint": "Add an explicit JOIN condition: e.dept_id = d.id",
        "required_patterns": ["join", "e.dept_id", "d.id", "on"],
        "forbidden_patterns": [", departments", ", employees"],
        "bonus_patterns": ["inner join", "left join"],
    },
    {
        "id": "fix_002",
        "schema_context": (
            "Table: users (id INT PK, email VARCHAR UNIQUE, username VARCHAR(50), "
            "role VARCHAR(20), password_hash VARCHAR(255))"
        ),
        "sql_query": (
            "def get_user(username_input):\n"
            "    query = f\"SELECT id, email, role FROM users WHERE username = '{username_input}'\"\n"
            "    return db.execute(query)"
        ),
        "issue_description": "SQL injection vulnerability: user input is interpolated directly into the query string.",
        "hint": "Use parameterized queries (? placeholder or %s) instead of string formatting.",
        "required_patterns": ["?", "%s", "param", "prepared", "execute("],
        "forbidden_patterns": ["f\"", "f'", "+ username", "format("],
        "bonus_patterns": ["cursor.execute", "db.execute(query,"],
    },
    {
        "id": "fix_003",
        "schema_context": (
            "Table: sales (id INT PK, product_id INT, sale_date DATE INDEX, "
            "amount DECIMAL, region VARCHAR)"
        ),
        "sql_query": (
            "SELECT product_id, SUM(amount) AS total_revenue\n"
            "FROM sales\n"
            "WHERE DATE_FORMAT(sale_date, '%Y-%m') = '2024-01'\n"
            "GROUP BY product_id\n"
            "ORDER BY total_revenue DESC"
        ),
        "issue_description": "DATE_FORMAT() on an indexed column prevents index usage, causing a full table scan.",
        "hint": "Replace DATE_FORMAT() with a range condition: sale_date >= '2024-01-01' AND sale_date < '2024-02-01'",
        "required_patterns": ["sale_date >=", "sale_date <", "2024-01-01"],
        "forbidden_patterns": ["date_format", "year(sale_date", "month(sale_date"],
        "bonus_patterns": ["between", "2024-02-01"],
    },
    {
        "id": "fix_004",
        "schema_context": (
            "Table: orders (id INT PK, customer_id INT INDEX, status VARCHAR, total DECIMAL)\n"
            "Table: customers (id INT PK, name VARCHAR, email VARCHAR, tier VARCHAR)"
        ),
        "sql_query": (
            "SELECT o.id, o.total, c.name\n"
            "FROM orders o\n"
            "JOIN customers c ON o.customer_id = c.id\n"
            "WHERE o.status = 'completed'\n"
            "  AND o.total > (SELECT AVG(total) FROM orders WHERE status = 'completed')"
        ),
        "issue_description": "The correlated subquery SELECT AVG(total) is re-executed for every row scanned.",
        "hint": "Pre-compute the average in a CTE or derived table so it's calculated once.",
        "required_patterns": ["with", "cte", "avg_total", "avg(total"],
        "forbidden_patterns": [],
        "bonus_patterns": ["with avg_cte", "cross join (select avg"],
    },
    {
        "id": "fix_005",
        "schema_context": (
            "Table: products (id INT PK, name VARCHAR, category VARCHAR INDEX, price DECIMAL, stock INT)\n"
            "Table: order_items (id INT PK, order_id INT INDEX, product_id INT INDEX, quantity INT)"
        ),
        "sql_query": (
            "SELECT p.id, p.name,\n"
            "       (SELECT SUM(oi.quantity) FROM order_items oi WHERE oi.product_id = p.id) AS units_sold\n"
            "FROM products p\n"
            "WHERE p.category = 'electronics'\n"
            "  AND p.stock > 0"
        ),
        "issue_description": "Correlated subquery in SELECT clause executes once per product row, causing N+1 queries.",
        "hint": "Replace the correlated subquery with a LEFT JOIN + GROUP BY or a window function.",
        "required_patterns": ["left join", "group by", "sum(oi.quantity"],
        "forbidden_patterns": ["(select sum(oi.quantity"],
        "bonus_patterns": ["coalesce", "left join order_items"],
    },
]


# ══════════════════════════════════════════════════════════════════════════════
#  HARD — full_review
# ══════════════════════════════════════════════════════════════════════════════

REVIEW_TASKS: List[Dict] = [
    {
        "id": "rev_001",
        "schema_context": (
            "Table: users (id INT PK, username VARCHAR(50), email VARCHAR(100),\n"
            "       password_hash VARCHAR(255), role ENUM('admin','user'),\n"
            "       last_login TIMESTAMP, is_active TINYINT)\n"
            "Table: user_sessions (id INT PK, user_id INT FK, token VARCHAR(255),\n"
            "       created_at TIMESTAMP, expires_at TIMESTAMP)\n"
            "Table: audit_log (id INT PK, user_id INT, action VARCHAR(100),\n"
            "       details TEXT, created_at TIMESTAMP INDEX)"
        ),
        "sql_query": (
            "query = f\"\"\"\n"
            "SELECT *\n"
            "FROM users u, user_sessions s, audit_log a\n"
            "WHERE u.username = '{username}'\n"
            "  AND s.user_id = u.id\n"
            "  AND a.user_id = u.id\n"
            "  AND s.expires_at > NOW()\n"
            "ORDER BY a.created_at DESC\n"
            "\"\"\""
        ),
        "issues": ["sql_injection", "cartesian_product", "select_star", "missing_limit"],
        "rubric": {
            "identifies_sql_injection": {
                "weight": 0.25,
                "patterns": ["injection", "sqli", "parameteriz", "f-string", "f\"\"\"", "interpolat"],
            },
            "identifies_cartesian": {
                "weight": 0.20,
                "patterns": ["cartesian", "cross", "implicit join", "missing join", "comma join"],
            },
            "identifies_select_star": {
                "weight": 0.15,
                "patterns": ["select *", "wildcard", "all columns", "explicit columns", "avoid *"],
            },
            "adds_limit_clause": {
                "weight": 0.10,
                "patterns": ["limit", "pagination", "top n", "unbounded"],
            },
            "provides_fixed_query_with_params": {
                "weight": 0.30,
                "patterns": ["select u.id", "select u.email", "join user_sessions", "join audit_log",
                             "where u.username = ?", "where u.username = %s", "parameterized",
                             "prepared statement", "limit 100", "limit 50"],
            },
        },
    },
    {
        "id": "rev_002",
        "schema_context": (
            "Table: products (id INT PK, name VARCHAR(100), category VARCHAR(50) INDEX,\n"
            "       price DECIMAL, stock INT, created_at TIMESTAMP)\n"
            "Table: order_items (id INT PK, order_id INT INDEX, product_id INT INDEX,\n"
            "       quantity INT, unit_price DECIMAL)\n"
            "Table: orders (id INT PK, customer_id INT INDEX,\n"
            "       created_at TIMESTAMP INDEX, status VARCHAR(20))"
        ),
        "sql_query": (
            "SELECT p.name, p.category,\n"
            "       SUM(oi.quantity)            AS total_sold,\n"
            "       SUM(oi.quantity*oi.unit_price) AS revenue,\n"
            "       (SELECT COUNT(*)\n"
            "        FROM order_items\n"
            "        WHERE product_id = p.id)   AS item_count\n"
            "FROM products p, order_items oi, orders o\n"
            "WHERE oi.product_id = p.id\n"
            "  AND oi.order_id   = o.id\n"
            "  AND YEAR(o.created_at) = 2024\n"
            "  AND p.stock > 0\n"
            "ORDER BY revenue DESC"
        ),
        "issues": ["correlated_subquery", "function_on_indexed_col", "missing_group_by", "missing_limit"],
        "rubric": {
            "identifies_correlated_subquery": {
                "weight": 0.25,
                "patterns": ["correlated", "subquery", "per row", "n+1", "count(*) inside", "per-product"],
            },
            "identifies_function_on_index": {
                "weight": 0.20,
                "patterns": ["year(", "function on", "sargable", "index on created_at",
                             "can't use index", "full scan", "date range"],
            },
            "identifies_missing_group_by": {
                "weight": 0.15,
                "patterns": ["group by", "aggregate", "grouping", "missing group"],
            },
            "uses_date_range_fix": {
                "weight": 0.10,
                "patterns": ["between", "created_at >=", "2024-01-01", ">= '2024"],
            },
            "provides_fixed_query": {
                "weight": 0.30,
                "patterns": ["group by p.id", "group by p.name", "left join order_items",
                             "join orders", "created_at >= '2024", "limit"],
            },
        },
    },
    {
        "id": "rev_003",
        "schema_context": (
            "Table: transactions (id INT PK, account_id INT INDEX, merchant VARCHAR(100),\n"
            "       amount DECIMAL, category VARCHAR(50), created_at TIMESTAMP INDEX,\n"
            "       is_flagged TINYINT)\n"
            "Table: accounts (id INT PK, user_id INT INDEX, balance DECIMAL,\n"
            "       account_type VARCHAR(20), is_active TINYINT)\n"
            "Table: fraud_rules (id INT PK, rule_name VARCHAR(100), threshold DECIMAL,\n"
            "       category VARCHAR(50), is_active TINYINT)"
        ),
        "sql_query": (
            "SELECT *\n"
            "FROM transactions t\n"
            "WHERE t.account_id IN (\n"
            "    SELECT id FROM accounts WHERE balance < 0\n"
            ")\n"
            "AND t.amount > (\n"
            "    SELECT AVG(amount) * 2\n"
            "    FROM transactions\n"
            "    WHERE category = t.category   -- correlated!\n"
            ")\n"
            "AND EXISTS (\n"
            "    SELECT 1 FROM fraud_rules\n"
            "    WHERE is_active = 1\n"
            "      AND threshold < t.amount\n"
            ")\n"
            "ORDER BY t.created_at DESC"
        ),
        "issues": ["select_star", "multiple_correlated_subqueries", "missing_limit", "in_subquery_vs_join"],
        "rubric": {
            "identifies_select_star": {
                "weight": 0.10,
                "patterns": ["select *", "wildcard", "explicit columns", "avoid *"],
            },
            "identifies_correlated_subqueries": {
                "weight": 0.30,
                "patterns": ["correlated", "per-row", "per row", "subquery", "avg(amount) * 2",
                             "re-execut", "n+1", "category = t.category"],
            },
            "identifies_missing_limit": {
                "weight": 0.10,
                "patterns": ["limit", "pagination", "unbounded result", "all rows"],
            },
            "suggests_cte_or_join": {
                "weight": 0.20,
                "patterns": ["with ", "cte", "common table", "join fraud_rules",
                             "join accounts", "left join", "pre-compute"],
            },
            "provides_optimized_query": {
                "weight": 0.30,
                "patterns": ["with avg_by_category", "with negative_accounts", "join accounts a",
                             "join fraud_rules f", "t.id, t.account_id", "limit 100", "limit 500"],
            },
        },
    },
]


# ══════════════════════════════════════════════════════════════════════════════
#  Graders
# ══════════════════════════════════════════════════════════════════════════════

def grade_classify(action_content: str, task: Dict) -> Tuple[float, str]:
    """Grade classify_issue task. Returns (score 0-1, feedback string)."""
    content_lower = action_content.lower()
    label = task["label"]

    if label in content_lower:
        return 0.999, f"✓ Correct! The primary issue is '{label}'."

    # Partial credit: keyword synonyms
    for kw in task.get("alt_keywords", []):
        if kw.lower() in content_lower:
            return 0.5, (
                f"Partially correct. You identified related concepts but the precise label is '{label}'."
            )

    return 0.001, (
        f"Incorrect. The primary issue type is '{label}'. "
        "Valid labels: select_star, sql_injection, cartesian_product, missing_index, n_plus_one."
    )


def grade_fix(action_content: str, task: Dict) -> Tuple[float, str]:
    """Grade fix_query task. Returns (score 0-1, feedback string)."""
    content_lower = action_content.lower()
    score = 0.0

    required = task.get("required_patterns", [])
    forbidden = task.get("forbidden_patterns", [])
    bonus = task.get("bonus_patterns", [])

    # Required elements (up to 0.70)
    if required:
        matched = sum(1 for p in required if p.lower() in content_lower)
        score += 0.70 * (matched / len(required))

    # Penalty for keeping forbidden patterns (up to -0.20)
    if forbidden:
        violations = sum(1 for p in forbidden if p.lower() in content_lower)
        if violations:
            score -= 0.20 * (violations / len(forbidden))

    # Structural SQL bonus (0.15) — looks like a real query rewrite
    sql_structural = ["select", "from", "where", "join"]
    if sum(1 for kw in sql_structural if kw in content_lower) >= 3:
        score += 0.15

    # Bonus patterns (0.15)
    if bonus:
        b_matched = sum(1 for p in bonus if p.lower() in content_lower)
        score += 0.15 * (b_matched / len(bonus))

    score = max(0.001, min(0.999, round(score, 4)))

    if score >= 0.85:
        fb = "Excellent fix! The rewrite correctly addresses the issue."
    elif score >= 0.60:
        fb = f"Good progress. Some required elements present. Hint: {task['hint']}"
    elif score >= 0.30:
        fb = f"Partial fix. Important elements missing. Hint: {task['hint']}"
    else:
        fb = f"The fix needs significant work. Hint: {task['hint']}"

    return score, fb


def grade_review(action_content: str, task: Dict) -> Tuple[float, str]:
    """Grade full_review task using a multi-criterion rubric. Returns (score 0-1, feedback)."""
    content_lower = action_content.lower()
    rubric: Dict = task["rubric"]
    score = 0.0
    found_criteria = []
    missed_criteria = []

    for criterion, meta in rubric.items():
        weight: float = meta["weight"]
        patterns: List[str] = meta["patterns"]
        if any(p.lower() in content_lower for p in patterns):
            score += weight
            found_criteria.append(criterion.replace("_", " "))
        else:
            missed_criteria.append(criterion.replace("_", " "))

    score = max(0.001, min(0.999, round(score, 4)))

    found_str = ", ".join(found_criteria) if found_criteria else "none"
    missed_str = ", ".join(missed_criteria) if missed_criteria else "none"

    if score >= 0.85:
        fb = f"Excellent review! Criteria satisfied: {found_str}."
    elif score >= 0.55:
        fb = f"Good review. Found: {found_str}. Still missing: {missed_str}."
    elif score >= 0.25:
        fb = f"Partial review. Found: {found_str}. Missing: {missed_str}."
    else:
        fb = f"Incomplete review. Missing most criteria: {missed_str}."

    return score, fb


# ══════════════════════════════════════════════════════════════════════════════
#  Task registry helpers
# ══════════════════════════════════════════════════════════════════════════════

TASK_REGISTRY: Dict[str, Dict] = {
    "classify_issue": {
        "data": CLASSIFY_TASKS,
        "max_steps": 1,
        "difficulty": "easy",
        "grader": grade_classify,
    },
    "fix_query": {
        "data": FIX_TASKS,
        "max_steps": 3,
        "difficulty": "medium",
        "grader": grade_fix,
    },
    "full_review": {
        "data": REVIEW_TASKS,
        "max_steps": 5,
        "difficulty": "hard",
        "grader": grade_review,
    },
}


def get_task_description(task_name: str) -> str:
    descriptions = {
        "classify_issue": (
            "Identify the PRIMARY issue type in the SQL query below. "
            "Respond with exactly one of these labels (include the label clearly in your response): "
            "select_star, sql_injection, cartesian_product, missing_index, n_plus_one. "
            "Briefly explain your reasoning."
        ),
        "fix_query": (
            "The SQL query below has the described issue. Rewrite the query to fix it. "
            "Provide your corrected SQL query and briefly explain what you changed. "
            "You have multiple attempts — feedback will guide you."
        ),
        "full_review": (
            "Perform a FULL code review of the SQL query below. You must: "
            "(1) List ALL issues found (there are multiple), "
            "(2) Provide a complete corrected/optimized query, "
            "(3) Explain each fix and its performance/security impact. "
            "You have multiple attempts — use feedback to improve your review."
        ),
    }
    return descriptions.get(task_name, "Complete the task.")


def sample_task(task_name: str, rng: Optional[random.Random] = None) -> Dict:
    """Sample a random task scenario for the given task name."""
    rng = rng or random.Random()
    data = TASK_REGISTRY[task_name]["data"]
    task = rng.choice(data).copy()
    task["task_name"] = task_name
    task["max_steps"] = TASK_REGISTRY[task_name]["max_steps"]
    task["task_description"] = get_task_description(task_name)
    return task


def grade_action(action_content: str, task: Dict) -> Tuple[float, str]:
    """Dispatch to the correct grader based on task_name."""
    task_name = task.get("task_name", "classify_issue")
    grader = TASK_REGISTRY[task_name]["grader"]
    return grader(action_content, task)
