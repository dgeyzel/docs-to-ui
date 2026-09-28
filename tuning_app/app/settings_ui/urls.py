from plain.urls import Router, path

from app.settings_ui import views


class SettingsRouter(Router):
    namespace = "settings"
    urls = (path("", views.SettingsView, name="index"),)
