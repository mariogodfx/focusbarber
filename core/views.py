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
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views.generic import View

from django.db import models

from .models import (
    Appointment,
    Payment,
    Product,
    Professional,
    ProfessionalAvailability,
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
    pode_gerir_agenda = (
        user.role in ("owner", "manager")
        or TenantMembership.objects.bypass_tenant()
        .filter(user=user, role__in=[TenantMembership.Role.OWNER, TenantMembership.Role.MANAGER], is_active=True)
        .exists()
        or user.is_superadmin
    )
    pode_convidar = (
        user.role in ("owner", "manager") or user.is_superadmin
        or TenantMembership.objects.bypass_tenant()
        .filter(user=user, role__in=[TenantMembership.Role.OWNER, TenantMembership.Role.MANAGER], is_active=True)
        .exists()
    )
    if pode_gerir_agenda:
        admin_tenant_ids = set(
            TenantMembership.objects.bypass_tenant()
            .filter(user=user, role__in=[TenantMembership.Role.OWNER, TenantMembership.Role.MANAGER], is_active=True)
            .values_list("tenant_id", flat=True)
        )
        if user.role == "owner" and user.tenant_id:
            admin_tenant_ids.add(user.tenant_id)
        if user.is_superadmin:
            from .models import Tenant
            admin_tenant_ids = set(Tenant.objects.values_list("id", flat=True))
        appointments = (
            Appointment.objects.bypass_tenant()
            .filter(tenant_id__in=admin_tenant_ids)
            .select_related("professional", "service", "professional__tenant")
            .order_by("-date", "-start_time")
        )
    else:
        appointments = (
            Appointment.objects.bypass_tenant()
            .filter(professional__user=user)
            .select_related("professional", "service", "professional__tenant")
            .order_by("-date", "-start_time")
        )
    if pode_gerir_agenda:
        sessions = (
            Session.objects.bypass_tenant()
            .filter(tenant_id__in=admin_tenant_ids)
            .select_related("professional", "professional__tenant", "appointment", "service", "payment")
            .prefetch_related(
                models.Prefetch("items", queryset=SessionProduct.objects.bypass_tenant().select_related("product"))
            )
            .order_by("-started_at")
        )
    else:
        sessions = (
            Session.objects.bypass_tenant()
            .filter(professional__user=user)
            .select_related("professional", "professional__tenant", "appointment", "service", "payment")
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
    if pode_gerir_agenda:
        tenant_ids |= admin_tenant_ids
    product_filters = {"tenant_id__in": tenant_ids}
    if not pode_convidar:
        product_filters["is_active"] = True
    all_products = (
        Product.objects.bypass_tenant()
        .filter(**product_filters)
        .order_by("name")
    )
    products_by_tenant = {}
    for p in all_products:
        products_by_tenant.setdefault(p.tenant_id, []).append(p)
    if pode_gerir_agenda:
        session_q = models.Q(professional__user=user) | models.Q(tenant_id__in=admin_tenant_ids)
    else:
        session_q = models.Q(professional__user=user)
    session_appointment_ids = set(
        Session.objects.bypass_tenant()
        .filter(session_q, appointment__isnull=False)
        .values_list("appointment_id", flat=True)
    )
    in_progress_session_ids = set(
        Session.objects.bypass_tenant()
        .filter(session_q, appointment__isnull=False, status=Session.Status.IN_PROGRESS)
        .values_list("appointment_id", flat=True)
    )
    if pode_gerir_agenda:
        prof_qs = (
            Professional.objects.bypass_tenant()
            .filter(tenant_id__in=admin_tenant_ids)
            .select_related("user", "tenant")
            .prefetch_related(
                models.Prefetch("services", queryset=Service.objects.bypass_tenant()),
                models.Prefetch("availability", queryset=ProfessionalAvailability.objects.bypass_tenant()),
            )
            .order_by("user__first_name")
        )
        all_professionals = []
        for p in prof_qs:
            available_days = sum(1 for a in p.availability.all() if a.available)
            all_professionals.append({
                "pk": p.pk,
                "name": p.user.get_full_name() or p.user.email,
                "email": p.user.email,
                "tenant": p.tenant.name,
                "services_count": p.services.all().count(),
                "available_days": available_days,
                "is_active": p.is_active,
            })
    else:
        all_professionals = []
    admin_tenants = []
    sent_invitations = []
    if user.is_superadmin:
        from .models import Tenant
        admin_tenants = Tenant.objects.all().order_by("name")
        sent_invitations = (
            ProfessionalInvitation.objects.bypass_tenant()
            .select_related("tenant", "professional_user", "invited_by")
            .order_by("-created_at")
        )
    elif pode_convidar:
        admin_memberships = (
            TenantMembership.objects.bypass_tenant()
            .filter(user=user, role__in=[TenantMembership.Role.OWNER, TenantMembership.Role.MANAGER], is_active=True)
            .select_related("tenant")
        )
        admin_tenants = [m.tenant for m in admin_memberships]
        admin_tenant_ids = [m.tenant.id for m in admin_memberships]
        if pode_convidar:
            sent_invitations = (
                ProfessionalInvitation.objects.bypass_tenant()
                .filter(tenant_id__in=admin_tenant_ids)
                .select_related("tenant", "professional_user", "invited_by")
                .order_by("-created_at")
            )
        else:
            sent_invitations = (
                ProfessionalInvitation.objects.bypass_tenant()
                .filter(invited_by=user)
                .select_related("tenant", "professional_user")
                .order_by("-created_at")
            )
    return {
        "invitations": invitations,
        "memberships": memberships,
        "professionals": professionals,
        "appointments": appointments,
        "sessions": sessions,
        "products_by_tenant": products_by_tenant,
        "session_appointment_ids": session_appointment_ids,
        "in_progress_session_ids": in_progress_session_ids,
        "products": all_products,
        "pode_convidar": pode_convidar,
        "admin_tenants": admin_tenants,
        "sent_invitations": sent_invitations,
        "all_professionals": all_professionals,
    }


@method_decorator(login_required, name="dispatch")
class PainelProfissionalView(View):
    """Dashboard do profissional: convites + barbearias vinculadas."""

    template_name = "core/painel.html"

    def get(self, request):
        ctx = _professional_dashboard_context(request.user)
        return render(request, self.template_name, ctx)


@login_required
def convite_enviar(request):
    """Owner/manager envia convite para um profissional se juntar a barbearia."""
    if request.method != "POST":
        return redirect("core:painel")
    email = request.POST.get("email", "").strip()
    tenant_id = request.POST.get("tenant_id", "").strip()
    if not email or not tenant_id:
        messages.error(request, "E-mail e barbearia sao obrigatorios.")
        return redirect("core:painel")
    try:
        tenant_id = int(tenant_id)
    except (ValueError, TypeError):
        messages.error(request, "Barbearia invalida.")
        return redirect("core:painel")
    pode_convidar = (
        request.user.is_superadmin
        or request.user.role in ("owner", "manager")
        or TenantMembership.objects.bypass_tenant()
        .filter(
            user=request.user, tenant_id=tenant_id,
            role__in=[TenantMembership.Role.OWNER, TenantMembership.Role.MANAGER],
            is_active=True,
        )
        .exists()
    )
    if not pode_convidar:
        messages.error(request, "Voce nao tem permissao para convidar nesta barbearia.")
        return redirect("core:painel")
    User = get_user_model()
    try:
        target = User.objects.get(email=email)
    except User.DoesNotExist:
        messages.error(request, "Nenhum usuario encontrado com este e-mail.")
        return redirect("core:painel")
    if ProfessionalInvitation.objects.bypass_tenant().filter(
        tenant_id=tenant_id, professional_user=target, status=ProfessionalInvitation.Status.PENDING,
    ).exists():
        messages.error(request, "Ja existe um convite pendente para este usuario nesta barbearia.")
        return redirect("core:painel")
    if TenantMembership.objects.bypass_tenant().filter(
        tenant_id=tenant_id, user=target, is_active=True,
    ).exists():
        messages.error(request, "Este usuario ja esta vinculado a esta barbearia.")
        return redirect("core:painel")
    ProfessionalInvitation.objects.bypass_tenant().create(
        tenant_id=tenant_id,
        professional_user=target,
        invited_by=request.user,
    )
    messages.success(request, "Convite enviado para {}!".format(email))
    return redirect("core:painel")


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
    is_admin = TenantMembership.objects.bypass_tenant().filter(
        user=request.user, tenant=inv.tenant,
        role__in=[TenantMembership.Role.OWNER, TenantMembership.Role.MANAGER],
        is_active=True,
    ).exists()
    if not (is_invitee or is_sender or is_admin or request.user.is_superadmin):
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
def profissional_cadastrar(request):
    """Cadastra um novo profissional (usuário) no painel."""
    if request.method != "POST":
        return redirect("core:painel")
    pode = (
        request.user.is_superadmin
        or request.user.role in ("owner", "manager")
        or TenantMembership.objects.bypass_tenant()
        .filter(user=request.user, role__in=[TenantMembership.Role.OWNER, TenantMembership.Role.MANAGER], is_active=True)
        .exists()
    )
    if not pode:
        messages.error(request, "Você não tem permissão para cadastrar profissionais.")
        return redirect("core:painel")
    name = request.POST.get("name", "").strip()
    tenant_id = request.POST.get("tenant_id", "").strip()
    role = request.POST.get("role", "").strip()
    password = request.POST.get("password", "")
    confirm = request.POST.get("confirm_password", "")
    if not name or " " not in name:
        messages.error(request, "Informe o nome e sobrenome do profissional.")
        return redirect("core:painel")
    if not tenant_id:
        messages.error(request, "Selecione a barbearia.")
        return redirect("core:painel")
    if not role:
        messages.error(request, "Selecione o perfil.")
        return redirect("core:painel")
    if not password or len(password) < 6:
        messages.error(request, "A senha deve ter no mínimo 6 caracteres.")
        return redirect("core:painel")
    if password != confirm:
        messages.error(request, "As senhas não conferem.")
        return redirect("core:painel")
    try:
        tenant_id = int(tenant_id)
    except (ValueError, TypeError):
        messages.error(request, "Barbearia inválida.")
        return redirect("core:painel")
    from .models import Tenant
    tenant = get_object_or_404(Tenant, pk=tenant_id)
    allowed_roles = {"professional"}
    if request.user.role == "owner" or request.user.is_superadmin:
        allowed_roles.add("manager")
    if request.user.is_superadmin:
        allowed_roles.add("owner")
    if role not in allowed_roles:
        messages.error(request, "Perfil não permitido.")
        return redirect("core:painel")
    User = get_user_model()
    first_name = name.rsplit(" ", 1)[0]
    last_name = name.rsplit(" ", 1)[1] if " " in name else ""
    email_base = name.lower().replace(" ", ".") + "@" + tenant.slug + ".local"
    if User.objects.filter(email=email_base).exists():
        messages.error(request, "Já existe um usuário com este e-mail gerado.")
        return redirect("core:painel")
    try:
        user = User.objects.create_user(
            email=email_base,
            password=password,
            tenant=tenant,
            role=role,
            first_name=first_name,
            last_name=last_name,
            is_active=True,
        )
        messages.success(request, f"Profissional '{name}' cadastrado com sucesso! E-mail: {email_base}")
    except Exception as e:
        messages.error(request, f"Erro ao cadastrar: {e}")
    return redirect("core:painel")


@login_required
def profissional_toggle_active(request, pk):
    """Alterna o status ativo/inativo de um profissional."""
    if request.method != "POST":
        return redirect("core:painel")
    prof = get_object_or_404(
        Professional.objects.bypass_tenant().select_related("tenant"),
        pk=pk,
    )
    pode = (
        request.user.is_superadmin
        or TenantMembership.objects.bypass_tenant()
        .filter(user=request.user, tenant=prof.tenant,
                role__in=[TenantMembership.Role.OWNER, TenantMembership.Role.MANAGER],
                is_active=True)
        .exists()
    )
    if not pode:
        messages.error(request, "Você não tem permissão para alterar este profissional.")
        return redirect("core:painel")
    prof.is_active = not prof.is_active
    prof.save(update_fields=["is_active"])
    status = "ativado" if prof.is_active else "desativado"
    messages.success(request, f"Profissional '{prof.user.get_full_name() or prof.user.email}' {status}.")
    return redirect("core:painel")


@login_required
def appointment_confirmar(request, pk):
    if request.method != "POST":
        return redirect("core:painel")
    appt = get_object_or_404(
        Appointment.objects.bypass_tenant(),
        pk=pk,
    )
    pode_gerenciar = (
        appt.professional.user_id == request.user.pk
        or TenantMembership.objects.bypass_tenant()
        .filter(user=request.user, tenant=appt.tenant,
                role__in=[TenantMembership.Role.OWNER, TenantMembership.Role.MANAGER],
                is_active=True)
        .exists()
        or request.user.is_superadmin
    )
    if not pode_gerenciar:
        raise PermissionDenied
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
        pk=pk,
    )
    pode_gerenciar = (
        appt.professional.user_id == request.user.pk
        or TenantMembership.objects.bypass_tenant()
        .filter(user=request.user, tenant=appt.tenant,
                role__in=[TenantMembership.Role.OWNER, TenantMembership.Role.MANAGER],
                is_active=True)
        .exists()
        or request.user.is_superadmin
    )
    if not pode_gerenciar:
        raise PermissionDenied
    if appt.status != Appointment.Status.CONFIRMED:
        messages.error(request, "So e possivel concluir agendamentos confirmados.")
        return redirect("core:painel")
    sess_in_progress = Session.objects.bypass_tenant().filter(
        appointment=appt, status=Session.Status.IN_PROGRESS,
    ).first()
    if sess_in_progress:
        messages.error(request, "Feche a conta do atendimento antes de concluir o agendamento.")
        return redirect("core:painel")
    appt.status = Appointment.Status.COMPLETED
    appt.save(update_fields=["status"])
    messages.success(request, "Agendamento de '{}' concluido. Pendente: registrar pagamento.".format(appt.client_name))
    return redirect("core:painel")


@login_required
def appointment_cancelar(request, pk):
    if request.method != "POST":
        return redirect("core:painel")
    appt = get_object_or_404(
        Appointment.objects.bypass_tenant(),
        pk=pk,
    )
    pode_gerenciar = (
        appt.professional.user_id == request.user.pk
        or TenantMembership.objects.bypass_tenant()
        .filter(user=request.user, tenant=appt.tenant,
                role__in=[TenantMembership.Role.OWNER, TenantMembership.Role.MANAGER],
                is_active=True)
        .exists()
        or request.user.is_superadmin
    )
    if not pode_gerenciar:
        raise PermissionDenied
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
        pk=pk, status=Appointment.Status.CONFIRMED,
    )
    pode_gerenciar = (
        appt.professional.user_id == request.user.pk
        or TenantMembership.objects.bypass_tenant()
        .filter(user=request.user, tenant=appt.tenant,
                role__in=[TenantMembership.Role.OWNER, TenantMembership.Role.MANAGER],
                is_active=True)
        .exists()
        or request.user.is_superadmin
    )
    if not pode_gerenciar:
        raise PermissionDenied
    if Session.objects.bypass_tenant().filter(appointment=appt, status=Session.Status.IN_PROGRESS).exists():
        messages.error(request, "Ja existe uma sessao em andamento para este agendamento.")
        return redirect("core:painel")
    prof = appt.professional
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


