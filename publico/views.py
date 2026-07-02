"""Views da Página Pública — Sprint 4 (PRD §9 — módulo "Página pública").

Rota pública (sem auth) que exibe a barbearia + seus serviços ativos,
seguindo o design system do projeto. PRD §23: carregamento < 2s.
"""
from django.views.generic import DetailView

from core.models import BusinessHours, Service, Tenant


class BarbeariaPublicaView(DetailView):
    """Página pública de uma barbearia: /<slug>/.

    - Públicamente acessível (não requer login).
    - Só exibe a barbearia se ativa.
    - Lista apenas serviços ativos (Sprint 3 — flag is_active).
    - Lista os horários de funcionamento (Sprint 5+ — BusinessHours).
    - Acesso direto ao modelo Tenant (não filtrado pelo TenantMiddleware,
      pois o usuário é anônimo). O slug lookup é intencional e explícito.
    """

    model = Tenant
    template_name = "publico/barbearia.html"
    context_object_name = "barbearia"
    slug_field = "slug"
    slug_url_kwarg = "slug"

    def get_queryset(self):
        # Apenas barbearias ativas aparecem publicamente.
        return Tenant.objects.filter(is_active=True)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        tenant = self.object
        ctx["servicos"] = (
            Service.objects.bypass_tenant().filter(tenant=tenant, is_active=True)
        )
        # Horários de funcionamento (ordenados por dia da semana).
        ctx["horarios"] = (
            BusinessHours.objects.bypass_tenant().filter(tenant=tenant)
            .order_by("weekday")
        )
        return ctx