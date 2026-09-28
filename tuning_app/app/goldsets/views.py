from typing import Any

from d2u.generation.convert import generated_to_docpage
from d2u.generations.models import Generation, GenerationStatus
from d2u.schemas.gold import GOLD_SPLITS
from d2u.sources.exceptions import InputError
from plain.forms import BaseForm, ValidationError
from plain.http import NotFoundError404, RedirectResponse, Response
from plain.postgres.aggregates import Count
from plain.postgres.expressions import Q
from plain.templates import Template
from plain.templates.views import FormView, TemplateView
from plain.urls import reverse
from plain.views import View

from app.goldsets import editor
from app.goldsets.exceptions import GoldSetError
from app.goldsets.forms import (
    BulkSplitForm,
    ExampleCreateForm,
    FillForm,
    GoldSetForm,
    GoldSetImportForm,
    ReviewForm,
    generation_model_choices,
    language_choices,
)
from app.goldsets.models import (
    ExampleStatus,
    GoldExample,
    GoldExampleRevision,
    GoldSet,
)
from app.goldsets.services import (
    assign_split,
    content_hash,
    create_example,
    describe_input_error,
    empty_page,
    import_generation,
    import_gold_set,
    line_counts,
    parser_page,
    save_expected,
    save_review,
    set_status,
    start_model_seed,
)
from app.goldsets.starter import load_starter_sets

RECENT_GENERATIONS_LIMIT = 20
HISTORY_LIMIT = 50
MESSAGES = {
    "saved": "Expected page saved.",
    "review": "Review details saved.",
    "approved": "Example approved.",
    "draft": "Example returned to draft.",
    "filled": "Expected page replaced from the parser.",
    "seeding": "A model is filling in the expected page.",
    "created": "Example created.",
    "moved": "Split updated.",
}
EDITOR_KINDS = ("http", "function", "class", "method")
EDITOR_LOCATIONS = ("path", "query", "header", "body", "arg", "kwarg")


def _error_text(exc: GoldSetError | InputError) -> str:
    return describe_input_error(exc) if isinstance(exc, InputError) else str(exc)


def _form_errors(form: BaseForm) -> list[str]:
    return [str(error) for errors in form.errors.values() for error in errors]


def _get_set(url_kwargs: dict[str, Any]) -> GoldSet:
    gold_set = GoldSet.query.get_or_none(int(url_kwargs["id"]))
    if gold_set is None:
        raise NotFoundError404()
    return gold_set


def _get_example(url_kwargs: dict[str, Any]) -> GoldExample:
    example = GoldExample.query.get_or_none(
        id=int(url_kwargs["example_id"]), gold_set__id=int(url_kwargs["id"])
    )
    if example is None:
        raise NotFoundError404()
    return example


def _redirect(url: str, message: str = "") -> RedirectResponse:
    return RedirectResponse(
        f"{url}?message={message}" if message else url, status_code=302
    )


def _set_url(gold_set: GoldSet) -> str:
    return reverse("goldsets:detail", id=gold_set.id)


def _example_url(example: GoldExample) -> str:
    return reverse("goldsets:example", id=example.gold_set.id, example_id=example.id)


def _message(view: View) -> str:
    return MESSAGES.get(view.request.query_params.get("message", ""), "")


class GoldSetListView(TemplateView):
    """Gold sets, with forms to create, import and load starter sets."""

    template_name = "goldsets/list.html"

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        context["gold_sets"] = list(
            GoldSet.query.annotate(
                total=Count("examples"),
                approved=Count(
                    "examples", filter=Q(examples__status=ExampleStatus.APPROVED.value)
                ),
            ).order_by("name")
        )
        # Only the submitted form's values and errors are shown again, so the
        # other forms are plain inputs rather than bound (and invalid) forms.
        context["create_values"] = {"name": "", "language": ""}
        context["create_errors"] = []
        context["import_errors"] = []
        context["languages"] = language_choices()
        return context

    def post(self) -> Response:
        action = self.request.form_data.get("form", "")
        if action == "starter":
            load_starter_sets([name for name, _ in language_choices()])
            return _redirect(reverse("goldsets:list"))
        if action == "import":
            return self._import()
        form = GoldSetForm(request=self.request)
        if not form.is_valid():
            return self.render(
                create_values={
                    "name": form["name"].value() or "",
                    "language": form["language"].value() or "",
                },
                create_errors=_form_errors(form),
                status_code=422,
            )
        gold_set = GoldSet(
            name=form.cleaned_data["name"], language=form.cleaned_data["language"]
        )
        gold_set.create()
        return _redirect(_set_url(gold_set))

    def _import(self) -> Response:
        form = GoldSetImportForm(request=self.request)
        if form.is_valid():
            try:
                gold_set = import_gold_set(form.cleaned_data["file"])
            except GoldSetError as exc:
                form.add_error("file", ValidationError(str(exc)))
            else:
                return _redirect(_set_url(gold_set))
        return self.render(import_errors=_form_errors(form), status_code=422)


