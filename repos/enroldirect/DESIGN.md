# EnrolDirect — Design

Why this application is shaped the way it is. Read
[`ARCHITECTURE.md`](ARCHITECTURE.md) first for *what* it is;
[`README.md`](README.md) carries the operational picture.

## Scope keywords

Online enrolment channel, self-serve enrolment, access preference, member
access, guest access, prospect population, eligibility gate, access decision,
denial reason, applicant category, plan member enrolment, benefit take-up,
enrolment refusal, impact analysis, contract status gate.

---

## 1. Design intent

One question: **may this applicant use the self-serve enrolment channel on this
contract?**

Three commitments follow, and they are unusual enough to state plainly:

1. **A decision without a reason is a defect.** This is member-facing. A
   refusal that cannot name the gate that closed becomes a phone call.
2. **The gate is written once and reused.** Every path that admits someone runs
   the same check.
3. **An open question is modelled, not guessed.** Where the rules do not cover
   a population, the application says so and sizes the options rather than
   picking one silently.

## 2. Enforcement and ownership are separate

PolicyCore **owns** the access preferences; EnrolDirect **enforces** them.

This split was deliberate and it is the reason this application exists as a
separate thing at all. The sponsor agrees the preferences at contract
inception, they live on the contract record, and they reach here as data.

The consequence: **changing what a preference means is a change to a contract
between two systems.** It cannot be done as a local edit here, which is exactly
why the prospect question required an impact analysis before code.

The preference strings are the integration contract. An unknown preference is
*absent*, and absent means *not granted* — so renaming one here without
renaming it in PolicyCore silently disables a gate rather than raising. That
failure mode is why `preferences.py` holds them as named constants with the
vocabulary contract documented in place, and why `unknown_preferences()`
reports rather than raises: a contract carrying a preference from a newer
PolicyCore release should still serve its known preferences correctly, and a
hard failure would take the whole channel down for one unrecognised string.

## 3. Gate ordering is a security property

```
1. contract ACTIVE?
2. category → preference?
3. sponsor enabled it?
```

**Check 1 must precede check 3.** A lapsed contract retains whatever
preferences it was configured with. Reverse the two and stale configuration on
a dead contract grants access to a live channel.

What makes this genuinely dangerous is that it is **invisible to
category-level testing**: every category would still resolve to the right
preference, every preference check would still work, and the only broken case
is one nobody thinks to write a test for. Both the unit suite and the
regression suite pin the ordering explicitly, with a lapsed contract that *has*
the preference enabled — the case that only fails if the order is wrong.

## 4. Decisions carry reasons

`EligibilityDecision` returns `granted`, the reasons, and two separate
preference fields:

- `requiredPreference` — what was consulted for this applicant.
- `authorisingPreference` — what actually opened the gate. `None` on every
  denial.

They are recorded separately because downstream consumers word confirmations
and reconcile on the preference that *did the work*, not one inferred from the
applicant's category. Today those coincide for everyone the gate admits; they
are still kept distinct, because the moment they diverge, a single field would
silently be wrong somewhere downstream.

Returning a bare boolean was rejected. This is member-facing: the refusal text
*is* the product for anyone who gets refused.

## 5. The prospect, and why it is unresolved on purpose

`PROSPECT` — on the roster, holding no active benefit — resolves to **no
preference**, so a prospect is refused at the gate today.

**That refusal is the current behaviour, not a decision.** Neither preference
was written for this population. `impact.py` models both options against the
seeded directory and recommends one; acting on that recommendation is a change
to the gate that has not been made.

The design choice was to make the gap **explicit and measurable** rather than
resolve it by default. `preference_for_category` is one lookup in one place —
not a branch repeated at each call site — specifically so that whatever is
eventually decided lands in exactly one function.

The analysis recomputes from current configuration on every request rather than
serving a stored conclusion. That is what makes it an analysis *surface* rather
than a document: it cannot go stale relative to the rules it claims to mirror.
The regression suite pins the model to those rules so the two cannot drift.

## 6. No persistence, and what it costs

Contracts and applicants are seeded in-process. The enrolment log is in-memory.
Nothing survives a restart.

The constraint is the estate-wide one: it must run in a locked-down sandbox, so
a datastore is a dependency it cannot take. The benefit is real — this
application starts alone, needs nothing beside it, and recovery is provision,
deploy, start.

**The cost must be stated rather than glossed:** the enrolment log is not
durable, so it **cannot be the audit record of last resort**. Access decisions
and their reasons are the evidence trail if a refusal is disputed — and today
that trail dies with the process. If those outcomes must survive an incident,
they need shipping somewhere durable. That is a gap in the current design.

## 7. Data faults fail at the boundary

`Applicant.__post_init__` rejects two combinations outright:

- `MEMBER` with no active benefit — that is a prospect, mislabelled upstream.
- `PROSPECT` holding an active benefit — that is a member, not yet promoted.

Both are upstream data faults that would **grant or deny the wrong access
silently**. Coercing them to the "obviously intended" category was rejected:
that hides a data quality problem in the system that consumes it, and the
consuming system is the one that would be blamed for the wrong outcome.

Failing loudly at construction puts the error next to the bad record.

## 8. Enrolment reuses the gate

`POST /api/enrolments` runs the access gate — **reused, not reimplemented** —
then confirms the plan is on the applicant's contract and open to their
effective category.

An enrolment path with its own copy of the access rules is how a channel ends up
admitting someone the gate would have turned away. The two would drift on the
first change to either.

## 9. Scope boundary with PolicyCore

This application answers **whether the online channel is open** to someone.

**When** they may join at all — waiting periods, life events, enrolment
windows — is a different question owned by PolicyCore's `enrolment/`.

The two compose; they do not overlap. Someone can be eligible to enrol and
still be refused the online channel, and that is a correct outcome.

## 10. Deliberate non-goals

| Not done | Why |
|---|---|
| Resolving the prospect question in code | It is a contract between two systems; §5 |
| Persisting enrolments | Sandbox constraint; the cost is documented, not hidden |
| Owning the access preferences | PolicyCore owns them; this enforces them |
| Coercing mislabelled applicants | Hides an upstream data fault; §7 |
| A second copy of the gate for enrolment | Guarantees drift; §8 |
| Deciding applicant category | Derived upstream by plan administration |

## 11. What must not regress

`tests/test_regression_enroldirect.py` is human-authored, lives outside this
directory, and **no automated process may write to it**.

Its assertions go through HTTP and read fields off JSON rather than
constructing decisions directly, so adding a field to the decision payload is
not a regression — and nothing asserts the *absence* of a field. Everything it
asserts holds before and after the prospect question is settled, because it
pins the ground that must not move rather than the answer under debate.
