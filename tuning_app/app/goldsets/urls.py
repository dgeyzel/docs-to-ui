from plain.urls import Router, path

from app.goldsets import views


class GoldSetsRouter(Router):
    namespace = "goldsets"
    urls = (
        path("", views.GoldSetListView, name="list"),
        path("<int:id>", views.GoldSetDetailView, name="detail"),
        path("<int:id>/examples/new", views.ExampleCreateView, name="example_create"),
        path(
            "<int:id>/examples/<int:example_id>",
            views.ExampleDetailView,
            name="example",
        ),
        path(
            "<int:id>/examples/<int:example_id>/seed",
            views.ExampleSeedStatusView,
            name="example_seed",
        ),
    )
