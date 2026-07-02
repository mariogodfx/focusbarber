"""
Testes do Sprint 5+ — Horário de funcionamento + Disponibilidade do profissional.

Validação (PRD §26 — Sprint 5 "MANUAL (CRÍTICO)"):
  ✅ horário de funcionamento da barbearia (BusinessHours, flag por dia)
  ✅ disponibilidade do profissional (ProfessionalAvailability, mesmo formato)
  ✅ conformidade da disponibilidade do profissional com a barbearia:
     • Fora do expediente da barbearia => rejeitado
     • Barbearia fechada no dia => rejeitado
     • Intervalo do profissional precisa cobrir o intervalo da barbearia

Roda:  python manage.py test core.tests.test_sprint5
"""
from datetime import time

from django.contrib.admin.sites import AdminSite
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase

from base.models import User
from core.admin import ProfessionalAdmin, ProfessionalServiceInline
from core.models import (
    BusinessHours,
    Professional,
    ProfessionalAvailability,
    ProfessionalService,
    Service,
    Tenant,
    set_current_tenant,
)


def _make_pro(tenant, email):
    u = User.objects.create_user(
        email=email, password="x", tenant=tenant, role=User.Role.PROFESSIONAL,
        first_name="Barb", last_name="Test",
    )
    # O signal auto_create_membership_and_professional já cria o Professional
    # (e o TenantMembership) ao criar o usuário professional com tenant.
    return Professional.objects.bypass_tenant().get(tenant=tenant, user=u)


class BusinessHoursTests(TestCase):
    def setUp(self):
        self.t = Tenant.objects.create(name="A", slug="a")

    def test_signal_cria_7_linhas_padrao(self):
        # Signal post_save do Tenant cria 7 linhas (uma por dia), todas fechadas.
        rows = BusinessHours.objects.bypass_tenant().filter(tenant=self.t)
        self.assertEqual(rows.count(), 7)
        self.assertFalse(any(r.is_open for r in rows))

    def test_abrir_dia_com_intervalo_valido(self):
        seg = BusinessHours.objects.bypass_tenant().get(tenant=self.t, weekday=1)
        seg.is_open = True
        seg.open_time = time(8, 0)
        seg.close_time = time(20, 0)
        seg.break_start = time(12, 0)
        seg.break_end = time(14, 0)
        seg.full_clean()  # não levanta

    def test_intervalo_fora_do_expediente_rejeitado(self):
        seg = BusinessHours.objects.bypass_tenant().get(tenant=self.t, weekday=1)
        seg.is_open = True
        seg.open_time = time(8, 0)
        seg.close_time = time(18, 0)
        seg.break_start = time(11, 0)
        seg.break_end = time(19, 0)  # foge do expediente
        with self.assertRaises(ValidationError):
            seg.full_clean()

    def test_dia_fechado_nao_valida_horarios(self):
        seg = BusinessHours.objects.bypass_tenant().get(tenant=self.t, weekday=0)
        # is_open=False default — sem validação de horários.
        seg.full_clean()