def _pode_gerenciar_sessao(user, sess):
    """Verifica se user pode gerenciar a sessao (profissional, owner, manager, superadmin)."""
    return (
        sess.professional.user_id == user.pk
        or TenantMembership.objects.bypass_tenant()
        .filter(user=user, tenant=sess.tenant,
                role__in=[TenantMembership.Role.OWNER, TenantMembership.Role.MANAGER],
                is_active=True)
        .exists()
        or user.is_superadmin
    )


@login_required
def sessao_adicionar_produto(request, pk):
    """Adiciona produto a uma sessao em andamento."""
    if request.method != "POST":
        return redirect("core:painel")
    sess = get_object_or_404(
        Session.objects.bypass_tenant(),
        pk=pk, status=Session.Status.IN_PROGRESS,
    )
    if not _pode_gerenciar_sessao(request.user, sess):
        raise PermissionDenied
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
        pk=pk, session__status=Session.Status.IN_PROGRESS,
    )
    if not _pode_gerenciar_sessao(request.user, item.session):
        raise PermissionDenied
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
        pk=pk, status=Session.Status.IN_PROGRESS,
    )
    if not _pode_gerenciar_sessao(request.user, sess):
        raise PermissionDenied
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
        pk=pk, status=Session.Status.IN_PROGRESS,
    )
    if not _pode_gerenciar_sessao(request.user, sess):
        raise PermissionDenied
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
    quantity = request.POST.get("quantity", "").strip()
    tenant_id = request.POST.get("tenant_id", "").strip()
    if not name or not price or not tenant_id:
        messages.error(request, "Nome, preco e barbearia sao obrigatorios.")
        return redirect("core:painel")
    try:
        price = Decimal(price)
    except Exception:
        messages.error(request, "Preco invalido.")
        return redirect("core:painel")
    qty = 0
    if quantity:
        try:
            qty = int(quantity)
        except (ValueError, TypeError):
            messages.error(request, "Quantidade invalida.")
            return redirect("core:painel")
    pode_gerenciar = (
        request.user.role in ("owner", "manager") or request.user.is_superadmin
        or TenantMembership.objects.bypass_tenant()
        .filter(user=request.user, tenant_id=tenant_id,
                role__in=[TenantMembership.Role.OWNER, TenantMembership.Role.MANAGER],
                is_active=True)
        .exists()
    )
    if not pode_gerenciar:
        messages.error(request, "Voce nao tem permissao para criar produtos nesta barbearia.")
        return redirect("core:painel")
    Product.objects.bypass_tenant().create(
        tenant_id=tenant_id, name=name, price=price, quantity=qty,
    )
    messages.success(request, "Produto '{}' criado (estoque: {}).".format(name, qty))
    return redirect("core:painel")


