"""Sinais do app base — sincroniza permissões por role (PRD §8) e auto-vínculo.

Sprint 5+ — Auto-vínculo: ao criar um usuário NOVO com perfil owner/manager/
professional e tenant preenchido, cria automaticamente:
  - TenantMembership (vínculo usuário × barbearia)
  - Professional (apenas para role=professional)

Isso evita retrabalho: o dono cadastra o usuário e o vínculo + perfil de
profissional já ficam prontos. Usa get_or_create (idempotente).
"""
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import User
from .permissions import sync_role_permissions


# Mapeamento User.Role -> TenantMembership.Role
_MEMBERSHIP_ROLE = {
    User.Role.OWNER: "owner",
    User.Role.MANAGER: "manager",
    User.Role.PROFESSIONAL: "professional",
}


@receiver(post_save, sender=User)
def sync_user_role_permissions(sender, instance, created, raw, using, **kwargs):
    """Aplica as permissões Django definidas para a role do usuário."""
    # Em migrations raw não tocamos nas permissões.
    if raw:
        return
    sync_role_permissions(instance)


@receiver(post_save, sender=User)
def auto_create_membership_and_professional(sender, instance, created, raw, using, **kwargs):
    """Cria TenantMembership (e Professional p/ professional) ao criar usuário.

    Condições:
      - Apenas created=True (não dispara em update).
      - role in (owner, manager, professional) E tenant preenchido.
      - Idempotente via get_or_create (re-executar o seed não duplica).
    """
    if raw or not created:
        return
    role = instance.role
    membership_role = _MEMBERSHIP_ROLE.get(role)
    if membership_role is None or instance.tenant_id is None:
        return

    # Imports lazy para evitar import circular (base <- core).
    from core.models import Professional, TenantMembership

    TenantMembership.objects.using(using).get_or_create(
        tenant=instance.tenant,
        user=instance,
        role=membership_role,
        defaults={"is_active": True},
    )
    if role == User.Role.PROFESSIONAL:
        Professional.objects.using(using).get_or_create(
            tenant=instance.tenant,
            user=instance,
            defaults={"is_active": True},
        )