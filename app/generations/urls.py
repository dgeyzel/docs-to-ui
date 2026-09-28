from plain.urls import Router, path

from app.generations import views


class GenerationsRouter(Router):
    namespace = "generations"
    urls = (
        path("", views.HomeView, name="create"),
        path("<int:id>/", views.GenerationDetailView, name="detail"),
        path("<int:id>/status", views.GenerationStatusView, name="status"),
        path("<int:id>/regenerate", views.RegenerateView, name="regenerate"),
        path("<int:id>/feedback", views.FeedbackView, name="feedback"),
        path("<int:id>/export.html", views.ExportHtmlView, name="export_html"),
        path("<int:id>/export.json", views.ExportJsonView, name="export_json"),
    )
