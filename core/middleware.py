"""
TenantMiddleware — PRD §13.2: "Middleware de tenant deve ser obrigatório em
todas requisições autenticadas".

Estratégia de resolução (em ordem):
  1. Usuário autenticado: usa request.user.tenant (cada usuário pertence a uma
     barbearia). Superadmin SaaS (tenant=null) => contexto sem tenant ativo;
     acessos administrativos globais usam .bypass_tenant() explícito.
  2. (Futuro) Subdomínio/host => slug do tenant — preparado em código mas
     requer roteamento DNS (Sprint de deploy). Para o MVP, via usuário.

Posicionamento: imediatamente APÓS AuthenticationMiddleware (precisa de user).
"""
from django.utils.deprecation import MiddlewareMixin

from .models import set_current_tenant


class TenantMiddleware(MiddlewareMixin):
    """Resolve e publica o tenant da requisição atual (ContextVar).

    Regras:
      - Usuário comum autenticado => tenant = user.tenant (filtro ativo).
      - Superadmin SaaS (is_superadmin) => bypass: vê todos os tenants.
      - Não autenticado => sem tenant (nenhum dado exposto).
    """

    def process_request(self, request):
        user = getattr(request, "user", None)
        tenant = None
        bypass = False
        if user is not None and user.is_authenticated and not user.is_anonymous:
            # Superadmin SaaS = acesso global (vê todas as barbearias).
            if getattr(user, "is_superadmin", False):
                bypass = True
            else:
                tenant = getattr(user, "tenant", None)
        request.tenant = tenant
        request.tenant_bypass = bypass
        set_current_tenant(tenant, bypass=bypass, user=user)

    def process_response(self, request, response):
        # Limpa o contexto ao fim da requisição — evita vazamento entre
        # requisições/threads reutilizadas.
        set_current_tenant(None, bypass=False, user=None)
        return response