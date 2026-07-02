from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Multi-Tenant Core"
    # Sprint 2: modelo Tenant, middleware de tenant, QuerySet filtrado.

    def ready(self):
        # Importa os sinais (criação de 7 linhas-padrão de horário/availability).
        from . import signals  # noqa: F401