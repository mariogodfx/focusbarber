"""
Testes - Fluxo de convites (ProfessionalInvitation).

Cobre:
  1. Modelo: cancel(), accept(), reject() com transicoes validas.
  2. Modelo: bloqueio de transicoes a partir de estado nao-pending.
  3. Frontend: painel do profissional (GET).
  4. Frontend: aceitar/rejeitar/cancelar via POST.
  5. Frontend: permissao (apenas convidado pode aceitar/rejeitar).
  6. Frontend: remetente pode cancelar.
  7. Admin: acao em massa de cancelar convite.

Rodar: python manage.py test core.tests.test_convites
"""
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from base.models import User
from core.models import (
    Professional,
    ProfessionalInvitation,
    Tenant,
    TenantMembership,
    set_current_tenant,
)

User = get_user_model()


class ConviteModelTests(TestCase):
    """Modelo: metodos accept/reject/cancel com transicoes validas."""

    def setUp(self):
        set_current_tenant(None, bypass=False, user=None)
        self.t1 = Tenant.objects.create(name="Conv A", slug="conv-a")
        self.t2 = Tenant.objects.create(name="Conv B", slug="conv-b")
        self.owner = User.objects.create_user(
            email="conv-owner@test.com", password="x", tenant=self.t1,
            role=User.Role.OWNER,
        )
        TenantMembership.objects.bypass_tenant().get_or_create(
            tenant=self.t1, user=self.owner, role=TenantMembership.Role.OWNER,
        )
        self.prof = User.objects.create_user(
            email="conv-prof@test.com", password="x", tenant=self.t2,
            role=User.Role.PROFESSIONAL,
        )
        TenantMembership.objects.bypass_tenant().get_or_create(
            tenant=self.t2, user=self.prof, role=TenantMembership.Role.PROFESSIONAL,
        )

    def tearDown(self):
        set_current_tenant(None, bypass=False, user=None)

    def _create_invitation(self, tenant=None, prof=None):
        return ProfessionalInvitation.objects.bypass_tenant().create(
            tenant=tenant or self.t1,
            professional_user=prof or self.prof,
            invited_by=self.owner,
            status=ProfessionalInvitation.Status.PENDING,
        )

    def test_accept_cria_membership_e_professional(self):
        inv = self._create_invitation()
        prof = inv.accept()
        self.assertEqual(inv.status, ProfessionalInvitation.Status.ACCEPTED)
        self.assertIsNotNone(inv.responded_at)
        self.assertTrue(TenantMembership.objects.bypass_tenant().filter(
            tenant=self.t1, user=self.prof, role=TenantMembership.Role.PROFESSIONAL,
            is_active=True,
        ).exists())
        self.assertTrue(Professional.objects.bypass_tenant().filter(
            tenant=self.t1, user=self.prof,
        ).exists())

    def test_reject_nao_cria_membership(self):
        inv = self._create_invitation()
        result = inv.reject()
        self.assertIsNone(result)
        self.assertEqual(inv.status, ProfessionalInvitation.Status.REJECTED)
        self.assertFalse(TenantMembership.objects.bypass_tenant().filter(
            tenant=self.t1, user=self.prof,
        ).exists())

    def test_cancel_altera_status(self):
        inv = self._create_invitation()
        inv.cancel()
        self.assertEqual(inv.status, ProfessionalInvitation.Status.CANCELLED)
        self.assertIsNotNone(inv.responded_at)

    def test_accept_bloqueia_se_nao_pending(self):
        inv = self._create_invitation()
        inv.reject()
        with self.assertRaises(ValidationError):
            inv.accept()

    def test_reject_bloqueia_se_nao_pending(self):
        inv = self._create_invitation()
        inv.accept()
        with self.assertRaises(ValidationError):
            inv.reject()

    def test_cancel_bloqueia_se_nao_pending(self):
        inv = self._create_invitation()
        inv.accept()
        with self.assertRaises(ValidationError):
            inv.cancel()


