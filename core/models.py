"""
Multi-Tenant Core — PRD §16: "Shared database + tenant_id obrigatório".

Camadas:
  - Tenant (Barbearia) — raiz do isolamento. Também carrega os dados públicos
    exibidos na Página Pública (Sprint 4): logo, capa, descrição, contato.
  - TenantManager — criação/lookup de tenants (não filtrado).
  - current_tenant() — resolução do tenant da requisição atual (middleware).
  - TenantOwnedModel + TenantOwnedManager — QuerySet filtrado por tenant e
    proteção contra acesso cross-tenant em get()/save().

Regras PRD:
  - §13.2: "Toda query deve obrigatoriamente respeitar tenant_id".
  - §13.3: uploads vinculados ao tenant; validar tipo e tamanho máximo (4MB);
           mídia servida via camada controlada (view pública supervisionada).
  - §11:  "Multi-tenant obrigatório em todas queries".
  - §16:  "QuerySet global filtrado", "Proteção contra cross-tenant access".
"""
import os
import re
import uuid
from datetime import time as _time

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _


# ---------- Constantes PRD §13.3 (Segurança de Arquivos e Mídia) ----------
MAX_UPLOAD_BYTES = 4 * 1024 * 1024  # PRD §13.3 — tamanho máximo: 4MB.
ALLOWED_IMAGE_TYPES = {"jpg", "jpeg", "png", "webp"}


def _tenant_image_path(tenant_slug, attr):
    """Caminho de upload isolado por tenant (PRD §13.3 — vinculado ao tenant)."""
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in (tenant_slug or "sem"))
    return f"barbearias/{safe}/{attr}"


def tenant_logo_path(instance, filename):
    return _tenant_image_path(getattr(instance, "slug", None), "logo" + _ext(filename))


def tenant_cover_path(instance, filename):
    return _tenant_image_path(getattr(instance, "slug", None), "cover" + _ext(filename))


def _entity_image_path(tenant_slug, entity, attr, filename):
    """Caminho isolado por tenant para imagens de Professional (PRD §13.3)."""
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in (tenant_slug or "sem"))
    ext = os.path.splitext(filename)[1].lower() or ".jpg"
    return f"barbearias/{safe}/{entity}/{attr}{ext}"


def professional_photo_path(instance, filename):
    slug = getattr(getattr(instance, "tenant", None), "slug", None)
    return _entity_image_path(slug, "profissionais", "photo", filename)


def _ext(filename):
    ext = os.path.splitext(filename)[1].lower()
    return ext if ext else ".jpg"


def validate_image_file(file):
    """Validação PRD §13.3: tipo permitido (extensão) + tamanho <= 4MB.

   Não usa Pillow (dependência ausente no container dev): checa extensão e
    tamanho do arquivo, que é suficiente para a validação CLI do Sprint 4.
    """
    name = getattr(file, "name", "") or ""
    ext = os.path.splitext(name)[1].lower().lstrip(".")
    if ext not in ALLOWED_IMAGE_TYPES:
        raise ValidationError(
            _("Tipo de arquivo não permitido: .%(ext)s. Use: %(ok)s.")
            % {"ext": ext, "ok": ", ".join(sorted(ALLOWED_IMAGE_TYPES))}
        )
    # Tamanho: alguns storages expõem .size, outros exigem ler.
    size = getattr(file, "size", None)
    if size is None:
        try:
            file.seek(0, os.SEEK_END)
            size = file.tell()
            file.seek(0)
        except (AttributeError, OSError):
            size = 0
    if size and size > MAX_UPLOAD_BYTES:
        raise ValidationError(
            _("Arquivo muito grande (%(mb).1f MB). Tamanho máximo: 4 MB.")
            % {"mb": size / (1024 * 1024)}
        )

# Resolver thread-local para o tenant da requisição atual.
try:
    import contextvars  # async-safe
    _current: "contextvars.ContextVar[Tenant | None]" = contextvars.ContextVar(
        "current_tenant", default=None
    )
    _bypass: "contextvars.ContextVar[bool]" = contextvars.ContextVar(
        "tenant_bypass", default=False
    )
    _current_user_var = contextvars.ContextVar("current_user", default=None)
except ImportError:  # pragma: no cover
    import threading

    class _Local(threading.local):
        value = None
        bypass = False
        user = None

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
    _current_user_var = _ContextVarShim("user", None)


def set_current_tenant(tenant, bypass=False, user=None):
    """Definido pelo TenantMiddleware; usado por TenantOwnedManager.

    ``bypass=True`` sinaliza acesso global (superadmin SaaS): o ContextVar de
    tenant fica None (sem escopo) mas o manager NÃO filtra — mostra tudo.
    ``user`` é o usuário da requisição (para verificação de membership multi-unidade).
    """
    _current.set(tenant)
    _bypass.set(bypass)
    _current_user_var.set(user)


