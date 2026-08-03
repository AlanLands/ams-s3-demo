"""The change-map diagram for the QA design document.

A picture of what this change touches: which service, which architectural
layer, which files, and — where the CR crosses a service boundary — the call
that crosses it. Handed to QA alongside the design doc so "affected areas" is
something you can look at rather than a paragraph you have to hold in your
head.

## Derived, not generated

No LLM call. Every element comes from data the pipeline already holds: the
target's changed-file set, the path each file sits at, and (optionally) the
downstream applications the cross-team check surfaced. Same reasoning as the
routing panel — a model-drawn architecture diagram can be plausibly wrong in a
way nobody notices in a demo, it would need its own replay recording to stay
deterministic, and it would fail closed on a cache miss. This one is a pure
function of the file list, so it always renders and never needs warming.

The trade is honesty about precision: layering is inferred from path and
filename conventions, so the diagram is a *map of the blast radius*, not a
verified call graph. `LAYERS` documents each rule, and anything unmatched
lands in "Other" rather than being forced into a layer it may not belong to.

## Why hand-rolled SVG

Mermaid or similar would mean a new frontend dependency, a runtime parse of
model-adjacent text, and — because the design doc downloads as a standalone
file — inlining a megabyte of renderer into every exported document. The
layout here is a fixed grid of at most a few columns, so emitting the SVG
directly is less code than wiring a library, embeds in the export as plain
markup, and prints to PDF without a JavaScript step.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from html import escape
from pathlib import Path

from s3_enhancement.targets import Target

REPO_ROOT = Path(__file__).resolve().parents[1]

# Layer inference, most specific rule first. Each entry is
# (layer name, filename suffixes, path fragments) — a file matches if any
# suffix matches its filename or any fragment appears in its path.
LAYERS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    # Entry points: what a user or an HTTP client touches first.
    ("Interface", ("app.py", "main.py"), ("/views/", "/static/")),
    # Persistence and the shapes that cross it.
    ("Data", ("db.py", "models.py", "seed.py"), ("/repository/", "/entity/")),
    # Business rules and outbound calls. Broadest rule, so it runs last.
    ("Logic", (".py",), ("/core/",)),
)
LAYER_ORDER = ("Interface", "Logic", "Data", "Other")

# A record/dataclass carrying only fields is the data shape for its service,
# not logic — but it has no suffix that says so. These are the demo estate's
# record types; anything else falls through to the rules above.
_DATA_RECORDS = ("policy.py", "claim.py")

_BOX_W = 190
_BOX_H = 46
_BOX_GAP = 12
_COL_GAP = 46
_ROW_GAP = 34
_LABEL_W = 78
_PAD = 16
_HEADER_H = 30


@dataclass
class DiagramNode:
    rel_path: str
    filename: str
    layer: str
    service: str
    is_new: bool = False


@dataclass
class ChangeMap:
    """The diagram's data, kept separate from its rendering so the same facts
    can be asserted in tests without parsing SVG."""

    services: list[str]
    nodes: list[DiagramNode]
    downstream: list[str] = field(default_factory=list)
    # Service pairs the changed code calls across, e.g. ("claims", "policy").
    crossings: list[tuple[str, str]] = field(default_factory=list)

    def nodes_in(self, service: str, layer: str) -> list[DiagramNode]:
        return [n for n in self.nodes if n.service == service and n.layer == layer]

    @property
    def layers_used(self) -> list[str]:
        present = {node.layer for node in self.nodes}
        return [layer for layer in LAYER_ORDER if layer in present]


def _layer_for(rel_path: str) -> str:
    filename = rel_path.rsplit("/", 1)[-1]
    if filename in _DATA_RECORDS:
        return "Data"
    for layer, suffixes, fragments in LAYERS:
        if any(filename.endswith(suffix) for suffix in suffixes):
            return layer
        if any(fragment in f"/{rel_path}" for fragment in fragments):
            return layer
    return "Other"


def _service_for(rel_path: str, target: Target) -> str:
    """The deployable unit a file belongs to.

    The ClaimsPortal target is one target root holding two services (see
    CLAUDE.md), so its files split by the directory under the root. A
    single-service target returns one bucket named for the application.
    """
    if target.root is None:
        return target.display_name
    try:
        prefix = target.root.relative_to(REPO_ROOT).as_posix() + "/"
    except ValueError:
        return target.display_name
    if not rel_path.startswith(prefix):
        return target.display_name
    remainder = rel_path[len(prefix) :]
    head = remainder.split("/", 1)[0]
    # A file directly under the root (repos/policycore/app.py) means the target
    # is not split into services at all.
    if "/" not in remainder or not head.endswith("_service"):
        return target.root.name
    return head


def _is_new(rel_path: str) -> bool:
    """Whether this file is created by the change rather than edited by it.

    Asked of git, because by the time the design doc is drafted the change has
    already been applied and the file exists on disk either way. A repo
    without git, or a path git cannot answer for, degrades to "modified" — an
    unbadged box is a smaller error than a wrong badge.
    """
    try:
        result = subprocess.run(
            ["git", "cat-file", "-e", f"HEAD:{rel_path}"],
            cwd=REPO_ROOT,
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode != 0


def build_change_map(
    target: Target,
    *,
    changed_files: list[str] | None = None,
    downstream: list[str] | None = None,
) -> ChangeMap:
    """Assemble the diagram's facts for `target`.

    `changed_files` defaults to the target's codegen allowlist — the files the
    CR is contracted to touch — so the map is available before, during and
    after apply, and does not depend on a proposal still being in memory.
    """
    # `is None`, not falsiness: an explicitly empty list means "this change
    # touches nothing", and quietly substituting the whole allowlist for it
    # would draw a diagram of files the caller just said were not involved.
    files = list(target.codegen_allowlist if changed_files is None else changed_files)
    nodes = [
        DiagramNode(
            rel_path=rel_path,
            filename=rel_path.rsplit("/", 1)[-1],
            layer=_layer_for(rel_path),
            service=_service_for(rel_path, target),
            is_new=_is_new(rel_path),
        )
        for rel_path in files
    ]

    services: list[str] = []
    for node in nodes:
        if node.service not in services:
            services.append(node.service)

    # A *_client.py in one service is an outbound HTTP call to another. With
    # exactly two services in the change there is only one candidate for the
    # other end, so the edge is unambiguous; with more, drawing it would be a
    # guess and is skipped.
    crossings: list[tuple[str, str]] = []
    if len(services) == 2:
        for node in nodes:
            if node.filename.endswith("_client.py"):
                other = [s for s in services if s != node.service][0]
                edge = (node.service, other)
                if edge not in crossings:
                    crossings.append(edge)

    return ChangeMap(
        services=services,
        nodes=nodes,
        downstream=list(downstream or []),
        crossings=crossings,
    )


def _tidy_service(name: str) -> str:
    return name.replace("-", " ").replace("_", " ").title()


def caption_for(change_map: ChangeMap) -> str:
    """The diagram's provenance line.

    Says what was read rather than what was drawn, and only claims the parts
    the diagram actually contains — a single-service change has no
    cross-service call, and a caption that mentions one is the kind of small
    inaccuracy that costs credibility in the room where it matters.
    """
    parts = ["layers"]
    if len(change_map.services) > 1:
        parts.insert(0, "services")
    if change_map.crossings:
        parts.append("the cross-service call")
    read = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    return (
        f"Derived from the change's file set — {read} are read from the applied "
        "paths, not generated by a model. Layering follows path and filename "
        "convention, so this is a map of what the change touches rather than a "
        "verified call graph."
    )


def render_svg(change_map: ChangeMap, *, title: str = "Change map") -> str:
    """Standalone SVG for `change_map`.

    Self-contained by design: presentation attributes rather than a stylesheet,
    no external fonts, no script. It has to survive being embedded in an
    exported HTML file, printed to PDF, and rendered inside the console, and
    the only way to be sure of all three is to depend on nothing.
    """
    layers = change_map.layers_used
    services = change_map.services or ["Application"]
    if not change_map.nodes:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="420" height="60" '
            'role="img" aria-label="No changed files to map">'
            '<text x="10" y="34" font-family="system-ui, sans-serif" font-size="13" '
            'fill="#6e6d66">No changed files to map.</text></svg>'
        )

    # A row is as tall as the busiest cell in it, so a service with three files
    # in one layer does not overlap the row beneath.
    row_heights = [
        max(
            1,
            max(len(change_map.nodes_in(service, layer)) for service in services),
        )
        * (_BOX_H + _BOX_GAP)
        - _BOX_GAP
        for layer in layers
    ]

    col_x = [
        _PAD + _LABEL_W + index * (_BOX_W + _COL_GAP) for index in range(len(services))
    ]
    row_y: list[int] = []
    cursor = _PAD + _HEADER_H
    for height in row_heights:
        row_y.append(cursor)
        cursor += height + _ROW_GAP
    content_bottom = cursor - _ROW_GAP

    downstream_y = content_bottom + 26 if change_map.downstream else content_bottom
    width = _PAD * 2 + _LABEL_W + len(services) * _BOX_W + (len(services) - 1) * _COL_GAP
    height = downstream_y + (44 if change_map.downstream else 0) + _PAD

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}" '
        'font-family="system-ui, -apple-system, Segoe UI, sans-serif">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
    ]

    # Service headers.
    for index, service in enumerate(services):
        parts.append(
            f'<text x="{col_x[index] + _BOX_W // 2}" y="{_PAD + 14}" text-anchor="middle" '
            f'font-size="12" font-weight="700" fill="#363530">'
            f"{escape(_tidy_service(service))}</text>"
        )

    # Layer bands: label on the left, then each service's files in that layer.
    for row, layer in enumerate(layers):
        band_top = row_y[row]
        parts.append(
            f'<text x="{_PAD}" y="{band_top + 16}" font-size="10" font-weight="700" '
            f'fill="#6e6d66" letter-spacing="0.06em">{escape(layer.upper())}</text>'
        )
        for index, service in enumerate(services):
            for depth, node in enumerate(change_map.nodes_in(service, layer)):
                x = col_x[index]
                y = band_top + depth * (_BOX_H + _BOX_GAP)
                fill = "#f5e6e9" if node.is_new else "#f7f7f6"
                stroke = "#a20a29" if node.is_new else "#c9c8c3"
                parts.append(
                    f'<rect x="{x}" y="{y}" width="{_BOX_W}" height="{_BOX_H}" rx="4" '
                    f'fill="{fill}" stroke="{stroke}"/>'
                )
                parts.append(
                    f'<text x="{x + 10}" y="{y + 19}" font-size="12" font-weight="600" '
                    f'fill="#363530">{escape(node.filename)}</text>'
                )
                if node.is_new:
                    parts.append(
                        f'<text x="{x + _BOX_W - 10}" y="{y + 19}" text-anchor="end" '
                        f'font-size="9" font-weight="700" fill="#a20a29" '
                        f'letter-spacing="0.05em">NEW</text>'
                    )
                parts.append(
                    f'<text x="{x + 10}" y="{y + 35}" font-size="9.5" fill="#6e6d66">'
                    f"{escape(_shorten(node.rel_path))}</text>"
                )

    # Vertical arrows between consecutive layers, per service.
    parts.append(
        '<defs><marker id="cm-arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        '<path d="M 0 0 L 10 5 L 0 10 z" fill="#9a9992"/></marker></defs>'
    )
    for index, service in enumerate(services):
        # Consecutive *occupied* rows, not consecutive layers: policy-service
        # changes an Interface and a Data file but no Logic file, and leaving
        # its column unconnected would read as two unrelated changes.
        occupied = [row for row in range(len(layers)) if change_map.nodes_in(service, layers[row])]
        for row, next_row in zip(occupied, occupied[1:]):
            x = col_x[index] + _BOX_W // 2
            y1 = row_y[row] + row_heights[row]
            y2 = row_y[next_row]
            parts.append(
                f'<line x1="{x}" y1="{y1 + 4}" x2="{x}" y2="{y2 - 6}" stroke="#9a9992" '
                f'stroke-width="1.5" marker-end="url(#cm-arrow)"/>'
            )

    # Cross-service call, drawn between the two service columns. Direction
    # matters and is not always left-to-right: claims-service calls
    # policy-service, and an arrow drawn the other way would tell QA to test
    # the dependency backwards.
    for source, destination in change_map.crossings:
        if source not in services or destination not in services:
            continue
        source_index = services.index(source)
        destination_index = services.index(destination)
        if source_index < destination_index:
            x1 = col_x[source_index] + _BOX_W + 6
            x2 = col_x[destination_index] - 6
        else:
            x1 = col_x[source_index] - 6
            x2 = col_x[destination_index] + _BOX_W + 6
        y = row_y[0] - 12
        parts.append(
            f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="#007cbf" '
            f'stroke-width="1.5" stroke-dasharray="4 3" marker-end="url(#cm-arrow)"/>'
        )
        parts.append(
            f'<text x="{(x1 + x2) // 2}" y="{y - 5}" text-anchor="middle" font-size="9.5" '
            f'fill="#007cbf">HTTP</text>'
        )

    if change_map.downstream:
        parts.append(
            f'<line x1="{_PAD}" y1="{content_bottom + 10}" x2="{width - _PAD}" '
            f'y2="{content_bottom + 10}" stroke="#e0dfda"/>'
        )
        joined = ", ".join(change_map.downstream)
        parts.append(
            f'<text x="{_PAD}" y="{downstream_y + 12}" font-size="10" font-weight="700" '
            f'fill="#6e6d66" letter-spacing="0.06em">DOWNSTREAM</text>'
        )
        parts.append(
            f'<text x="{_PAD}" y="{downstream_y + 30}" font-size="11.5" fill="#363530">'
            f"{escape(joined)}</text>"
        )

    parts.append("</svg>")
    return "".join(parts)


def _shorten(rel_path: str, limit: int = 34) -> str:
    """Trim a path from the left — the tail identifies the file, the head is
    the part every box in the diagram shares."""
    if len(rel_path) <= limit:
        return rel_path
    return "…" + rel_path[-(limit - 1) :]


def build_svg(
    target: Target,
    *,
    changed_files: list[str] | None = None,
    downstream: list[str] | None = None,
) -> tuple[str, ChangeMap]:
    change_map = build_change_map(
        target, changed_files=changed_files, downstream=downstream
    )
    return render_svg(change_map), change_map
