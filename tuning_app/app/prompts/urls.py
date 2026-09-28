from plain.urls import Router, path

from app.prompts import views


class PromptsRouter(Router):
    namespace = "prompts"
    urls = (
        path("", views.PromptListView, name="list"),
        path("diff", views.PromptDiffView, name="diff"),
        path("<int:id>", views.PromptDetailView, name="detail"),
        path("<int:id>/export", views.PromptExportView, name="export"),
    )