def current_tenant():
    """Retorna o Tenant da requisição atual ou None."""
    return _current.get()


def is_tenant_bypass():
    """True quando o contexto atual é de acesso global (superadmin SaaS)."""
    return _bypass.get()


def current_user():
    """Retorna o usuário da requisição atual ou None (definido pelo middleware)."""
    return _current_user_var.get()


def _user_has_membership_in_tenant(tenant_id):
    """Verifica se o usuário da requisição atual tem membership ativa no tenant.

    Usado por TenantOwnedModel.save() para permitir gravação em barbearias
    das memberships do usuário (multi-unidade), não apenas no tenant legado.
    """
    user = _current_user_var.get()
    if user is None or getattr(user, "is_superadmin", False):
        return True  # sem usuário no contexto (shell/seed) ou superadmin SaaS.
    # Import tardio: TenantMembership é definido mais abaixo neste arquivo.
    TenantMembership_local = globals().get("TenantMembership")
    if TenantMembership_local is None:
        return False
    return TenantMembership_local.objects.bypass_tenant().filter(
        tenant_id=tenant_id,
        user_id=user.pk,
        is_active=True,
    ).exists()


class TenantManager(models.Manager):
    """Manager da raiz Tenant — NÃO filtra (é o próprio escopo)."""

    use_in_migrations = True


class Tenant(models.Model):
    """Uma barbearia (tenant). Raiz do isolamento de dados.

    Sprint 4 — também carrega os dados públicos da Página Pública:
    logo, capa (cover), descrição e contato. As imagens são armazenadas em
    paths isolados por slug (PRD §13.3 — vinculadas ao tenant) e validadas
    quanto a tipo/tamanho.
    """

    slug = models.SlugField(_("slug"), max_length=60, unique=True)
    name = models.CharField(_("nome"), max_length=120)
    is_active = models.BooleanField(_("ativo"), default=True)
    created_at = models.DateTimeField(_("criado em"), auto_now_add=True)
    updated_at = models.DateTimeField(_("atualizado em"), auto_now=True)

    # PRD §16: identificador externo opcional (p/ múltiplos estabelecimentos).
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    # ---------- Sprint 4 — Página Pública ----------
    tagline = models.CharField(_("slogan"), max_length=120, blank=True)
    description = models.TextField(_("descrição"), max_length=600, blank=True)
    phone = models.CharField(_("telefone de contato"), max_length=20, blank=True)
    address = models.CharField(_("endereço"), max_length=200, blank=True)
    whatsapp = models.CharField(_("whatsapp"), max_length=20, blank=True)
    instagram = models.CharField(_("instagram (handle)"), max_length=60, blank=True)
    # Horário de funcionamento estruturado é gerido pelo modelo `BusinessHours`
    # (uma linha por dia da semana, com flag de abertura e intervalo). No
    # `post_save` do Tenant criamos as 7 linhas-padrão (todas fechadas) para
    # facilitar a configuração (PRD Sprint 5 — UX facilitada).

    logo = models.FileField(
        _("logo"),
        upload_to=tenant_logo_path,
        validators=[validate_image_file],
        blank=True,
        null=True,
    )
    cover = models.FileField(
        _("capa (foto)"),
        upload_to=tenant_cover_path,
        validators=[validate_image_file],
        blank=True,
        null=True,
    )

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
        # com o da requisição OU ser uma barbearia onde o usuário tem membership
        # ativa (multi-unidade) — SALVO superadmin SaaS (bypass ativo).
        if not is_tenant_bypass():
            cur = current_tenant()
            if cur is not None and self.tenant_id != cur.pk:
                if not _user_has_membership_in_tenant(self.tenant_id):
                    raise ValidationError(
                        _("Tentativa de gravar dado em tenant alheio (cross-tenant).")
                    )
        super().save(*args, **kwargs)


# ---------- Sprint 5 — Serviços + Profissionais ----------


class Service(TenantOwnedModel):
    """Serviço de barbearia (Sprint 5 — formalizado).

    Sprint 3 (ajuste): flag `is_active` para ativar/inativar serviços.
    Regras de guarda (defesa em profundidade):
      - Ninguém (salvo superadmin SaaS) pode EXCLUIR serviço — só inativar.
      - `is_active` só pode ser alterado por owner/manager/superadmin.
    """

    name = models.CharField(_("nome"), max_length=120)
    DURATION_CHOICES = (
        (30, "30 minutos"),
        (60, "60 minutos"),
        (90, "90 minutos"),
        (120, "120 minutos"),
    )
    duration_minutes = models.PositiveIntegerField(
        _("duração (min)"), choices=DURATION_CHOICES, default=30,
    )
    price = models.DecimalField(_("preço"), max_digits=10, decimal_places=2, default=0)
    is_active = models.BooleanField(_("ativo"), default=True)

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
        if self.duration_minutes <= 0:
            raise ValidationError({"duration_minutes": _("Duração deve ser positiva.")})


