from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.db import models
from django.utils.safestring import mark_safe
from django.utils.decorators import method_decorator
from django.utils.http import unquote

from .models import (
    Appointment,
    BusinessHours,
    Product,
    Professional,
    ProfessionalAvailability,
    ProfessionalInvitation,
    ProfessionalService,
    Service,
    Session,
    SessionProduct,
    Tenant,
    TenantMembership,
    current_tenant,
    current_user,
    set_current_tenant,
)


# Roles autorizadas a alterar a flag `is_active` de um serviço.
# (superadmin SaaS usa is_superuser — tratado à parte via request.user.is_superadmin)
SERVICE_TOGGLE_ROLES = ("owner", "manager")
# Roles com gestão de profissionais/disponibilidade.
PROFESSIONAL_MANAGER_ROLES = ("owner", "manager")


class TenantContextMixin:
    """Ajusta o ``current_tenant()`` para o tenant do objeto sendo editado.

    Problema arquitetural (multi-unidade):
        O ``TenantMiddleware`` define ``current_tenant = user.tenant`` (legado).
        Quando um dono com memberships em várias barbearias edita a 2ª unidade,
        o contexto da requisição aponta para a 1ª barbearia, mas o objeto
        pertence à 2ª. A validação do Admin (``Model.clean()``,
        ``ModelForm.is_valid()``, querysets de inlines) ocorre **antes** de
        ``save_model``/``save_formset``, causando erro cross-tenant.

    Solução:
        ``changeform_view`` é o ponto mais alto do ciclo de vida do form no
        Admin — engloba construção do form, validação e salvamento. Setamos o
        ``current_tenant`` para o tenant do objeto **antes** de delegar ao
        ``super()``, garantindo que todo o ciclo opere no tenant correto.
        O contexto original é restaurado em ``finally``.
    """

    def _resolve_tenant(self, obj):
        """Extrai o tenant do objeto. Se o próprio objeto for um Tenant, retorna-o."""
        if obj is None:
            return None
        if isinstance(obj, Tenant):
            return obj
        return getattr(obj, "tenant", None)

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        prev_tenant = current_tenant()
        prev_user = current_user()
        tenant = None
        if object_id is not None:
            obj = self.get_object(request, unquote(object_id))
            tenant = self._resolve_tenant(obj)
        if tenant is not None:
            set_current_tenant(tenant, bypass=False, user=request.user)
        try:
            return super().changeform_view(request, object_id, form_url, extra_context)
        finally:
            set_current_tenant(prev_tenant, bypass=False, user=prev_user)


