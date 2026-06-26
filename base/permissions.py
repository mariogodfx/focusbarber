"""
RBAC por role — PRD §8: "Toda operação depende de tenant_id + role".

Mapeia cada perfil de usuário (role) ao conjunto de permissões Django que ele
recebe automaticamente. O sinal post_save do User sincroniza as permissões
sempre que o usuário é criado/alterado.

Permissões são definidas como "<app_label>.<codename>" para leitura humana:
  ex: "core.view_tenant", "core.add_service", ...

Hierarquia (do maior para o menor escopo):
  superadmin  => tudo (is_superuser, tratado à parte)
  owner       => gestão completa da própria barbearia
  manager     => operação (agendamentos, clientes, sessões) — sem gestão de usuários nem financeiro crítico
  professional=> execução (sessões, services) — leitura/escrita do que executa
  client      => leitura do próprio perfil + agendamento (público)
"""
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q

# ---------- Catálogo de permissões por role ----------
# Cada entrada: lista de strings "<app>.<codename>".
ROLE_PERMISSIONS = {
    "superadmin": [],  # usa is_superuser (acesso global) — sem lista explícita.
    "owner": [
        # Gestão da própria barbearia (CRUD).
        "core.view_tenant", "core.change_tenant",
        # Usuários da barbearia.
        "base.view_user", "base.add_user", "base.change_user",
        # Serviços da barbearia.
        "core.view_service", "core.add_service", "core.change_service", "core.delete_service",
    ],
    "manager": [
        # Operação: vê a barbearia (somente leitura).
        "core.view_tenant",
        # Usuários: vê, mas não gerencia permissões críticas.
        "base.view_user", "base.add_user", "base.change_user",
        # Serviços (CRUD operacional).
        "core.view_service", "core.add_service", "core.change_service",
    ],
    "professional": [
        # Execução: vê serviços; sem criar/excluir.
        "core.view_service", "core.change_service",
        # Vê usuários (clientes/profissionais) — leitura.
        "base.view_user",
    ],
    "client": [
        # Acesso público: vê próprios dados (tratados por views específicas).
        # Cliente tipicamente não acessa o admin.
        "base.view_user",
    ],
}


def _resolve_permission(code):
    """Converte 'app.codename' num objeto Permission (ou None se inexistente)."""
    try:
        app_label, codename = code.split(".", 1)
        ct = ContentType.objects.filter(app_label=app_label)
        return Permission.objects.filter(content_type__in=ct, codename=codename).first()
    except (ValueError, TypeError):
        return None


def get_permissions_for_role(role):
    """Retorna queryset de Permission para a role informada."""
    codes = ROLE_PERMISSIONS.get(role, [])
    codenames = [c.split(".", 1)[1] for c in codes if "." in c]
    if not codenames:
        return Permission.objects.none()
    app_labels = {c.split(".", 1)[0] for c in codes if "." in c}
    return Permission.objects.filter(
        content_type__app_label__in=app_labels,
        codename__in=codenames,
    )


def sync_role_permissions(user):
    """Sincroniza as permissões Django do usuário conforme sua role.

    - superadmin: nada a fazer (usa is_superuser — acesso total implícito).
    - demais: remove as permissões manuais e aplica as da role.
    """
    if getattr(user, "is_superadmin", False):
        return  # superadmin não usa lista por role.
    expected = get_permissions_for_role(user.role)
    # Substitui TODAS as permissões diretas pelas da role.
    user.user_permissions.set(expected)


# ---------- Helpers de checagem para views ----------

class RoleRequiredMixin:
    """Mixin para views: exige que request.user.role esteja em `allowed_roles`.

    Uso:
        class MinhaView(RoleRequiredMixin, View):
            allowed_roles = ("owner", "manager")
    """

    allowed_roles = ()

    def dispatch(self, request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login
            return redirect_to_login(request.get_full_path())
        if getattr(user, "is_superadmin", False) or user.role in self.allowed_roles:
            return super().dispatch(request, *args, **kwargs)
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied(_("Você não tem permissão para acessar esta área."))


# Import tardio de gettext para evitar ciclo no carregamento do app.
from django.utils.translation import gettext_lazy as _  # noqa: E402