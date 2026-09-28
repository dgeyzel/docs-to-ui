from d2u.traces.urls import TracesRouter
from plain.assets.urls import AssetsRouter
from plain.urls import Router, include, path

from app.dashboard.views import DashboardView, RootRedirectView
from app.evals.urls import EvalsRouter, MetricsRouter
from app.goldsets.urls import GoldSetsRouter
from app.models_ui.urls import ModelsRouter
from app.settings_ui.urls import SettingsRouter


class AppRouter(Router):
    namespace = ""
    # Every Tuning app page lives under /tuning/ (SPEC §9), so the two apps
    # could later merge without URL changes.
    urls = (
        include("assets/", AssetsRouter),
        include("tuning/traces/", TracesRouter),
        include("tuning/settings/", SettingsRouter),
        include("tuning/models/", ModelsRouter),
        include("tuning/goldsets/", GoldSetsRouter),
        include("tuning/evals/", EvalsRouter),
        include("tuning/metrics/", MetricsRouter),
        path("tuning/", DashboardView, name="dashboard"),
        path("", RootRedirectView),
    )
