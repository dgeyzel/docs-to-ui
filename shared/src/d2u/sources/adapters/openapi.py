"""OpenAPI 3.0 / 3.1 adapter (JSON or YAML), single file or multi-file.

Structure is extracted deterministically from the documents. `$ref`s resolve
within the bundle only: internal pointers and relative file paths are
followed; remote refs and refs escaping the bundle root are rejected, and
nothing is ever fetched from the network.
"""

import json
import logging
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

import yaml

from d2u.schemas.docpage import (
    ApiSurface,
    Operation,
    Param,
    ParamLocation,
    SourceLocation,
)
from d2u.sources.bundle import SourceBundle, SourceFile
from d2u.sources.exceptions import InputError

logger = logging.getLogger(__name__)

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
PARAMETER_LOCATIONS = ("path", "query", "header", "cookie")
MAX_REF_HOPS = 32
MAX_SCHEMA_DEPTH = 6
MAX_DEFAULT_CHARS = 200

_YAML_ENTRY_KEY = re.compile(r"^openapi\s*:", re.MULTILINE)
_JSON_ENTRY_KEY = re.compile(r'"openapi"\s*:')
# libyaml is much faster on large documents; fall back to the pure-Python loader.
_Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
# A JSON escape for a character outside the BMP: a UTF-16 surrogate pair, as
# json.dumps writes emoji. An escaped backslash (\\) is matched first so that
# `\\ud83d` stays literal text.
_JSON_SURROGATE_PAIR = re.compile(
    r"\\\\|\\u(d[89ab][0-9a-f]{2})\\u(d[c-f][0-9a-f]{2})", re.IGNORECASE
)
_JSON_HIGH_SURROGATE = re.compile(r"\\ud[89ab]", re.IGNORECASE)

Keys = tuple[str | int, ...]


class OpenApiAdapter:
    """Adapter for OpenAPI 3.0 and 3.1 documents."""

    name: str = "openapi"
    display_name: str = "OpenAPI"
    file_extensions: tuple[str, ...] = (".yaml", ".yml", ".json")
    default_excludes: tuple[str, ...] = ()
    example_languages: tuple[str, ...] = ("curl", "python", "json")

    def includes(self, path: str) -> bool:
        """Whether the path has a JSON or YAML extension."""
        return path.lower().endswith(self.file_extensions)

    def sniff(self, bundle: SourceBundle) -> float:
        """Return 1.0 when a file declares a top-level `openapi` key."""
        files = self._included(bundle)
        if any(_looks_like_entry(file) for file in files):
            return 1.0
        return 0.1 if files else 0.0

    def extract(self, bundle: SourceBundle) -> ApiSurface:
        """Parse the entry document and list its operations.

        Raises:
            InputError: The document is missing, ambiguous or invalid.
        """
        entry = self._entry_source(bundle)
        workspace = _Workspace(self._included(bundle))
        return _extract_surface(workspace.document(entry.path))

    def group_key(self, op: Operation) -> str:
        """Group by the operation's first tag, or its first path segment."""
        return op.group_hint

    def _included(self, bundle: SourceBundle) -> list[SourceFile]:
        return [file for file in bundle.files if self.includes(file.path)]

    def check_syntax(self, bundle: SourceBundle) -> None:
        """Parse the entry document and check it declares OpenAPI 3.0 or 3.1.

        Raises:
            InputError: No entry document, a syntax error, or a bad version.
        """
        entry = self._entry_source(bundle)
        document = _Workspace(self._included(bundle)).document(entry.path)
        if not isinstance(document.data, dict):
            raise InputError(
                path=entry.path, line=1, message="The document must be a mapping."
            )
        _check_version(document)

    def entry_file(self, bundle: SourceBundle) -> str | None:
        """The OpenAPI document to document: the chosen one, or the only candidate.

        Raises:
            InputError: No OpenAPI file, or several candidates and none chosen.
        """
        return self._entry_source(bundle).path

    def _entry_source(self, bundle: SourceBundle) -> SourceFile:
        files = self._included(bundle)
        if not files:
            raise InputError(
                path="",
                line=None,
                message="No OpenAPI file (.yaml, .yml or .json) was found.",
            )
        if bundle.entry:
            chosen = next((file for file in files if file.path == bundle.entry), None)
            if chosen is None:
                raise InputError(
                    path=bundle.entry,
                    line=None,
                    message="The chosen entry file is not an OpenAPI file in the input.",
                )
            return chosen
        candidates = [file for file in files if _looks_like_entry(file)]
        if len(candidates) > 1:
            names = ", ".join(file.path for file in candidates)
            raise InputError(
                path="",
                line=None,
                message=(
                    f"Several files look like OpenAPI entry files: {names}. "
                    "Choose one in the Entry file field."
                ),
            )
        if candidates:
            return candidates[0]
        if len(files) == 1:
            # Parse it anyway so the user gets a precise error.
            return files[0]
        raise InputError(
            path="",
            line=None,
            message="No file declares a top-level `openapi` version.",
        )