class Professional(TenantOwnedModel):
    """Profissional (barbeiro) vinculado a um usuário de role=professional.

    Vínculo com serviços é feito via `ProfessionalService` (M2M `through`)
    para garantir isolamento por tenant na relação. A disponibilidade
    semanal é dada por `ProfessionalAvailability` (inline).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="professional_profiles",
        verbose_name=_("usuário"),
    )
    bio = models.CharField(_("biografia"), max_length=300, blank=True)
    photo = models.FileField(
        _("foto"),
        upload_to=professional_photo_path,
        validators=[validate_image_file],
        blank=True,
        null=True,
    )
    is_active = models.BooleanField(_("ativo"), default=True)
    services = models.ManyToManyField(
        Service,
        through="ProfessionalService",
        related_name="professionals",
        through_fields=("professional", "service"),
        verbose_name=_("serviços"),
        blank=True,
    )

    class Meta:
        verbose_name = _("profissional")
        verbose_name_plural = _("profissionais")
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "user"),
                name="unique_professional_user_per_tenant",
            ),
        ]

    def __str__(self):
        name = (self.user.first_name or "").strip()
        if name and self.user.last_name:
            name = f"{name} {self.user.last_name}"
        return name or self.user.email

    @property
    def is_owner_professional(self):
        """True quando o dono da barbearia atende como profissional."""
        return getattr(self.user, "role", None) == "owner"

    def clean(self):
        super().clean()
        # O User vinculado precisa ser profissional OU dono (algumas barbearias
        # têm o dono atendendo) e possuir vínculo ativo (TenantMembership) com
        # a barbearia — cross-tenant proibido via membership explícita.
        if self.user_id is not None:
            allowed = {"professional", "owner"}
            if getattr(self.user, "role", None) not in allowed:
                raise ValidationError(
                    {"user": _("O usuário precisa ter perfil 'Profissional' ou 'Dono' "
                              "(role=professional ou role=owner).")}
                )
            membership_roles = [TenantMembership.Role.PROFESSIONAL]
            if getattr(self.user, "role", None) == "owner":
                membership_roles.append(TenantMembership.Role.OWNER)
            if not TenantMembership.objects.bypass_tenant().filter(
                tenant=self.tenant,
                user=self.user,
                role__in=membership_roles,
                is_active=True,
            ).exists():
                raise ValidationError(
                    {"user": _("O usuário não possui vínculo ativo com esta barbearia.")}
                )


class ProfessionalService(TenantOwnedModel):
    """Vínculo multitenant entre Professional e Service (tabela `through`).

    Garante que profissional e serviço pertençam ao mesmo tenant (defesa em
    profundidade além do filtro automático do TenantOwnedManager).
    """

    professional = models.ForeignKey(
        Professional,
        on_delete=models.CASCADE,
        related_name="+",
        verbose_name=_("profissional"),
    )
    service = models.ForeignKey(
        Service,
        on_delete=models.CASCADE,
        related_name="+",
        verbose_name=_("serviço"),
    )

    class Meta:
        verbose_name = _("vínculo profissional × serviço")
        verbose_name_plural = _("vínculos profissional × serviço")
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "professional", "service"),
                name="unique_prof_service_per_tenant",
            ),
        ]

    def __str__(self):
        return f"{self.professional} → {self.service}"

    def clean(self):
        super().clean()
        if self.professional_id and self.service_id:
            if self.professional.tenant_id != self.tenant_id:
                raise ValidationError(
                    _("Profissional não pertence a esta barbearia (cross-tenant).")
                )
            if self.service.tenant_id != self.tenant_id:
                raise ValidationError(
                    _("Serviço não pertence a esta barbearia (cross-tenant).")
                )
            if self.professional.tenant_id != self.service.tenant_id:
                raise ValidationError(
                    _("Profissional e serviço pertencem a barbearias diferentes (cross-tenant).")
                )


class TenantMembership(TenantOwnedModel):
    """Vinculo explicito entre usuario e barbearia/unidade."""

    class Role(models.TextChoices):
        OWNER = "owner", _("Dono")
        MANAGER = "manager", _("Gerente")
        PROFESSIONAL = "professional", _("Profissional")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tenant_memberships",
        verbose_name=_("usuario"),
    )
    role = models.CharField(_("perfil"), max_length=20, choices=Role.choices)
    is_active = models.BooleanField(_("ativo"), default=True)

    class Meta:
        verbose_name = _("vinculo usuario x barbearia")
        verbose_name_plural = _("vinculos usuario x barbearia")
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "user", "role"),
                name="unique_tenant_membership_user_role",
            ),
        ]

    def __str__(self):
        return f"{self.user} · {self.tenant} · {self.get_role_display()}"


class ProfessionalInvitation(TenantOwnedModel):
    """Convite de uma barbearia para um profissional existente."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Aguardando aprovacao")
        ACCEPTED = "accepted", _("Aceito")
        REJECTED = "rejected", _("Rejeitado")
        CANCELLED = "cancelled", _("Cancelado")

    professional_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="professional_invitations",
        verbose_name=_("profissional convidado"),
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sent_professional_invitations",
        verbose_name=_("convidado por"),
    )
    status = models.CharField(
        _("status"), max_length=20, choices=Status.choices, default=Status.PENDING,
    )
    responded_at = models.DateTimeField(_("respondido em"), blank=True, null=True)

    class Meta:
        verbose_name = _("convite de profissional")
        verbose_name_plural = _("convites de profissionais")
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "professional_user"),
                condition=models.Q(status="pending"),
                name="unique_pending_professional_invitation",
            ),
        ]

    def __str__(self):
        return f"{self.tenant} → {self.professional_user} ({self.get_status_display()})"

    def clean(self):
        super().clean()
        if getattr(self.professional_user, "role", None) != "professional":
            raise ValidationError({"professional_user": _("O convidado precisa ter perfil Profissional.")})

    def accept(self):
        from django.utils import timezone

        if self.status != self.Status.PENDING:
            raise ValidationError(_("Apenas convites aguardando aprovacao podem ser aceitos."))
        membership, _created = TenantMembership.objects.bypass_tenant().get_or_create(
            tenant=self.tenant,
            user=self.professional_user,
            role=TenantMembership.Role.PROFESSIONAL,
            defaults={"is_active": True},
        )
        if not membership.is_active:
            membership.is_active = True
            membership.save()
        professional, _prof_created = Professional.objects.bypass_tenant().get_or_create(
            tenant=self.tenant,
            user=self.professional_user,
            defaults={"is_active": True},
        )
        if not professional.is_active:
            professional.is_active = True
            professional.save()
        self.status = self.Status.ACCEPTED
        self.responded_at = timezone.now()
        self.save(update_fields=("status", "responded_at", "updated_at"))
        return professional

    def reject(self):
        from django.utils import timezone

        if self.status != self.Status.PENDING:
            raise ValidationError(_("Apenas convites aguardando aprovacao podem ser rejeitados."))
        self.status = self.Status.REJECTED
        self.responded_at = timezone.now()
        self.save(update_fields=("status", "responded_at", "updated_at"))
        return None

    def cancel(self):
        from django.utils import timezone

        if self.status != self.Status.PENDING:
            raise ValidationError(_("Apenas convites aguardando aprovacao podem ser cancelados."))
        self.status = self.Status.CANCELLED
        self.responded_at = timezone.now()
        self.save(update_fields=("status", "responded_at", "updated_at"))


