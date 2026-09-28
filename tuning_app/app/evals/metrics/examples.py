"""Example validity (SPEC §9.5): do a page's code examples hold up? Plain-free.

JSON must parse, Python must `ast.parse`, and a curl command's URL path must
exist in the gold page's HTTP surface. Examples in other languages can't be
checked and are left out.
"""

import ast
import json
import re

from d2u.schemas.docpage import ApiSurface, DocPage, Example

_CURL_URL = re.compile(r"https?://[^/\s'\"]+(/[^\s?'\"#]*)?")


def path_template(pattern: str) -> re.Pattern[str]:
    """A regex matching an HTTP path pattern such as `/pets/{id}`."""
    parts = [
        "[^/]+" if part.startswith("{") and part.endswith("}") else re.escape(part)
        for part in pattern.strip("/").split("/")
    ]
    return re.compile("^/?" + "/".join(parts) + "/?$")


def surface_templates(surface: ApiSurface) -> list[re.Pattern[str]]:
    """Path templates for every HTTP operation in a surface."""
    return [
        path_template(op.signature.partition(" ")[2])
        for op in surface.operations
        if op.kind == "http" and " " in op.signature
    ]


def _curl_is_valid(code: str, templates: list[re.Pattern[str]]) -> bool:
    match = _CURL_URL.search(code)
    if match is None:
        return False
    path = match.group(1) or "/"
    # Examples often include a base path such as /v1; accept any suffix match.
    segments = path.strip("/").split("/")
    candidates = ["/" + "/".join(segments[start:]) for start in range(len(segments))]
    return any(
        template.match(candidate) for template in templates for candidate in candidates
    )


def example_is_valid(example: Example, templates: list[re.Pattern[str]]) -> bool | None:
    """True or False for languages that can be checked, None otherwise."""
    language = example.language.lower()
    if language == "json":
        try:
            json.loads(example.code)
        except json.JSONDecodeError:
            return False
        return True
    if language == "python":
        try:
            ast.parse(example.code)
        except SyntaxError:
            return False
        return True
    if language in ("curl", "shell", "bash") and "curl" in example.code:
        return _curl_is_valid(example.code, templates)
    return None


def example_validity(output: DocPage, gold: DocPage) -> tuple[float, int]:
    """The share of checkable examples that are valid, and how many were checked.

    No checkable examples scores 0: a page without usable examples earns
    nothing for them.
    """
    templates = surface_templates(gold.surface)
    results = [
        verdict
        for entry in output.operations
        for example in entry.examples
        if (verdict := example_is_valid(example, templates)) is not None
    ]
    if not results:
        return 0.0, 0
    return sum(results) / len(results), len(results)
