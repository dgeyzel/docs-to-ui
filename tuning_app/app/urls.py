from d2u.traces.urls import TracesRouter
from plain.assets.urls import AssetsRouter
from plain.urls import Router, include, path

from app.dashboard.views import DashboardView, RootRedirectView


class AppRouter(Router):
    namespace = ""
    # Every Tuning app page lives under /tuning/ (SPEC §9), so the two apps
    # could later merge without URL changes.
    urls = (
        include("assets/", AssetsRouter),
        include("tuning/traces/", TracesRouter),
        path("tuning/", DashboardView, name="dashboard"),
        path("", RootRedirectView),
    )