WEEKDAYS_CHOICES = (
    (0, _("Domingo")),
    (1, _("Segunda-feira")),
    (2, _("Terça-feira")),
    (3, _("Quarta-feira")),
    (4, _("Quinta-feira")),
    (5, _("Sexta-feira")),
    (6, _("Sábado"))
)


def _fmt(t):
    return t.strftime("%H:%M") if t else "—"


def _intervals_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


DDDS_VALIDOS = {
    "61", "62", "64", "65", "66", "67",
    "81", "82", "83", "84", "85", "86", "87", "88", "89",
    "71", "73", "74", "75", "77",
    "63", "68", "69", "91", "92", "93", "94", "95", "96", "97", "98", "99",
    "11", "12", "13", "14", "15", "16", "17", "18", "19",
    "21", "22", "24", "27", "28",
    "31", "32", "33", "34", "35", "37", "38",
    "41", "42", "43", "44", "45", "46", "47", "48", "49",
    "51", "53", "54", "55",
}


def validate_br_phone(phone):
    """Valida celular BR: 11 digitos, DDD real, 3o digito=9, 4o digito em [5-9]."""
    if not phone or not phone.strip():
        return False
    digits = re.sub(r"\D", "", phone)
    if len(digits) != 11:
        return False
    if digits[2] != "9":
        return False
    if digits[3] not in "56789":
        return False
    return digits[:2] in DDDS_VALIDOS


