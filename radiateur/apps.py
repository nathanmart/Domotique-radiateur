from django.apps import AppConfig


class RadiateurConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'radiateur'

    def ready(self):  # pragma: no cover - executed at runtime
        from . import runtime

        runtime.initialize()
