"""Views da Pagina Publica - Sprint 4 (PRD S9 - modulo Pagina publica).

Rota publica (sem auth) que exibe a barbearia + seus servicos ativos,
seguindo o design system do projeto. PRD S23: carregamento < 2s.

Sprint 6 - Agendamento publico: /<slug>/agendar/ (PRD S10 - fluxo cliente).
"""
from datetime import datetime, timedelta

from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import DetailView, View

from core.models import (
    Appointment,
    BusinessHours,
    Professional,
    ProfessionalAvailability,
    ProfessionalService,
    Service,
    Tenant,
    set_current_tenant,
)


class BarbeariaPublicaView(DetailView):
    """Pagina publica de uma barbearia: /<slug>/."""

    model = Tenant
    template_name = "publico/barbearia.html"
    context_object_name = "barbearia"
    slug_field = "slug"
    slug_url_kwarg = "slug"

    def get_queryset(self):
        return Tenant.objects.filter(is_active=True)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        tenant = self.object
        ctx["servicos"] = (
            Service.objects.bypass_tenant().filter(tenant=tenant, is_active=True)
        )
        ctx["horarios"] = (
            BusinessHours.objects.bypass_tenant().filter(tenant=tenant)
            .order_by("weekday")
        )
        return ctx


def _get_available_slots(tenant, professional, date_obj, duration_min):
    """Retorna lista de horarios disponiveis para o profissional na data."""
    weekday = (date_obj.weekday() + 1) % 7

    avail = (
        ProfessionalAvailability.objects.bypass_tenant()
        .filter(
            tenant=tenant, professional=professional,
            weekday=weekday, available=True,
        ).first()
    )
    if avail is None:
        return []

    if avail.break_start and avail.break_end:
        avail_intervals = [
            (avail.start_time, avail.break_start),
            (avail.break_end, avail.end_time),
        ]
    else:
        avail_intervals = [(avail.start_time, avail.end_time)]

    booked = list(
        Appointment.objects.bypass_tenant()
        .filter(
            tenant=tenant, professional=professional, date=date_obj,
            status__in=[Appointment.Status.PENDING, Appointment.Status.CONFIRMED],
        ).values_list("start_time", "end_time")
    )

    slots = []
    for interval_start, interval_end in avail_intervals:
        base = datetime(2000, 1, 1)
        cur = datetime.combine(base, interval_start)
        end_dt = datetime.combine(base, interval_end)
        step = timedelta(minutes=duration_min)
        while cur + step <= end_dt:
            slot_start = cur.time()
            slot_end = (cur + step).time()
            conflict = False
            for b_start, b_end in booked:
                if slot_start < b_end and b_start < slot_end:
                    conflict = True
                    break
            if not conflict:
                slots.append(slot_start)
            cur += step
    return slots


