"""Painel do Profissional - frontend para o barbeiro gerenciar convites.

Rotas:
  - /painel/                          -> dashboard (convites + barbearias)
  - /painel/convite/<pk>/aceitar/     -> aceitar convite (POST)
  - /painel/convite/<pk>/rejeitar/    -> rejeitar convite (POST)
  - /painel/convite/<pk>/cancelar/    -> cancelar convite (POST)
"""
from datetime import datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views.generic import View

from django.db import models

from .models import (
    Appointment,
    Product,
    Professional,
    ProfessionalInvitation,
    Service,
    Session,
    SessionProduct,
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
    sessions = (
        Session.objects.bypass_tenant()
        .filter(professional__user=user)
        .select_related("professional", "professional__tenant", "appointment")
        .prefetch_related(
            models.Prefetch("items", queryset=SessionProduct.objects.bypass_tenant().select_related("product"))
        )
        .order_by("-started_at")
    )
    tenant_ids = set(
        Professional.objects.bypass_tenant()
        .filter(user=user)
        .values_list("tenant_id", flat=True)
    )
    all_products = (
        Product.objects.bypass_tenant()
        .filter(tenant_id__in=tenant_ids, is_active=True)
        .order_by("name")
    )
    products_by_tenant = {}
    for p in all_products:
        products_by_tenant.setdefault(p.tenant_id, []).append(p)
    session_appointment_ids = set(
        Session.objects.bypass_tenant()
        .filter(professional__user=user, appointment__isnull=False)
        .values_list("appointment_id", flat=True)
    )
    return {
        "invitations": invitations,
        "memberships": memberships,
        "professionals": professionals,
        "appointments": appointments,
        "sessions": sessions,
        "products_by_tenant": products_by_tenant,
        "session_appointment_ids": session_appointment_ids,
        "products": all_products,
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


# --- Sprint 7: Sessoes ---

@login_required
def sessao_iniciar(request, pk):
    """Inicia sessao a partir de um agendamento confirmado."""
    if request.method != "POST":
        return redirect("core:painel")
    appt = get_object_or_404(
        Appointment.objects.bypass_tenant(),
        pk=pk, professional__user=request.user,
        status=Appointment.Status.CONFIRMED,
    )
    if Session.objects.bypass_tenant().filter(appointment=appt, status=Session.Status.IN_PROGRESS).exists():
        messages.error(request, "Ja existe uma sessao em andamento para este agendamento.")
        return redirect("core:painel")
    prof = Professional.objects.bypass_tenant().filter(
        user=request.user, tenant=appt.tenant,
    ).first()
    if not prof:
        messages.error(request, "Perfil profissional nao encontrado para esta barbearia.")
        return redirect("core:painel")
    sess = Session.objects.bypass_tenant().create(
        tenant=appt.tenant,
        appointment=appt,
        service=appt.service,
        service_price=appt.service.price,
        professional=prof,
        client_name=appt.client_name,
        client_phone=appt.client_phone,
        status=Session.Status.IN_PROGRESS,
    )
    messages.success(request, "Atendimento de '{}' iniciado!".format(appt.client_name))
    return redirect("core:painel")


@login_required
def sessao_iniciar_avulso(request):
    """Inicia sessao avulsa (sem agendamento)."""
    if request.method != "POST":
        return redirect("core:painel")
    client_name = request.POST.get("client_name", "").strip()
    client_phone = request.POST.get("client_phone", "").strip()
    tenant_id = request.POST.get("tenant_id", "").strip()
    if not client_name or not tenant_id:
        messages.error(request, "Nome do cliente e barbearia sao obrigatorios.")
        return redirect("core:painel")
    prof = Professional.objects.bypass_tenant().filter(
        user=request.user, tenant_id=tenant_id,
    ).first()
    if not prof:
        messages.error(request, "Perfil profissional nao encontrado para esta barbearia.")
        return redirect("core:painel")
    sess = Session.objects.bypass_tenant().create(
        tenant_id=tenant_id,
        professional=prof,
        client_name=client_name,
        client_phone=client_phone,
        status=Session.Status.IN_PROGRESS,
    )
    messages.success(request, "Atendimento avulso de '{}' iniciado!".format(client_name))
    return redirect("core:painel")


@login_required
def sessao_adicionar_produto(request, pk):
    """Adiciona produto a uma sessao em andamento."""
    if request.method != "POST":
        return redirect("core:painel")
    sess = get_object_or_404(
        Session.objects.bypass_tenant(),
        pk=pk, professional__user=request.user,
        status=Session.Status.IN_PROGRESS,
    )
    product_id = request.POST.get("product_id")
    quantity = int(request.POST.get("quantity", 1))
    if not product_id or quantity < 1:
        messages.error(request, "Produto e quantidade invalidos.")
        return redirect("core:painel")
    product = get_object_or_404(
        Product.objects.bypass_tenant(),
        pk=product_id, tenant=sess.tenant,
    )
    SessionProduct.objects.bypass_tenant().create(
        tenant=sess.tenant,
        session=sess,
        product=product,
        quantity=quantity,
        unit_price=product.price,
    )
    messages.success(request, "{}x {} adicionado a sessao.".format(quantity, product.name))
    return redirect("core:painel")


@login_required
def sessao_remover_produto(request, pk):
    """Remove item de uma sessao em andamento."""
    if request.method != "POST":
        return redirect("core:painel")
    item = get_object_or_404(
        SessionProduct.objects.bypass_tenant(),
        pk=pk, session__professional__user=request.user,
        session__status=Session.Status.IN_PROGRESS,
    )
    item.delete()
    messages.success(request, "Produto removido da sessao.")
    return redirect("core:painel")


@login_required
def sessao_fechar(request, pk):
    """Fecha sessao: calcula total e marca como completed."""
    if request.method != "POST":
        return redirect("core:painel")
    sess = get_object_or_404(
        Session.objects.bypass_tenant(),
        pk=pk, professional__user=request.user,
        status=Session.Status.IN_PROGRESS,
    )
    items = SessionProduct.objects.bypass_tenant().filter(session=sess)
    servico = sess.service_price or 0
    produtos = sum(item.total_price for item in items)
    total = servico + produtos
    sess.total_amount = total
    sess.status = Session.Status.COMPLETED
    sess.closed_at = datetime.now()
    sess.save(update_fields=["total_amount", "status", "closed_at"])
    messages.success(request, "Conta de '{}' fechada: R$ {:.2f}".format(sess.client_name, total))
    return redirect("core:painel")


@login_required
def sessao_cancelar(request, pk):
    if request.method != "POST":
        return redirect("core:painel")
    sess = get_object_or_404(
        Session.objects.bypass_tenant(),
        pk=pk, professional__user=request.user,
        status=Session.Status.IN_PROGRESS,
    )
    sess.status = Session.Status.CANCELLED
    sess.closed_at = datetime.now()
    sess.save(update_fields=["status", "closed_at"])
    messages.success(request, "Atendimento de '{}' cancelado.".format(sess.client_name))
    return redirect("core:painel")


@login_required
def produto_criar(request):
    if request.method != "POST":
        return redirect("core:painel")
    name = request.POST.get("name", "").strip()
    price = request.POST.get("price", "").strip()
    tenant_id = request.POST.get("tenant_id", "").strip()
    if not name or not price or not tenant_id:
        messages.error(request, "Nome, preco e barbearia sao obrigatorios.")
        return redirect("core:painel")
    try:
        price = Decimal(price)
    except Exception:
        messages.error(request, "Preco invalido.")
        return redirect("core:painel")
    if not Professional.objects.bypass_tenant().filter(
        user=request.user, tenant_id=tenant_id,
    ).exists():
        messages.error(request, "Voce nao tem perfil nesta barbearia.")
        return redirect("core:painel")
    Product.objects.bypass_tenant().create(
        tenant_id=tenant_id, name=name, price=price,
    )
    messages.success(request, "Produto '{}' criado.".format(name))
    return redirect("core:painel")


@login_required
def produto_inativar(request, pk):
    if request.method != "POST":
        return redirect("core:painel")
    prod = get_object_or_404(Product.objects.bypass_tenant(), pk=pk)
    if not Professional.objects.bypass_tenant().filter(
        user=request.user, tenant=prod.tenant,
    ).exists():
        raise PermissionDenied
    prod.is_active = False
    prod.save(update_fields=["is_active"])
    messages.success(request, "Produto '{}' inativado.".format(prod.name))
    return redirect("core:painel")