class ProfessionalAvailabilityTests(TestCase):
    def setUp(self):
        self.t = Tenant.objects.create(name="A", slug="a")
        self.pro = _make_pro(self.t, "barb@a.test")

    def test_signal_cria_7_linhas_padrao(self):
        rows = ProfessionalAvailability.objects.bypass_tenant().filter(professional=self.pro)
        self.assertEqual(rows.count(), 7)
        self.assertFalse(any(r.available for r in rows))

    def _config_loja(self, weekday, *, opened, open_t, close_t, brk=None):
        bh = BusinessHours.objects.bypass_tenant().get(tenant=self.t, weekday=weekday)
        bh.is_open = opened
        bh.open_time = open_t
        bh.close_time = close_t
        if brk:
            bh.break_start, bh.break_end = brk
        else:
            bh.break_start = bh.break_end = None
        bh.save()
        return bh

    def test_disp_dentro_do_expediente_ok(self):
        self._config_loja(1, opened=True, open_t=time(8, 0), close_t=time(20, 0),
                          brk=(time(12, 0), time(14, 0)))
        pa = ProfessionalAvailability.objects.bypass_tenant().get(
            tenant=self.t, professional=self.pro, weekday=1
        )
        pa.available = True
        pa.start_time = time(8, 0)
        pa.end_time = time(20, 0)
        pa.break_start = time(12, 0)
        pa.break_end = time(14, 0)
        pa.full_clean()  # não levanta

    def test_disp_inicio_antes_abertura_barbearia_rejeitado(self):
        self._config_loja(1, opened=True, open_t=time(8, 0), close_t=time(20, 0),
                          brk=(time(12, 0), time(14, 0)))
        pa = ProfessionalAvailability.objects.bypass_tenant().get(
            tenant=self.t, professional=self.pro, weekday=1
        )
        pa.available = True
        pa.start_time = time(7, 0)  # antes da abertura
        pa.end_time = time(20, 0)
        pa.break_start = time(12, 0)
        pa.break_end = time(14, 0)
        with self.assertRaises(ValidationError):
            pa.full_clean()

    def test_disp_fim_apos_fechamento_barbearia_rejeitado(self):
        self._config_loja(1, opened=True, open_t=time(8, 0), close_t=time(18, 0),
                          brk=(time(12, 0), time(13, 0)))
        pa = ProfessionalAvailability.objects.bypass_tenant().get(
            tenant=self.t, professional=self.pro, weekday=1
        )
        pa.available = True
        pa.start_time = time(8, 0)
        pa.end_time = time(19, 0)  # depois do fechamento
        pa.break_start = time(12, 0)
        pa.break_end = time(13, 0)
        with self.assertRaises(ValidationError):
            pa.full_clean()

    def test_disp_dia_barbearia_fechada_rejeitado(self):
        # Domingo fechado (default).
        pa = ProfessionalAvailability.objects.bypass_tenant().get(
            tenant=self.t, professional=self.pro, weekday=0
        )
        pa.available = True
        pa.start_time = time(8, 0)
        pa.end_time = time(12, 0)
        with self.assertRaises(ValidationError):
            pa.full_clean()

    def test_sem_intervalo_profissional_quando_loja_tem_e_trabalha_no_almoço_rejeitado(self):
        # Loja 8-20 break 12-14; profissional trabalha 8-20 sem break próprio =>
        # atenderia das 12 às 14 (loja fechada). REJEITADO.
        self._config_loja(1, opened=True, open_t=time(8, 0), close_t=time(20, 0),
                          brk=(time(12, 0), time(14, 0)))
        pa = ProfessionalAvailability.objects.bypass_tenant().get(
            tenant=self.t, professional=self.pro, weekday=1
        )
        pa.available = True
        pa.start_time = time(8, 0)
        pa.end_time = time(20, 0)
        with self.assertRaises(ValidationError):
            pa.full_clean()

    def test_morning_only_profissional_sem_intervalo_ok(self):
        # Profissional trabalha só das 9 às 12 (acaba antes do almoço da loja).
        # Não precisa de break — não está presente durante o intervalo da loja.
        self._config_loja(1, opened=True, open_t=time(8, 0), close_t=time(20, 0),
                          brk=(time(12, 0), time(14, 0)))
        pa = ProfessionalAvailability.objects.bypass_tenant().get(
            tenant=self.t, professional=self.pro, weekday=1
        )
        pa.available = True
        pa.start_time = time(9, 0)
        pa.end_time = time(12, 0)  # termina exatamente no início do break da loja
        pa.full_clean()  # não levanta

    def test_exp_prof_sobrepoe_break_loja_rejeitado(self):
        # Profissional 13-20 (tarde) mas break 12-14 da loja: o expediente dele
        # começa 13h, dentro do break da loja (12-14) => rejeitado.
        self._config_loja(1, opened=True, open_t=time(8, 0), close_t=time(20, 0),
                          brk=(time(12, 0), time(14, 0)))
        pa = ProfessionalAvailability.objects.bypass_tenant().get(
            tenant=self.t, professional=self.pro, weekday=1
        )
        pa.available = True
        pa.start_time = time(13, 0)  # dentro do break da loja
        pa.end_time = time(20, 0)
        with self.assertRaises(ValidationError):
            pa.full_clean()

    def test_disp_valida_mesmo_parcial_dentro_do_expediente(self):
        # profissional trabalha só das 9 às 17 (dentro do expediente 8-20),
        # com break 12-14 cobrindo o break da loja — OK.
        self._config_loja(2, opened=True, open_t=time(8, 0), close_t=time(20, 0),
                          brk=(time(12, 0), time(14, 0)))
        pa = ProfessionalAvailability.objects.bypass_tenant().get(
            tenant=self.t, professional=self.pro, weekday=2
        )
        pa.available = True
        pa.start_time = time(9, 0)
        pa.end_time = time(17, 0)
        pa.break_start = time(12, 0)
        pa.break_end = time(14, 0)
        pa.full_clean()  # não levanta

    def test_pa_de_profissional_cross_tenant_rejeitado(self):
        t2 = Tenant.objects.create(name="B", slug="b")
        pro_b = _make_pro(t2, "barb@b.test")
        pa = ProfessionalAvailability(
            tenant=self.t, professional=pro_b, weekday=1,
            available=True, start_time=time(8, 0), end_time=time(18, 0),
        )
        with self.assertRaises(ValidationError):
            pa.full_clean()


