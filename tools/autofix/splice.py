"""Generic AST-located read/write for a registered FixTarget.

Locates exactly one plain-string `ast.Constant` — either a module-level `NAME = "..."`
assignment, or one field of one tuple inside a module-level list literal — by its
source coordinates, and replaces only that span. Cannot touch control flow, imports,
function bodies, or anything not shaped exactly like its registry entry says: any
drift (renamed variable, reordered list, a field that's no longer a plain string)
raises `SpliceError` instead of silently editing the wrong thing.
"""

from __future__ import annotations

import ast

from tools.autofix.targets import FixTarget


class SpliceError(Exception):
    pass


def _find_module_constant(tree: ast.Module, name: str) -> ast.Constant:
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == name:
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                return node.value
            raise SpliceError(f"{name!r} is not a plain string-literal assignment")
    raise SpliceError(f"module-level constant {name!r} not found")


def _find_tuple_field(
    tree: ast.Module, list_name: str, tuple_index: int, field_index: int
) -> ast.Constant:
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not (isinstance(target, ast.Name) and target.id == list_name):
            continue
        if not isinstance(node.value, ast.List):
            raise SpliceError(f"{list_name!r} is not a list literal")
        elements = node.value.elts
        if tuple_index >= len(elements):
            raise SpliceError(
                f"{list_name}[{tuple_index}] out of range ({len(elements)} entries)"
            )
        tup = elements[tuple_index]
        if not isinstance(tup, ast.Tuple):
            raise SpliceError(f"{list_name}[{tuple_index}] is not a tuple literal")
        if field_index >= len(tup.elts):
            raise SpliceError(f"{list_name}[{tuple_index}][{field_index}] out of range")
        field = tup.elts[field_index]
        if not isinstance(field, ast.Constant) or not isinstance(field.value, str):
            raise SpliceError(
                f"{list_name}[{tuple_index}][{field_index}] is not a plain string literal"
            )
        return field
    raise SpliceError(f"list {list_name!r} not found")


def _locate(target: FixTarget) -> tuple[str, ast.Constant]:
    source = target.file.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(target.file))
    if target.kind == "module_constant":
        assert target.constant_name is not None
        node = _find_module_constant(tree, target.constant_name)
    elif target.kind == "tuple_field":
        assert target.list_name is not None
        assert target.tuple_index is not None
        assert target.field_index is not None
        node = _find_tuple_field(tree, target.list_name, target.tuple_index, target.field_index)
    else:
        raise SpliceError(f"unknown target kind {target.kind!r}")
    return source, node


def _char_offset(lines: list[str], lineno: int, col_offset: int) -> int:
    return sum(len(line) for line in lines[: lineno - 1]) + col_offset


def read_target(target: FixTarget) -> str:
    _source, node = _locate(target)
    value = node.value
    assert isinstance(value, str)
    return value


def write_target(target: FixTarget, new_value: str) -> None:
    """Replace `target`'s string literal with `new_value`, validating the result
    parses as Python before ever writing it to disk."""
    source, node = _locate(target)
    lines = source.splitlines(keepends=True)
    start = _char_offset(lines, node.lineno, node.col_offset)
    end = _char_offset(lines, node.end_lineno, node.end_col_offset)

    replacement = repr(new_value)
    new_source = source[:start] + replacement + source[end:]

    ast.parse(new_source, filename=str(target.file))  # validate before writing
    target.file.write_text(new_source, encoding="utf-8")
