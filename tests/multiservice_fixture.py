"""A synthetic two-service Target, for the tests that need one.

Not a test module (no `test_` prefix, so pytest does not collect it) and not
registered in `s3_enhancement.targets` — nothing resolves it by id, and it
never reaches the console.

**Why it exists.** `diagram.build_change_map` and
`release.build_deployment_plan` both do real work when a change spans two
deployable services: splitting files into services, inferring the cross-service
call from a `*_client.py`, and ordering the deploy callee-before-caller so the
caller never spends a window reading a field the callee has not shipped. That
is the part of those modules most worth testing, because getting it backwards
produces a plan that looks reasonable and is wrong.

Until 2026-08-04 those tests ran against the ClaimsPortal target, which was one
target root holding two services. ClaimsPortal was removed from the demo, and
with it the only real multi-service target. Deleting the tests along with it
would have quietly dropped coverage of a feature the code still implements and
that the next multi-service target will depend on — so the fixture became
synthetic instead.

It needs nothing on disk. `build_change_map` reads `codegen_allowlist` (plain
strings) and uses `root` only to split those strings into services, so the
paths below describe a repository that does not have to exist.
"""

from __future__ import annotations

from pathlib import Path

from s3_enhancement.targets import REPO_ROOT, Target

_ROOT = REPO_ROOT / "repos" / "twoservice"
_ORDERS = "repos/twoservice/orders_service"
_LEDGER = "repos/twoservice/ledger_service"

# orders_service calls ledger_service through `ledger_client.py`. That filename
# is not decoration: `diagram.build_change_map` infers the cross-service edge
# from the `*_client.py` suffix, and with exactly two services in the change
# there is one unambiguous candidate for the other end. Rename it and the
# crossing disappears, which is what the direction tests are asserting.
TWO_SERVICE = Target(
    target_id="twoservice-synthetic-fixture",
    source_kind="local",
    display_name="TwoService — synthetic multi-service fixture",
    root=_ROOT,
    core_files=(
        f"{_LEDGER}/ledger.py",
        f"{_LEDGER}/main.py",
        f"{_ORDERS}/order.py",
        f"{_ORDERS}/ledger_client.py",
        f"{_ORDERS}/main.py",
    ),
    codegen_allowlist=(
        f"{_LEDGER}/ledger.py",
        f"{_LEDGER}/main.py",
        f"{_ORDERS}/order.py",
        f"{_ORDERS}/ledger_client.py",
        f"{_ORDERS}/main.py",
        f"{_ORDERS}/order_rules.py",
    ),
    testgen_allowlist=("tests/test_s3_twoservice.py",),
    # Deliberately no `post_apply_command`: one of the plan tests asserts that a
    # target without a migration step gets no migrate step invented for it.
    regression_paths=("tests/test_regression_twoservice.py",),
    cache_namespace="twoservice_synthetic_fixture",
)
