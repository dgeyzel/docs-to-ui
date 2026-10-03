from plain.urls import Router, path

from app.api import views


class ApiRouter(Router):
    namespace = "api"
    urls = (
        path("generations", views.GenerationsView, name="generations"),
        path("generations/<int:id>", views.GenerationView, name="generation"),
        path("generations/<int:id>/page", views.PageView, name="page"),
        path("generations/<int:id>/page.html", views.PageHtmlView, name="page_html"),
        path(
            "generations/<int:id>/regenerate", views.RegenerateView, name="regenerate"
        ),
        path("generations/<int:id>/feedback", views.FeedbackView, name="feedback"),
        path("openapi.json", views.OpenApiView, name="openapi"),
    )