def _looks_like_entry(file: SourceFile) -> bool:
    # JSON is valid YAML, so either syntax may appear under either extension.
    return bool(_YAML_ENTRY_KEY.search(file.text) or _JSON_ENTRY_KEY.search(file.text))


class _Workspace:
    """Every JSON/YAML file in the bundle, parsed on first use."""

    def __init__(self, files: list[SourceFile]) -> None:
        self._files = {file.path: file for file in files}
        self._documents: dict[str, _Document] = {}

    def has(self, path: str) -> bool:
        return path in self._files

    def document(self, path: str) -> _Document:
        if path not in self._documents:
            document = _parse(self._files[path], self)
            _check_refs(document)
            self._documents[path] = document
        return self._documents[path]


@dataclass(frozen=True, slots=True)
class _Document:
    path: str
    data: Any
    root: yaml.Node
    workspace: _Workspace

    def line(self, keys: Keys) -> int | None:
        """Best-effort 1-based line of the node at `keys` (or its nearest ancestor)."""
        node = self.root
        line = node.start_mark.line + 1
        for key in keys:
            if isinstance(node, yaml.MappingNode):
                match = _mapping_child(node, str(key))
                if match is None:
                    return line
                key_node, node = match
                line = key_node.start_mark.line + 1
            elif isinstance(node, yaml.SequenceNode) and isinstance(key, int):
                if key >= len(node.value):
                    return line
                node = node.value[key]
                line = node.start_mark.line + 1
            else:
                return line
        return line

    def error(self, keys: Keys, message: str) -> InputError:
        return InputError(path=self.path, line=self.line(keys), message=message)

    def resolve(self, value: Any, keys: Keys) -> tuple[Any, Keys, _Document]:
        """Follow `$ref`s until a non-reference value is reached.

        Returns the value, its keys and the document it lives in, which
        differs from `self` when a ref points into another bundle file.
        """
        document: _Document = self
        for _ in range(MAX_REF_HOPS):
            if not isinstance(value, dict) or "$ref" not in value:
                return value, keys, document
            ref = value["$ref"]
            ref_keys = (*keys, "$ref")
            if not isinstance(ref, str):
                raise document.error(ref_keys, "$ref must be a string.")
            target, pointer = document.ref_target(ref, ref_keys)
            keys = _pointer_keys(pointer)
            value = target.lookup(keys, ref_keys=ref_keys, ref=ref, referrer=document)
            document = target
        raise document.error(keys, "Too many nested $refs (is there a cycle?).")

    def ref_target(self, ref: str, ref_keys: Keys) -> tuple[_Document, str]:
        """The document a ref points into, and the JSON pointer within it."""
        file_part, _, pointer = ref.partition("#")
        if not file_part:
            return self, pointer
        problem = _ref_problem(ref)
        if problem:
            raise self.error(ref_keys, problem)
        target_path = _join_ref_path(self.path, file_part)
        if target_path is None:
            raise self.error(ref_keys, f"$ref {ref!r} points outside the input.")
        if not self.workspace.has(target_path):
            raise self.error(
                ref_keys, f"$ref target {file_part!r} was not found in the input."
            )
        return self.workspace.document(target_path), pointer

    def lookup(
        self, keys: Keys, *, ref_keys: Keys, ref: str, referrer: _Document
    ) -> Any:
        current: Any = self.data
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            elif isinstance(current, list) and isinstance(key, str) and key.isdigit():
                index = int(key)
                if index >= len(current):
                    raise referrer.error(ref_keys, f"$ref {ref!r} does not resolve.")
                current = current[index]
            else:
                raise referrer.error(ref_keys, f"$ref {ref!r} does not resolve.")
        return current


def _mapping_child(
    node: yaml.MappingNode, key: str
) -> tuple[yaml.Node, yaml.Node] | None:
    for key_node, value_node in node.value:
        if isinstance(key_node, yaml.ScalarNode) and key_node.value == key:
            return key_node, value_node
    return None