@admin.register(Tenant)
class TenantAdmin(TenantContextMixin, admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "has_logo", "has_cover", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    ordering = ("name",)
    readonly_fields = ("logo_preview", "cover_preview")

    fieldsets = (
        (None, {"fields": ("name", "slug", "is_active")}),
        ("Página Pública", {
            "fields": ("tagline", "description", "phone", "address",
                       "whatsapp", "instagram"),
        }),
        ("Mídia (PRD §13.3 — máx 4MB, jpg/png/webp)", {
            "fields": ("logo", "logo_preview", "cover", "cover_preview"),
        }),
    )
    inlines = ()  # preenchido abaixo (BusinessHoursInline)

    def get_inlines(self, request, obj):
        # Horários de funcionamento só fazem sentido p/ barbearia já criada.
        return (BusinessHoursInline,) if obj is not None else ()

    def save_formset(self, request, form, formset, change):
        # Garante o tenant nas linhas do BusinessHoursInline (defesa extra).
        tenant = form.instance
        if not request.user.is_superadmin and tenant is not None:
            for f in formset.forms:
                if not f.has_changed():
                    continue
                inst = f.instance
                if getattr(inst, "tenant_id", None) is None:
                    inst.tenant = tenant
        super().save_formset(request, form, formset, change)

    # ---------- Isolamento + isolamento de exibição ----------
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superadmin:
            return qs
        # Dono/gerente com memberships em várias barbearias vê todas elas.
        tenant_ids = _managed_tenant_ids(request.user, roles=("owner", "manager"))
        if not tenant_ids:
            tenant = getattr(request, "tenant", None)
            return qs.filter(pk=tenant.pk) if tenant is not None else qs.none()
        return qs.filter(pk__in=tenant_ids)

    def has_add_permission(self, request):
        # Só superadmin cria novas barbearias (tenants).
        return request.user.is_superadmin

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superadmin

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        # Não-superadmin não pode mexer no slug/is_active/uuid da própria raiz.
        if not request.user.is_superadmin:
            for f in ("slug", "is_active"):
                if f in form.base_fields:
                    form.base_fields[f].disabled = True
        return form

    # ---------- Previews de imagem no admin ----------
    def _img(self, obj, field, label):
        f = getattr(obj, field, None)
        if not f:
            return mark_safe("<i style='color:#999'>—</i>")
        return mark_safe(
            f"<img src='{f.url}' alt='{label}' "
            f"style='max-height:160px;border:1px solid rgba(200,169,126,.2)'>"
        )

    def logo_preview(self, obj):
        return self._img(obj, "logo", "logo")

    logo_preview.short_description = "Prévia do logo"

    def cover_preview(self, obj):
        return self._img(obj, "cover", "capa")

    cover_preview.short_description = "Prévia da capa"

    def has_logo(self, obj):
        return bool(obj.logo)

    has_logo.boolean = True
    has_logo.short_description = "logo"

    def has_cover(self, obj):
        return bool(obj.cover)

    has_cover.boolean = True
    has_cover.short_description = "capa"


@admin.register(Service)
class ServiceAdmin(TenantContextMixin, admin.ModelAdmin):
    list_display = ("name", "tenant", "duration_minutes", "is_active")
    list_filter = ("tenant", "is_active")
    list_editable = ("is_active",)  # edição rápida em lista (validada em save_model)
    search_fields = ("name",)
    ordering = ("tenant", "name")

    # ---------- Isolamento multi-tenant ----------
    def get_queryset(self, request):
        qs = Service.objects.bypass_tenant()
        if request.user.is_superadmin:
            return qs
        tenant_ids = _managed_tenant_ids(request.user, roles=("owner", "manager", "professional"))
        if not tenant_ids:
            tenant = getattr(request, "tenant", None)
            return qs.filter(tenant=tenant) if tenant is not None else qs.none()
        return qs.filter(tenant_id__in=tenant_ids)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        # Limita o dropdown `tenant` às barbearias das memberships (multi-unidade).
        _restrict_tenant_field_to_memberships(form, request, roles=("owner", "manager"), obj=obj)
        # Profissionais e clientes não podem mexer em `is_active`:
        # removemos o campo do form para esses perfis (defesa em profundidade).
        if request.user.role not in SERVICE_TOGGLE_ROLES and not request.user.is_superadmin:
            if "is_active" in form.base_fields:
                form.base_fields["is_active"].disabled = True
        return form

    def save_model(self, request, obj, form, change):
        # Garante que não-superadmin não crie serviço em tenant alheio.
        if not request.user.is_superadmin and obj.tenant_id is None:
            tenant_ids = _managed_tenant_ids(request.user, roles=("owner", "manager"))
            obj.tenant_id = tenant_ids[0] if tenant_ids else getattr(getattr(request, "tenant", None), "pk", None)
        # Regra: `is_active` só pode ser alterado por owner/manager/superadmin.
        if change:
            can_toggle = request.user.is_superadmin or request.user.role in SERVICE_TOGGLE_ROLES
            if not can_toggle and "is_active" in form.changed_data:
                raise PermissionDenied(
                    "Apenas o dono, o gerente ou um superadmin pode ativar/inativar um serviço."
                )
        super().save_model(request, obj, form, change)

    # ---------- Bloqueio de exclusão (defesa em profundidade) ----------
    # Serviços não podem ser excluídos por ninguém além do superadmin SaaS.
    # Donos/gerentes/barbeiros devem INATIVAR o serviço (is_active=False).
    def has_delete_permission(self, request, obj=None):
        # Delega à permissão Django E exige superadmin SaaS.
        if not request.user.is_superadmin:
            return False
        return super().has_delete_permission(request, obj)

    def delete_model(self, request, obj):
        if not request.user.is_superadmin:
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied("Exclusão de serviços é reservada ao superadmin SaaS. Use a inativação.")
        super().delete_model(request, obj)

    def get_actions(self, request):
        # Remove a ação em massa "Excluir selecionados" para não-superadmin.
        actions = super().get_actions(request)
        if not request.user.is_superadmin and "delete_selected" in actions:
            del actions["delete_selected"]
        return actions

    def get_changeform_initial_data(self, request):
        # Pré-preenche o tenant ao abrir o form de adição (respeita memberships).
        initial = super().get_changeform_initial_data(request)
        if not request.user.is_superadmin:
            tenant_ids = _managed_tenant_ids(request.user, roles=("owner", "manager"))
            if tenant_ids and len(tenant_ids) == 1:
                initial["tenant"] = tenant_ids[0]
            else:
                tenant = getattr(request, "tenant", None)
                if tenant is not None:
                    initial["tenant"] = tenant
        return initial

# ---------- Sprint 5 — Profissionais + Serviços + Disponibilidade ----------


def _managed_tenant_ids(user, roles=("owner", "manager")):
    """IDs das barbearias onde o usuário tem membership ativa com as roles dadas.

    Retorna None para superadmin SaaS (escopo global).
    """
    if getattr(user, "is_superadmin", False):
        return None
    return list(TenantMembership.objects.bypass_tenant().filter(
        user=user,
        role__in=roles,
        is_active=True,
    ).values_list("tenant_id", flat=True))


def _restrict_tenant_field_to_memberships(form, request, roles=("owner", "manager"), obj=None):
    """Limita o dropdown `tenant` às barbearias das memberships do usuário.

    - Edição (obj is not None): tenant é imutável (save() bloqueia troca).
      Campo desabilitado para TODOS os usuários — previne o erro.
    - Superadmin (add): vê todas (não filtra).
    - Single-unit (add): tenant fixo/desabilitado (UX preservada).
    - Multi-unit (add): dropdown selecionável entre as memberships.
    """
    if "tenant" not in form.base_fields:
        return
    # Edição: tenant é imutável — desabilita para evitar tentativa de troca.
    if obj is not None:
        form.base_fields["tenant"].disabled = True
        return
    if request.user.is_superadmin:
        return
    tenant_ids = _managed_tenant_ids(request.user, roles=roles)
    if not tenant_ids:
        tenant = getattr(request, "tenant", None)
        if tenant is None:
            return
        form.base_fields["tenant"].queryset = form.base_fields["tenant"].queryset.filter(pk=tenant.pk)
        form.base_fields["tenant"].initial = tenant
        form.base_fields["tenant"].disabled = True
        return
    field = form.base_fields["tenant"]
    field.queryset = field.queryset.filter(pk__in=tenant_ids)
    if len(tenant_ids) == 1:
        field.initial = tenant_ids[0]
        field.disabled = True
    else:
        # Multi-unit add: deixa selecionável, pré-preenche com user.tenant se válido.
        cur = getattr(request, "tenant", None)
        if cur is not None and cur.pk in tenant_ids:
            field.initial = cur


@admin.register(TenantMembership)
class TenantMembershipAdmin(TenantContextMixin, admin.ModelAdmin):
    list_display = ("tenant", "user", "role", "is_active", "created_at")
    list_filter = ("role", "is_active", "tenant")
    search_fields = ("user__email", "tenant__name")

    def get_queryset(self, request):
        qs = TenantMembership.objects.bypass_tenant()
        if request.user.is_superadmin:
            return qs
        tenant_ids = _managed_tenant_ids(request.user, roles=("owner", "manager", "professional"))
        return qs.filter(tenant_id__in=tenant_ids)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        # Limita o dropdown `tenant` às barbearias das memberships do dono.
        _restrict_tenant_field_to_memberships(form, request, roles=("owner", "manager"), obj=obj)
        return form

    def save_model(self, request, obj, form, change):
        # Garante que o tenant seja uma das barbearias do dono (multi-unidade).
        if not request.user.is_superadmin and obj.tenant_id is None:
            tenant_ids = _managed_tenant_ids(request.user, roles=("owner", "manager"))
            obj.tenant_id = tenant_ids[0] if tenant_ids else None
        super().save_model(request, obj, form, change)


@admin.register(ProfessionalInvitation)
class ProfessionalInvitationAdmin(TenantContextMixin, admin.ModelAdmin):
    list_display = ("tenant", "professional_user", "invited_by", "status", "created_at", "responded_at")
    list_filter = ("status", "tenant")
    search_fields = ("professional_user__email", "invited_by__email", "tenant__name")
    actions = ("admin_cancelar_convite",)
    readonly_fields = ("status", "responded_at", "created_at")

    fieldsets = (
        (None, {"fields": ("tenant", "professional_user", "invited_by", "status")}),
        ("Datas", {"fields": ("created_at", "responded_at")}),
    )

    def get_queryset(self, request):
        qs = ProfessionalInvitation.objects.bypass_tenant()
        if request.user.is_superadmin:
            return qs
        managed_ids = _managed_tenant_ids(request.user, roles=("owner", "manager"))
        return qs.filter(models.Q(tenant_id__in=managed_ids) | models.Q(professional_user=request.user))

    def get_actions(self, request):
        actions = super().get_actions(request)
        # Profissionais (não-gestores) não veem a ação em massa de cancelar.
        is_manager = (
            request.user.is_superadmin
            or request.user.role in ("owner", "manager")
        )
        if not is_manager and "admin_cancelar_convite" in actions:
            del actions["admin_cancelar_convite"]
        return actions

    @admin.action(description="Cancelar convites selecionados (pendente → cancelado)")
    def admin_cancelar_convite(self, request, queryset):
        from django.contrib import messages
        from django.core.exceptions import ValidationError
        count = 0
        errors = 0
        for inv in queryset:
            if inv.status != ProfessionalInvitation.Status.PENDING:
                errors += 1
                continue
            # Remetente ou superadmin pode cancelar qualquer convite pendente.
            is_sender = inv.invited_by_id == request.user.pk
            if not (request.user.is_superadmin or is_sender):
                errors += 1
                continue
            try:
                inv.cancel()
                count += 1
            except ValidationError:
                errors += 1
        if count:
            messages.success(request, f"{count} convite(s) cancelado(s).")
        if errors:
            messages.warning(request, f"{errors} convite(s) não puderam ser cancelados (não estavam pendentes ou sem permissão).")

    def save_model(self, request, obj, form, change):
        if not request.user.is_superadmin and obj.tenant_id is None:
            tenant_ids = _managed_tenant_ids(request.user, roles=("owner", "manager"))
            obj.tenant_id = tenant_ids[0] if tenant_ids else None
        if obj.invited_by_id is None:
            obj.invited_by = request.user
        super().save_model(request, obj, form, change)


class ProfessionalServiceInline(admin.TabularInline):
    """Vínculo profissional × serviço (inline no ProfessionalAdmin)."""
    model = ProfessionalService
    extra = 0  # não exibe linhas em branco (evita "já existe" p/ edição)
    can_delete = True
    verbose_name = "serviço vinculado"
    verbose_name_plural = "serviços vinculados"
    autocomplete = False

    def get_queryset(self, request):
        qs = ProfessionalService.objects.bypass_tenant()
        if request.user.is_superadmin:
            return qs
        tenant_ids = _managed_tenant_ids(request.user, roles=("owner", "manager", "professional"))
        if tenant_ids:
            return qs.filter(tenant_id__in=tenant_ids)
        tenant = getattr(request, "tenant", None)
        return qs.filter(tenant=tenant) if tenant is not None else qs.none()

    def get_formset(self, request, obj=None, **kwargs):
        fs = super().get_formset(request, obj=obj, **kwargs)
        # O inline pertence ao tenant do Professional pai (obj). Para TODOS os
        # usuários (inclusive superuser), o dropdown de `service` só mostra
        # serviços do tenant do pai — elimina cross-tenant (barbearia A em B).
        parent_tenant = getattr(obj, "tenant", None)
        bf = fs.form.base_fields
        if parent_tenant is not None:
            if "service" in bf:
                bf["service"].queryset = Service.objects.bypass_tenant().filter(tenant=parent_tenant)
            if "tenant" in bf:
                bf["tenant"].queryset = Tenant.objects.filter(pk=parent_tenant.pk)
                bf["tenant"].initial = parent_tenant
                bf["tenant"].disabled = True
        return fs


def _inline_tenant_filter(request, qs):
    """Helper: filtra queryset de inline pelo tenant do usuário logado."""
    if request.user.is_superadmin:
        return qs
    tenant = getattr(request, "tenant", None)
    return qs.none() if tenant is None else qs.filter(tenant=tenant)


def _tenant_scoped_queryset(request, model):
    """Queryset admin pelo tenant da request, independente do ContextVar."""
    qs = model.objects.bypass_tenant()
    if request.user.is_superadmin:
        return qs
    tenant = getattr(request, "tenant", None)
    return qs.none() if tenant is None else qs.filter(tenant=tenant)


def _restrict_inline_tenant_field(fs, request, also=()):
    """Limita/fixa o campo `tenant` (e FKs listados em `also`) ao tenant
    do usuário logado, e desabilita a edição do `tenant` (já é fixo).

    Evita expor todas as barbearias no dropdown e impede criar registros
    em tenant alheio via inline.
    """
    if request.user.is_superadmin:
        return  # superadmin SaaS vê/selecciona tudo.
    tenant = getattr(request, "tenant", None)
    if tenant is None:
        return
    bf = fs.form.base_fields
    # Campo `tenant`: só a própria barbearia, desabilitado + initial fixo.
    if "tenant" in bf:
        fld = bf["tenant"]
        fld.queryset = fld.queryset.filter(pk=tenant.pk)
        fld.initial = tenant
        fld.disabled = True
    # Demais FKs que precisam ser filtrados pelo mesmo tenant.
    for name in also:
        if name in bf:
            f = bf[name]
            manager = getattr(f.queryset.model, "objects", None)
            if manager is not None and hasattr(manager, "bypass_tenant"):
                f.queryset = manager.bypass_tenant().filter(tenant=tenant)
            else:
                f.queryset = f.queryset.filter(tenant=tenant)


class BusinessHoursInline(admin.TabularInline):
    """Horário de funcionamento da barbearia (1 linha por dia da semana).

    Mostra exatamente os 7 dias (max_num=7), já criados pelo signal no
    `post_save` do Tenant: o dono só marca a flag `is_open` e ajusta os
    horários/intervalo. Múltiplos dias com o mesmo expediente são editados
    repetindo a configuração (UI simples e explícita).
    """
    model = BusinessHours
    extra = 0
    max_num = 7
    can_delete = False
    verbose_name = "horário de funcionamento"
    verbose_name_plural = "Horários de funcionamento (1 linha por dia)"
    ordering = ("weekday",)

    def get_queryset(self, request):
        qs = BusinessHours.objects.bypass_tenant()
        if request.user.is_superadmin:
            return qs
        tenant_ids = _managed_tenant_ids(request.user, roles=("owner", "manager"))
        if tenant_ids:
            return qs.filter(tenant_id__in=tenant_ids)
        tenant = getattr(request, "tenant", None)
        return qs.filter(tenant=tenant) if tenant is not None else qs.none()

    def get_formset(self, request, obj=None, **kwargs):
        fs = super().get_formset(request, obj=obj, **kwargs)
        # O inline pertence ao tenant do Tenant pai (obj).
        parent_tenant = obj
        bf = fs.form.base_fields
        if parent_tenant is not None and "tenant" in bf:
            bf["tenant"].queryset = bf["tenant"].queryset.filter(pk=parent_tenant.pk)
            bf["tenant"].initial = parent_tenant
            bf["tenant"].disabled = True
        return fs


class ProfessionalAvailabilityInline(admin.TabularInline):
    """Disponibilidade semanal do profissional (1 linha por dia).

    Mostra os 7 dias (criados pelo signal em `post_save` de Professional).
    O dono/gerente marca a flag `available` e ajusta horário/intervalo;
    o `clean()` de ProfessionalAvailability valida a conformidade com o
    horário da barbearia.
    """
    model = ProfessionalAvailability
    extra = 0
    max_num = 7
    can_delete = False
    verbose_name = "disponibilidade do profissional"
    verbose_name_plural = "Disponibilidade (1 linha por dia)"
    ordering = ("weekday",)

    def get_queryset(self, request):
        qs = ProfessionalAvailability.objects.bypass_tenant()
        if request.user.is_superadmin:
            return qs
        tenant_ids = _managed_tenant_ids(request.user, roles=("owner", "manager", "professional"))
        if tenant_ids:
            return qs.filter(tenant_id__in=tenant_ids)
        tenant = getattr(request, "tenant", None)
        return qs.filter(tenant=tenant) if tenant is not None else qs.none()

    def get_formset(self, request, obj=None, **kwargs):
        fs = super().get_formset(request, obj=obj, **kwargs)
        # O inline pertence ao tenant do Professional pai (obj).
        parent_tenant = getattr(obj, "tenant", None)
        bf = fs.form.base_fields
        if parent_tenant is not None:
            if "professional" in bf:
                bf["professional"].queryset = Professional.objects.bypass_tenant().filter(tenant=parent_tenant)
            if "tenant" in bf:
                bf["tenant"].queryset = Tenant.objects.filter(pk=parent_tenant.pk)
                bf["tenant"].initial = parent_tenant
                bf["tenant"].disabled = True
        return fs


@admin.register(Professional)
class ProfessionalAdmin(TenantContextMixin, admin.ModelAdmin):
    list_display = ("__str__", "user_email", "tenant", "is_active",
                    "qtd_servicos", "dias_disponiveis")
    list_filter = ("is_active",)
    search_fields = ("user__email", "user__first_name", "user__last_name", "bio")
    ordering = ("tenant", "user__first_name")
    list_editable = ("is_active",)
    inlines = (ProfessionalServiceInline, ProfessionalAvailabilityInline)
    readonly_fields = ("photo_preview",)

    fieldsets = (
        (None, {"fields": ("user", "tenant", "is_active")}),
        ("Perfil público", {"fields": ("bio", "photo", "photo_preview")}),
    )

    # ---------- Helpers ----------
    @admin.display(description="e-mail")
    def user_email(self, obj):
        return obj.user.email

    @admin.display(description="serviços")
    def qtd_servicos(self, obj):
        return ProfessionalService.objects.bypass_tenant().filter(professional=obj).count()

    @admin.display(description="dias disp.")
    def dias_disponiveis(self, obj):
        return ProfessionalAvailability.objects.bypass_tenant().filter(
            professional=obj, available=True
        ).count()

    def photo_preview(self, obj):
        if not obj.photo:
            return mark_safe("<i style='color:#999'>—</i>")
        return mark_safe(
            f"<img src='{obj.photo.url}' alt='foto' "
            f"style='max-height:160px;border:1px solid rgba(200,169,126,.2)'>"
        )
    photo_preview.short_description = "Prévia da foto"

    # ---------- Isolamento multi-tenant ----------
    def get_queryset(self, request):
        qs = Professional.objects.bypass_tenant()
        if request.user.is_superadmin:
            return qs
        tenant_ids = _managed_tenant_ids(request.user, roles=("owner", "manager", "professional"))
        return qs.filter(tenant_id__in=tenant_ids)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        # Limita o dropdown `tenant` às barbearias das memberships (multi-unidade).
        _restrict_tenant_field_to_memberships(form, request, roles=("owner", "manager", "professional"), obj=obj)
        if not request.user.is_superadmin:
            from base.models import User
            tenant_ids = _managed_tenant_ids(request.user, roles=("owner", "manager", "professional"))
            # Campo `user`: mostra users das barbearias das memberships OU users
            # com TenantMembership ativa nesses tenants e role professional/owner.
            if "user" in form.base_fields:
                uf = form.base_fields["user"]
                if tenant_ids:
                    uf.queryset = uf.queryset.filter(
                        models.Q(tenant_id__in=tenant_ids) |
                        models.Q(tenant_memberships__tenant_id__in=tenant_ids,
                                 tenant_memberships__is_active=True),
                        role__in=[User.Role.PROFESSIONAL, User.Role.OWNER],
                    ).distinct()
                else:
                    tenant = getattr(request, "tenant", None)
                    if tenant is not None:
                        uf.queryset = uf.queryset.filter(
                            tenant=tenant,
                            role__in=[User.Role.PROFESSIONAL, User.Role.OWNER],
                        )
            if request.user.role not in PROFESSIONAL_MANAGER_ROLES:
                for fn in ("is_active", "user"):
                    if fn in form.base_fields:
                        form.base_fields[fn].disabled = True
        return form

    def save_model(self, request, obj, form, change):
        if not request.user.is_superadmin and obj.tenant_id is None:
            tenant_ids = _managed_tenant_ids(request.user, roles=("owner", "manager", "professional"))
            obj.tenant_id = tenant_ids[0] if tenant_ids else getattr(getattr(request, "tenant", None), "pk", None)
        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        # Garante que as linhas dos inlines (ProfessionalService,
        # ProfessionalAvailability) sejam gravadas com o tenant do
        # profissional pai (defesa em profundidade — vale para TODOS, inclusive
        # superuser: o inline pertence ao tenant do Professional pai).
        tenant = form.instance.tenant
        if tenant is not None:
            for f in formset.forms:
                if not f.has_changed():
                    continue
                inst = f.instance
                if getattr(inst, "tenant_id", None) is None:
                    inst.tenant = tenant
        super().save_formset(request, form, formset, change)

    def has_delete_permission(self, request, obj=None):
        return (
            request.user.is_superadmin or request.user.role in PROFESSIONAL_MANAGER_ROLES
        ) and super().has_delete_permission(request, obj)

    def get_actions(self, request):
        actions = super().get_actions(request)
        if request.user.role not in PROFESSIONAL_MANAGER_ROLES and not request.user.is_superadmin:
            if "delete_selected" in actions:
                del actions["delete_selected"]
        return actions

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        if not request.user.is_superadmin:
            tenant_ids = _managed_tenant_ids(request.user, roles=("owner", "manager", "professional"))
            if tenant_ids and len(tenant_ids) == 1:
                initial["tenant"] = tenant_ids[0]
            else:
                tenant = getattr(request, "tenant", None)
                if tenant is not None:
                    initial["tenant"] = tenant
        return initial


# ---------- Sprint 6 — Agendamento (Core) ----------


@admin.register(Appointment)
class AppointmentAdmin(TenantContextMixin, admin.ModelAdmin):
    list_display = ("date", "start_time", "client_name", "professional",
                    "service", "status")
    list_filter = ("status", "date", "professional")
    search_fields = ("client_name", "client_phone", "client_email")
    date_hierarchy = "date"
    ordering = ("-date", "-start_time")
    actions = ("confirmar_agendamentos", "cancelar_agendamentos")

    fieldsets = (
        (None, {"fields": ("tenant", "professional", "service", "status")}),
        ("Cliente", {"fields": ("client_name", "client_phone", "client_email")}),
        ("Horario", {"fields": ("date", "start_time", "end_time")}),
        ("Extras", {"fields": ("notes",)}),
    )
    readonly_fields = ("end_time",)

    def get_queryset(self, request):
        qs = Appointment.objects.bypass_tenant()
        if request.user.is_superadmin:
            return qs
        tenant_ids = _managed_tenant_ids(
            request.user, roles=("owner", "manager", "professional")
        )
        if tenant_ids:
            return qs.filter(tenant_id__in=tenant_ids)
        return qs.none()

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        _restrict_tenant_field_to_memberships(
            form, request,
            roles=("owner", "manager", "professional"),
            obj=obj,
        )
        if not request.user.is_superadmin:
            tenant_ids = _managed_tenant_ids(
                request.user,
                roles=("owner", "manager", "professional"),
            )
            if "professional" in form.base_fields and tenant_ids:
                form.base_fields["professional"].queryset = (
                    Professional.objects.bypass_tenant().filter(
                        tenant_id__in=tenant_ids, is_active=True,
                    )
                )
            if "service" in form.base_fields and tenant_ids:
                form.base_fields["service"].queryset = (
                    Service.objects.bypass_tenant().filter(
                        tenant_id__in=tenant_ids, is_active=True,
                    )
                )
        return form

    def save_model(self, request, obj, form, change):
        if not request.user.is_superadmin and obj.tenant_id is None:
            tenant_ids = _managed_tenant_ids(
                request.user,
                roles=("owner", "manager", "professional"),
            )
            obj.tenant_id = tenant_ids[0] if tenant_ids else None
        super().save_model(request, obj, form, change)

    @admin.action(description="Confirmar agendamentos selecionados")
    def confirmar_agendamentos(self, request, queryset):
        from django.contrib import messages
        count = 0
        for apt in queryset.filter(status=Appointment.Status.PENDING):
            apt.status = Appointment.Status.CONFIRMED
            apt.save(update_fields=["status", "updated_at"])
            count += 1
        if count:
            messages.success(request, f"{count} agendamento(s) confirmado(s).")
        else:
            messages.warning(request, "Nenhum agendamento pendente selecionado.")

    @admin.action(description="Cancelar agendamentos selecionados")
    def cancelar_agendamentos(self, request, queryset):
        from django.contrib import messages
        count = 0
        for apt in queryset.filter(
            status__in=[Appointment.Status.PENDING, Appointment.Status.CONFIRMED]
        ):
            apt.status = Appointment.Status.CANCELLED
            apt.save(update_fields=["status", "updated_at"])
            count += 1
        if count:
            messages.success(request, f"{count} agendamento(s) cancelado(s).")
        else:
            messages.warning(request, "Nenhum agendamento ativo selecionado.")


# --- Sprint 7: Produtos ---

@admin.register(Product)
class ProductAdmin(TenantContextMixin, admin.ModelAdmin):
    list_display = ("name", "price", "category", "is_active")
    list_filter = ("is_active", "category")
    search_fields = ("name",)


# --- Sprint 7: Sessoes ---

class SessionProductInline(admin.TabularInline):
    model = SessionProduct
    extra = 0
    readonly_fields = ("unit_price",)


@admin.register(Session)
class SessionAdmin(TenantContextMixin, admin.ModelAdmin):
    list_display = ("client_name", "professional", "status", "total_amount", "started_at")
    list_filter = ("status",)
    search_fields = ("client_name", "client_phone")
    inlines = [SessionProductInline]
    readonly_fields = ("total_amount",)


@admin.register(SessionProduct)
class SessionProductAdmin(TenantContextMixin, admin.ModelAdmin):
    list_display = ("session", "product", "quantity", "unit_price", "total_price")
    search_fields = ("session__client_name", "product__name")
