"""Custom middleware enforcing authentication across the dashboard."""

from __future__ import annotations

from fnmatch import fnmatch

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import HttpRequest, HttpResponse


class LoginRequiredMiddleware:
    """Redirect anonymous users to the login page for protected URLs."""

    def __init__(self, get_response):
        self.get_response = get_response
        exempt = getattr(settings, "LOGIN_EXEMPT_URLS", ())
        self.exempt_patterns: tuple[str, ...] = tuple(exempt)

    def _is_exempt(self, path: str) -> bool:
        if not path:
            return False

        static_url = getattr(settings, "STATIC_URL", None) or ""
        if static_url and path.startswith(static_url):
            return True

        media_url = getattr(settings, "MEDIA_URL", None) or ""
        if media_url and path.startswith(media_url):
            return True

        for pattern in self.exempt_patterns:
            if fnmatch(path, pattern):
                return True

        return False

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.user.is_authenticated:
            return self.get_response(request)

        path = request.path_info
        if self._is_exempt(path):
            return self.get_response(request)

        return redirect_to_login(path)
