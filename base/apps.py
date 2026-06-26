from django.apps import AppConfig


class BaseConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "base"
    verbose_name = "Base / Autenticação"

    def ready(self):
        # Importa os sinais para conectá-los ao carregar o app.
        from . import signals  # noqa: F401