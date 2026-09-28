"""Small pages for metric tests, built the way the production code builds them."""

from d2u.generation.convert import generated_to_docpage
from d2u.schemas.docpage import DocPage, Example
from d2u.schemas.generated import GeneratedOperation, GeneratedPage, GeneratedParam


def param(name: str, **fields: object) -> GeneratedParam:
    values: dict[str, object] = {
        "name": name,
        "location": "query",
        "type": "integer",
        "required": False,
    }
    return GeneratedParam.model_validate(values | fields)


def http_op(
    method: str, path: str, *params: GeneratedParam, **fields: object
) -> GeneratedOperation:
    values: dict[str, object] = {
        "kind": "http",
        "method": method,
        "path": path,
        "signature": f"{method} {path}",
        "group": "Pets",
        "summary": f"{method} {path}",
        "params": list(params),
    }
    return GeneratedOperation.model_validate(values | fields)


def page(*ops: GeneratedOperation) -> DocPage:
    built, _ = generated_to_docpage(
        GeneratedPage(title="API", overview_md="", operations=list(ops)),
        language="openapi",
        line_counts={},
    )
    return built


def example(language: str, code: str) -> Example:
    return Example(title=language, language=language, code=code)
