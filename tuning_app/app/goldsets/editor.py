"""The expected-page form editor (SPEC §9.2): form data ↔ `GeneratedPage`.

The editor works on the same shape the LLM returns, so saving converts it
with the production conversion and IDs are derived in code, never typed in.
Inputs are named `title`, `op-0-summary`, `op-0-param-1-name`,
`op-0-example-2-code` and so on, with `op-count`, `op-0-param-count` and
`op-0-example-count` giving the number of rows. Structural edits (adding or
removing rows) are submit buttons named `action`, handled without saving.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pydantic
from d2u.generation.convert import base_operation_id, docpage_to_generated
from d2u.schemas.docpage import DocPage
from d2u.schemas.generated import GeneratedOperation, GeneratedPage

OPERATION_FIELDS = (
    "kind",
    "method",
    "path",
    "qualified_name",
    "signature",
    "group",
    "summary",
    "description_md",
    "returns",
    "source_path",
    "source_line",
)
PARAM_FIELDS = ("name", "location", "type", "default", "description")
EXAMPLE_FIELDS = ("title", "language", "code")
# Empty values of these mean "not set".
OPTIONAL_FIELDS = {
    "method",
    "path",
    "qualified_name",
    "returns",
    "source_path",
    "default",
}
MAX_ROWS = 500
_ACTION = re.compile(
    r"^(add_operation|remove_operation-(\d+)|add_param-(\d+)|remove_param-(\d+)-(\d+)"
    r"|add_example-(\d+)|remove_example-(\d+)-(\d+))$"
)

State = dict[str, Any]


@dataclass(slots=True)
class EditorResult:
    """A validated page, or the errors to show next to each input."""

    page: GeneratedPage | None = None
    errors: dict[str, str] = field(default_factory=dict)


def _count(data: Mapping[str, Any], name: str) -> int:
    raw = str(data.get(name, "0") or "0")
    return min(int(raw), MAX_ROWS) if raw.isdigit() else 0


def _text(data: Mapping[str, Any], name: str) -> str:
    return str(data.get(name, "") or "").replace("\r\n", "\n")


def blank_operation(language: str) -> State:
    """A new, empty operation of the language's usual kind."""
    return {
        "kind": "http" if language == "openapi" else "function",
        **{name: "" for name in OPERATION_FIELDS if name != "kind"},
        "params": [],
        "examples": [],
    }


def blank_param(language: str) -> State:
    """A new, empty parameter."""
    location = "query" if language == "openapi" else "arg"
    return {
        "name": "",
        "location": location,
        "type": "",
        "required": False,
        "default": "",
        "description": "",
    }


def blank_example() -> State:
    """A new, empty code example."""
    return {"title": "", "language": "", "code": ""}


def state_from_page(page: DocPage) -> State:
    """The editor state for a stored page, with every value as text."""
    generated = docpage_to_generated(page).model_dump(mode="json")
    for op in generated["operations"]:
        for name in OPERATION_FIELDS:
            op[name] = "" if op.get(name) is None else str(op[name])
        for param in op["params"]:
            param["default"] = param["default"] or ""
    return generated


def state_from_form(data: Mapping[str, Any]) -> State:
    """The editor state as submitted, before validation."""
    operations = []
    for i in range(_count(data, "op-count")):
        prefix = f"op-{i}-"
        op: State = {name: _text(data, prefix + name) for name in OPERATION_FIELDS}
        op["params"] = [
            {name: _text(data, f"{prefix}param-{j}-{name}") for name in PARAM_FIELDS}
            | {"required": f"{prefix}param-{j}-required" in data}
            for j in range(_count(data, prefix + "param-count"))
        ]
        op["examples"] = [
            {
                name: _text(data, f"{prefix}example-{k}-{name}")
                for name in EXAMPLE_FIELDS
            }
            for k in range(_count(data, prefix + "example-count"))
        ]
        operations.append(op)
    return {
        "title": _text(data, "title"),
        "overview_md": _text(data, "overview_md"),
        "operations": operations,
    }