class AgendamentoView(View):
    """Pagina de agendamento publico: /<slug>/agendar/.

    Fluxo: seleciona profissional -> servico -> data -> horario -> confirma.
    Tudo numa unica pagina com filtros dinamicos via GET params.
    """

    template_name = "publico/agendar.html"

    def get_barbearia(self, slug):
        return get_object_or_404(Tenant, slug=slug, is_active=True)

    def get(self, request, slug):
        barbearia = self.get_barbearia(slug)
        set_current_tenant(barbearia, bypass=False, user=None)

        profissionais = list(
            Professional.objects.bypass_tenant()
            .filter(tenant=barbearia, is_active=True)
            .select_related("user")
        )
        servicos = list(
            Service.objects.bypass_tenant()
            .filter(tenant=barbearia, is_active=True)
        )

        prof_id = request.GET.get("professional")
        svc_id = request.GET.get("service")
        date_str = request.GET.get("date")

        selected_prof = None
        selected_svc = None
        selected_date = None

        if prof_id:
            selected_prof = next((p for p in profissionais if str(p.pk) == prof_id), None)
        if svc_id:
            selected_svc = next((s for s in servicos if str(s.pk) == svc_id), None)
        if date_str:
            try:
                selected_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                selected_date = None

        available_slots = []
        if selected_prof and selected_svc and selected_date:
            available_slots = _get_available_slots(
                barbearia, selected_prof, selected_date,
                selected_svc.duration_minutes,
            )

        servicos_por_prof = {}
        for p in profissionais:
            psvc_ids = set(
                ProfessionalService.objects.bypass_tenant()
                .filter(professional=p)
                .values_list("service_id", flat=True)
            )
            servicos_por_prof[str(p.pk)] = [s.pk for s in servicos if s.pk in psvc_ids]

        import json
        ctx = {
            "barbearia": barbearia,
            "profissionais": profissionais,
            "servicos": servicos,
            "servicos_por_prof_json": json.dumps(servicos_por_prof),
            "selected_prof": selected_prof,
            "selected_svc": selected_svc,
            "selected_date": selected_date,
            "date_str": date_str or "",
            "available_slots": available_slots,
        }
        return render(request, self.template_name, ctx)

    def post(self, request, slug):
        barbearia = self.get_barbearia(slug)

        prof_id = request.POST.get("professional")
        svc_id = request.POST.get("service")
        date_str = request.POST.get("date")
        start_time_str = request.POST.get("start_time")
        client_name = request.POST.get("client_name", "").strip()
        client_phone = request.POST.get("client_phone", "").strip()
        client_email = request.POST.get("client_email", "").strip()

        errors = []

        if not all([prof_id, svc_id, date_str, start_time_str, client_name, client_phone]):
            errors.append("Todos os campos sao obrigatorios (exceto e-mail).")

        prof = None
        svc = None
        apt_date = None
        start_time = None

        if prof_id:
            prof = (
                Professional.objects.bypass_tenant()
                .filter(pk=prof_id, tenant=barbearia, is_active=True)
                .first()
            )
            if not prof:
                errors.append("Profissional invalido.")
        if svc_id:
            svc = (
                Service.objects.bypass_tenant()
                .filter(pk=svc_id, tenant=barbearia, is_active=True)
                .first()
            )
            if not svc:
                errors.append("Servico invalido.")
        if date_str:
            try:
                apt_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                errors.append("Data invalida.")
        if start_time_str:
            try:
                start_time = datetime.strptime(start_time_str, "%H:%M").time()
            except ValueError:
                errors.append("Horario invalido.")

        if not errors and prof and svc and apt_date and start_time:
            set_current_tenant(barbearia, bypass=False, user=None)
            apt = Appointment(
                tenant=barbearia,
                professional=prof,
                service=svc,
                client_name=client_name,
                client_phone=client_phone,
                client_email=client_email,
                date=apt_date,
                start_time=start_time,
                status=Appointment.Status.PENDING,
            )
            try:
                apt.full_clean()
                apt.save()
                return redirect("publico:agendar_sucesso", slug=slug)
            except Exception as e:
                if hasattr(e, "message_dict"):
                    for field, msgs in e.message_dict.items():
                        for msg in msgs:
                            errors.append(msg)
                elif hasattr(e, "messages"):
                    errors.extend(e.messages)
                else:
                    errors.append(str(e))

        profissionais = list(
            Professional.objects.bypass_tenant()
            .filter(tenant=barbearia, is_active=True)
            .select_related("user")
        )
        servicos = list(
            Service.objects.bypass_tenant()
            .filter(tenant=barbearia, is_active=True)
        )

        available_slots = []
        if prof and svc and apt_date:
            available_slots = _get_available_slots(
                barbearia, prof, apt_date, svc.duration_minutes,
            )

        ctx = {
            "barbearia": barbearia,
            "profissionais": profissionais,
            "servicos": servicos,
            "selected_prof": prof,
            "selected_svc": svc,
            "selected_date": apt_date,
            "date_str": date_str or "",
            "available_slots": available_slots,
            "errors": errors,
            "form_data": {
                "client_name": client_name,
                "client_phone": client_phone,
                "client_email": client_email,
            },
        }
        return render(request, self.template_name, ctx)


class AgendamentoSucessoView(DetailView):
    """Pagina de confirmacao apos agendar: /<slug>/agendar/sucesso/."""

    model = Tenant
    template_name = "publico/agendar_sucesso.html"
    context_object_name = "barbearia"
    slug_field = "slug"
    slug_url_kwarg = "slug"

    def get_queryset(self):
        return Tenant.objects.filter(is_active=True)
