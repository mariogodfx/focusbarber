# Auto-Vínculo no Cadastro de Usuário + Escopo Multi-Unidade

## Objetivo

1. Ao cadastrar um usuário NOVO com perfil owner/manager/professional e tenant
   preenchido, criar automaticamente o `TenantMembership` correspondente. Se o
   perfil for professional, criar também o `Professional` — evitando retrabalho.
2. Validar no admin: role owner/manager/professional exige tenant preenchido.
3. Dono/gerente com memberships em várias barbearias enxerga todas elas no admin
   (Tenant, Service, Professional) — não apenas a do `User.tenant` legado.
4. Superuser (e qualquer usuário) editando um `Professional` só vê no dropdown de
   serviços os serviços da barbearia daquele profissional (elimina cross-tenant).

## Decisões Aprovadas

- A automação dispara APENAS no cadastro de usuário NOVO (não em mudança de role
  de usuário existente).
- Mecanismo: signal `post_save` em `User` (capta admin, shell, seed, APIs futuras).
- Escopo multi-unidade por admin via `_managed_tenant_ids()` — o middleware não
  é alterado (`request.tenant` continua sendo `user.tenant` legado).
- O dropdown de serviços no inline de `ProfessionalService` é filtrado pelo
  tenant do Professional pai para TODOS os usuários, inclusive superadmin.

## 1. Signal de Auto-Vínculo

Arquivo: `base/signals.py`

Novo signal `post_save` em `User`:
- Condição: `created=True` (apenas criação, não update).
- Se `role` in (owner, manager, professional) E `tenant_id` não é None:
  - `TenantMembership.get_or_create(tenant=user.tenant, user=user, role=<role>)`
    com `defaults={"is_active": True}`.
    - Mapeamento de role: `User.Role.OWNER` → `TenantMembership.Role.OWNER`,
      `MANAGER` → `MANAGER`, `PROFESSIONAL` → `PROFESSIONAL`.
- Se `role == professional` E `tenant_id` não é None:
  - `Professional.get_or_create(tenant=user.tenant, user=user)` com
    `defaults={"is_active": True}`.
- Imports lazy (`from core.models import ...`) dentro do signal para evitar
  import circular (base ← core).
- Idempotente via `get_or_create` — re-executar o seed não duplica.

O signal existente `sync_user_role_permissions` permanece intacto.

## 2. Validação Admin — Tenant Obrigatório

Arquivo: `base/admin.py` — `CustomUserAdmin.get_form`

- Injeta um método `clean` no form que valida: se `role` in
  (owner, manager, professional) e `tenant` está vazio →
  `raise ValidationError({"tenant": "Informe a barbearia para este perfil."})`.
- Aplica-se apenas ao form do admin (criação via shell/seed não passa por aqui,
  e o signal só age quando `tenant` está preenchido).

## 3. Escopo Multi-Unidade para Donos/Gerentes

### `TenantAdmin.get_queryset` (`core/admin.py`)
- Não-superadmin: filtra por `_managed_tenant_ids(user, roles=("owner","manager"))`
  em vez de `request.tenant.pk`. Dono com 2 memberships vê ambas as barbearias.

### `ServiceAdmin` (`core/admin.py`)
- `get_queryset`: não-superadmin filtra por
  `_managed_tenant_ids(user, roles=("owner","manager","professional"))`.
- `get_form`: campo `tenant` deixa de ser disabled/fixed em `request.tenant`;
  vira dropdown limitado às memberships do usuário (selecionável quando há
  múltiplas unidades). Single-unit: continua fixo/desabilitado (UX preservada).
- `save_model`: se `tenant_id` é None, usa o primeiro das memberships (fallback).

### `ProfessionalAdmin.get_form` (`core/admin.py`)
- Campo `tenant`: dropdown limitado às memberships do usuário (owner/manager/
  professional). Selecionável quando há múltiplas.
- Campo `user`: queryset mostra users com `tenant__in` memberships OU users com
  `TenantMembership` ativa em algum desses tenants e role professional/owner.
- `save_formset`: inlines herdam o tenant do Professional pai (já feito hoje
  para não-superadmin — passa a valer para todos).

### Inlines (`ProfessionalServiceInline`, `ProfessionalAvailabilityInline`)
- `get_queryset`: escopam pelo tenant do **Professional pai** (obj), não
  `request.tenant`. Assim, ao editar um Professional da barbearia B, só aparecem
  os registros da barbearia B.
- `get_formset`: o campo `tenant` do inline é fixado ao tenant do Professional
  pai (disabled) para TODOS os usuários.

## 4. Superuser — Dropdown de Serviços Restrito ao Tenant do Profissional

Arquivo: `core/admin.py` — `ProfessionalServiceInline.get_formset`

- Quando `obj` (Professional pai) existe: o queryset de `service` é filtrado por
  `obj.tenant` para TODOS os usuários, inclusive superadmin.
- Elimina a possibilidade de vincular serviço da barbearia A a profissional da
  barbearia B (cross-tenant).
- `_restrict_inline_tenant_field`: passa a também aplicar restrição por `obj`
  quando há um Professional pai (não pula para superadmin nesse caso).

## Testes Esperados

### Signal
- Criar user professional + tenant → Membership(role=professional) + Professional
  criados automaticamente.
- Criar user owner + tenant → Membership(role=owner) criado; Professional NÃO.
- Criar user client + tenant → nenhum criado.
- Criar user professional sem tenant → nenhum criado.
- Update de user existente → não dispara (idempotente).

### Admin form validation
- Form de criação com role=professional e tenant vazio → ValidationError em
  `tenant`.

### Multi-unit
- Owner com 2 memberships → ServiceAdmin.get_queryset mostra serviços de ambas;
  TenantAdmin.get_queryset mostra ambas; campo `tenant` no form de Service é
  selecionável entre as duas.

### Superuser service dropdown
- Superuser edita Professional da barbearia A → dropdown de serviço no inline
  só mostra serviços da barbearia A (não da barbearia B).
- Superuser edita Professional da barbearia B → só serviços da barbearia B.

## Fora do Escopo

- Disparar automação em mudança de role de usuário existente.
- Remover `User.tenant` (legado, mantido para compatibilidade).
- Alterar o middleware ( continua definindo `request.tenant = user.tenant`).
- Telas públicas/customizadas fora do admin.

## Arquivos a Modificar

- `base/signals.py` — novo signal de auto-vínculo.
- `base/admin.py` — validação de tenant obrigatório no form.
- `core/admin.py` — escopo multi-unidade (TenantAdmin, ServiceAdmin,
  ProfessionalAdmin) + restrição de serviço por tenant do Professional pai.
- `core/tests/test_sprint5.py` ou novo arquivo de testes.
