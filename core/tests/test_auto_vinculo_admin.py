"""
Testes — Auto-vínculo no cadastro de usuário + escopo multi-unidade.

Cobre:
  1. Signal de auto-criação (TenantMembership + Professional) ao cadastrar user.
  2. Validação admin: role owner/manager/professional exige tenant.
  3. Dono com memberships em várias barbearias enxerga todas no admin.
  4. Superuser editando Professional só vê serviços do tenant daquele profissional.
  5. Cross-tenant save com membership multi-unidade.
  6. Duração do serviço padronizada (choices).
  7. TenantMembershipAdmin — dropdown tenant restrito às memberships.
  8. TenantContextMixin — POST no admin edita BusinessHours da 2ª barbearia.

Rodar: python manage.py test core.tests.test_auto_vinculo_admin
"""
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase
from django.urls import reverse

from base.models import User
from core.admin import (
    ProfessionalAdmin,
    ProfessionalServiceInline,
    ServiceAdmin,
    TenantAdmin,
    TenantContextMixin,
)
from core.models import (
    BusinessHours,
    Professional,
    Service,
    Tenant,
    TenantMembership,
)

User = get_user_model()


# ====================================================================
# 1. Signal de auto-criação
# ====================================================================
class AutoVinculoSignalTests(TestCase):
    """Signal cria TenantMembership (+ Professional p/ professional) ao criar user."""

    def setUp(self):
        self.t = Tenant.objects.create(name="Sig A", slug="sig-a")

    def test_professional_com_tenant_cria_membership_e_professional(self):
        u = User.objects.create_user(
            email="prof-sig@test", password="x", tenant=self.t,
            role=User.Role.PROFESSIONAL,
        )
        self.assertTrue(TenantMembership.objects.bypass_tenant().filter(
            tenant=self.t, user=u, role=TenantMembership.Role.PROFESSIONAL,
            is_active=True,
        ).exists())
        self.assertTrue(Professional.objects.bypass_tenant().filter(
            tenant=self.t, user=u,
        ).exists())

    def test_owner_com_tenant_cria_membership_sem_professional(self):
        u = User.objects.create_user(
            email="owner-sig@test", password="x", tenant=self.t,
            role=User.Role.OWNER,
        )
        self.assertTrue(TenantMembership.objects.bypass_tenant().filter(
            tenant=self.t, user=u, role=TenantMembership.Role.OWNER,
        ).exists())
        self.assertFalse(Professional.objects.bypass_tenant().filter(
            tenant=self.t, user=u,
        ).exists())

    def test_manager_com_tenant_cria_membership(self):
        u = User.objects.create_user(
            email="mgr-sig@test", password="x", tenant=self.t,
            role=User.Role.MANAGER,
        )
        self.assertTrue(TenantMembership.objects.bypass_tenant().filter(
            tenant=self.t, user=u, role=TenantMembership.Role.MANAGER,
        ).exists())

    def test_client_com_tenant_nao_cria_membership_nem_professional(self):
        u = User.objects.create_user(
            email="cli-sig@test", password="x", tenant=self.t,
            role=User.Role.CLIENT,
        )
        self.assertFalse(TenantMembership.objects.bypass_tenant().filter(
            tenant=self.t, user=u,
        ).exists())
        self.assertFalse(Professional.objects.bypass_tenant().filter(
            tenant=self.t, user=u,
        ).exists())

    def test_professional_sem_tenant_nao_cria_nada(self):
        u = User.objects.create_user(
            email="prof-notenant@test", password="x",
            role=User.Role.PROFESSIONAL,
        )
        self.assertFalse(TenantMembership.objects.bypass_tenant().filter(
            user=u,
        ).exists())
        self.assertFalse(Professional.objects.bypass_tenant().filter(
            user=u,
        ).exists())

    def test_update_nao_dispara_novamente(self):
        u = User.objects.create_user(
            email="upd@test", password="x", tenant=self.t,
            role=User.Role.PROFESSIONAL,
        )
        before = TenantMembership.objects.bypass_tenant().filter(user=u).count()
        u.first_name = "Changed"
        u.save()
        after = TenantMembership.objects.bypass_tenant().filter(user=u).count()
        self.assertEqual(before, after)