def _availability_working_intervals(availability):
    if not availability.available:
        return []
    if availability.break_start and availability.break_end:
        return [
            (availability.start_time, availability.break_start),
            (availability.break_end, availability.end_time),
        ]
    return [(availability.start_time, availability.end_time)]


class BusinessHours(TenantOwnedModel):
    """Horário de funcionamento da barbearia por dia da semana (Sprint 5+).

    Modelo "facilitado": uma linha por dia da semana com flag de abertura
    (`is_open`) + horário de funcionamento (`open_time`/`close_time`) +
    intervalo de almoço (`break_start`/`break_end`, opcionais).

    Exemplo (lojista): Seg–Sex aberto 08h–20h com intervalo 12h–14h;
    Sábado aberto 08h–18h sem intervalo; Domingo fechado.
    O sinal `post_save` do Tenant cria as 7 linhas-padrão (todas fechadas)
    para que o dono só precise marcar a flag e ajustar os horários.
    """

    tenant = models.ForeignKey(  # type: ignore[assignment]
        Tenant,
        on_delete=models.CASCADE,
        related_name="business_hours",
        verbose_name=_("barbearia"),
    )
    weekday = models.IntegerField(_("dia da semana"), choices=WEEKDAYS_CHOICES)
    is_open = models.BooleanField(_("aberto?"), default=False)
    open_time = models.TimeField(_("abertura"), default=_time(8, 0))
    close_time = models.TimeField(_("fechamento"), default=_time(18, 0))
    break_start = models.TimeField(_("início do intervalo"), blank=True, null=True)
    break_end = models.TimeField(_("fim do intervalo"), blank=True, null=True)

    class Meta:
        verbose_name = _("horário de funcionamento")
        verbose_name_plural = _("horários de funcionamento")
        ordering = ("weekday",)
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "weekday"),
                name="unique_business_hours_per_tenant_weekday",
            ),
        ]

    def __str__(self):
        if not self.is_open:
            return f"{self.get_weekday_display()}: fechado"
        extra = ""
        if self.break_start and self.break_end:
            extra = f" (intervalo {_fmt(self.break_start)}–{_fmt(self.break_end)})"
        return f"{self.get_weekday_display()}: {_fmt(self.open_time)}–{_fmt(self.close_time)}{extra}"

    def clean(self):
        super().clean()
        if self.is_open:
            if self.close_time <= self.open_time:
                raise ValidationError(_("Fechamento deve ser maior que a abertura."))

            if self.break_start or self.break_end:
                if not (self.break_start and self.break_end):
                    raise ValidationError(
                        _("Informe início e fim do intervalo, ou deixe ambos vazios.")
                    )

                if self.break_end <= self.break_start:
                    raise ValidationError(
                        _("Fim do intervalo deve ser maior que o início.")
                    )

                if not (
                    self.open_time <= self.break_start <
                    self.break_end <= self.close_time
                ):
                    raise ValidationError(
                        _("O intervalo precisa estar dentro do horário de funcionamento.")
                    )

    @property
    def working_intervals(self):
        """Lista de tuplas (start, end) que representam expediente efetivo."""
        if not self.is_open:
            return []
        if self.break_start and self.break_end:
            return [(self.open_time, self.break_start),
                    (self.break_end, self.close_time)]
        return [(self.open_time, self.close_time)]


