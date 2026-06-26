from django.contrib import admin

from .models import Service, Tenant


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    ordering = ("name",)


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "duration_minutes")
    list_filter = ("tenant",)
    search_fields = ("name",)
    ordering = ("tenant", "name")

    # ---------- Isolamento multi-tenant ----------
    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        # Não-superadmin só pode criar/editar serviços do próprio tenant:
        # limita o dropdown `tenant` à própria barbearia e força o default.
        if not request.user.is_superadmin:
            tenant = getattr(request, "tenant", None)
            if tenant is not None and "tenant" in form.base_fields:
                field = form.base_fields["tenant"]
                field.queryset = field.queryset.filter(pk=tenant.pk)
                if obj is None:
                    field.initial = tenant
        return form

    def save_model(self, request, obj, form, change):
        # Garante que não-superadmin não crie serviço em tenant alheio.
        if not request.user.is_superadmin and obj.tenant_id is None:
            obj.tenant = getattr(request, "tenant", None)
        super().save_model(request, obj, form, change)

    def get_changeform_initial_data(self, request):
        # Pré-preenche o tenant ao abrir o form de adição.
        initial = super().get_changeform_initial_data(request)
        if not request.user.is_superadmin:
            tenant = getattr(request, "tenant", None)
            if tenant is not None:
                initial["tenant"] = tenant
        return initial