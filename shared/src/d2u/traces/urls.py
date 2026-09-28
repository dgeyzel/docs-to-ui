from plain.urls import Router, path

from d2u.traces import views


class TracesRouter(Router):
    namespace = "traces"
    urls = (
        path("", views.TraceListView, name="list"),
        path("<str:trace_id>", views.TraceDetailView, name="detail"),
        path("<str:trace_id>/spans/<str:span_id>", views.SpanDetailView, name="span"),
    )
