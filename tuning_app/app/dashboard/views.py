from plain.templates.views import TemplateView
from plain.views import RedirectView


class DashboardView(TemplateView):
    template_name = "dashboard/index.html"


class RootRedirectView(RedirectView):
    """Send / to the dashboard: every Tuning app page lives under /tuning/."""

    url_name = "dashboard"