@login_required
def produto_toggle_active(request, pk):
    """Ativa/desativa um produto."""
    if request.method != "POST":
        return redirect("core:painel")
    prod = get_object_or_404(Product.objects.bypass_tenant(), pk=pk)
    if not _pode_gerenciar_produto(request.user, prod):
        raise PermissionDenied
    prod.is_active = not prod.is_active
    prod.save(update_fields=["is_active"])
    status = "ativado" if prod.is_active else "inativado"
    messages.success(request, "Produto '{}' {}.".format(prod.name, status))
    return redirect("core:painel")


def _pode_gerenciar_produto(user, prod):
    return (
        user.role in ("owner", "manager") or user.is_superadmin
        or TenantMembership.objects.bypass_tenant()
        .filter(user=user, tenant=prod.tenant,
                role__in=[TenantMembership.Role.OWNER, TenantMembership.Role.MANAGER],
                is_active=True)
        .exists()
    )


@login_required
def produto_abastecer(request, pk):
    """Adiciona quantidade ao estoque de um produto."""
    if request.method != "POST":
        return redirect("core:painel")
    prod = get_object_or_404(Product.objects.bypass_tenant(), pk=pk)
    if not _pode_gerenciar_produto(request.user, prod):
        raise PermissionDenied
    qty = request.POST.get("quantity", "").strip()
    if not qty:
        messages.error(request, "Quantidade obrigatoria.")
        return redirect("core:painel")
    try:
        qty = int(qty)
    except (ValueError, TypeError):
        messages.error(request, "Quantidade invalida.")
        return redirect("core:painel")
    if qty <= 0:
        messages.error(request, "Quantidade deve ser positiva.")
        return redirect("core:painel")
    from .models import StockMovement
    StockMovement.objects.bypass_tenant().create(
        tenant=prod.tenant,
        product=prod,
        quantity=qty,
        movement_type=StockMovement.MovementType.RESTOCK,
        description=request.POST.get("description", "").strip(),
        created_by=request.user,
    )
    Product.objects.bypass_tenant().filter(pk=prod.pk).update(
        quantity=models.F("quantity") + qty
    )
    messages.success(request, "Estoque de '{}' atualizado: +{} unidades.".format(prod.name, qty))
    return redirect("core:painel")


