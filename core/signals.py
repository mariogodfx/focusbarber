"""Sinais do app core — auto-cria as 7 linhas-padrão de horários.

Ao criar um Tenant, criamos as 7 linhas de BusinessHours (uma por dia, todas
fechadas por padrão) para facilitar a configuração pelo dono — basta marcar
a flag `is_open` e ajustar `open_time`/`close_time`/`break_*`.

Ao criar um Professional, criamos as 7 linhas de ProfessionalAvailability
(todas indisponíveis por padrão) — o dono/gerente só marca `available` e
ajusta os horários, respeitando o horário da barbearia (validado em clean()).
"""
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import BusinessHours, Professional, ProfessionalAvailability, Tenant


@receiver(post_save, sender=Tenant)
def _seed_business_hours(sender, instance, created, raw, using, **kwargs):
    if raw or not created:
        return
    # Cria as 7 linhas-padrão (uma por dia, todas fechadas).
    # Usa bypass_tenant + transaction.atomic para não depender do contexto da
    # requisição (o Tenant pode ser criado via admin, signal, shell, etc.).
    with transaction.atomic(using=using):
        for wd in range(0, 7):
            BusinessHours.objects.using(using).get_or_create(
                tenant=instance, weekday=wd,
            )


@receiver(post_save, sender=Professional)
def _seed_professional_availability(sender, instance, created, raw, using, **kwargs):
    if raw or not created:
        return
    with transaction.atomic(using=using):
        for wd in range(0, 7):
            ProfessionalAvailability.objects.using(using).get_or_create(
                tenant=instance.tenant, professional=instance, weekday=wd,
            )