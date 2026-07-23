"""Pre-warms `.cache/llm` for S1's demo rows.

`demo/reset_s1.sh` clears `.cache/llm` before every rehearsal so S1 beats replay
live — that's deliberate, it's how the live-call path gets tested. But nothing
currently re-populates the cache before the actual client demo runs, so the first
click after a reset pays full LLM latency (and live-call risk) on stage. Run this
right after a reset, before presenting: `common/llm.py`'s `complete()` already checks
the disk cache before calling any provider, so once a row is warmed here, My Queue's
background processing (and S1's batch mode) serves it instantly with no further live
calls.

Mirrors `s1_triage/batch.py`'s `run_one()` pipeline exactly — including its
self-service auto-resolve short-circuit and its early stop when the quality gate
rejects an incident — so this never burns a live call on a stage the demo won't
actually reach for that row. `s1_triage/app.py`'s `_render_incident_pipeline()`
(My Queue's per-ticket drill-down) shares every cache key this warms, since it's
only ever reached for tickets the background pass already assigned to an engineer.
(`s1_triage/__main__.py`'s smoke runner is a different, always-run-every-stage tool;
don't reuse it here.)

At the current 30-row demo scale, warming every row is cheap enough to be the
default — this is also what makes S1's batch mode's "Run batch" click feel instant
live: pre-warm once during rehearsal, replay from cache on stage.
"""

from __future__ import annotations

import argparse

from common.schema import Incident
from s1_triage.data_access import KbArticle, load_incidents, load_kb_articles
from s1_triage.quality_gate import assess
from s1_triage.resolution import draft_resolution
from s1_triage.routing import route
from s1_triage.self_service import match_self_service
from s1_triage.similar_incidents import find_similar
from s1_triage.triage import triage


def warm_row(row: int, incidents: list[Incident], kb_articles: list[KbArticle]) -> str:
    incident = incidents[row]

    if match_self_service(incident) is not None:
        return f"row {row} ({incident.number}): self-service — no LLM call needed"

    verdict = assess(incident)
    if not verdict.investigable:
        return f"row {row} ({incident.number}): quality gate only — rejected, stops here"

    triage_result = triage(incident)
    route(incident, triage_result)
    similar = find_similar(incident, incidents)
    draft_resolution(incident, similar, kb_articles)
    return f"row {row} ({incident.number}): full pipeline warmed"


def warm_rows(rows: list[int] | None) -> list[str]:
    incidents = load_incidents()
    kb_articles = load_kb_articles()
    target_rows = rows if rows else list(range(len(incidents)))
    return [warm_row(row, incidents, kb_articles) for row in target_rows]


def main() -> None:
    parser = argparse.ArgumentParser(description="Pre-warm .cache/llm for S1 demo rows")
    parser.add_argument(
        "rows",
        type=int,
        nargs="*",
        default=None,
        help="0-indexed incident rows to warm (default: every row in the dataset)",
    )
    args = parser.parse_args()
    for line in warm_rows(args.rows):
        print(line)


if __name__ == "__main__":
    main()
