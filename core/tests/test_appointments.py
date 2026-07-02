"""
Testes - Sprint 6: Agendamento (Core).

Cobre:
  1. Criacao de agendamento valido.
  2. Bloqueio de conflito de horario (dois agendamentos no mesmo slot).
  3. Agendamento fora do expediente da barbearia.
  4. Agendamento fora da disponibilidade do profissional.
  5. Profissional nao oferece o servico.
  6. Data passada bloqueada.
  7. Cancelamento libera o slot.
  8. Isolamento multi-tenant (agendamento em tenant alheio).
  9. Fluxo publico completo (GET + POST).
  10. Conflito com horarios sobrepostos (nao mesmo inicio).

Rodar: python manage.py test core.tests.test_appointments
"""
import datetime as dt

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from base.models import User
from core.models import (
    Appointment,
    BusinessHours,
    Professional,
    ProfessionalAvailability,
    ProfessionalService,
    Service,
    Tenant,
    TenantMembership,
    set_current_tenant,
)

User = get_user_model()


def _tomorrow_weekday():
    """Retorna a data de amanha (sempre futura)."""
    return dt.date.today() + dt.timedelta(days=1)


def _weekday_num(date_obj):
    """Converte date.weekday() (0=Seg) para o padrao do sistema (0=Dom)."""
    return (date_obj.weekday() + 1) % 7


class AppointmentBaseTestCase(TestCase):
    """Setup compartilhado: tenant, profissional, servico, disponibilidade."""

    @classmethod
    def setUpTestData(cls):
        set_current_tenant(None, bypass=False, user=None)
        cls.tenant = Tenant.objects.create(name="Agend Test", slug="agend-test")
        cls.tenant2 = Tenant.objects.create(name="Agend Test 2", slug="agend-test-2")

        cls.prof_user = User.objects.create_user(
            email="prof-agend@test.com", password="x", tenant=cls.tenant,
            role=User.Role.PROFESSIONAL,
        )
        cls.prof, _ = Professional.objects.bypass_tenant().get_or_create(
            tenant=cls.tenant, user=cls.prof_user,
            defaults={"is_active": True},
        )
        cls.svc = Service.objects.bypass_tenant().create(
            tenant=cls.tenant, name="Corte Agend", duration_minutes=30,
        )
        ProfessionalService.objects.bypass_tenant().create(
            tenant=cls.tenant, professional=cls.prof, service=cls.svc,
        )

        cls.tomorrow = _tomorrow_weekday()
        cls.wd = _weekday_num(cls.tomorrow)

        bh = BusinessHours.objects.bypass_tenant().get(
            tenant=cls.tenant, weekday=cls.wd,
        )
        bh.is_open = True
        bh.open_time = dt.time(8, 0)
        bh.close_time = dt.time(18, 0)
        bh.save()

        avail = ProfessionalAvailability.objects.bypass_tenant().get(
            tenant=cls.tenant, professional=cls.prof, weekday=cls.wd,
        )
        avail.available = True
        avail.start_time = dt.time(8, 0)
        avail.end_time = dt.time(18, 0)
        avail.save()

    def setUp(self):
        set_current_tenant(self.tenant, bypass=False, user=None)


class AppointmentConflictTests(AppointmentBaseTestCase):
    """Bloqueio de conflito de horario (PRD S11)."""

    def test_criar_agendamento_valido(self):
        apt = Appointment(
            tenant=self.tenant,
            professional=self.prof,
            service=self.svc,
            client_name="Joao Silva",
            client_phone="11999999999",
            date=self.tomorrow,
            start_time=dt.time(9, 0),
        )
        apt.full_clean()
        apt.save()
        self.assertEqual(apt.status, Appointment.Status.PENDING)
        self.assertEqual(apt.end_time, dt.time(9, 30))

    def test_bloqueia_conflito_mesmo_horario(self):
        apt1 = Appointment(
            tenant=self.tenant, professional=self.prof, service=self.svc,
            client_name="Cliente A", client_phone="111",
            date=self.tomorrow, start_time=dt.time(10, 0),
        )
        apt1.full_clean()
        apt1.save()

        apt2 = Appointment(
            tenant=self.tenant, professional=self.prof, service=self.svc,
            client_name="Cliente B", client_phone="222",
            date=self.tomorrow, start_time=dt.time(10, 0),
        )
        with self.assertRaises(ValidationError):
            apt2.full_clean()

    def test_bloqueia_conflito_sobreposto(self):
        """Agendamento 10:00-10:30 conflita com 10:15-10:45."""
        apt1 = Appointment(
            tenant=self.tenant, professional=self.prof, service=self.svc,
            client_name="Cliente A", client_phone="111",
            date=self.tomorrow, start_time=dt.time(10, 0),
        )
        apt1.full_clean()
        apt1.save()

        svc60 = Service.objects.bypass_tenant().create(
            tenant=self.tenant, name="Barba Agend", duration_minutes=60,
        )
        ProfessionalService.objects.bypass_tenant().create(
            tenant=self.tenant, professional=self.prof, service=svc60,
        )
        apt2 = Appointment(
            tenant=self.tenant, professional=self.prof, service=svc60,
            client_name="Cliente B", client_phone="222",
            date=self.tomorrow, start_time=dt.time(10, 15),
        )
        with self.assertRaises(ValidationError):
            apt2.full_clean()

    def test_cancelamento_libera_slot(self):
        apt1 = Appointment(
            tenant=self.tenant, professional=self.prof, service=self.svc,
            client_name="Cliente A", client_phone="111",
            date=self.tomorrow, start_time=dt.time(10, 0),
        )
        apt1.full_clean()
        apt1.save()
        apt1.status = Appointment.Status.CANCELLED
        apt1.save(update_fields=["status"])

        apt2 = Appointment(
            tenant=self.tenant, professional=self.prof, service=self.svc,
            client_name="Cliente B", client_phone="222",
            date=self.tomorrow, start_time=dt.time(10, 0),
        )
        apt2.full_clean()
        apt2.save()
        self.assertEqual(apt2.status, Appointment.Status.PENDING)