class ProfessionalAvailability(TenantOwnedModel):
    """Disponibilidade semanal de um profissional (Sprint 5+) — mesmo modelo
    facilitado do `BusinessHours`: uma linha por dia com flag `available`,
    horário `start_time`/`end_time` e intervalo opcional.

    Regras de conformidade (validadas em `clean()`):
      - Se a barbearia estiver FECHADA no dia => profissional NÃO pode atender.
      - O expediente do profissional precisa estar CONTIDO no da barbearia.
      - Se a barbearia tem intervalo (lunch) obrigatório, o profissional precisa
        ter um intervalo que o cubra (pra não atender com a loja fechada).
    """

    tenant = models.ForeignKey(  # type: ignore[assignment]
        Tenant,
        on_delete=models.CASCADE,
        related_name="+",
        verbose_name=_("barbearia"),
    )
    professional = models.ForeignKey(
        Professional,
        on_delete=models.CASCADE,
        related_name="availability",
        verbose_name=_("profissional"),
    )
    weekday = models.IntegerField(_("dia da semana"), choices=WEEKDAYS_CHOICES)
    available = models.BooleanField(_("disponível?"), default=False)
    start_time = models.TimeField(_("início"), default=_time(8, 0))
    end_time = models.TimeField(_("fim"), default=_time(18, 0))
    break_start = models.TimeField(_("início do intervalo"), blank=True, null=True)
    break_end = models.TimeField(_("fim do intervalo"), blank=True, null=True)

    class Meta:
        verbose_name = _("disponibilidade do profissional")
        verbose_name_plural = _("disponibilidades dos profissionais")
        ordering = ("professional", "weekday")
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "professional", "weekday"),
                name="unique_proavailability_per_tenant_pro_weekday",
            ),
        ]

    def __str__(self):
        if not self.available:
            return f"{self.professional} · {self.get_weekday_display()}: indisponível"
        extra = ""
        if self.break_start and self.break_end:
            extra = f" (intervalo {_fmt(self.break_start)}–{_fmt(self.break_end)})"
        return (f"{self.professional} · {self.get_weekday_display()}: "
                f"{_fmt(self.start_time)}–{_fmt(self.end_time)}{extra}")

    def clean(self):
        super().clean()
        if self.professional_id and self.professional.tenant_id != self.tenant_id:
            raise ValidationError(
                _("O profissional não pertence a esta barbearia (cross-tenant).")
            )
        if not self.available:
            return  # indisponível — nada a validar.
        if self.end_time <= self.start_time:
            raise ValidationError(_("Fim deve ser maior que o início."))
        if self.break_start or self.break_end:
            if not (self.break_start and self.break_end):
                raise ValidationError(
                    _("Informe início e fim do intervalo, ou deixe ambos vazios.")
                )
            if self.break_end <= self.break_start:
                raise ValidationError(_("Fim do intervalo deve ser maior que o início."))
            if not (self.start_time <= self.break_start < self.break_end <= self.end_time):
                raise ValidationError(
                    _("O intervalo do profissional precisa estar dentro do seu expediente.")
                )
        # ----- Conformidade com o horário da barbearia (PRD §11) -----
        bh = (
            BusinessHours.objects.bypass_tenant()
            .filter(tenant=self.tenant, weekday=self.weekday)
            .first()
        )
        if bh is None:
            raise ValidationError(
                _("Horário de funcionamento da barbearia não configurado para este dia.")
            )
        if not bh.is_open:
            raise ValidationError(
                _("A barbearia está FECHADA neste dia — o profissional não pode atender.")
            )
        # Expediente do profissional contido no expediente da loja.
        if self.start_time < bh.open_time or self.end_time > bh.close_time:
            raise ValidationError(
                _("Disponibilidade fora do horário da barbearia "
                  "(%(a)s–%(b)s). Permitido: %(o)s–%(c)s.")
                % {"a": _fmt(self.start_time), "b": _fmt(self.end_time),
                   "o": _fmt(bh.open_time), "c": _fmt(bh.close_time)}
            )
        # Se a loja tem intervalo, os expedientes EFETIVOS do profissional (excluindo
        # o seu próprio intervalo) não podem se sobrepor ao intervalo da loja:
        # o profissional não pode atender durante o almoço da loja (loja fechada).
        if bh.break_start and bh.break_end:
            if self.break_start and self.break_end:
                pro_intervals = [(self.start_time, self.break_start),
                                 (self.break_end, self.end_time)]
            else:
                pro_intervals = [(self.start_time, self.end_time)]
            for (s, e) in pro_intervals:
                if s < bh.break_end and bh.break_start < e:
                    raise ValidationError(
                        _("O expediente do profissional (%(a)s–%(b)s) se sobrepõe "
                          "ao intervalo da barbearia (%(c)s–%(d)s).")
                        % {"a": _fmt(s), "b": _fmt(e),
                           "c": _fmt(bh.break_start), "d": _fmt(bh.break_end)}
                    )
        # ----- Conflito de agenda entre barbearias (mesmo usuário) -----
        # Para o mesmo usuário, uma disponibilidade ativa em uma barbearia
        # não pode se sobrepor a outra ativa em outra barbearia no mesmo dia.
        current_intervals = _availability_working_intervals(self)
        other_rows = (
            ProfessionalAvailability.objects.bypass_tenant()
            .filter(
                professional__user=self.professional.user,
                weekday=self.weekday,
                available=True,
            )
            .exclude(pk=self.pk)
        )
        for other in other_rows:
            for start, end in current_intervals:
                for other_start, other_end in _availability_working_intervals(other):
                    if _intervals_overlap(start, end, other_start, other_end):
                        raise ValidationError(
                            _("Conflito de agenda com %(tenant)s em %(start)s–%(end)s.")
                            % {
                                "tenant": other.tenant,
                                "start": _fmt(other_start),
                                "end": _fmt(other_end),
                            }
                        )


# ---------- Sprint 6 — Agendamento (Core) ----------