# ====================================================================
# 2. Validação admin — tenant obrigatório
# ====================================================================
class AdminFormTenantRequiredTests(TestCase):
    """Form do admin valida: role owner/manager/professional exige tenant."""

    def setUp(self):
        self.factory = RequestFactory()
        self.site = AdminSite()
        self.t = Tenant.objects.create(name="FormA", slug="form-a")
        self.superadmin = User.objects.create_superuser(
            email="root-form@test", password="x",
        )

    def _request(self, user):
        request = self.factory.get("/admin/base/user/add/")
        request.user = user
        request.tenant = getattr(user, "tenant", None)
        request.tenant_bypass = False
        return request

    def test_form_rejeita_professional_sem_tenant(self):
        from base.admin import CustomUserAdmin
        admin = CustomUserAdmin(User, self.site)
        request = self._request(self.superadmin)
        form_class = admin.get_form(request, obj=None)
        form = form_class(data={
            "email": "no-tenant@test.com", "role": User.Role.PROFESSIONAL,
            "password1": "Senh4Forte!x", "password2": "Senh4Forte!x",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("tenant", form.errors)

    def test_form_aceita_client_sem_tenant(self):
        from base.admin import CustomUserAdmin
        admin = CustomUserAdmin(User, self.site)
        request = self._request(self.superadmin)
        form_class = admin.get_form(request, obj=None)
        form = form_class(data={
            "email": "cli-nt@test.com", "role": User.Role.CLIENT,
            "password1": "Senh4Forte!x", "password2": "Senh4Forte!x",
        })
        # Cliente sem tenant é válido (não exige tenant).
        self.assertTrue(form.is_valid(), msg=form.errors)


# ====================================================================
# 3. Dono multi-unidade enxerga todas as barbearias
# ====================================================================
class OwnerMultiUnitAdminTests(TestCase):
    """Owner com memberships em 2 barbearias vê ambas em Tenant/Service/Professional."""

    def setUp(self):
        self.factory = RequestFactory()
        self.site = AdminSite()
        self.t1 = Tenant.objects.create(name="MU A", slug="mu-a")
        self.t2 = Tenant.objects.create(name="MU B", slug="mu-b")
        self.owner = User.objects.create_user(
            email="mu-owner@test", password="x", tenant=self.t1,
            role=User.Role.OWNER, is_staff=True,
        )
        # Signal cria membership(t1, owner); criamos a segunda manualmente.
        TenantMembership.objects.bypass_tenant().get_or_create(
            tenant=self.t1, user=self.owner, role=TenantMembership.Role.OWNER,
        )
        TenantMembership.objects.bypass_tenant().create(
            tenant=self.t2, user=self.owner, role=TenantMembership.Role.OWNER,
        )
        # Serviços em ambos tenants.
        self.svc1 = Service.objects.bypass_tenant().create(
            tenant=self.t1, name="Corte A", duration_minutes=30,
        )
        self.svc2 = Service.objects.bypass_tenant().create(
            tenant=self.t2, name="Corte B", duration_minutes=30,
        )

    def _request(self):
        request = self.factory.get("/admin/")
        request.user = self.owner
        request.tenant = self.t1  # tenant legado
        request.tenant_bypass = False
        return request

    def test_tenant_admin_mostra_ambas_barbearias(self):
        admin = TenantAdmin(Tenant, self.site)
        qs = admin.get_queryset(self._request())
        self.assertEqual(set(qs), {self.t1, self.t2})

    def test_service_admin_mostra_servicos_de_ambas(self):
        admin = ServiceAdmin(Service, self.site)
        qs = admin.get_queryset(self._request())
        self.assertEqual(set(qs), {self.svc1, self.svc2})

    def test_service_form_tenant_e_selecioavel_multi_unidade(self):
        admin = ServiceAdmin(Service, self.site)
        form_class = admin.get_form(self._request(), obj=None)
        tenant_field = form_class.base_fields["tenant"]
        self.assertEqual(
            set(tenant_field.queryset),
            {self.t1, self.t2},
        )
        self.assertFalse(tenant_field.disabled)

    def test_service_form_tenant_desabilitado_em_edicao(self):
        """Na edição, o campo tenant é desabilitado (imutável por save())."""
        admin = ServiceAdmin(Service, self.site)
        form_class = admin.get_form(self._request(), obj=self.svc2)
        tenant_field = form_class.base_fields["tenant"]
        self.assertTrue(tenant_field.disabled)


# ====================================================================
# 4. Superuser — dropdown de serviços restrito ao tenant do profissional
# ====================================================================
class SuperuserServiceDropdownTests(TestCase):
    """Superuser editando Professional da barbearia A só vê serviços da A."""

    def setUp(self):
        self.factory = RequestFactory()
        self.site = AdminSite()
        self.t1 = Tenant.objects.create(name="Drop A", slug="drop-a")
        self.t2 = Tenant.objects.create(name="Drop B", slug="drop-b")
        self.superadmin = User.objects.create_superuser(
            email="root-drop@test", password="x",
        )
        # Professional user sem tenant (não dispara signal).
        self.prof_user = User.objects.create_user(
            email="prof-drop@test", password="x",
            role=User.Role.PROFESSIONAL,
        )
        TenantMembership.objects.bypass_tenant().create(
            tenant=self.t1, user=self.prof_user, role=TenantMembership.Role.PROFESSIONAL,
        )
        self.pro = Professional.objects.bypass_tenant().create(
            tenant=self.t1, user=self.prof_user,
        )
        self.svc_a = Service.objects.bypass_tenant().create(
            tenant=self.t1, name="Corte A", duration_minutes=30,
        )
        self.svc_b = Service.objects.bypass_tenant().create(
            tenant=self.t2, name="Corte B", duration_minutes=30,
        )

    def _request(self):
        request = self.factory.get("/admin/core/professional/")
        request.user = self.superadmin
        request.tenant = None
        request.tenant_bypass = True
        return request

    def test_dropdown_service_so_mostra_do_tenant_do_profissional(self):
        inline = ProfessionalServiceInline(Professional, self.site)
        formset = inline.get_formset(self._request(), obj=self.pro)
        service_qs = formset.form.base_fields["service"].queryset
        self.assertIn(self.svc_a, list(service_qs))
        self.assertNotIn(self.svc_b, list(service_qs))


# ====================================================================
# 5. Cross-tenant save com membership multi-unidade
# ====================================================================
class MultiUnitSaveTests(TestCase):
    """Dono com membership em 2 barbearias consegue gravar em ambas."""

    def setUp(self):
        from core.models import set_current_tenant
        self.t1 = Tenant.objects.create(name="Save A", slug="save-a")
        self.t2 = Tenant.objects.create(name="Save B", slug="save-b")
        self.owner = User.objects.create_user(
            email="save-owner@test.com", password="x", tenant=self.t1,
            role=User.Role.OWNER,
        )
        # Signal cria membership(t1, owner); criamos a segunda manualmente.
        TenantMembership.objects.bypass_tenant().get_or_create(
            tenant=self.t1, user=self.owner, role=TenantMembership.Role.OWNER,
        )
        TenantMembership.objects.bypass_tenant().create(
            tenant=self.t2, user=self.owner, role=TenantMembership.Role.OWNER,
        )
        # Simula o middleware: user logado com tenant legado = t1.
        set_current_tenant(self.t1, bypass=False, user=self.owner)

    def tearDown(self):
        from core.models import set_current_tenant
        set_current_tenant(None, bypass=False, user=None)

    def test_dono_grava_servico_na_segunda_barbearia(self):
        """Dono com membership em t2 consegue criar serviço em t2."""
        svc = Service(tenant=self.t2, name="Corte B", duration_minutes=30)
        svc.save()  # não deve levantar ValidationError
        self.assertTrue(Service.objects.bypass_tenant().filter(
            tenant=self.t2, name="Corte B",
        ).exists())

    def test_dono_sem_membership_em_outra_barbearia_bloqueado(self):
        """Dono sem membership em t3 e bloqueado ao gravar em t3."""
        from core.models import set_current_tenant
        from django.core.exceptions import ValidationError
        # Reseta contexto p/ criar t3 sem disparar guarda cross-tenant no signal.
        set_current_tenant(None, bypass=False, user=None)
        t3 = Tenant.objects.create(name="Save C", slug="save-c")
        # Restaura contexto: user logado com tenant legado = t1.
        set_current_tenant(self.t1, bypass=False, user=self.owner)
        svc = Service(tenant=t3, name="Corte C", duration_minutes=30)
        with self.assertRaises(ValidationError):
            svc.save()


# ====================================================================
# 6. Duração do serviço padronizada (choices)
# ====================================================================
class ServiceDurationChoicesTests(TestCase):
    """ duração do serviço aceita apenas 30/60/90/120 minutos."""

    def tearDown(self):
        from core.models import set_current_tenant
        set_current_tenant(None, bypass=False, user=None)

    def test_choices_contem_apenas_30_60_90_120(self):
        from core.models import Service
        choices = [v for v, _ in Service.DURATION_CHOICES]
        self.assertEqual(choices, [30, 60, 90, 120])

    def test_duracao_valida_aceita(self):
        t = Tenant.objects.create(name="Dur A", slug="dur-a")
        from core.models import set_current_tenant
        set_current_tenant(t, bypass=False, user=None)
        try:
            svc = Service(tenant=t, name="Corte", duration_minutes=60)
            svc.full_clean()
        finally:
            set_current_tenant(None, bypass=False, user=None)


# ====================================================================
# 7. TenantMembershipAdmin — dropdown tenant restrito às memberships
# ====================================================================
class TenantMembershipAdminFormTests(TestCase):
    """No form de TenantMembership, o dropdown tenant só mostra barbearias
    das memberships do dono logado."""

    def setUp(self):
        self.factory = RequestFactory()
        self.site = AdminSite()
        self.t1 = Tenant.objects.create(name="TM A", slug="tm-a")
        self.t2 = Tenant.objects.create(name="TM B", slug="tm-b")
        self.t3 = Tenant.objects.create(name="TM C", slug="tm-c")
        self.owner = User.objects.create_user(
            email="tm-owner@test.com", password="x", tenant=self.t1,
            role=User.Role.OWNER, is_staff=True,
        )
        # Signal cria membership(t1, owner); criar a segunda manualmente.
        TenantMembership.objects.bypass_tenant().get_or_create(
            tenant=self.t1, user=self.owner, role=TenantMembership.Role.OWNER,
        )
        TenantMembership.objects.bypass_tenant().create(
            tenant=self.t2, user=self.owner, role=TenantMembership.Role.OWNER,
        )
        # t3 NÃO tem membership do owner.

    def _request(self):
        request = self.factory.get("/admin/core/tenantmembership/add/")
        request.user = self.owner
        request.tenant = self.t1
        request.tenant_bypass = False
        return request

    def test_dropdown_tenant_so_mostra_barbearias_do_dono(self):
        from core.admin import TenantMembershipAdmin
        admin = TenantMembershipAdmin(TenantMembership, self.site)
        form_class = admin.get_form(self._request(), obj=None)
        tenant_qs = form_class.base_fields["tenant"].queryset
        pks = set(tenant_qs.values_list("pk", flat=True))
        self.assertIn(self.t1.pk, pks)
        self.assertIn(self.t2.pk, pks)
        self.assertNotIn(self.t3.pk, pks)


# ====================================================================
# 8. TenantContextMixin — POST no admin edita BusinessHours da 2ª barbearia
# ====================================================================
class TenantContextMixinBusinessHoursTests(TestCase):
    """O mixin ajusta current_tenant() ANTES da validação do Admin.

    Reproduz o bug original: dono com memberships em t1 e t2 edita os
    horários de funcionamento (BusinessHours inline) da t2 via POST no admin.
    Sem o mixin, a validação falha porque current_tenant() = t1 (legado),
    enquanto o objeto pertence a t2.
    """

    def setUp(self):
        self.t1 = Tenant.objects.create(name="BH A", slug="bh-a")
        self.t2 = Tenant.objects.create(name="BH B", slug="bh-b")
        self.owner = User.objects.create_user(
            email="bh-owner@test.com", password="x", tenant=self.t1,
            role=User.Role.OWNER, is_staff=True,
        )
        TenantMembership.objects.bypass_tenant().get_or_create(
            tenant=self.t1, user=self.owner, role=TenantMembership.Role.OWNER,
        )
        TenantMembership.objects.bypass_tenant().create(
            tenant=self.t2, user=self.owner, role=TenantMembership.Role.OWNER,
        )
        # BusinessHours já existem (criados pelo signal post_save do Tenant).
        self.bh_t2 = BusinessHours.objects.bypass_tenant().filter(
            tenant=self.t2, weekday=0,
        ).first()

    def test_changeform_view_ajusta_tenant_antes_da_validacao(self):
        """POST no admin da 2ª barbearia retorna 302 (sucesso), não 200 (erro)."""
        from django.test import Client
        client = Client()
        client.force_login(self.owner)
        url = reverse("admin:core_tenant_change", args=[self.t2.pk])
        # Monta dados do form principal do Tenant + inline de BusinessHours.
        tenant_data = {
            "name": self.t2.name,
            "slug": self.t2.slug,
            "is_active": "on",
            "tagline": "",
            "description": "",
            "phone": "",
            "address": "",
            "whatsapp": "",
            "instagram": "",
        }
        # Dados do inline BusinessHours (formset management + 1 linha).
        prefix = "business_hours"
        bh = self.bh_t2
        bh_data = {
            f"{prefix}-TOTAL_FORMS": "1",
            f"{prefix}-INITIAL_FORMS": "1",
            f"{prefix}-0-id": str(bh.pk),
            f"{prefix}-0-tenant": str(self.t2.pk),
            f"{prefix}-0-weekday": "0",
            f"{prefix}-0-is_open": "on",
            f"{prefix}-0-open_time": "09:00",
            f"{prefix}-0-close_time": "18:00",
            f"{prefix}-0-break_start": "",
            f"{prefix}-0-break_end": "",
        }
        data = {**tenant_data, **bh_data}
        response = client.post(url, data, follow=False)
        self.assertEqual(
            response.status_code, 302,
            msg=f"Esperado 302 (redirect pós-save), obtido {response.status_code}. "
                f"O TenantContextMixin não ajustou current_tenant() antes da validação.",
        )

    def test_tenant_context_mixin_aplicado_em_todos_admins(self):
        """Todos os ModelAdmins multi-tenant herdam TenantContextMixin."""
        from core.admin import (
            ServiceAdmin as SA,
            TenantAdmin as TA,
            TenantMembershipAdmin as TMA,
            ProfessionalAdmin as PA,
            ProfessionalInvitationAdmin as PIA,
        )
        for admin_cls in (TA, SA, TMA, PA, PIA):
            self.assertTrue(
                issubclass(admin_cls, TenantContextMixin),
                msg=f"{admin_cls.__name__} não herda TenantContextMixin",
            )