class AppointmentValidationTests(AppointmentBaseTestCase):
    """Validacoes de horario, disponibilidade, servico, data."""

    def test_bloqueia_fora_expediente_barbearia(self):
        apt = Appointment(
            tenant=self.tenant, professional=self.prof, service=self.svc,
            client_name="Cliente", client_phone="111",
            date=self.tomorrow, start_time=dt.time(7, 0),
        )
        with self.assertRaises(ValidationError):
            apt.full_clean()

    def test_bloqueia_profissional_indisponivel(self):
        wd = (_weekday_num(self.tomorrow) + 1) % 7
        if wd == 0:
            wd = 1
        other_date = self.tomorrow + dt.timedelta(days=1)
        while _weekday_num(other_date) != wd:
            other_date += dt.timedelta(days=1)

        bh_other = BusinessHours.objects.bypass_tenant().get(
            tenant=self.tenant, weekday=_weekday_num(other_date),
        )
        bh_other.is_open = True
        bh_other.open_time = dt.time(8, 0)
        bh_other.close_time = dt.time(18, 0)
        bh_other.save()

        avail_other = ProfessionalAvailability.objects.bypass_tenant().get(
            tenant=self.tenant, professional=self.prof,
            weekday=_weekday_num(other_date),
        )
        avail_other.available = False
        avail_other.save()

        apt = Appointment(
            tenant=self.tenant, professional=self.prof, service=self.svc,
            client_name="Cliente", client_phone="111",
            date=other_date, start_time=dt.time(10, 0),
        )
        with self.assertRaises(ValidationError):
            apt.full_clean()

    def test_bloqueia_servico_nao_vinculado(self):
        svc2 = Service.objects.bypass_tenant().create(
            tenant=self.tenant, name="Outro Serv", duration_minutes=30,
        )
        apt = Appointment(
            tenant=self.tenant, professional=self.prof, service=svc2,
            client_name="Cliente", client_phone="111",
            date=self.tomorrow, start_time=dt.time(10, 0),
        )
        with self.assertRaises(ValidationError):
            apt.full_clean()

    def test_bloqueia_data_passada(self):
        yesterday = dt.date.today() - dt.timedelta(days=1)
        apt = Appointment(
            tenant=self.tenant, professional=self.prof, service=self.svc,
            client_name="Cliente", client_phone="111",
            date=yesterday, start_time=dt.time(10, 0),
        )
        with self.assertRaises(ValidationError):
            apt.full_clean()

    def test_bloqueia_profissional_inativo(self):
        self.prof.is_active = False
        self.prof.save(update_fields=["is_active"])
        apt = Appointment(
            tenant=self.tenant, professional=self.prof, service=self.svc,
            client_name="Cliente", client_phone="111",
            date=self.tomorrow, start_time=dt.time(10, 0),
        )
        with self.assertRaises(ValidationError):
            apt.full_clean()
        self.prof.is_active = True
        self.prof.save(update_fields=["is_active"])