class Appointment(TenantOwnedModel):
    """Agendamento de um cliente com um profissional (Sprint 6 — PRD §10/§11).

    Fluxo: Cliente -> Profissional -> Servico -> Horario -> Confirmacao.
    Regras de negocio (PRD §11):
      - Nenhum conflito de horario por profissional.
      - Multi-tenant obrigatorio em todas queries.
    """

    class Status(models.TextChoices):
        PENDING = "pending", _("Aguardando confirmacao")
        CONFIRMED = "confirmed", _("Confirmado")
        CANCELLED = "cancelled", _("Cancelado")
        COMPLETED = "completed", _("Concluido")

    professional = models.ForeignKey(
        Professional,
        on_delete=models.CASCADE,
        related_name="appointments",
        verbose_name=_("profissional"),
    )
    service = models.ForeignKey(
        Service,
        on_delete=models.CASCADE,
        related_name="appointments",
        verbose_name=_("servico"),
    )
    client_name = models.CharField(_("nome do cliente"), max_length=120)
    client_phone = models.CharField(_("telefone"), max_length=20)
    client_email = models.EmailField(_("e-mail"), blank=True)
    date = models.DateField(_("data"))
    start_time = models.TimeField(_("inicio"))
    end_time = models.TimeField(_("fim"), blank=True, null=True)
    status = models.CharField(
        _("status"), max_length=20, choices=Status.choices, default=Status.PENDING,
    )
    notes = models.TextField(_("observacoes"), blank=True)

    class Meta:
        verbose_name = _("agendamento")
        verbose_name_plural = _("agendamentos")
        ordering = ("-date", "-start_time")
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "professional", "date", "start_time"),
                condition=models.Q(status__in=["pending", "confirmed"]),
                name="unique_active_appointment_per_slot",
            ),
        ]

    def __str__(self):
        return "{} - {} - {} {}".format(
            self.client_name, self.professional, self.date, _fmt(self.start_time),
        )

    @property
    def is_active_status(self):
        return self.status in (self.Status.PENDING, self.Status.CONFIRMED)

    def _compute_end_time(self):
        from datetime import datetime, timedelta
        base = datetime(2000, 1, 1)
        start_dt = datetime.combine(base, self.start_time)
        end_dt = start_dt + timedelta(minutes=self.service.duration_minutes)
        return end_dt.time()

    def clean(self):
        super().clean()
        errors = {}

        if not self.client_name or not self.client_name.strip():
            errors["client_name"] = _("Nome do cliente e obrigatorio.")
        if not self.client_phone or not self.client_phone.strip():
            errors["client_phone"] = _("Telefone e obrigatorio.")
        elif not validate_br_phone(self.client_phone):
            errors["client_phone"] = _("WhatsApp invalido. Informe DDD + 9 + numero (ex: 11999999999).")
        if not self.date:
            errors["date"] = _("Data e obrigatoria.")
        if not self.start_time:
            errors["start_time"] = _("Horario de inicio e obrigatorio.")

        if self.professional_id and self.service_id:
            if self.professional.tenant_id != self.tenant_id:
                errors["professional"] = _("Profissional nao pertence a esta barbearia.")
            if self.service.tenant_id != self.tenant_id:
                errors["service"] = _("Servico nao pertence a esta barbearia.")
            if self.professional.tenant_id != self.service.tenant_id:
                errors["service"] = _("Profissional e servico pertencem a barbearias diferentes.")
            if not self.professional.is_active:
                errors["professional"] = _("Profissional inativo.")
            if not self.service.is_active:
                errors["service"] = _("Servico inativo.")
            vinculo = ProfessionalService.objects.bypass_tenant().filter(
                tenant=self.tenant, professional=self.professional,
                service=self.service,
            ).exists()
            if not vinculo:
                errors["service"] = _("O profissional nao oferece este servico.")

        if self.date and self.start_time and self.service_id:
            import datetime as dt_mod

            if self.date < dt_mod.date.today():
                errors["date"] = _("Nao e possivel agendar em data passada.")

            self.end_time = self._compute_end_time()

            weekday = self.date.weekday()
            numeric_weekday = (weekday + 1) % 7

            bh = (
                BusinessHours.objects.bypass_tenant()
                .filter(tenant=self.tenant, weekday=numeric_weekday)
                .first()
            )
            if bh is None or not bh.is_open:
                errors["date"] = _("A barbearia esta fechada neste dia.")
            else:
                for interval in bh.working_intervals:
                    if self.start_time >= interval[0] and self.end_time <= interval[1]:
                        break
                else:
                    errors["start_time"] = _(
                        "Horario fora do expediente da barbearia (%(o)s - %(c)s)."
                    ) % {"o": _fmt(bh.open_time), "c": _fmt(bh.close_time)}

            avail = (
                ProfessionalAvailability.objects.bypass_tenant()
                .filter(
                    tenant=self.tenant,
                    professional=self.professional,
                    weekday=numeric_weekday,
                ).first()
            )
            if avail is None or not avail.available:
                errors["date"] = _("Profissional indisponivel neste dia.")
            else:
                avail_intervals = _availability_working_intervals(avail)
                for interval in avail_intervals:
                    if self.start_time >= interval[0] and self.end_time <= interval[1]:
                        break
                else:
                    errors["start_time"] = _(
                        "Horario fora da disponibilidade do profissional."
                    )

            if self.professional_id and not errors.get("professional"):
                conflicts = (
                    Appointment.objects.bypass_tenant()
                    .filter(
                        tenant=self.tenant,
                        professional=self.professional,
                        date=self.date,
                        status__in=[self.Status.PENDING, self.Status.CONFIRMED],
                    )
                    .exclude(pk=self.pk)
                )
                for other in conflicts:
                    if _intervals_overlap(
                        self.start_time, self.end_time,
                        other.start_time, other.end_time,
                    ):
                        errors["start_time"] = _(
                            "Conflito de horario: ja existe agendamento "
                            "as %(s)s-%(e)s."
                        ) % {"s": _fmt(other.start_time), "e": _fmt(other.end_time)}
                        break

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.service_id and self.start_time:
            self.end_time = self._compute_end_time()
        super().save(*args, **kwargs)


