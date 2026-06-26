"""
Testes do Sprint 3 — login por e-mail + permissões por role (RBAC).

Cobrem a validação CLI:
  ✅ login email funcionando  (autenticação pelo campo email)
  ✅ permissões por role        (cada role recebe exatamente suas permissões)

Roda:  python manage.py test base.tests.test_auth
"""
from django.contrib.auth import authenticate
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from base.models import User
from base.permissions import ROLE_PERMISSIONS, get_permissions_for_role, sync_role_permissions
from core.models import Tenant


class LoginEmailTests(TestCase):
    """Validação CLI: login email funcionando."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Alpha", slug="alpha")
        self.user = User.objects.create_user(
            email="dono@alpha.test",
            password="Senh4Forte!x",
            tenant=self.tenant,
            role=User.Role.OWNER,
        )

    def test_login_com_email_funciona(self):
        """Autenticar com email + senha retorna o usuário."""
        u = authenticate(None, username="dono@alpha.test", password="Senh4Forte!x")
        self.assertIsNotNone(u)
        self.assertEqual(u.email, "dono@alpha.test")

    def test_login_email_case_insensitive(self):
        """Aceita o e-mail em qualquer caixa (estilo comum de login)."""
        u = authenticate(None, username="DONO@ALPHA.TEST", password="Senh4Forte!x")
        self.assertIsNotNone(u)

    def test_senha_errada_nao_loga(self):
        u = authenticate(None, username="dono@alpha.test", password="errada")
        self.assertIsNone(u)

    def test_email_inexistente_nao_loga(self):
        u = authenticate(None, username="ninguem@alpha.test", password="Senh4Forte!x")
        self.assertIsNone(u)

    def test_usuario_inativo_nao_loga(self):
        self.user.is_active = False
        self.user.save()
        u = authenticate(None, username="dono@alpha.test", password="Senh4Forte!x")
        self.assertIsNone(u)


class RolePermissionsTests(TestCase):
    """Validação RBAC: cada role recebe exatamente suas permissões."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Alpha", slug="alpha")

    def _make(self, role):
        return User.objects.create_user(
            email=f"{role}@alpha.test",
            password="x",
            tenant=self.tenant,
            role=role,
        )

    def test_owner_recebe_permissoes_da_role(self):
        u = self._make(User.Role.OWNER)
        codenames = set(u.user_permissions.values_list("codename", flat=True))
        expected = {
            c.split(".", 1)[1]
            for c in ROLE_PERMISSIONS["owner"]
        }
        self.assertTrue(expected)  # não é vazio
        self.assertEqual(codenames, expected,
                         f"Owner deve ter exatamente: {expected}, tem: {codenames}")

    def test_manager_nao_tem_delete_service(self):
        u = self._make(User.Role.MANAGER)
        codenames = set(u.user_permissions.values_list("codename", flat=True))
        self.assertIn("change_service", codenames)
        self.assertNotIn("delete_service", codenames)
        # manager também não pode criar usuário com permissões plenas?
        self.assertIn("add_user", codenames)

    def test_profissional_sem_permissao_de_criar_servico(self):
        u = self._make(User.Role.PROFESSIONAL)
        codenames = set(u.user_permissions.values_list("codename", flat=True))
        self.assertIn("view_service", codenames)
        self.assertIn("change_service", codenames)
        self.assertNotIn("add_service", codenames)
        self.assertNotIn("delete_service", codenames)

    def test_client_permissao_minima(self):
        u = self._make(User.Role.CLIENT)
        codenames = set(u.user_permissions.values_list("codename", flat=True))
        # Cliente apenas vê (e não acessa o admin na prática).
        self.assertEqual(codenames, {"view_user"})

    def test_superadmin_nao_usa_lista_de_role(self):
        sup = User.objects.create_superuser(email="admin@focus.test", password="x")
        # is_superuser cuida do acesso total; lista por role fica vazia.
        codenames = set(sup.user_permissions.values_list("codename", flat=True))
        self.assertEqual(codenames, set())

    def test_trocar_role_sincroniza_permissoes(self):
        u = self._make(User.Role.OWNER)
        owner_codenames = set(u.user_permissions.values_list("codename", flat=True))
        u.role = User.Role.PROFESSIONAL
        u.save()
        u.refresh_from_db()
        prof_codenames = set(u.user_permissions.values_list("codename", flat=True))
        self.assertNotEqual(owner_codenames, prof_codenames)
        self.assertNotIn("delete_service", prof_codenames)
        self.assertNotIn("add_tenant" if False else "add_service", prof_codenames)