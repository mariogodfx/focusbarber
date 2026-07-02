"""
Testes do Service — flag is_active + regras de exclusão/inativação (Sprint 3 ajuste).

Regras validadas (PRD §8 + ajustes solicitados):
  ✅ Serviço possui campo is_active (default True).
  ✅ Dono da barbearia NÃO pode excluir serviço (só inativar).
  ✅ flag is_active só pode ser alterada por owner/manager/superadmin.

Roda:  python manage.py test core.tests.test_service
"""
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from core.admin import ServiceAdmin
from core.models import Service, Tenant, set_current_tenant

User = get_user_model()


def _make_user(tenant, role, email="x@test", super=False):
    if super:
        return User.objects.create_superuser(email=email, password="x")
    return User.objects.create_user(
        email=email, password="x", tenant=tenant, role=role,
    )


class ServiceIsActiveFieldTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Alpha", slug="alpha")
        set_current_tenant(self.tenant, bypass=False)
        self.svc = Service.objects.create(
            tenant=self.tenant, name="Corte", duration_minutes=30
        )
        set_current_tenant(None, bypass=False)

    def test_default_is_active_true(self):
        self.assertTrue(self.svc.is_active)

    def test_pode_inativar_servico(self):
        self.svc.is_active = False
        self.svc.save()
        self.svc.refresh_from_db()
        self.assertFalse(self.svc.is_active)


class ServiceAdminRulesTests(TestCase):
    """Validam exclusão bloqueada + restrição de toggle de is_active no admin."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Alpha", slug="alpha")
        set_current_tenant(self.tenant, bypass=False)
        self.svc = Service.objects.create(
            tenant=self.tenant, name="Corte", duration_minutes=30
        )
        set_current_tenant(None, bypass=False)
        self.factory = RequestFactory()
        self.admin = ServiceAdmin(Service, None)  # admin_site irrelevante aqui

    def _req(self, user):
        req = self.factory.get("/admin/core/service/")
        req.user = user
        req.tenant = getattr(user, "tenant", None)
        req.tenant_bypass = bool(getattr(user, "is_superadmin", False))
        return req

    # ---- Exclusão reservada ao superadmin SaaS ----
    def test_owner_nao_pode_excluir(self):
        u = _make_user(self.tenant, User.Role.OWNER, "dono@test")
        self.assertFalse(self.admin.has_delete_permission(self._req(u), self.svc))

    def test_manager_nao_pode_excluir(self):
        u = _make_user(self.tenant, User.Role.MANAGER, "gerente@test")
        self.assertFalse(self.admin.has_delete_permission(self._req(u), self.svc))

    def test_profissional_nao_pode_excluir(self):
        u = _make_user(self.tenant, User.Role.PROFESSIONAL, "barb@test")
        self.assertFalse(self.admin.has_delete_permission(self._req(u), self.svc))

    def test_superadmin_pode_excluir(self):
        u = _make_user(None, None, "admin@test", super=True)
        self.assertTrue(self.admin.has_delete_permission(self._req(u), self.svc))

    # ---- toggle de is_active só para owner/manager/superadmin ----
    def test_profissional_nao_pode_inativar(self):
        from django.core.exceptions import PermissionDenied
        u = _make_user(self.tenant, User.Role.PROFESSIONAL, "barb@test")
        set_current_tenant(self.tenant, bypass=False)
        try:
            self.svc.is_active = False
            # Simula o save_model com change=True e is_active em changed_data.
            form = type("F", (), {"changed_data": ["is_active"], "cleaned_data": {"is_active": False}})()
            with self.assertRaises(PermissionDenied):
                self.admin.save_model(self._req(u), self.svc, form, change=True)
        finally:
            set_current_tenant(None, bypass=False)
        self.svc.refresh_from_db()
        self.assertTrue(self.svc.is_active)  # nao foi alterado

    def test_owner_pode_inativar(self):
        u = _make_user(self.tenant, User.Role.OWNER, "dono@test")
        set_current_tenant(self.tenant, bypass=False)
        try:
            self.svc.is_active = False
            form = type("F", (), {"changed_data": ["is_active"], "cleaned_data": {"is_active": False}})()
            self.admin.save_model(self._req(u), self.svc, form, change=True)
        finally:
            set_current_tenant(None, bypass=False)
        self.svc.refresh_from_db()
        self.assertFalse(self.svc.is_active)

    def test_manager_pode_inativar(self):
        u = _make_user(self.tenant, User.Role.MANAGER, "gerente@test")
        set_current_tenant(self.tenant, bypass=False)
        try:
            self.svc.is_active = False
            form = type("F", (), {"changed_data": ["is_active"], "cleaned_data": {"is_active": False}})()
            self.admin.save_model(self._req(u), self.svc, form, change=True)
        finally:
            set_current_tenant(None, bypass=False)
        self.svc.refresh_from_db()
        self.assertFalse(self.svc.is_active)