def _unescape_pointer(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def _pointer_keys(pointer: str) -> Keys:
    if pointer in ("", "/"):
        return ()
    return tuple(_unescape_pointer(token) for token in pointer.lstrip("/").split("/"))


_URL_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def _ref_problem(ref: str) -> str | None:
    """Why a ref may not be followed, or None if it's fine."""
    file_part = ref.partition("#")[0]
    if not file_part:
        return None
    if file_part.startswith("//") or _URL_SCHEME.match(file_part):
        return f"Remote $refs are not supported: {ref!r}."
    if file_part.startswith("/"):
        return f"$refs must be relative paths: {ref!r}."
    return None


def _join_ref_path(base: str, relative: str) -> str | None:
    """Resolve a relative ref path against the referring file; None if it escapes."""
    parts: list[str] = list(PurePosixPath(base).parent.parts)
    for part in relative.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(part)
    return "/".join(parts)


def _decode_surrogate_pair(match: re.Match[str]) -> str:
    if match[1] is None:
        return match[0]
    high, low = int(match[1], 16), int(match[2], 16)
    return chr(0x10000 + ((high - 0xD800) << 10) + (low - 0xDC00))


def _yaml_readable_text(file: SourceFile) -> str:
    """The file's text, with JSON surrogate-pair escapes decoded.

    JSON is read as YAML, but PyYAML rejects the surrogate pairs JSON uses
    for characters such as emoji. Valid JSON has no comments or single-quoted
    strings, so every pair is an escape inside a string and decoding it is
    exact. Lines don't move, so error lines still match the file.

    Raises:
        InputError: The text is meant as JSON but isn't valid; YAML would
            only report the first escape, not the real problem.
    """
    text = file.text
    if _JSON_HIGH_SURROGATE.search(text) is None:
        return text
    try:
        json.loads(text)
    except ValueError as exc:
        if isinstance(exc, json.JSONDecodeError) and text.lstrip().startswith(
            ("{", "[")
        ):
            raise InputError(
                path=file.path, line=exc.lineno, message=f"Invalid JSON: {exc.msg}."
            ) from exc
        return text
    return _JSON_SURROGATE_PAIR.sub(_decode_surrogate_pair, text)


def _parse(file: SourceFile, workspace: _Workspace) -> _Document:
    loader = _Loader(_yaml_readable_text(file))
    try:
        root = loader.get_single_node()
        if root is None:
            raise InputError(path=file.path, line=None, message="The file is empty.")
        data = loader.construct_document(root)
    except yaml.MarkedYAMLError as exc:
        mark = exc.problem_mark or exc.context_mark
        line = mark.line + 1 if mark is not None else None
        problem = exc.problem or "syntax error"
        raise InputError(
            path=file.path, line=line, message=f"Invalid YAML/JSON: {problem}."
        ) from exc
    except yaml.YAMLError as exc:
        raise InputError(
            path=file.path, line=None, message="Invalid YAML/JSON."
        ) from exc
    except RecursionError as exc:
        raise InputError(
            path=file.path, line=None, message="The document is nested too deeply."
        ) from exc
    finally:
        loader.dispose()

    return _Document(path=file.path, data=data, root=root, workspace=workspace)


def _extract_surface(doc: _Document) -> ApiSurface:
    if not isinstance(doc.data, dict):
        raise InputError(
            path=doc.path, line=1, message="The document must be a mapping."
        )
    _check_version(doc)

    info = doc.data.get("info")
    title = info.get("title") if isinstance(info, dict) else None
    if not isinstance(title, str) or not title.strip():
        title = doc.path

    paths = doc.data.get("paths", {})
    if paths is None:
        paths = {}
    if not isinstance(paths, dict):
        raise doc.error(("paths",), "`paths` must be a mapping.")

    operations: list[Operation] = []
    for raw_path, raw_item in paths.items():
        path = str(raw_path)
        item, item_keys, item_doc = doc.resolve(raw_item, ("paths", raw_path))
        if not isinstance(item, dict):
            raise item_doc.error(item_keys, f"Path item {path!r} must be a mapping.")
        for method in HTTP_METHODS:
            if method in item:
                operations.append(
                    _operation(
                        item_doc,
                        path=path,
                        method=method,
                        item=item,
                        item_keys=item_keys,
                    )
                )

    if not operations:
        raise InputError(
            path=doc.path, line=None, message="The document defines no operations."
        )
    return ApiSurface(title=title.strip(), language="openapi", operations=operations)


def _check_version(doc: _Document) -> None:
    if "swagger" in doc.data and "openapi" not in doc.data:
        raise doc.error(
            ("swagger",),
            "Swagger 2.0 is not supported; convert the document to OpenAPI 3.",
        )
    version = doc.data.get("openapi")
    if version is None:
        raise InputError(
            path=doc.path,
            line=1,
            message="Missing top-level `openapi` version (3.0 or 3.1).",
        )
    if not isinstance(version, str) or not re.match(r"3\.[01](\.|$)", version):
        raise doc.error(
            ("openapi",),
            f"Unsupported OpenAPI version {version!r}; expected 3.0 or 3.1.",
        )


def _check_refs(doc: _Document) -> None:
    # Iterative walk with an identity set: YAML aliases can share (or nest)
    # objects, and revisiting them could take exponential time.
    seen: set[int] = set()
    stack: list[tuple[Any, Keys]] = [(doc.data, ())]
    while stack:
        value, keys = stack.pop()
        if id(value) in seen:
            continue
        if isinstance(value, dict):
            seen.add(id(value))
            ref = value.get("$ref")
            problem = _ref_problem(ref) if isinstance(ref, str) else None
            if problem:
                raise doc.error((*keys, "$ref"), problem)
            stack.extend((child, (*keys, str(key))) for key, child in value.items())
        elif isinstance(value, list):
            seen.add(id(value))
            stack.extend((child, (*keys, index)) for index, child in enumerate(value))


def _operation(
    doc: _Document, *, path: str, method: str, item: dict[str, Any], item_keys: Keys
) -> Operation:
    op_keys = (*item_keys, method)
    raw = item[method]
    if not isinstance(raw, dict):
        raise doc.error(
            op_keys, f"Operation {method.upper()} {path} must be a mapping."
        )

    op_id = f"{method.upper()} {path}"
    params = _parameters(
        doc, op_id=op_id, item=item, item_keys=item_keys, raw=raw, op_keys=op_keys
    )
    body = _request_body(doc, op_id=op_id, raw=raw, op_keys=op_keys)
    if body is not None:
        params.append(body)

    return Operation(
        id=op_id,
        kind="http",
        signature=op_id,
        group_hint=_group_hint(path=path, tags=raw.get("tags")),
        params=params,
        returns=_returns(doc, raw=raw, op_keys=op_keys),
        source_description=_join_text(raw.get("summary"), raw.get("description")),
        location=SourceLocation(path=doc.path, line=doc.line(op_keys) or 1),
    )


def _parameters(
    doc: _Document,
    *,
    op_id: str,
    item: dict[str, Any],
    item_keys: Keys,
    raw: dict[str, Any],
    op_keys: Keys,
) -> list[Param]:
    # Operation-level parameters override path-level ones with the same name and location.
    merged: dict[tuple[str, str], tuple[dict[str, Any], Keys]] = {}
    for container, keys in ((item, item_keys), (raw, op_keys)):
        entries = container.get("parameters", [])
        if entries is None:
            continue
        if not isinstance(entries, list):
            raise doc.error((*keys, "parameters"), "`parameters` must be a list.")
        for index, entry in enumerate(entries):
            param, param_keys, param_doc = doc.resolve(
                entry, (*keys, "parameters", index)
            )
            if (
                not isinstance(param, dict)
                or not isinstance(param.get("name"), str)
                or param.get("in") not in PARAMETER_LOCATIONS
            ):
                raise param_doc.error(
                    param_keys,
                    "Each parameter needs a string `name` and an `in` of "
                    "path, query, header or cookie.",
                )
            merged[(param["name"], param["in"])] = (param, param_keys)

    params: list[Param] = []
    used_ids: set[str] = set()
    for (name, location), (param, _) in merged.items():
        if location == "cookie":
            # The DocPage schema has no cookie location; cookie auth is
            # documented through security schemes, not parameters.
            logger.debug("Skipping cookie parameter %s on %s", name, op_id)
            continue
        param_id = f"{op_id}#{name}"
        if param_id in used_ids:
            param_id = f"{op_id}#{location}.{name}"
        used_ids.add(param_id)
        schema = param.get("schema")
        if schema is None:
            schema = _content_schema(param.get("content"))
        params.append(
            Param(
                id=param_id,
                name=name,
                location=_param_location(location),
                type=_schema_type(doc, schema),
                required=location == "path" or param.get("required") is True,
                default=_default_text(schema),
                source_description=_join_text(param.get("description")),
            )
        )
    return params


def _param_location(location: str) -> ParamLocation:
    if location == "path":
        return "path"
    if location == "query":
        return "query"
    return "header"


def _request_body(
    doc: _Document, *, op_id: str, raw: dict[str, Any], op_keys: Keys
) -> Param | None:
    if raw.get("requestBody") is None:
        return None
    body, body_keys, body_doc = doc.resolve(
        raw["requestBody"], (*op_keys, "requestBody")
    )
    if not isinstance(body, dict):
        raise body_doc.error(body_keys, "`requestBody` must be a mapping.")
    schema = _content_schema(body.get("content"))
    return Param(
        id=f"{op_id}#body",
        name="body",
        location="body",
        type=_schema_type(doc, schema),
        required=body.get("required") is True,
        source_description=_join_text(body.get("description")),
    )


def _returns(doc: _Document, *, raw: dict[str, Any], op_keys: Keys) -> str | None:
    responses = raw.get("responses")
    if not isinstance(responses, dict) or not responses:
        return None
    by_code = {str(code): code for code in responses}
    success = sorted(code for code in by_code if code.startswith("2"))
    code = success[0] if success else ("default" if "default" in by_code else None)
    if code is None:
        return None
    response, _, _ = doc.resolve(
        responses[by_code[code]], (*op_keys, "responses", by_code[code])
    )
    if not isinstance(response, dict):
        return code
    schema = _content_schema(response.get("content"))
    if schema is not None:
        return f"{code} {_schema_type(doc, schema)}"
    description = _join_text(response.get("description"))
    return f"{code} {description}" if description else code


def _content_schema(content: Any) -> Any:
    if not isinstance(content, dict) or not content:
        return None
    media = content.get("application/json")
    if media is None:
        media = next(iter(content.values()))
    return media.get("schema") if isinstance(media, dict) else None


def _schema_type(doc: _Document, schema: Any, depth: int = 0) -> str:
    if depth > MAX_SCHEMA_DEPTH or not isinstance(schema, dict):
        return "any"
    ref = schema.get("$ref")
    if isinstance(ref, str):
        return _ref_name(ref)
    for combinator, separator in (("oneOf", " | "), ("anyOf", " | "), ("allOf", " & ")):
        options = schema.get(combinator)
        if isinstance(options, list) and options:
            names = [_schema_type(doc, option, depth + 1) for option in options]
            return separator.join(dict.fromkeys(names))

    nullable = schema.get("nullable") is True
    declared = schema.get("type")
    if isinstance(declared, list):
        names = [name for name in declared if isinstance(name, str)]
        nullable = nullable or "null" in names
        parts = [
            _single_type(doc, schema, name, depth) for name in names if name != "null"
        ]
    elif isinstance(declared, str):
        parts = [_single_type(doc, schema, declared, depth)]
    elif "enum" in schema:
        parts = ["enum"]
    elif "properties" in schema:
        parts = ["object"]
    else:
        parts = ["any"]
    if not parts:
        parts = ["null"]
        nullable = False
    text = " | ".join(parts)
    return f"{text} | null" if nullable else text


def _ref_name(ref: str) -> str:
    """A readable type name: the pointer's last segment, or the file's stem."""
    file_part, _, pointer = ref.partition("#")
    if pointer.strip("/"):
        return _unescape_pointer(pointer.rstrip("/").rsplit("/", 1)[-1])
    return PurePosixPath(file_part).stem or ref


def _single_type(doc: _Document, schema: dict[str, Any], name: str, depth: int) -> str:
    if name == "array":
        return f"array[{_schema_type(doc, schema.get('items'), depth + 1)}]"
    fmt = schema.get("format")
    if isinstance(fmt, str) and fmt:
        return f"{name}({fmt})"
    return name


def _default_text(schema: Any) -> str | None:
    if not isinstance(schema, dict) or "default" not in schema:
        return None
    text = json.dumps(schema["default"], ensure_ascii=False, default=str)
    if len(text) > MAX_DEFAULT_CHARS:
        return text[: MAX_DEFAULT_CHARS - 1] + "…"
    return text


def _group_hint(*, path: str, tags: Any) -> str:
    if isinstance(tags, list) and tags and isinstance(tags[0], str) and tags[0]:
        return tags[0]
    segments = [s for s in path.split("/") if s and not s.startswith("{")]
    return segments[0] if segments else "default"


def _join_text(*values: Any) -> str | None:
    parts = [
        value.strip() for value in values if isinstance(value, str) and value.strip()
    ]
    return "\n\n".join(parts) if parts else None
