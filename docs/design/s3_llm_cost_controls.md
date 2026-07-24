# S3 LLM cost controls — what already exists, and the rules new features must follow

Reference doc for anyone adding a new LLM-calling feature to S3 (quick-impact
chat, code-suggestion chat, cross-team impact detection, etc.). Point at this
instead of re-deriving cost discipline per feature.

## What already exists

- **Everything goes through `common/llm.py`** (`complete()` / `stream_complete()`).
  No provider SDK call happens anywhere else in the codebase.
- **`LLM_MODE=live|record|replay`** (default **`replay`**, set in `.env.example`).
  `replay` serves a recorded response with zero network calls — this is the
  default for a reason (CLAUDE.md's demo-reliability rule: recorded outputs
  are primary, live calls are opt-in, never the reverse). `record` runs live
  and also refreshes the replay recording; `live` runs live without recording.
- **On-disk caching, independent of mode**: `complete()` hash-caches by
  `(provider, model, system, prompt)` — or an explicit `cache_key` when one is
  passed — under `.cache/llm/`. Even in `live` mode, an identical call never
  re-spends. `stream_complete()` has its own literal-filename replay store
  under `s3_enhancement/cache/*.json`, used for the S3 codegen/testgen beats.
- **`common/telemetry.py`**: `log_call()` fires on every single `complete()`/
  `stream_complete()` invocation automatically (cached-or-not, tokens,
  latency, success) — nothing to wire up per feature.
- **`tools/cost_dashboard.py`**: reads that telemetry log to show spend over
  time. Check it after adding a new call path to confirm it shows up.
- **Scoped context, not whole-repo context**: `s3_enhancement/relevance.py`'s
  `select_relevant_files()` narrows any prompt's codebase context to a
  handful of relevant files (visible in the UI's "files in this app" vs.
  "files used for this change" panel, and the scoped-vs-naive token-savings
  panel). Every prompt that needs codebase context calls this — never a raw
  whole-repo dump.

## Rules new conversational features must follow

1. **Capped clarification turns.** A conversational feature (quick-impact
   chat, code-suggestion/revise chat) may ask **at most 2** follow-up
   questions per session before it must produce a final answer. Enforce this
   server-side with an explicit turn counter passed into the prompt — once
   the cap is hit, the prompt must forbid asking another question and
   require a final answer. Do not leave this to model discretion; an
   open-ended "ask whatever you need" loop has no token ceiling.
2. **Scoped context only, always.** Any new prompt that needs to see the
   codebase builds its context via `relevance.select_relevant_files()`
   (`analyze.py`'s `_read_codebase_context` is the reference implementation),
   never a manual file read/dump.
3. **Cache by the smallest sufficient key.** A multi-turn conversation caches
   by a hash of the **full transcript so far**, not just the latest message —
   this makes a rehearsed conversation fully reproducible under
   `LLM_MODE=replay` (every turn replays deterministically), the same
   guarantee every other S3 demo beat already has.
4. **Re-use existing result shapes.** New features should return data shaped
   like existing dataclasses (e.g. `analyze.EffortEstimate`) where the
   content overlaps, so the frontend doesn't need a second bespoke renderer
   and so there's no second prompt independently re-deriving the same
   estimate format.
