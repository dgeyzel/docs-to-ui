"""The `EnrichOperations` metric (SPEC §13).

| Component          | Weight                        |
| Schema validity    | hard gate: 0 if output invalid |
| Coverage           | 0.25 |
| Fidelity           | 0.25 |
| Consistency        | 0.15 (judge) |
| Example validity   | 0.15 |
| Prose quality      | 0.20 (judge) |
"""

import ast
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import dspy
import pydantic

from app.llm.schemas import BatchEnrichment, Example, Operation, OperationDocs
from app.llm.signatures import JudgeEnrichment

WEIGHTS = {
    "coverage": 0.25,
    "fidelity": 0.25,
    "consistency": 0.15,
    "examples": 0.15,
    "prose": 0.20,
}
# During bootstrapping DSPy asks for pass/fail; a demo must score at least this.
BOOTSTRAP_THRESHOLD = 0.7
_CURL_URL = re.compile(r"https?://[^/\s'\"]+(/[^\s?'\"#]*)?")


@dataclass(frozen=True, slots=True)
class JudgeVerdict:
    """Judge scores, both normalized to 0.0–1.0."""

    consistency: float
    prose: float


Judge = Callable[[list[Operation], BatchEnrichment], JudgeVerdict]


@dataclass(frozen=True, slots=True)
class EnrichScore:
    """Every component of the metric, and the weighted total."""

    valid: bool
    coverage: float
    fidelity: float
    consistency: float
    examples: float
    prose: float

    @property
    def total(self) -> float:
        if not self.valid:
            return 0.0
        return round(
            sum(
                getattr(self, component) * weight
                for component, weight in WEIGHTS.items()
            ),
            6,
        )

    def components(self) -> dict[str, float]:
        """Component scores plus the total, for reports."""
        return {component: getattr(self, component) for component in WEIGHTS} | {
            "total": self.total
        }


def parse_result(result: Any) -> BatchEnrichment | None:
    """The output as a `BatchEnrichment`, or None if it doesn't validate."""
    if isinstance(result, BatchEnrichment):
        return result
    try:
        return BatchEnrichment.model_validate(result)
    except pydantic.ValidationError:
        return None


def coverage(operations: list[Operation], docs: list[OperationDocs]) -> float:
    """Share of the batch's operation IDs that got documentation."""
    if not operations:
        return 0.0
    documented = {entry.operation_id for entry in docs}
    return sum(1 for op in operations if op.id in documented) / len(operations)


def fidelity(operations: list[Operation], docs: list[OperationDocs]) -> float:
    """Share of doc entries that reference only operations and params that exist."""
    if not docs:
        return 0.0
    params = {op.id: {param.id for param in op.params} for op in operations}
    faithful = sum(
        1
        for entry in docs
        if entry.operation_id in params
        and set(entry.param_descriptions) <= params[entry.operation_id]
    )
    return faithful / len(docs)


def _path_template(pattern: str) -> re.Pattern[str]:
    parts = [
        "[^/]+" if part.startswith("{") and part.endswith("}") else re.escape(part)
        for part in pattern.strip("/").split("/")
    ]
    return re.compile("^/?" + "/".join(parts) + "/?$")


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
    """True/False for languages that can be checked, None otherwise."""
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


def example_validity(operations: list[Operation], docs: list[OperationDocs]) -> float:
    """Share of checkable examples that are valid: JSON parses, Python parses,
    and curl URLs point at a path in the surface. No examples scores 0."""
    templates = [
        _path_template(op.signature.partition(" ")[2])
        for op in operations
        if op.kind == "http" and " " in op.signature
    ]
    results = [
        verdict
        for entry in docs
        for example in entry.examples
        if (verdict := example_is_valid(example, templates)) is not None
    ]
    if not results:
        return 0.0
    return sum(results) / len(results)


def score_enrichment(
    *, operations: list[Operation], result: Any, judge: Judge | None
) -> EnrichScore:
    """Score one batch's output. Without a judge, judged components score 0."""
    parsed = parse_result(result)
    if parsed is None:
        return EnrichScore(False, 0.0, 0.0, 0.0, 0.0, 0.0)
    verdict = judge(operations, parsed) if judge else JudgeVerdict(0.0, 0.0)
    return EnrichScore(
        valid=True,
        coverage=coverage(operations, parsed.operations),
        fidelity=fidelity(operations, parsed.operations),
        consistency=verdict.consistency,
        examples=example_validity(operations, parsed.operations),
        prose=verdict.prose,
    )


def llm_judge(lm: dspy.BaseLM) -> Judge:
    """A judge that asks `lm` to grade consistency and prose quality."""
    program = dspy.Predict(JudgeEnrichment)

    def judge(
        operations: list[Operation], documentation: BatchEnrichment
    ) -> JudgeVerdict:
        with dspy.context(lm=lm):
            prediction = program(operations=operations, documentation=documentation)
        consistency = min(1.0, max(0.0, float(prediction.consistency)))
        prose = (min(5, max(1, int(prediction.prose_quality))) - 1) / 4
        return JudgeVerdict(consistency=consistency, prose=prose)

    return judge


def make_enrich_metric(judge: Judge | None) -> Callable[..., float | bool]:
    """A DSPy metric: the total score, or pass/fail while bootstrapping."""

    def metric(
        example: dspy.Example, prediction: dspy.Prediction, trace: Any = None
    ) -> float | bool:
        score = score_enrichment(
            operations=example.operations, result=prediction.result, judge=judge
        )
        if trace is not None:
            return score.total >= BOOTSTRAP_THRESHOLD
        return score.total

    return metric
