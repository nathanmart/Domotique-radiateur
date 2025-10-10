"""Authentication views for the radiateur application."""

from django.conf import settings
from django.contrib.auth.views import LoginView


class PersistentLoginView(LoginView):
    """Login view keeping the session active for an extended period."""

    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        # Refresh the session expiry so authenticated users can stay logged in
        # as long as they use the interface regularly.
        self.request.session.set_expiry(settings.SESSION_COOKIE_AGE)
        return response

