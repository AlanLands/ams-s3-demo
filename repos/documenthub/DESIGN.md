# DocumentHub — design

Why the service is shaped the way it is, and which parts of that shape are
load-bearing.

## Whole packs per audience, not one letter with substitutions

The obvious design is one confirmation letter with `{planName}`-style
placeholders and a couple of conditional paragraphs. It was rejected.

The variable parts are not the parts that go wrong. Nobody sends a letter with
the wrong plan name — that field is populated from the record and is right by
construction. What goes wrong is the *framing*: whether we tell the recipient
they already hold coverage, whether we ask them to prove who they are, whether
we treat them as a stranger to the plan sponsor. Those are not fields. They are
the letter.

So the unit is a whole worded pack per **audience** — a recipient in a
particular relationship with the sponsor — and the only decision the service
makes is which audience someone belongs to. That decision then gets one name,
one function, and one place to look when a letter is wrong.

## Selection lives in exactly one function

`wording.audience_for` is the only place in the service that decides an
audience. `packs.build_pack` calls it; nothing else tests a record's fields to
reach a conclusion of its own.

This is enforced by the regression suite rather than by convention, because the
failure it prevents is quiet: if assembly could also inspect the record, the
letter and the enclosures could be chosen on different grounds, and the
envelope would contradict the page inside it. Nothing would raise, and the pack
would print.

## `feed.py` is a contract, and this service may not write to it

Every field on `EnrolmentRecord` is populated by EnrolDirect. DocumentHub reads
them and must never derive, default or correct one. In particular it must not
infer `onRoster` from anything else.

The reason is not layering purity. A service that infers its own input can
disagree with the system of record about the same person while remaining
internally consistent — and then produce a confident, well-formed, wrong
document that no amount of reading the document reveals. Keeping the input
external means a wrong pack is always traceable to either a wrong record or a
wrong rule, and both are findable.

This is why `feed.py` sits in the target's `core_files` but **not** in its
`codegen_allowlist`: the pipeline must read it to understand the change and
must not edit it. Same arrangement as `impact.py` in `repos/enroldirect/`, for
the same reason.

## The audit checks the packs' premise, not the rule's logic

`GET /api/audit/selection-inputs` reports, per record, whether the pack it
would receive claims MapleSure holds no member record for it
(`Wording.assumesNoMemberRecord`) while the sponsor lists it on the roster
(`feed.onRoster`).

Both halves are asserted by someone other than the selection rule — one by
Communications when the pack was worded, one by the sponsor. That is
deliberate and it is the only thing that makes the endpoint worth having: **a
rule cannot audit itself.** An endpoint that checked "did `audience_for` return
what `audience_for` would return" is a tautology, and one that checked "does a
rostered person get the member pack" would hard-code the very assumption under
review.

`assumesNoMemberRecord` is data on the wording rather than a computed property
for the same reason. Any audience added later has to declare it, honestly — a
pack that encloses an identity confirmation form is making that claim whether
or not it admits to it.

## The one-to-one that was never a rule

Until now, every recipient fell into one of two combinations:

| On roster | Authorised by | Pack |
|---|---|---|
| yes | Member access | member |
| no | Guest access | guest |

So selecting on the authorising preference alone was sufficient, and
`audience_for` reads exactly one field.

**That alignment was a property of who EnrolDirect happened to admit, not a
rule, and it was never enforced anywhere** — not in the feed's validation, not
in a test, not in a comment. It held because prospects (on the roster, holding
no active benefit) were refused at the enrolment gate entirely, so the third
combination never reached this service.

US-2026-045 settles that prospects are checked against the Guest preference.
From the day it ships, the third combination arrives: `onRoster = true` with
Guest access. `audience_for` has no branch for it and, by construction, falls
through to the guest pack.

The consequence is not an error and nothing logs it. It is a letter telling a
person listed on their own sponsor's roster that we hold no record of them,
enclosing a form asking them to prove their identity. Plan administration then
withdraws that request one telephone call at a time.

`ENR-20260804-005` in the seeded feed is that record. US-2026-046 adds the
third audience.

## Deliberate non-goals

- **No printing, no PDF, no template engine.** Packs are returned as
  structured JSON with a plain-text body. Rendering is the print vendor's job,
  and a rendering dependency would break the venv-only rule.
- **No persistence.** The feed is an in-process literal and packs are computed
  on request. There is no pack history to reconcile, deliberately — this is a
  demo target, and a stored artifact would need a migration step on every
  wording change.
- **No wording editor.** Prose lives in source and moves through review. A
  runtime editor would make the regression suite's pinned wording meaningless.
- **The service does not re-decide access.** If a record says an enrolment was
  authorised, it was. Re-checking eligibility here would be a second
  implementation of EnrolDirect's gate, which is the disagreement this design
  spends most of its effort avoiding.

## Note for whoever re-records the codegen cache

This target is registered by manifest and had no committed replay recording
when it was created — its first codegen run is a live call that records
itself (`repos/README.md`, "What a dropped-in repo gets").

Its declared mutation quotes `if record.onRoster:` from `wording.py`, which is
the line the story's acceptance criteria prescribe. `old_snippet` must appear
**verbatim in the generated code**, so re-check it against the recording after
the first live run and after every re-record. If the model phrases the branch
differently — `if record.onRoster is True:`, or an inverted test — the mutation
beat silently no-ops rather than failing loudly.
