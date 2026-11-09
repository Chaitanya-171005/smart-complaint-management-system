from django.apps import AppConfig


class ComplaintsConfig(AppConfig):
    name = "complaints"

    def ready(self):
        from . import checks  # noqa: F401 -- register Django's startup checks
