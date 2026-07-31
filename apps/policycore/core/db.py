"""SQLite-backed storage for the MapleSure group benefits mock app.

Plain stdlib sqlite3 only — no external DB. Database file lives at
data/mockapp.db (generated, gitignored — never hand-edit; regenerate via
apps.policycore.core.seed).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from apps.policycore.core.models import Claim, Endorsement, PlanMember, Policy

REPO_ROOT = Path(__file__).resolve().parents[3]
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

CREATE TABLE IF NOT EXISTS plan_members (
    member_id     TEXT PRIMARY KEY,
    policy_number TEXT NOT NULL REFERENCES policies (policy_number),
    member_name   TEXT NOT NULL,
    dependents    INTEGER NOT NULL DEFAULT 0,
    enrolled_on   TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'Active'
);

CREATE TABLE IF NOT EXISTS claims (
    claim_number  TEXT PRIMARY KEY,
    policy_number TEXT NOT NULL REFERENCES policies (policy_number),
    claim_type    TEXT NOT NULL,
    amount        REAL NOT NULL,
    status        TEXT NOT NULL,
    filed_at      TEXT NOT NULL,
    notes         TEXT NOT NULL DEFAULT '',
    member_id     TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS endorsements (
    endorsement_number TEXT PRIMARY KEY,
    policy_number      TEXT NOT NULL REFERENCES policies (policy_number),
    endorsement_type   TEXT NOT NULL,
    requested_change   TEXT NOT NULL,
    effective_date     TEXT NOT NULL,
    contact_phone      TEXT NOT NULL,
    contact_email      TEXT NOT NULL,
    filed_at           TEXT NOT NULL
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
    claim_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(claims)").fetchall()
    }
    if "member_id" not in claim_cols:
        conn.execute(
            "ALTER TABLE claims ADD COLUMN member_id TEXT NOT NULL DEFAULT ''"
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
        member_id=row["member_id"] if "member_id" in row.keys() else "",
    )


def _row_to_plan_member(row: sqlite3.Row) -> PlanMember:
    return PlanMember(
        member_id=row["member_id"],
        policy_number=row["policy_number"],
        member_name=row["member_name"],
        dependents=row["dependents"],
        enrolled_on=row["enrolled_on"],
        status=row["status"],
    )


def _row_to_endorsement(row: sqlite3.Row) -> Endorsement:
    return Endorsement(
        endorsement_number=row["endorsement_number"],
        policy_number=row["policy_number"],
        endorsement_type=row["endorsement_type"],
        requested_change=row["requested_change"],
        effective_date=row["effective_date"],
        contact_phone=row["contact_phone"],
        contact_email=row["contact_email"],
        filed_at=row["filed_at"],
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


def list_plan_members(policy_number: str) -> list[PlanMember]:
    """Return all plan members enrolled under a group contract, by member id."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM plan_members WHERE policy_number = ? ORDER BY member_id",
            (policy_number,),
        ).fetchall()
        return [_row_to_plan_member(r) for r in rows]
    finally:
        conn.close()


def get_plan_member(member_id: str) -> PlanMember | None:
    """Return a single plan member by id, or None if not found."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM plan_members WHERE member_id = ?", (member_id,)
        ).fetchone()
        return _row_to_plan_member(row) if row is not None else None
    finally:
        conn.close()


def list_endorsements(policy_number: str) -> list[Endorsement]:
    """Return all endorsement requests for a given policy, most recent first."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM endorsements WHERE policy_number = ? ORDER BY filed_at DESC",
            (policy_number,),
        ).fetchall()
        return [_row_to_endorsement(r) for r in rows]
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


def insert_plan_member(member: PlanMember) -> None:
    """Insert (or replace) a plan-member row. Used by the seed script."""
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO plan_members
                (member_id, policy_number, member_name, dependents, enrolled_on, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                member.member_id,
                member.policy_number,
                member.member_name,
                member.dependents,
                member.enrolled_on,
                member.status,
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
                (claim_number, policy_number, claim_type, amount, status, filed_at,
                 notes, member_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                claim.claim_number,
                claim.policy_number,
                claim.claim_type,
                claim.amount,
                claim.status,
                claim.filed_at,
                claim.notes,
                claim.member_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def insert_endorsement(endorsement: Endorsement) -> None:
    """Insert (or replace) an endorsement-request row."""
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO endorsements
                (endorsement_number, policy_number, endorsement_type, requested_change,
                 effective_date, contact_phone, contact_email, filed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                endorsement.endorsement_number,
                endorsement.policy_number,
                endorsement.endorsement_type,
                endorsement.requested_change,
                endorsement.effective_date,
                endorsement.contact_phone,
                endorsement.contact_email,
                endorsement.filed_at,
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
            "DROP TABLE IF EXISTS endorsements; "
            "DROP TABLE IF EXISTS claims; "
            "DROP TABLE IF EXISTS plan_members; "
            "DROP TABLE IF EXISTS policies;"
        )
        conn.commit()
    finally:
        conn.close()