class VinculoProfissionalTests(TestCase):
    """Re-valida vínculo professional × service (continua do Sprint 5 original)."""

    def setUp(self):
        self.t1 = Tenant.objects.create(name="A", slug="a")
        self.t2 = Tenant.objects.create(name="B", slug="b")
        set_current_tenant(self.t1, bypass=False)
        self.svc_a1 = Service.objects.create(tenant=self.t1, name="Corte", duration_minutes=30)
        set_current_tenant(self.t2, bypass=False)
        self.svc_b1 = Service.objects.create(tenant=self.t2, name="Corte", duration_minutes=30)
        set_current_tenant(None, bypass=False)
        self.pro = _make_pro(self.t1, "barb@a.test")

    def test_vincula_servico_do_mesmo_tenant(self):
        set_current_tenant(self.t1, bypass=False)
        try:
            ProfessionalService.objects.create(
                tenant=self.t1, professional=self.pro, service=self.svc_a1
            )
            self.assertEqual(self.pro.services.count(), 1)
        finally:
            set_current_tenant(None, bypass=False)

    def test_vincula_servico_de_outro_tenant_bloqueado(self):
        set_current_tenant(self.t1, bypass=False)
        try:
            ps = ProfessionalService(tenant=self.t1, professional=self.pro, service=self.svc_b1)
            with self.assertRaises(ValidationError):
                ps.full_clean()
        finally:
            set_current_tenant(None, bypass=False)


class OwnerComoProfissionalTests(TestCase):
    """Dono da barbearia (role=owner) pode ser cadastrado como profissional
    e configurar seus próprios horários de atendimento."""

    def setUp(self):
        from core.models import TenantMembership
        self.t = Tenant.objects.create(name="A", slug="a")
        self.owner = User.objects.create_user(
            email="dono@a.test", password="x", tenant=self.t,
            role=User.Role.OWNER, first_name="Carlos", last_name="Dono",
        )
        # O signal já cria a membership(owner) ao criar o usuário; usamos
        # get_or_create para idempotência.
        TenantMembership.objects.bypass_tenant().get_or_create(
            tenant=self.t,
            user=self.owner,
            role=TenantMembership.Role.OWNER,
        )

    def test_owner_pode_ser_profissional(self):
        pro = Professional(tenant=self.t, user=self.owner)
        pro.full_clean()  # não levanta
        pro.save()
        self.assertTrue(
            Professional.objects.bypass_tenant().get(tenant=self.t, user=self.owner).pk
        )
        self.assertTrue(pro.is_owner_professional)

    def test_owner_configura_disponibilidade(self):
        # Cria BusinessHours Seg aberto 9-18 e ProfessionalAvailability
        # do dono dentro desse expediente — deve ser aceito.
        from core.models import BusinessHours, ProfessionalAvailability
        set_current_tenant(self.t, bypass=False)
        try:
            bh = BusinessHours.objects.bypass_tenant().get(tenant=self.t, weekday=1)
            bh.is_open = True
            bh.open_time = time(9, 0)
            bh.close_time = time(18, 0)
            bh.save()

            pro = Professional.objects.create(tenant=self.t, user=self.owner)
            pa, _ = ProfessionalAvailability.objects.bypass_tenant().get_or_create(
                tenant=self.t, professional=pro, weekday=1,
            )
            pa.available = True
            pa.start_time = time(9, 0)
            pa.end_time = time(18, 0)
            pa.full_clean()  # não levanta
            pa.save()
            self.assertTrue(ProfessionalAvailability.objects.bypass_tenant().filter(
                professional=pro, weekday=1, available=True
            ).exists())
        finally:
            set_current_tenant(None, bypass=False)

    def test_manager_nao_pode_ser_profissional(self):
        mgr = User.objects.create_user(
            email="mgr@a.test", password="x", tenant=self.t,
            role=User.Role.MANAGER,
        )
        pro = Professional(tenant=self.t, user=mgr)
        with self.assertRaises(ValidationError):
            pro.full_clean()


