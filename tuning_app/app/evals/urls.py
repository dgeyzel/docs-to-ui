from plain.urls import Router, path

from app.evals import views


class EvalsRouter(Router):
    namespace = "evals"
    urls = (
        path("", views.EvalListView, name="list"),
        path("new", views.EvalCreateView, name="create"),
        path("compare", views.CompareView, name="compare"),
        path("<int:id>", views.EvalDetailView, name="detail"),
        path("<int:id>/status", views.EvalStatusView, name="status"),
        path(
            "<int:id>/results/<int:result_id>",
            views.ResultDetailView,
            name="result",
        ),
    )


class MetricsRouter(Router):
    namespace = "metrics"
    urls = (path("", views.MetricsView, name="index"),)