class AppointmentMultiTenantTests(AppointmentBaseTestCase):
    """Isolamento multi-tenant em agendamentos."""

    def test_agendamento_isolado_por_tenant(self):
        prof2 = Professional.objects.bypass_tenant().create(
            tenant=self.tenant2, user=self.prof_user, is_active=True,
        )
        svc2 = Service.objects.bypass_tenant().create(
            tenant=self.tenant2, name="Corte T2", duration_minutes=30,
        )
        ProfessionalService.objects.bypass_tenant().create(
            tenant=self.tenant2, professional=prof2, service=svc2,
        )

        bh2 = BusinessHours.objects.bypass_tenant().get(
            tenant=self.tenant2, weekday=self.wd,
        )
        bh2.is_open = True
        bh2.open_time = dt.time(8, 0)
        bh2.close_time = dt.time(18, 0)
        bh2.save()

        avail2 = ProfessionalAvailability.objects.bypass_tenant().get(
            tenant=self.tenant2, professional=prof2, weekday=self.wd,
        )
        avail2.available = True
        avail2.start_time = dt.time(8, 0)
        avail2.end_time = dt.time(18, 0)
        avail2.save()

        apt = Appointment(
            tenant=self.tenant, professional=self.prof, service=self.svc,
            client_name="Cliente", client_phone="111",
            date=self.tomorrow, start_time=dt.time(10, 0),
        )
        apt.full_clean()
        apt.save()

        set_current_tenant(self.tenant2, bypass=False, user=None)
        apt_t2 = Appointment(
            tenant=self.tenant2, professional=prof2, service=svc2,
            client_name="Cliente T2", client_phone="222",
            date=self.tomorrow, start_time=dt.time(10, 0),
        )
        apt_t2.full_clean()
        apt_t2.save()

        set_current_tenant(self.tenant, bypass=False, user=None)
        count_t1 = Appointment.objects.bypass_tenant().filter(
            tenant=self.tenant,
        ).count()
        count_t2 = Appointment.objects.bypass_tenant().filter(
            tenant=self.tenant2,
        ).count()
        self.assertEqual(count_t1, 1)
        self.assertEqual(count_t2, 1)


class AgendamentoPublicoTests(AppointmentBaseTestCase):
    """Fluxo publico: cliente -> agendamento via web."""

    def test_get_pagina_agendamento(self):
        resp = self.client.get(
            reverse("publico:agendar", args=[self.tenant.slug])
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "AGENDAR")
        self.assertContains(resp, self.prof.__str__())
        self.assertContains(resp, self.svc.name)

    def test_get_pagina_agendamento_barbearia_inativa(self):
        self.tenant.is_active = False
        self.tenant.save(update_fields=["is_active"])
        resp = self.client.get(
            reverse("publico:agendar", args=[self.tenant.slug])
        )
        self.assertEqual(resp.status_code, 404)
        self.tenant.is_active = True
        self.tenant.save(update_fields=["is_active"])

    def test_post_cria_agendamento(self):
        resp = self.client.post(
            reverse("publico:agendar", args=[self.tenant.slug]),
            data={
                "professional": str(self.prof.pk),
                "service": str(self.svc.pk),
                "date": self.tomorrow.strftime("%Y-%m-%d"),
                "start_time": "11:00",
                "client_name": "Cliente Web",
                "client_phone": "11988887777",
                "client_email": "cliente@test.com",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            Appointment.objects.bypass_tenant().filter(
                tenant=self.tenant,
                client_name="Cliente Web",
                start_time=dt.time(11, 0),
            ).exists()
        )

    def test_post_conflito_retorna_erro(self):
        apt1 = Appointment(
            tenant=self.tenant, professional=self.prof, service=self.svc,
            client_name="Cliente A", client_phone="111",
            date=self.tomorrow, start_time=dt.time(10, 0),
        )
        apt1.full_clean()
        apt1.save()

        resp = self.client.post(
            reverse("publico:agendar", args=[self.tenant.slug]),
            data={
                "professional": str(self.prof.pk),
                "service": str(self.svc.pk),
                "date": self.tomorrow.strftime("%Y-%m-%d"),
                "start_time": "10:00",
                "client_name": "Cliente B",
                "client_phone": "222",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(
            Appointment.objects.bypass_tenant().filter(
                client_name="Cliente B",
            ).exists()
        )

    def test_get_slots_disponiveis(self):
        resp = self.client.get(
            reverse("publico:agendar", args=[self.tenant.slug]),
            data={
                "professional": str(self.prof.pk),
                "service": str(self.svc.pk),
                "date": self.tomorrow.strftime("%Y-%m-%d"),
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "09:00")
        self.assertContains(resp, "10:00")

    def test_get_slots_exclui_ocupados(self):
        apt = Appointment(
            tenant=self.tenant, professional=self.prof, service=self.svc,
            client_name="Cliente A", client_phone="111",
            date=self.tomorrow, start_time=dt.time(10, 0),
        )
        apt.full_clean()
        apt.save()

        resp = self.client.get(
            reverse("publico:agendar", args=[self.tenant.slug]),
            data={
                "professional": str(self.prof.pk),
                "service": str(self.svc.pk),
                "date": self.tomorrow.strftime("%Y-%m-%d"),
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "10:00")

    def test_pagina_sucesso(self):
        resp = self.client.get(
            reverse("publico:agendar_sucesso", args=[self.tenant.slug])
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Confirmado")