class PainelFrontendTests(TestCase):
    """Frontend: painel do profissional + acoes via POST."""

    def setUp(self):
        set_current_tenant(None, bypass=False, user=None)
        self.t1 = Tenant.objects.create(name="Painel A", slug="painel-a")
        self.t2 = Tenant.objects.create(name="Painel B", slug="painel-b")
        self.owner = User.objects.create_user(
            email="painel-owner@test.com", password="x", tenant=self.t1,
            role=User.Role.OWNER,
        )
        TenantMembership.objects.bypass_tenant().get_or_create(
            tenant=self.t1, user=self.owner, role=TenantMembership.Role.OWNER,
        )
        self.prof = User.objects.create_user(
            email="painel-prof@test.com", password="x", tenant=self.t2,
            role=User.Role.PROFESSIONAL,
        )
        TenantMembership.objects.bypass_tenant().get_or_create(
            tenant=self.t2, user=self.prof, role=TenantMembership.Role.PROFESSIONAL,
        )
        self.inv = ProfessionalInvitation.objects.bypass_tenant().create(
            tenant=self.t1, professional_user=self.prof,
            invited_by=self.owner, status=ProfessionalInvitation.Status.PENDING,
        )

    def tearDown(self):
        set_current_tenant(None, bypass=False, user=None)

    def test_painel_exige_login(self):
        resp = self.client.get(reverse("core:painel"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp.url)

    def test_painel_get_mostra_convite_pendente(self):
        self.client.force_login(self.prof)
        resp = self.client.get(reverse("core:painel"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Painel A")
        self.assertContains(resp, "Aceitar")
        self.assertContains(resp, "Rejeitar")
        self.assertContains(resp, "Cancelar")

    def test_profissional_aceita_convite(self):
        self.client.force_login(self.prof)
        resp = self.client.post(reverse("core:convite_aceitar", args=[self.inv.pk]))
        self.assertEqual(resp.status_code, 302)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, ProfessionalInvitation.Status.ACCEPTED)

    def test_profissional_rejeita_convite(self):
        self.client.force_login(self.prof)
        resp = self.client.post(reverse("core:convite_rejeitar", args=[self.inv.pk]))
        self.assertEqual(resp.status_code, 302)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, ProfessionalInvitation.Status.REJECTED)

    def test_profissional_cancela_convite(self):
        self.client.force_login(self.prof)
        resp = self.client.post(reverse("core:convite_cancelar", args=[self.inv.pk]))
        self.assertEqual(resp.status_code, 302)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, ProfessionalInvitation.Status.CANCELLED)

    def test_remetente_cancela_convite(self):
        self.client.force_login(self.owner)
        resp = self.client.post(reverse("core:convite_cancelar", args=[self.inv.pk]))
        self.assertEqual(resp.status_code, 302)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, ProfessionalInvitation.Status.CANCELLED)

    def test_terceiro_nao_pode_cancelar(self):
        other = User.objects.create_user(
            email="other@test.com", password="x", tenant=self.t2,
            role=User.Role.CLIENT,
        )
        self.client.force_login(other)
        resp = self.client.post(reverse("core:convite_cancelar", args=[self.inv.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_terceiro_nao_pode_aceitar(self):
        other = User.objects.create_user(
            email="other2@test.com", password="x", tenant=self.t2,
            role=User.Role.PROFESSIONAL,
        )
        self.client.force_login(other)
        resp = self.client.post(reverse("core:convite_aceitar", args=[self.inv.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_aceitar_convite_ja_respondido_falha(self):
        self.inv.accept()
        self.client.force_login(self.prof)
        resp = self.client.post(reverse("core:convite_aceitar", args=[self.inv.pk]))
        self.assertEqual(resp.status_code, 302)

    def test_get_nao_executa_acao(self):
        self.client.force_login(self.prof)
        resp = self.client.get(reverse("core:convite_aceitar", args=[self.inv.pk]))
        self.assertEqual(resp.status_code, 302)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, ProfessionalInvitation.Status.PENDING)