class GoldSetDetailView(TemplateView):
    """A set's examples, bulk split assignment and generation import."""

    template_name = "goldsets/detail.html"

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        gold_set = _get_set(self.url_kwargs)
        examples = list(GoldExample.query.filter(gold_set=gold_set).order_by("id"))
        context["gold_set"] = gold_set
        context["examples"] = examples
        context["operation_counts"] = {
            example.id: len(example.expected_page().surface.operations)
            for example in examples
        }
        context["approved_by_split"] = {
            split: sum(
                1
                for example in examples
                if example.split == split and example.status == ExampleStatus.APPROVED
            )
            for split in ("train", "dev", "test")
        }
        context["content_hash"] = content_hash(gold_set)
        context["generations"] = list(
            Generation.query.filter(
                status=GenerationStatus.SUCCEEDED.value, language=gold_set.language
            ).order_by("-created_at")[:RECENT_GENERATIONS_LIMIT]
        )
        context["imported"] = {example.source for example in examples}
        context["message"] = _message(self)
        context["error"] = ""
        return context

    def post(self) -> Response:
        gold_set = _get_set(self.url_kwargs)
        if self.request.form_data.get("form", "") == "import_generation":
            return self._import_generation(gold_set)
        ids = list(
            GoldExample.query.filter(gold_set=gold_set).values_list("id", flat=True)
        )
        form = BulkSplitForm(request=self.request, example_ids=ids)
        if not form.is_valid():
            return self.render(
                error="Select at least one example and a split.", status_code=422
            )
        assign_split(gold_set, form.selected_ids(), form.cleaned_data["split"])
        return _redirect(_set_url(gold_set), "moved")

    def _import_generation(self, gold_set: GoldSet) -> Response:
        raw_id = str(self.request.form_data.get("generation", ""))
        generation = (
            Generation.query.get_or_none(int(raw_id)) if raw_id.isdigit() else None
        )
        if generation is None:
            return self.render(error="Choose a generation to import.", status_code=422)
        try:
            example = import_generation(gold_set, generation)
        except (GoldSetError, InputError) as exc:
            return self.render(error=_error_text(exc), status_code=422)
        return _redirect(_example_url(example), "created")


class ExampleCreateView(FormView[ExampleCreateForm]):
    """Paste or upload source, then choose how to fill the expected page."""

    template_name = "goldsets/example_new.html"
    form_class = ExampleCreateForm

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["gold_set"] = _get_set(self.url_kwargs)
        kwargs["initial"] = {"fill": "parser"}
        return kwargs

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        context["gold_set"] = context["form"].gold_set
        context["models"] = generation_model_choices()
        return context

    def form_valid(self, form: ExampleCreateForm) -> Response:
        gold_set = form.gold_set
        gold_input = form.gold_input()
        fill = form.cleaned_data["fill"]
        expected = empty_page(gold_set.language, gold_input)
        source, change = "manual", "Created"
        if fill == "parser":
            try:
                expected = parser_page(gold_set.language, gold_input)
            except InputError as exc:
                form.add_error(None, ValidationError(describe_input_error(exc)))
                return self.render(form=form, status_code=422)
            source, change = "parser_seed", "Seeded from the parser"
        example = create_example(
            gold_set,
            gold_input=gold_input,
            expected=expected,
            source=source,
            notes=form.cleaned_data["notes"] or "",
            change=change,
        )
        model = form.chosen_model()
        if fill == "model" and model is not None:
            start_model_seed(example, model)
            return _redirect(_example_url(example), "seeding")
        return _redirect(_example_url(example), "created")


