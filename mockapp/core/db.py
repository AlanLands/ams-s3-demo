"""SQLite-backed storage for the MapleSure policy/claims mock app.

Plain stdlib sqlite3 only — no external DB. Database file lives at
data/mockapp.db (generated, gitignored — never hand-edit; regenerate via
mockapp.core.seed).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from mockapp.core.models import Claim, Policy

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
DB_PATH = DATA_DIR / "mockapp.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS policies (
    policy_number TEXT PRIMARY KEY,
    holder_name   TEXT NOT NULL,
    product_type  TEXT NOT NULL,
    premium       REAL NOT NULL,
    start_date    TEXT NOT NULL,
    status        TEXT NOT NULL,
    coverage_tier TEXT NOT NULL DEFAULT 'Standard'
);

CREATE TABLE IF NOT EXISTS claims (
    claim_number  TEXT PRIMARY KEY,
    policy_number TEXT NOT NULL REFERENCES policies (policy_number),
    claim_type    TEXT NOT NULL,
    amount        REAL NOT NULL,
    status        TEXT NOT NULL,
    filed_at      TEXT NOT NULL,
    notes         TEXT NOT NULL DEFAULT ''
);
"""


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Ensure new columns exist on already-created tables (simple migrations)."""
    cols = {
        row[1] for row in conn.execute("PRAGMA table_info(policies)").fetchall()
    }
    if "coverage_tier" not in cols:
        conn.execute(
            """
            ALTER TABLE policies
            ADD COLUMN coverage_tier TEXT NOT NULL DEFAULT 'Standard'
            """
        )


def init_db() -> None:
    """Create the database file and tables if they don't already exist."""
    conn = _connect()
    try:
        conn.executescript(_SCHEMA)
        _ensure_columns(conn)
        conn.commit()
    finally:
        conn.close()


def _row_to_policy(row: sqlite3.Row) -> Policy:
    return Policy(
        policy_number=row["policy_number"],
        holder_name=row["holder_name"],
        product_type=row["product_type"],
        premium=row["premium"],
        start_date=row["start_date"],
        status=row["status"],
        coverage_tier=row["coverage_tier"]
        if "coverage_tier" in row.keys()
        else "Standard",
    )


def _row_to_claim(row: sqlite3.Row) -> Claim:
    return Claim(
        claim_number=row["claim_number"],
        policy_number=row["policy_number"],
        claim_type=row["claim_type"],
        amount=row["amount"],
        status=row["status"],
        filed_at=row["filed_at"],
        notes=row["notes"],
    )


def list_policies() -> list[Policy]:
    """Return all policies, ordered by policy_number."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM policies ORDER BY policy_number"
        ).fetchall()
        return [_row_to_policy(r) for r in rows]
    finally:
        conn.close()


def get_policy(policy_number: str) -> Policy | None:
    """Return a single policy by number, or None if not found."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM policies WHERE policy_number = ?", (policy_number,)
        ).fetchone()
        return _row_to_policy(row) if row is not None else None
    finally:
        conn.close()


def list_claims(policy_number: str) -> list[Claim]:
    """Return all claims for a given policy, most recently filed first."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM claims WHERE policy_number = ? ORDER BY filed_at DESC",
            (policy_number,),
        ).fetchall()
        return [_row_to_claim(r) for r in rows]
    finally:
        conn.close()


def insert_policy(policy: Policy) -> None:
    """Insert (or replace) a policy row. Used by the seed script."""
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO policies
                (policy_number, holder_name, product_type, premium, start_date,
                 status, coverage_tier)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                policy.policy_number,
                policy.holder_name,
                policy.product_type,
                policy.premium,
                policy.start_date,
                policy.status,
                policy.coverage_tier,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def insert_claim(claim: Claim) -> None:
    """Insert (or replace) a claim row."""
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO claims
                (claim_number, policy_number, claim_type, amount, status, filed_at, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                claim.claim_number,
                claim.policy_number,
                claim.claim_type,
                claim.amount,
                claim.status,
                claim.filed_at,
                claim.notes,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def wipe_db() -> None:
    """Drop all tables. Used by the seed script before reseeding."""
    conn = _connect()
    try:
        conn.executescript(
            "DROP TABLE IF EXISTS claims; DROP TABLE IF EXISTS policies;"
        )
        conn.commit()
    finally:
        conn.close()
