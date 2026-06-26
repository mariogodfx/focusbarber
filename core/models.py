"""
Multi-Tenant Core — PRD §16: "Shared database + tenant_id obrigatório".

Camadas:
  - Tenant (Barbearia) — raiz do isolamento.
  - TenantManager — criação/lookup de tenants (não filtrado).
  - current_tenant() — resolução do tenant da requisição atual (middleware).
  - TenantOwnedModel + TenantOwnedManager — QuerySet filtrado por tenant e
    proteção contra acesso cross-tenant em get()/save().

Regras PRD:
  - §13.2: "Toda query deve obrigatoriamente respeitar tenant_id".
  - §11:  "Multi-tenant obrigatório em todas queries".
  - §16:  "QuerySet global filtrado", "Proteção contra cross-tenant access".
"""
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

# Resolver thread-local para o tenant da requisição atual.
try:
    import contextvars  # async-safe
    _current: "contextvars.ContextVar[Tenant | None]" = contextvars.ContextVar(
        "current_tenant", default=None
    )
    _bypass: "contextvars.ContextVar[bool]" = contextvars.ContextVar(
        "tenant_bypass", default=False
    )
except ImportError:  # pragma: no cover
    import threading

    class _Local(threading.local):
        value = None
        bypass = False

    _local = _Local()

    class _ContextVarShim:
        def __init__(self, attr, default):
            self.attr = attr
            self.default = default

        def get(self, *_):
            return getattr(_local, self.attr, self.default)

        def set(self, v):
            setattr(_local, self.attr, v)

    _current = _ContextVarShim("value", None)
    _bypass = _ContextVarShim("bypass", False)


def set_current_tenant(tenant, bypass=False):
    """Definido pelo TenantMiddleware; usado por TenantOwnedManager.

    ``bypass=True`` sinaliza acesso global (superadmin SaaS): o ContextVar de
    tenant fica None (sem escopo) mas o manager NÃO filtra — mostra tudo.
    """
    _current.set(tenant)
    _bypass.set(bypass)


def current_tenant():
    """Retorna o Tenant da requisição atual ou None."""
    return _current.get()


def is_tenant_bypass():
    """True quando o contexto atual é de acesso global (superadmin SaaS)."""
    return _bypass.get()


class TenantManager(models.Manager):
    """Manager da raiz Tenant — NÃO filtra (é o próprio escopo)."""

    use_in_migrations = True


class Tenant(models.Model):
    """Uma barbearia (tenant). Raiz do isolamento de dados."""

    slug = models.SlugField(_("slug"), max_length=60, unique=True)
    name = models.CharField(_("nome"), max_length=120)
    is_active = models.BooleanField(_("ativo"), default=True)
    created_at = models.DateTimeField(_("criado em"), auto_now_add=True)
    updated_at = models.DateTimeField(_("atualizado em"), auto_now=True)

    # PRD §16: identificador externo opcional (p/ múltiplos estabelecimentos).
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    objects = TenantManager()

    class Meta:
        verbose_name = _("Barbearia (tenant)")
        verbose_name_plural = _("Barbearias (tenants)")
        ordering = ("name",)

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if not self.slug:
            raise ValidationError({"slug": _("Slug é obrigatório.")})


class TenantOwnedManager(models.Manager):
    """
    Manager de modelos pertencentes a um tenant — aplica isolamento.

    Comportamento:
      - Sempre filtra por tenant (o da requisição atual, salvo bypass explícito).
      - get()/get_or_create() impedem omitir o tenant (defesa em profundidade).
      - `.all()`/`.filter()`/`.exclude()` herdam o filtro de tenant.
      - `bypass_tenant()` desliga o filtro — reservado a superadmin SaaS.
    """

    use_in_migrations = True

    def get_queryset(self):
        qs = super().get_queryset()
        # Bypass ativo (superadmin SaaS) => vê tudo, sem filtro de tenant.
        if is_tenant_bypass():
            return qs
        # No Django data migrations / raw, current_tenant() pode ser None.
        tenant = current_tenant()
        if tenant is None:
            # Sem tenant no contexto => NÃO retorna dados de tenant nenhum.
            # Proteção: vazar dados sem tenant seria falha de segurança (PRD §13.2).
            # Exceção: superadmin SaaS via bypass (detectado acima).
            return qs.none()
        return qs.filter(tenant=tenant)

    def bypass_tenant(self):
        """Acesso sem filtro de tenant — apenas para superadmin SaaS."""
        return super().get_queryset()

    def get(self, *args, **kwargs):
        # Garante que_get não omita o tenant: aplicamos o filtro do queryset.
        return self.get_queryset().get(*args, **kwargs)

    def get_or_create(self, defaults=None, **kwargs):
        # Impede criar sem tenant no contexto.
        if "tenant" not in kwargs and current_tenant() is not None:
            kwargs.setdefault("tenant", current_tenant())
        return self.get_queryset().get_or_create(defaults=defaults, **kwargs)

    def create(self, **kwargs):
        if "tenant" not in kwargs and current_tenant() is not None:
            kwargs.setdefault("tenant", current_tenant())
        return self.get_queryset().create(**kwargs)


class TenantOwnedModel(models.Model):
    """
    Base abstrata: todo modelo multi-tenant herda desta.

    Práticas forçadas:
      - tenant_id obrigatório em toda linha (PRD §11/§13.2).
      - .save() bloqueia troca de tenant (imutabilidade do escopo).
      - Não permite instância sem tenant.
    """

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="+",
        verbose_name=_("barbearia"),
    )
    created_at = models.DateTimeField(_("criado em"), auto_now_add=True)
    updated_at = models.DateTimeField(_("atualizado em"), auto_now=True)

    objects = TenantOwnedManager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        # Mutabilidade do tenant: proibida — regra de isolamento.
        if self.pk:
            orig = type(self).objects.bypass_tenant().filter(pk=self.pk).first()
            if orig is not None and orig.tenant_id != self.tenant_id:
                raise ValidationError(
                    _("Não é permitido alterar o tenant de um registro.")
                )
        # Sem tenant absolutamente — bloqueia (mesmo fora de request).
        if self.tenant_id is None:
            raise ValidationError(_("tenant_id é obrigatório (multi-tenant)."))
        # Defensive: se há contexto de request, o tenant do objeto precisa bater
        # com o da requisição — SALVO superadmin SaaS (bypass ativo).
        if not is_tenant_bypass():
            cur = current_tenant()
            if cur is not None and self.tenant_id != cur.pk:
                raise ValidationError(
                    _("Tentativa de gravar dado em tenant alheio (cross-tenant).")
                )
        super().save(*args, **kwargs)


# ---------- Modelo de exemplo para validar isolamento ----------


class Service(TenantOwnedModel):
    """Serviço de barbearia — exemplo de modelo multi-tenant.

    Sprint 5 formaliza Serviços/Profissionais; aqui existe o mínimo para a
    validação CLI do isolamento (PRD §16: "Proteção contra cross-tenant access").
    """

    name = models.CharField(_("nome"), max_length=120)
    duration_minutes = models.PositiveIntegerField(_("duração (min)"), default=30)

    class Meta:
        verbose_name = _("serviço")
        verbose_name_plural = _("serviços")
        # Unicidade APENAS dentro do tenant (PRD §11 — multi-tenant em queries).
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "name"),
                name="unique_service_name_per_tenant",
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if not self.name:
            raise ValidationError({"name": _("Nome é obrigatório.")})
