"""Painel do Profissional - frontend para o barbeiro gerenciar convites.

Rotas:
  - /painel/                          -> dashboard (convites + barbearias)
  - /painel/convite/<pk>/aceitar/     -> aceitar convite (POST)
  - /painel/convite/<pk>/rejeitar/    -> rejeitar convite (POST)
  - /painel/convite/<pk>/cancelar/    -> cancelar convite (POST)
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views.generic import View

from django.db import models

from .models import (
    Appointment,
    Professional,
    ProfessionalInvitation,
    Service,
    TenantMembership,
    current_tenant,
    current_user,
    set_current_tenant,
)


def _professional_dashboard_context(user):
    """Contexto compartilhado: convites + barbearias + perfil profissional."""
    invitations = (
        ProfessionalInvitation.objects.bypass_tenant()
        .filter(professional_user=user)
        .select_related("tenant", "invited_by")
        .order_by("-created_at")
    )
    memberships = (
        TenantMembership.objects.bypass_tenant()
        .filter(user=user, is_active=True)
        .select_related("tenant")
        .order_by("tenant__name")
    )
    professionals = (
        Professional.objects.bypass_tenant()
        .filter(user=user)
        .select_related("tenant")
        .prefetch_related(
            models.Prefetch("services", queryset=Service.objects.bypass_tenant())
        )
        .order_by("tenant__name")
    )
    appointments = (
        Appointment.objects.bypass_tenant()
        .filter(professional__user=user)
        .select_related("professional", "service", "professional__tenant")
        .order_by("-date", "-start_time")
    )
    return {
        "invitations": invitations,
        "memberships": memberships,
        "professionals": professionals,
        "appointments": appointments,
    }


@method_decorator(login_required, name="dispatch")
class PainelProfissionalView(View):
    """Dashboard do profissional: convites + barbearias vinculadas."""

    template_name = "core/painel.html"

    def get(self, request):
        ctx = _professional_dashboard_context(request.user)
        return render(request, self.template_name, ctx)


@login_required
def convite_aceitar(request, pk):
    """Profissional convidado aceita o convite (pending -> accepted)."""
    if request.method != "POST":
        return redirect("core:painel")
    inv = get_object_or_404(
        ProfessionalInvitation.objects.bypass_tenant(),
        pk=pk, professional_user=request.user,
    )
    pt = current_tenant()
    pu = current_user()
    set_current_tenant(inv.tenant, bypass=False, user=request.user)
    try:
        inv.accept()
        messages.success(
            request,
            "Convite da barbearia '{}' aceito!".format(inv.tenant),
        )
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages))
    finally:
        set_current_tenant(pt, bypass=False, user=pu)
    return redirect("core:painel")


@login_required
def convite_rejeitar(request, pk):
    """Profissional convidado rejeita o convite (pending -> rejected)."""
    if request.method != "POST":
        return redirect("core:painel")
    inv = get_object_or_404(
        ProfessionalInvitation.objects.bypass_tenant(),
        pk=pk, professional_user=request.user,
    )
    pt = current_tenant()
    pu = current_user()
    set_current_tenant(inv.tenant, bypass=False, user=request.user)
    try:
        inv.reject()
        messages.success(
            request,
            "Convite da barbearia '{}' rejeitado.".format(inv.tenant),
        )
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages))
    finally:
        set_current_tenant(pt, bypass=False, user=pu)
    return redirect("core:painel")


@login_required
def convite_cancelar(request, pk):
    """Profissional convidado ou remetente cancela o convite (pending -> cancelled)."""
    if request.method != "POST":
        return redirect("core:painel")
    inv = get_object_or_404(
        ProfessionalInvitation.objects.bypass_tenant(),
        pk=pk,
    )
    is_invitee = inv.professional_user_id == request.user.pk
    is_sender = inv.invited_by_id == request.user.pk
    if not (is_invitee or is_sender or request.user.is_superadmin):
        raise PermissionDenied("Voce nao tem permissao para cancelar este convite.")
    pt = current_tenant()
    pu = current_user()
    set_current_tenant(inv.tenant, bypass=False, user=request.user)
    try:
        inv.cancel()
        messages.success(
            request,
            "Convite da barbearia '{}' cancelado.".format(inv.tenant),
        )
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages))
    finally:
        set_current_tenant(pt, bypass=False, user=pu)
    return redirect("core:painel")


@login_required
def appointment_confirmar(request, pk):
    if request.method != "POST":
        return redirect("core:painel")
    appt = get_object_or_404(
        Appointment.objects.bypass_tenant(),
        pk=pk, professional__user=request.user,
    )
    if appt.status == Appointment.Status.PENDING:
        appt.status = Appointment.Status.CONFIRMED
        appt.save(update_fields=["status"])
        messages.success(request, "Agendamento de '{}' confirmado.".format(appt.client_name))
    else:
        messages.error(request, "So e possivel confirmar agendamentos pendentes.")
    return redirect("core:painel")


@login_required
def appointment_concluir(request, pk):
    if request.method != "POST":
        return redirect("core:painel")
    appt = get_object_or_404(
        Appointment.objects.bypass_tenant(),
        pk=pk, professional__user=request.user,
    )
    if appt.status == Appointment.Status.CONFIRMED:
        appt.status = Appointment.Status.COMPLETED
        appt.save(update_fields=["status"])
        messages.success(request, "Agendamento de '{}' concluido.".format(appt.client_name))
    else:
        messages.error(request, "So e possivel concluir agendamentos confirmados.")
    return redirect("core:painel")


@login_required
def appointment_cancelar(request, pk):
    if request.method != "POST":
        return redirect("core:painel")
    appt = get_object_or_404(
        Appointment.objects.bypass_tenant(),
        pk=pk, professional__user=request.user,
    )
    if appt.status in (Appointment.Status.PENDING, Appointment.Status.CONFIRMED):
        appt.status = Appointment.Status.CANCELLED
        appt.save(update_fields=["status"])
        messages.success(request, "Agendamento de '{}' cancelado.".format(appt.client_name))
    else:
        messages.error(request, "Este agendamento nao pode ser cancelado.")
    return redirect("core:painel")