class ExampleDetailView(TemplateView):
    """Review an example and edit its expected page.

    One page, several forms, told apart by a hidden `form` input: the
    editor, the review details, approval and filling the page again.
    """

    template_name = "goldsets/example.html"

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        example = _get_example(self.url_kwargs)
        gold_input = example.gold_input()
        context["example"] = example
        context["gold_set"] = example.gold_set
        context["files"] = sorted(gold_input.files.items())
        context["entry"] = gold_input.entry
        context["state"] = editor.state_from_page(example.expected_page())
        context["errors"] = {}
        context["review_error"] = ""
        context["history"] = list(
            GoldExampleRevision.query.filter(example=example).order_by("-created_at")[
                :HISTORY_LIMIT
            ]
        )
        context["models"] = generation_model_choices()
        context["message"] = _message(self)
        context["status_error"] = ""
        context["splits"] = GOLD_SPLITS
        context["kinds"] = EDITOR_KINDS
        context["locations"] = EDITOR_LOCATIONS
        context["operation_id"] = editor.operation_id
        return context

    def post(self) -> Response:
        example = _get_example(self.url_kwargs)
        action = self.request.form_data.get("form", "editor")
        if action == "review":
            return self._review(example)
        if action in ("approve", "draft"):
            return self._status(example, action)
        if action == "fill":
            return self._fill(example)
        return self._editor(example)

    def _editor(self, example: GoldExample) -> Response:
        data = self.request.form_data
        state = editor.state_from_form(data)
        action = str(data.get("action", "save"))
        if action != "save":
            if not editor.apply_action(
                state, action, language=example.gold_set.language
            ):
                return Response("Unknown editor action.", status_code=400)
            return self.render(state=state)
        result = editor.validate(state)
        if result.page is None:
            return self.render(state=state, errors=result.errors, status_code=422)
        page, _ = generated_to_docpage(
            result.page,
            language=example.gold_set.language,
            line_counts=line_counts(example.gold_input()),
        )
        save_expected(example, page, change="Edited")
        return _redirect(_example_url(example), "saved")

    def _review(self, example: GoldExample) -> Response:
        form = ReviewForm(request=self.request)
        if not form.is_valid():
            return self.render(review_error="Choose a split.", status_code=422)
        save_review(
            example,
            split=form.cleaned_data["split"],
            notes=form.cleaned_data["notes"] or "",
        )
        return _redirect(_example_url(example), "review")

    def _status(self, example: GoldExample, action: str) -> Response:
        status = ExampleStatus.APPROVED if action == "approve" else ExampleStatus.DRAFT
        try:
            set_status(example, status)
        except GoldSetError as exc:
            return self.render(status_error=str(exc), status_code=422)
        return _redirect(
            _example_url(example), "approved" if action == "approve" else "draft"
        )

    def _fill(self, example: GoldExample) -> Response:
        form = FillForm(request=self.request)
        if not form.is_valid():
            return self.render(
                status_error="Choose a model to fill the page from.", status_code=422
            )
        try:
            if form.cleaned_data["fill"] == "parser":
                page = parser_page(example.gold_set.language, example.gold_input())
                save_expected(example, page, change="Replaced from the parser")
                return _redirect(_example_url(example), "filled")
            model = form.chosen_model()
            if model is None:
                return self.render(status_error="Choose a model.", status_code=422)
            start_model_seed(example, model)
        except (GoldSetError, InputError) as exc:
            return self.render(status_error=_error_text(exc), status_code=422)
        return _redirect(_example_url(example), "seeding")


class ExampleSeedStatusView(View):
    """Polled while a model fills in the page; reloads the page when done."""

    def get(self) -> Response:
        example = _get_example(self.url_kwargs)
        if example.seeding:
            html = Template("goldsets/seed_fragment.html").render({"example": example})
            return Response(html)
        return Response(headers={"HX-Redirect": _example_url(example)})
