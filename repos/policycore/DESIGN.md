# PolicyCore — Design

Why this application is shaped the way it is. Read
[`ARCHITECTURE.md`](ARCHITECTURE.md) first for *what* it is; this document
covers the decisions, the rules that are load-bearing, and the trade-offs
taken. [`README.md`](README.md) carries the operational picture.

## Scope keywords

Group contract administration, plan sponsor, plan member, dependant, group
benefits, plan tier, contribution, benefit claim intake, claim status,
amendment request, effective date, enrolment eligibility, waiting period,
member roster, policy administration, system of record.

---

## 1. Design intent

PolicyCore is the **authority for contract data**. Every other design decision
follows from that: it is the place a fact about a group contract is decided,
and everything else in the estate either reads that fact or enforces it.

That leads to three commitments:

1. **Correctness over convenience for anything contractual.** Effective dates,
   contribution amounts and tier transitions are refused rather than guessed.
2. **Requests are recorded, not applied.** A change to an in-force contract is
   an amendment with an effective date, not a mutation.
3. **No hidden coupling.** No outbound calls. Other applications depend on the
   *data* this owns, never on its availability at request time.

## 2. Layering, and why business logic is not in `app.py`

```
app.py           UI only — screens, forms, presentation
   │
core/*.py        business logic — no Streamlit, no CLI
   │
core/db.py       the only module that touches SQLite
```

The rule is that `core/` modules carry no presentation concerns. A `core/`
module that imports Streamlit is a bug, and the reason is portability: the
business rules must be callable from a test, a script, or a different front end
without dragging a UI framework in. Every regression and unit suite depends on
this being true — they call `core/` directly.

`app.py` never constructs a claim number, a timestamp or a default status. It
calls `submit_claim()`. Duplicating that construction in the view is how two
code paths start producing differently-shaped records.

## 3. The positional-construction contract

**This is the single most breakable thing in the repository.**

`core/seed.py` constructs every record with **positional** arguments:

```python
Policy(policy_number, sponsor_name, product_type, contribution, start_date, status)
```

Consequences, and they are not negotiable:

- A new field goes **last**.
- A new field carries a **default**.
- Existing field order does not change.

Violate any of those and seeding fails — not at the edit, but at the next
reseed, with an error that points at `seed.py` rather than at the dataclass
that moved. `tests/test_unit_policycore.py` asserts the six positional
arguments still construct and that everything after them has a default,
specifically so the failure lands next to the cause.

The same rule governs `Claim.member_id` and `Claim.notes`: both are last with
defaults because call sites that predate the plan-member layer file against the
group contract alone and must keep working.

## 4. Plan tiers

Tiers are **ordered**, and the ordering is the design:

```
Standard  →  Premium  →  Plus
```

A tier change is an upgrade or it is refused. Downgrades, same-tier changes and
unknown tiers all raise. This is deliberate: a downgrade mid-term has
contractual and billing consequences that a portal action must not quietly
perform, so the system declines and routes it to a human process.

Contribution is recalculated from the *ratio of multipliers*, not re-derived
from a rate table:

```
new_contribution = round(contribution / old_multiplier * new_multiplier, 2)
```

This preserves whatever sponsor-specific adjustment is already baked into the
stored contribution. Re-deriving from a table would silently discard it.

The refusal wording is a **fixed contract** — other scenarios in this estate
quote it verbatim, so rewording it is a breaking change, not a copy edit.

## 5. Amendments record intent

An amendment carries a `requested_change`, an `effective_date`, and a contact
route. Filing one does **not** mutate the contract.

The design question was whether a portal action should apply the change
directly. It should not: the effective date is contractual, amendments require
review, and an audit trail of *what was asked for and when* is the artefact
compliance actually needs. A system that mutates on request keeps no such
record.

The contact fields exist because an amendment that cannot be queried back to a
person stalls, and a stalled amendment misses its effective date.

## 6. Storage

**Plain SQLite via stdlib `sqlite3`, no ORM, no external database.**

The constraint is that this must run in a locked-down sandbox: no cloud-managed
service, no Docker requirement, no OS-specific dependency. That rules out a
server database and makes an ORM poor value — the query surface is small and
the schema is stable.

The cost is real and accepted: single-writer, local to the instance, and a
second process would serve inconsistent state. Capacity planning treats this as
a single-instance application.

**One migration hazard is permanent.** A database created before the
group-retirement vocabulary change carries a legacy `endorsements` table with a
foreign key to `policies`. Dropping `policies` while a row remains in it fails,
and the failure is not recoverable without deleting the database file. The wipe
path therefore drops that table first, unconditionally. That is not dead code.

## 7. Enrolment is two questions, not one

`enrolment/eligibility.py` answers **when** someone may join — waiting periods,
life events, enrolment windows.

Whether the **online self-serve channel** is open to them is a different
question, owned by EnrolDirect and gated on access preferences that live on the
contract record here.

The two compose and do not overlap. Merging them was considered and rejected:
they change for different reasons, on different timescales, driven by different
owners. A member can be eligible to enrol and still be refused the online
channel, and that is a correct outcome, not a contradiction.

**PolicyCore owns those preferences; EnrolDirect enforces them.** Changing what
a preference means is a change to a contract between two systems.

## 8. Deliberate non-goals

| Not done | Why |
|---|---|
| Multi-instance / horizontal scale | State is local by design; a second worker serves inconsistent state |
| ORM or migration framework | Small stable schema; hard rule against heavyweight dependencies |
| Applying amendments automatically | Effective dates are contractual and require review |
| Calling other services | Other applications depend on this data, not on this uptime |
| Owning online-channel access | That is EnrolDirect's, gated on preferences owned here |

## 9. What must not regress

`tests/test_regression_policycore.py` and
`tests/test_regression_policycore_enrolment.py` are human-authored, live
outside this directory, and **no automated process may write to them**. That
independence is the whole value: a suite a change can rewrite is not evidence
the change was safe.

Two rules for anything added to them: it must pass **before and after** every
change, and it must stay outside this directory.
