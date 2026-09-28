from plain.assets.urls import AssetsRouter
from plain.urls import Router, include, path

from app.generations.urls import GenerationsRouter
from app.generations.views import HomeView
from app.traces.urls import TracesRouter


class AppRouter(Router):
    namespace = ""
    urls = (
        include("assets/", AssetsRouter),
        include("generations/", GenerationsRouter),
        include("traces/", TracesRouter),
        path("", HomeView, name="home"),
    )