class Product(TenantOwnedModel):
    """Produto fisico vendido durante atendimentos (Sprint 7).

    Itens como pomadas, shampoos, pos-barbeiros, etc.
    """

    name = models.CharField(_("nome"), max_length=120)
    price = models.DecimalField(_("preco"), max_digits=10, decimal_places=2)
    cost = models.DecimalField(_("custo"), max_digits=10, decimal_places=2, blank=True, null=True)
    category = models.CharField(_("categoria"), max_length=60, blank=True)
    is_active = models.BooleanField(_("ativo"), default=True)

    class Meta:
        verbose_name = _("produto")
        verbose_name_plural = _("produtos")
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "name"),
                name="unique_product_name_per_tenant",
            ),
        ]

    def __str__(self):
        return self.name


class Session(TenantOwnedModel):
    """Atendimento/sessao (Sprint 7).

    Fluxo: Agendamento -> Sessao -> Produtos -> Fechamento -> Pagamento.
    Pode ser iniciado a partir de um Appointment confirmado ou avulso.
    """

    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", _("Em andamento")
        COMPLETED = "completed", _("Concluido")
        CANCELLED = "cancelled", _("Cancelado")

    appointment = models.ForeignKey(
        Appointment,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="sessions",
        verbose_name=_("agendamento"),
    )
    service = models.ForeignKey(
        Service,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="sessions",
        verbose_name=_("serviço"),
    )
    service_price = models.DecimalField(
        _("preço do serviço"), max_digits=10, decimal_places=2,
        blank=True, null=True,
    )
    professional = models.ForeignKey(
        Professional,
        on_delete=models.CASCADE,
        related_name="sessions",
        verbose_name=_("profissional"),
    )
    client_name = models.CharField(_("nome do cliente"), max_length=120)
    client_phone = models.CharField(_("telefone"), max_length=20, blank=True)
    status = models.CharField(
        _("status"), max_length=20, choices=Status.choices, default=Status.IN_PROGRESS,
    )
    total_amount = models.DecimalField(
        _("valor total"), max_digits=10, decimal_places=2, blank=True, null=True,
    )
    started_at = models.DateTimeField(_("iniciado em"), auto_now_add=True)
    closed_at = models.DateTimeField(_("fechado em"), null=True, blank=True)
    notes = models.TextField(_("observacoes"), blank=True)

    class Meta:
        verbose_name = _("sessao")
        verbose_name_plural = _("sessoes")
        ordering = ("-started_at",)

    def __str__(self):
        return "{} - {}".format(self.client_name, self.professional)

    @property
    def is_open(self):
        return self.status == self.Status.IN_PROGRESS


class SessionProduct(TenantOwnedModel):
    """Produto consumido durante uma sessao (Sprint 7)."""

    session = models.ForeignKey(
        Session,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name=_("sessao"),
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="+",
        verbose_name=_("produto"),
    )
    quantity = models.PositiveIntegerField(_("quantidade"), default=1)
    unit_price = models.DecimalField(_("preco unitario"), max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = _("item de sessao")
        verbose_name_plural = _("itens de sessao")

    def __str__(self):
        return "{} x {}".format(self.quantity, self.product)

    @property
    def total_price(self):
        return self.quantity * self.unit_price

    def save(self, *args, **kwargs):
        if not self.unit_price and self.product_id:
            self.unit_price = self.product.price
        super().save(*args, **kwargs)
