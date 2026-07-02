"""
Testes do Sprint 4 — Barbearia + Página Pública.

Validação CLI (PRD §26 — Sprint 4):
  ✅ upload imagens OK            (salva arquivo validado, rejeita tipo/tam)
  ✅ página pública 200 com dados (renderiza layout + só serviços ativos)

Roda:  python manage.py test publico.tests.test_sprint4
"""
import os

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase
from django.urls import reverse

from core.models import Service, Tenant, set_current_tenant
from publico.views import BarbeariaPublicaView


def _png(name="logo.png", size=None, content=b"\x89PNG\r\n\x1a\n"):
    data = content * (size or 1)
    return SimpleUploadedFile(name, data, content_type="image/png")


class UploadImagemTests(TestCase):
    """Validação CLI: 'upload imagens OK' (PRD §13.3 — tipo + tamanho 4MB)."""

    def setUp(self):
        self.t = Tenant.objects.create(name="Navalha", slug="navalha")

    def test_upload_logo_png_valido_salva(self):
        f = _png("logo.png")
        self.t.logo = f
        self.t.save()
        self.t.refresh_from_db()
        self.assertTrue(self.t.logo)
        self.assertIn("navalha", self.t.logo.name)

    def test_upload_tipo_nao_permitido_eh_rejeitado(self):
        from django.core.exceptions import ValidationError
        bad = SimpleUploadedFile("doc.pdf", b"%PDF-1.4", content_type="application/pdf")
        self.t.logo = bad
        with self.assertRaises(ValidationError):
            # full_clean dispara o validator do FileField.
            self.t.full_clean()

    def test_upload_extensao_nao_permitida_rejeitada(self):
        from django.core.exceptions import ValidationError
        bad = SimpleUploadedFile("logo.gif", b"GIF", content_type="image/gif")
        self.t.cover = bad
        with self.assertRaises(ValidationError):
            self.t.full_clean()

    def test_upload_oversized_rejeitado(self):
        from django.core.exceptions import ValidationError
        # 5 MB > limite 4MB.
        big = SimpleUploadedFile(
            "big.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * (5 * 1024 * 1024),
            content_type="image/png",
        )
        self.t.cover = big
        with self.assertRaises(ValidationError):
            self.t.full_clean()


class PaginaPublicaTests(TestCase):
    """Validação CLI: página pública renderiza layout + só serviços ativos."""

    def setUp(self):
        self.t = Tenant.objects.create(name="Navalha de Ouro", slug="navalha-de-ouro")
        self.t.tagline = "Premium Grooming"
        self.t.description = "Barbearia teste"
        self.t.phone = "(11) 99999-0000"
        self.t.save()
        # Serviços via contexto de tenant.
        set_current_tenant(self.t, bypass=False)
        self.ativo = Service.objects.create(
            tenant=self.t, name="Corte", duration_minutes=30, is_active=True
        )
        self.inativo = Service.objects.create(
            tenant=self.t, name="Platinado", duration_minutes=90, is_active=False
        )
        set_current_tenant(None, bypass=False)

    def test_publica_retorna_200(self):
        r = self.client.get(reverse("publico:barbearia", args=[self.t.slug]))
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, "publico/barbearia.html")

    def test_publica_contem_nome_e_tagline(self):
        r = self.client.get(reverse("publico:barbearia", args=[self.t.slug]))
        self.assertContains(r, "NAVALHA DE OURO")
        self.assertContains(r, "Premium Grooming")

    def test_publica_exibe_servicos_ativos_e_esconde_inativos(self):
        r = self.client.get(reverse("publico:barbearia", args=[self.t.slug]))
        self.assertContains(r, "CORTE")
        self.assertContains(r, "30 Min")
        self.assertNotContains(r, "Platinado")

    def test_publica_tenant_inativo_retorna_404(self):
        self.t.is_active = False
        self.t.save()
        r = self.client.get(reverse("publico:barbearia", args=[self.t.slug]))
        self.assertEqual(r.status_code, 404)

    def test_publica_slug_inexistente_404(self):
        r = self.client.get("/slug-que-nao-existe/")
        self.assertEqual(r.status_code, 404)

    def test_view_renderiza_com_servicos(self):
        factory = RequestFactory()
        req = factory.get(f"/{self.t.slug}/")
        view = BarbeariaPublicaView.as_view()
        r = view(req, slug=self.t.slug)
        self.assertEqual(r.status_code, 200)

    def test_estados_vazio_sem_servicos(self):
        t2 = Tenant.objects.create(name="Vazia", slug="vazia-barbearia")
        r = self.client.get(reverse("publico:barbearia", args=[t2.slug]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Serviços em breve")