@login_required
def produto_movimentacoes(request, pk):
    """Exibe historico de movimentacoes de um produto."""
    prod = get_object_or_404(Product.objects.bypass_tenant(), pk=pk)
    if not _pode_gerenciar_produto(request.user, prod):
        raise PermissionDenied
    from .models import StockMovement
    movs = (
        StockMovement.objects.bypass_tenant()
        .filter(product=prod)
        .select_related("created_by", "session")
        .order_by("-created_at")
    )
    return render(request, "core/movimentacoes.html", {
        "produto": prod,
        "movimentacoes": movs,
    })


@login_required
def pagamento_registrar(request, pk):
    """Registra pagamento manual para uma sessao concluida."""
    if request.method != "POST":
        return redirect("core:painel")
    sess = get_object_or_404(
        Session.objects.bypass_tenant(),
        pk=pk, status=Session.Status.COMPLETED,
    )
    if not _pode_gerenciar_sessao(request.user, sess):
        raise PermissionDenied
    if hasattr(sess, "payment"):
        messages.error(request, "Esta sessao ja possui pagamento registrado.")
        return redirect("core:painel")
    amount = request.POST.get("amount", "").strip()
    method = request.POST.get("payment_method", "").strip()
    if not amount or not method:
        messages.error(request, "Valor e forma de pagamento sao obrigatorios.")
        return redirect("core:painel")
    try:
        amount = Decimal(amount)
    except Exception:
        messages.error(request, "Valor invalido.")
        return redirect("core:painel")
    if method not in dict(Payment.PaymentMethod.choices):
        messages.error(request, "Forma de pagamento invalida.")
        return redirect("core:painel")
    Payment.objects.bypass_tenant().create(
        tenant=sess.tenant,
        session=sess,
        amount=amount,
        payment_method=method,
        confirmed_by=request.user,
    )
    if sess.appointment and sess.appointment.status == Appointment.Status.CONFIRMED:
        sess.appointment.status = Appointment.Status.COMPLETED
        sess.appointment.save(update_fields=["status"])
    messages.success(
        request,
        "Pagamento de R$ {:.2f} registrado para '{}'! Agendamento concluido.".format(amount, sess.client_name),
    )
    return redirect("core:painel")
