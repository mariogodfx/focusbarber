from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory, TestCase

from base.models import User
from core.admin import ProfessionalInvitationAdmin, TenantMembershipAdmin
from core.models import ProfessionalInvitation, Tenant, TenantMembership


class MembershipInvitationAdminTests(TestCase):
    def setUp(self):
        self.site = AdminSite()
        self.factory = RequestFactory()
        self.t1 = Tenant.objects.create(name="Admin A", slug="admin-a2")
        self.t2 = Tenant.objects.create(name="Admin B", slug="admin-b2")
        self.owner = User.objects.create_user(
            email="admin-owner@test", password="x", tenant=self.t1,
            role=User.Role.OWNER, is_staff=True,
        )
        self.prof = User.objects.create_user(
            email="admin-prof@test", password="x", role=User.Role.PROFESSIONAL,
            is_staff=True,
        )
        # Signal já cria membership(t1, owner); get_or_create p/ idempotência.
        TenantMembership.objects.bypass_tenant().get_or_create(
            tenant=self.t1, user=self.owner, role=TenantMembership.Role.OWNER,
        )
        TenantMembership.objects.bypass_tenant().get_or_create(
            tenant=self.t2, user=self.owner, role=TenantMembership.Role.OWNER,
        )

    def _request(self, user):
        request = self.factory.get("/admin/core/professionalinvitation/")
        request.user = user
        request.tenant = getattr(user, "tenant", None)
        request.tenant_bypass = False
        return request

    def test_owner_ve_memberships_das_suas_barbearias(self):
        admin = TenantMembershipAdmin(TenantMembership, self.site)
        request = self._request(self.owner)

        qs = admin.get_queryset(request)

        self.assertEqual(qs.count(), 2)

    def test_profissional_ve_convites_direcionados_a_ele(self):
        invitation = ProfessionalInvitation.objects.create(
            tenant=self.t1, professional_user=self.prof, invited_by=self.owner,
        )
        admin = ProfessionalInvitationAdmin(ProfessionalInvitation, self.site)
        request = self._request(self.prof)

        self.assertIn(invitation, list(admin.get_queryset(request)))

    def test_owner_ve_profissionais_das_varias_barbearias(self):
        from core.admin import ProfessionalAdmin
        from core.models import Professional

        TenantMembership.objects.create(
            tenant=self.t1, user=self.prof, role=TenantMembership.Role.PROFESSIONAL,
        )
        TenantMembership.objects.create(
            tenant=self.t2, user=self.prof, role=TenantMembership.Role.PROFESSIONAL,
        )
        pro1 = Professional.objects.bypass_tenant().create(tenant=self.t1, user=self.prof)
        pro2 = Professional.objects.bypass_tenant().create(tenant=self.t2, user=self.prof)

        admin = ProfessionalAdmin(Professional, self.site)
        request = self._request(self.owner)

        self.assertEqual(set(admin.get_queryset(request)), {pro1, pro2})
