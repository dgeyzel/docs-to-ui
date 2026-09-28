from d2u.traces.urls import TracesRouter
from plain.assets.urls import AssetsRouter
from plain.urls import Router, include, path

from app.generate.urls import GenerationsRouter
from app.generate.views import HomeView


class AppRouter(Router):
    namespace = ""
    urls = (
        include("assets/", AssetsRouter),
        include("generations/", GenerationsRouter),
        include("traces/", TracesRouter),
        path("", HomeView, name="home"),
    )
