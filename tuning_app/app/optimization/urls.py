from plain.urls import Router, path

from app.optimization import views


class OptimizationRouter(Router):
    namespace = "optimization"
    urls = (
        path("", views.OptimizationListView, name="list"),
        path("new", views.OptimizationCreateView, name="create"),
        path("<int:id>", views.OptimizationDetailView, name="detail"),
        path("<int:id>/status", views.OptimizationStatusView, name="status"),
    )