def apply_action(state: State, action: str, *, language: str) -> bool:
    """Add or remove a row in place; False if the action isn't recognized."""
    match = _ACTION.match(action)
    if match is None:
        return False
    operations: list[State] = state["operations"]
    name, _, rest = action.partition("-")
    indexes = [int(part) for part in rest.split("-")] if rest else []
    try:
        if name == "add_operation":
            operations.append(blank_operation(language))
        elif name == "remove_operation":
            operations.pop(indexes[0])
        elif name == "add_param":
            operations[indexes[0]]["params"].append(blank_param(language))
        elif name == "remove_param":
            operations[indexes[0]]["params"].pop(indexes[1])
        elif name == "add_example":
            operations[indexes[0]]["examples"].append(blank_example())
        elif name == "remove_example":
            operations[indexes[0]]["examples"].pop(indexes[1])
    except IndexError:
        return False
    return True


def _clean(state: State) -> State:
    """Empty optional values become None, so the schema sees them as unset."""
    operations = []
    for op in state["operations"]:
        cleaned = {
            name: (
                None if name in OPTIONAL_FIELDS and not op[name].strip() else op[name]
            )
            for name in OPERATION_FIELDS
        }
        line = op["source_line"].strip()
        cleaned["source_line"] = (int(line) if line.isdigit() else line) or None
        cleaned["params"] = [
            {
                **param,
                "default": param["default"] if param["default"].strip() else None,
            }
            for param in op["params"]
        ]
        cleaned["examples"] = op["examples"]
        operations.append(cleaned)
    return {**state, "operations": operations}


def input_name(loc: tuple[int | str, ...]) -> str:
    """The input a validation error location belongs to."""
    if not loc or loc[0] != "operations" or len(loc) < 2:
        return str(loc[0]) if loc else ""
    name = f"op-{loc[1]}"
    rest = loc[2:]
    if len(rest) >= 3 and rest[0] in ("params", "examples"):
        row = "param" if rest[0] == "params" else "example"
        return f"{name}-{row}-{rest[1]}-{rest[2]}"
    return f"{name}-{rest[0]}" if rest else name


def _identity_errors(page: GeneratedPage) -> dict[str, str]:
    errors: dict[str, str] = {}
    seen: dict[str, int] = {}
    for i, op in enumerate(page.operations):
        if op.kind == "http" and not (op.method and op.path):
            errors[f"op-{i}-path"] = "HTTP operations need a method and a path."
            continue
        if op.kind != "http" and not op.qualified_name:
            errors[f"op-{i}-qualified_name"] = (
                "Enter the qualified name, e.g. acme.Client.get."
            )
            continue
        op_id = base_operation_id(op)
        if op_id in seen:
            errors[f"op-{i}-signature"] = (
                f"Operation {seen[op_id] + 1} already has the ID {op_id}."
            )
        seen.setdefault(op_id, i)
        names = [param.name for param in op.params]
        for j, name in enumerate(names):
            if name in names[:j]:
                errors[f"op-{i}-param-{j}-name"] = "Another parameter has this name."
    return errors


def validate(state: State) -> EditorResult:
    """Validate the state as a `GeneratedPage` whose IDs can be derived."""
    try:
        page = GeneratedPage.model_validate(_clean(state))
    except pydantic.ValidationError as exc:
        errors: dict[str, str] = {}
        for error in exc.errors():
            errors.setdefault(input_name(tuple(error["loc"])), error["msg"])
        return EditorResult(errors=errors)
    errors = _identity_errors(page)
    return EditorResult(page=None if errors else page, errors=errors)


def operation_id(op: State) -> str:
    """The ID an operation in the editor will get, for display."""
    try:
        cleaned = _clean({"operations": [op]})["operations"][0]
        return base_operation_id(GeneratedOperation.model_validate(cleaned))
    except pydantic.ValidationError:
        return ""
