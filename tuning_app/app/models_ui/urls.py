from plain.urls import Router, path

from app.models_ui import views


class ModelsRouter(Router):
    namespace = "models"
    urls = (
        path("", views.ModelListView, name="list"),
        path("new", views.ModelCreateView, name="create"),
        path("params", views.ModelParamsView, name="params"),
        path("<int:id>", views.ModelDetailView, name="detail"),
        path("<int:id>/activate", views.ModelActivateView, name="activate"),
        path("<int:id>/test", views.ModelTestView, name="test"),
        path(
            "<int:id>/tests/<int:test_id>",
            views.ModelTestStatusView,
            name="test_status",
        ),
    )