class ProfessionalAdminTenantScopeTests(TestCase):
    """Admin deve exibir vínculos usando request.tenant, mesmo sem ContextVar."""

    def setUp(self):
        from core.models import TenantMembership
        self.factory = RequestFactory()
        self.site = AdminSite()
        self.t1 = Tenant.objects.create(name="A", slug="admin-a")
        self.t2 = Tenant.objects.create(name="B", slug="admin-b")
        self.owner = User.objects.create_user(
            email="owner-admin@a.test", password="x", tenant=self.t1,
            role=User.Role.OWNER, is_staff=True,
        )
        # Signal já cria membership(owner); get_or_create p/ idempotência.
        TenantMembership.objects.bypass_tenant().get_or_create(
            tenant=self.t1, user=self.owner, role=TenantMembership.Role.OWNER,
        )
        self.pro_user = User.objects.create_user(
            email="pro-admin@a.test", password="x", tenant=self.t1,
            role=User.Role.PROFESSIONAL,
        )
        set_current_tenant(self.t1, bypass=False)
        # Signal já cria o Professional ao criar pro_user; usamos get.
        self.pro = Professional.objects.bypass_tenant().get(tenant=self.t1, user=self.pro_user)
        self.svc = Service.objects.create(tenant=self.t1, name="Corte", duration_minutes=30)
        self.link = ProfessionalService.objects.create(
            tenant=self.t1, professional=self.pro, service=self.svc,
        )
        set_current_tenant(self.t2, bypass=False)
        self.other_svc = Service.objects.create(
            tenant=self.t2, name="Barba", duration_minutes=20,
        )
        set_current_tenant(None, bypass=False)

    def _request(self):
        request = self.factory.get("/admin/core/professional/")
        request.user = self.owner
        request.tenant = self.t1
        request.tenant_bypass = False
        return request

    def test_exibe_servicos_vinculados_sem_contextvar_ativo(self):
        set_current_tenant(None, bypass=False)

        admin = ProfessionalAdmin(Professional, self.site)
        request = self._request()
        self.assertIn(self.pro, list(admin.get_queryset(request)))
        self.assertEqual(admin.qtd_servicos(self.pro), 1)

        inline = ProfessionalServiceInline(Professional, self.site)
        self.assertIn(self.link, list(inline.get_queryset(request)))

        formset = inline.get_formset(request, obj=self.pro)
        service_qs = formset.form.base_fields["service"].queryset
        self.assertIn(self.svc, list(service_qs))
        self.assertNotIn(self.other_svc, list(service_qs))


