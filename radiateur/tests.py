from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class AuthenticationTests(TestCase):
    """Verify that the dashboard requires a valid authenticated session."""

    def setUp(self) -> None:
        self.password = "super-secret"
        self.user = get_user_model().objects.create_user(
            username="radiateur", password=self.password
        )

    def test_anonymous_user_is_redirected(self) -> None:
        """Protected views should redirect anonymous visitors to the login page."""

        protected_urls = [
            reverse("index"),
            reverse("planning"),
            reverse("options"),
            reverse("devices"),
        ]

        for url in protected_urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("login"), response.url)

    def test_authenticated_user_can_access_dashboard(self) -> None:
        """A valid user should be able to open the dashboard."""

        logged_in = self.client.login(username=self.user.username, password=self.password)
        self.assertTrue(logged_in)

        response = self.client.get(reverse("index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.user.get_username())

    def test_successful_login_sets_expected_session_expiry(self) -> None:
        """Logging in refreshes the session expiry to the configured duration."""

        response = self.client.post(
            reverse("login"),
            {"username": self.user.username, "password": self.password},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)

        expiry = self.client.session.get_expiry_age()
        self.assertAlmostEqual(
            expiry,
            settings.SESSION_COOKIE_AGE,
            delta=5,
        )
