"""Sinais do app base — sincroniza permissões por role (PRD §8)."""
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import User
from .permissions import sync_role_permissions


@receiver(post_save, sender=User)
def sync_user_role_permissions(sender, instance, created, raw, using, **kwargs):
    """Aplica as permissões Django definidas para a role do usuário."""
    # Em migrations raw não tocamos nas permissões.
    if raw:
        return
    sync_role_permissions(instance)