class TenantMembershipAndInvitationTests(TestCase):
    def setUp(self):
        self.t1 = Tenant.objects.create(name="Unidade A", slug="unidade-a")
        self.t2 = Tenant.objects.create(name="Unidade B", slug="unidade-b")
        self.owner = User.objects.create_user(
            email="owner-multi@test", password="x", tenant=self.t1,
            role=User.Role.OWNER,
        )
        self.prof_user = User.objects.create_user(
            email="prof-multi@test", password="x", tenant=None,
            role=User.Role.PROFESSIONAL, first_name="Ana", last_name="Pro",
        )

    def test_owner_pode_ter_membership_em_varias_barbearias(self):
        from core.models import TenantMembership

        # Signal já criou membership(t1, owner); get_or_create p/ idempotência.
        TenantMembership.objects.bypass_tenant().get_or_create(
            tenant=self.t1, user=self.owner, role=TenantMembership.Role.OWNER,
        )
        TenantMembership.objects.bypass_tenant().create(
            tenant=self.t2, user=self.owner, role=TenantMembership.Role.OWNER,
        )

        self.assertEqual(
            TenantMembership.objects.bypass_tenant().filter(
                user=self.owner,
                role=TenantMembership.Role.OWNER,
                is_active=True,
            ).count(),
            2,
        )

    def test_aceitar_convite_cria_membership_e_professional(self):
        from core.models import ProfessionalInvitation, TenantMembership

        invitation = ProfessionalInvitation.objects.create(
            tenant=self.t2,
            professional_user=self.prof_user,
            invited_by=self.owner,
        )

        professional = invitation.accept()
        invitation.refresh_from_db()

        self.assertEqual(invitation.status, ProfessionalInvitation.Status.ACCEPTED)
        self.assertEqual(professional.tenant, self.t2)
        self.assertEqual(professional.user, self.prof_user)
        self.assertTrue(TenantMembership.objects.bypass_tenant().filter(
            tenant=self.t2,
            user=self.prof_user,
            role=TenantMembership.Role.PROFESSIONAL,
            is_active=True,
        ).exists())

    def test_rejeitar_convite_nao_cria_vinculo(self):
        from core.models import ProfessionalInvitation, TenantMembership

        invitation = ProfessionalInvitation.objects.create(
            tenant=self.t2,
            professional_user=self.prof_user,
            invited_by=self.owner,
        )

        result = invitation.reject()
        invitation.refresh_from_db()

        self.assertIsNone(result)
        self.assertEqual(invitation.status, ProfessionalInvitation.Status.REJECTED)
        self.assertFalse(TenantMembership.objects.bypass_tenant().filter(
            tenant=self.t2,
            user=self.prof_user,
            role=TenantMembership.Role.PROFESSIONAL,
        ).exists())
        self.assertFalse(Professional.objects.bypass_tenant().filter(
            tenant=self.t2,
            user=self.prof_user,
        ).exists())

    def test_professional_exige_membership_ativa_no_tenant(self):
        pro = Professional(tenant=self.t2, user=self.prof_user)

        with self.assertRaises(ValidationError):
            pro.full_clean()

    def test_professional_com_membership_ativa_e_valido(self):
        from core.models import TenantMembership

        TenantMembership.objects.create(
            tenant=self.t2,
            user=self.prof_user,
            role=TenantMembership.Role.PROFESSIONAL,
        )

        pro = Professional(tenant=self.t2, user=self.prof_user)
        pro.full_clean()


class ProfessionalAvailabilityConflictTests(TestCase):
    def setUp(self):
        from core.models import TenantMembership

        self.t1 = Tenant.objects.create(name="Agenda A", slug="agenda-a")
        self.t2 = Tenant.objects.create(name="Agenda B", slug="agenda-b")
        self.user = User.objects.create_user(
            email="agenda-prof@test", password="x", role=User.Role.PROFESSIONAL,
        )
        TenantMembership.objects.create(
            tenant=self.t1, user=self.user, role=TenantMembership.Role.PROFESSIONAL,
        )
        TenantMembership.objects.create(
            tenant=self.t2, user=self.user, role=TenantMembership.Role.PROFESSIONAL,
        )
        self.pro1 = Professional.objects.bypass_tenant().create(tenant=self.t1, user=self.user)
        self.pro2 = Professional.objects.bypass_tenant().create(tenant=self.t2, user=self.user)
        for tenant in (self.t1, self.t2):
            bh = BusinessHours.objects.bypass_tenant().get(tenant=tenant, weekday=1)
            bh.is_open = True
            bh.open_time = time(8, 0)
            bh.close_time = time(20, 0)
            bh.break_start = None
            bh.break_end = None
            bh.save()

    def test_rejeita_disponibilidade_sobreposta_em_outra_barbearia(self):
        pa1 = ProfessionalAvailability.objects.bypass_tenant().get(
            tenant=self.t1, professional=self.pro1, weekday=1,
        )
        pa1.available = True
        pa1.start_time = time(9, 0)
        pa1.end_time = time(13, 0)
        pa1.save()

        pa2 = ProfessionalAvailability.objects.bypass_tenant().get(
            tenant=self.t2, professional=self.pro2, weekday=1,
        )
        pa2.available = True
        pa2.start_time = time(12, 0)
        pa2.end_time = time(18, 0)

        with self.assertRaises(ValidationError):
            pa2.full_clean()

    def test_aceita_disponibilidade_sem_sobreposicao_em_outra_barbearia(self):
        pa1 = ProfessionalAvailability.objects.bypass_tenant().get(
            tenant=self.t1, professional=self.pro1, weekday=1,
        )
        pa1.available = True
        pa1.start_time = time(9, 0)
        pa1.end_time = time(12, 0)
        pa1.save()

        pa2 = ProfessionalAvailability.objects.bypass_tenant().get(
            tenant=self.t2, professional=self.pro2, weekday=1,
        )
        pa2.available = True
        pa2.start_time = time(14, 0)
        pa2.end_time = time(18, 0)
        pa2.full_clean()
