"""
SEED FICTÍCIO — FocusBarber (Sprint 3 — Usuários e Permissões)
================================================================

Popula o banco com dados fictícios para validação MANUAL do que foi
implementado até a Sprint 3 (login por e-mail + permissões por role /
RBAC), Sprint 4 (Barbearia + Página Pública) e Sprint 5 (Serviços +
Profissionais), exercitando também o isolamento multi-tenant da Sprint 2.

Conteúdo criado:
  - 3 barbearias (tenants): Navalha de Ouro, Corte & Cia, Barba & Estilo
  - Dados públicos de cada barbearia (Sprint 4): slogan, descrição, contato,
    endereço — exibidos na Página Pública em /<slug>/
  - Horário de funcionamento estruturado (BusinessHours) de cada barbearia:
    uma linha por dia da semana com flag `is_open` + horário + intervalo.
  - Serviços vinculados a cada barbearia (model core.Service, multi-tenant),
    incluindo alguns marcados como inativos (is_active=False) p/ teste visual
  - Profissionais vinculados a usuários role=professional (Sprint 5):
    cada barbearia recebe 2 profissionais (Professional), cada um vinculado
    a parte dos serviços (ProfessionalService) e com disponibilidade semanal
    (ProfessionalAvailability) que respeita o horário da barbearia.
  - Usuários com TODOS os perfis do PRD §8:
        * superadmin SaaS  (tenant=null, acesso global)
        * owner            (1 por barbearia)
        * manager          (1 por barbearia)
        * professional     (2 por barbearia)  — vinculado a Professional
        * client           (2 por barbearia)

Todos os usuários usam a MESMA senha de teste:
        Senh4Forte!x

Como executar (a partir da raiz do projeto):
        python manage.py shell < docs/seed_ficticio.py

Idempotente: pode ser re-executado sem duplicar dados (usa get_or_create
por slug/e-mail). Ao re-executar:
  - Senhas NÃO são redefinidas (mantêm a da 1ª execução).
  - A flag `is_active` dos serviços É re-aplicada ao estado configurado no
    seed (para garantir o cenário de teste visual de inativos).
Para resetar por completo, use:
        python manage.py flush --no-input && python manage.py migrate

Regras de código exercitadas por este seed (validação indireta):
  - core.models.TenantOwnedManager  (filtro por tenant / bypass p/ superadmin)
  - core.models.TenantOwnedModel.save (bloqueio cross-tenant)
  - core.middleware.TenantMiddleware  (resolução via set_current_tenant)
  - base.permissions.sync_role_permissions + signal post_save (RBAC por role)
  - base.backends.EmailBackend (login por e-mail, case-insensitive)
"""
import os
import sys

# ---------- Bootstrap Django (roda como script standalone) ----------
# Coloca a raiz do projeto no sys.path (o script mora em docs/).
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
import django  # noqa: E402

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.db import transaction  # noqa: E402

from base.models import User  # noqa: E402
from core.models import (  # noqa: E402
    BusinessHours,
    Professional,
    ProfessionalAvailability,
    ProfessionalService,
    Service,
    Tenant,
    TenantMembership,
    set_current_tenant,
)

# ---------- Senha única p/ facilitar testes manuais de login ----------
SEED_PASSWORD = "Senh4Forte!x"

# ---------- Catálogo de dados fictícios ----------
BARBERSHOPS = [
    {
        "slug": "navalha-de-ouro",
        "name": "Navalha de Ouro",
        "tagline": "Tradição & Estilo",
        "description": "Barbearia clássica no coração da cidade. Cortes de precisão e barba navalhada por mestres com anos de ofício.",
        "phone": "(11) 4000-1001",
        "address": "Rua das Facas, 101 — Centro, São Paulo/SP",
        "whatsapp": "+5511940001001",
        "instagram": "navalhadeouro",
        # Horário de funcionamento (one por dia da semana): weekday -> dict.
        # 0=Dom,1=Seg,2=Ter,3=Qua,4=Qui,5=Sex,6=Sáb.
        "business_hours": {
            0: {"is_open": False},  # domingo fechado
            1: {"is_open": True,  "open": "09:00", "close": "20:00", "break": ("12:00", "14:00")},
            2: {"is_open": True,  "open": "09:00", "close": "20:00", "break": ("12:00", "14:00")},
            3: {"is_open": True,  "open": "09:00", "close": "20:00", "break": ("12:00", "14:00")},
            4: {"is_open": True,  "open": "09:00", "close": "20:00", "break": ("12:00", "14:00")},
            5: {"is_open": True,  "open": "09:00", "close": "20:00", "break": ("12:00", "14:00")},
            6: {"is_open": True,  "open": "09:00", "close": "18:00"},  # sábado sem intervalo
        },
        "services": [
            ("Corte Masculino", 30, True),
            ("Barba", 20, True),
            ("Corte + Barba", 45, True),
            ("Navalhado", 40, False),   # inativo para teste visual
            ("Platinado", 90, True),
        ],
        "professionals": [
            # (user-email-local, [nomes de serviço a vincular], disponibilidade)
            # disponibilidade: dict weekday -> (available(bool), open, close, break|None)
            ("barbeiro1", ["Corte Masculino", "Barba", "Corte + Barba"], {
                1: (True, "09:00", "20:00", ("12:00", "14:00")),
                3: (True, "09:00", "12:00", None),   # só manhã
                5: (True, "14:00", "20:00", None),    # só tarde
            }),
            ("barbeiro2", ["Corte Masculino", "Platinado"], {
                2: (True, "10:00", "19:00", ("12:00", "14:00")),
                4: (True, "09:00", "18:00", ("12:00", "14:00")),
                6: (True, "09:00", "18:00", None),
            }),
        ],
        "domain": "navalha.test",
    },
    {
        "slug": "corte-e-cia",
        "name": "Corte & Cia",
        "tagline": "Estilo que combina com você",
        "description": "Barbearia moderna para o homem que valoriza atendimento de qualidade e um ambiente descontraído.",
        "phone": "(11) 4000-2002",
        "address": "Av. dos Estilos, 202 — Vila Nova, São Paulo/SP",
        "whatsapp": "+5511940002002",
        "instagram": "corteecia",
        "business_hours": {
            0: {"is_open": False},
            1: {"is_open": True,  "open": "10:00", "close": "21:00", "break": ("13:00", "14:00")},
            2: {"is_open": True,  "open": "10:00", "close": "21:00", "break": ("13:00", "14:00")},
            3: {"is_open": True,  "open": "10:00", "close": "21:00", "break": ("13:00", "14:00")},
            4: {"is_open": True,  "open": "10:00", "close": "21:00", "break": ("13:00", "14:00")},
            5: {"is_open": True,  "open": "10:00", "close": "21:00", "break": ("13:00", "14:00")},
            6: {"is_open": True,  "open": "10:00", "close": "17:00"},  # sábado sem intervalo
        },
        "services": [
            ("Corte Social", 30, True),
            ("Degradê", 40, True),
            ("Sobrancelha", 15, True),
            ("Hidratação Capilar", 30, True),
        ],
        "professionals": [
            ("barbeiro1", ["Corte Social", "Degradê", "Sobrancelha"], {
                1: (True, "10:00", "21:00", ("13:00", "14:00")),
                3: (True, "10:00", "21:00", ("13:00", "14:00")),
                5: (True, "10:00", "16:00", ("13:00", "14:00")),
            }),
            ("barbeiro2", ["Corte Social", "Hidratação Capilar"], {
                2: (True, "12:00", "21:00", ("13:00", "14:00")),
                4: (True, "12:00", "21:00", ("13:00", "14:00")),
                6: (True, "10:00", "17:00", None),
            }),
        ],
        "domain": "corte.test",
    },
    {
        "slug": "barba-e-estilo",
        "name": "Barba & Estilo",
        "tagline": "Premium Grooming",
        "description": "Cuidado masculino completo: cortes, barba modelada e pigmentação com produtos premium.",
        "phone": "(11) 4000-3003",
        "address": "Praça do Estilo, 303 — Bairro Alto, São Paulo/SP",
        "whatsapp": "+5511940003003",
        "instagram": "barbaeestilo",
        "business_hours": {
            0: {"is_open": False},
            1: {"is_open": True,  "open": "09:00", "close": "20:00", "break": ("12:00", "13:00")},
            2: {"is_open": True,  "open": "09:00", "close": "20:00", "break": ("12:00", "13:00")},
            3: {"is_open": True,  "open": "09:00", "close": "20:00", "break": ("12:00", "13:00")},
            4: {"is_open": True,  "open": "09:00", "close": "20:00", "break": ("12:00", "13:00")},
            5: {"is_open": True,  "open": "09:00", "close": "20:00", "break": ("12:00", "13:00")},
            6: {"is_open": True,  "open": "09:00", "close": "19:00"},  # sábado sem intervalo
        },
        "services": [
            ("Corte Popular", 25, True),
            ("Barba Modelada", 25, True),
            ("Pigmentação", 60, True),
            ("Corte Kids", 20, False),  # inativo para teste visual
        ],
        "professionals": [
            ("barbeiro1", ["Corte Popular", "Barba Modelada", "Corte Kids"], {
                1: (True, "09:00", "20:00", ("12:00", "13:00")),
                3: (True, "09:00", "20:00", ("12:00", "13:00")),
                5: (True, "13:00", "20:00", None),   # só tarde (após break da loja)
            }),
            ("barbeiro2", ["Corte Popular", "Pigmentação"], {
                2: (True, "09:00", "20:00", ("12:00", "13:00")),
                4: (True, "09:00", "20:00", ("12:00", "13:00")),
                6: (True, "09:00", "19:00", None),
            }),
            # O DONO da barbearia também atende como profissional
            # (existe quando o dono presta serviço no próprio estabelecimento).
            ("dono", ["Corte Popular", "Barba Modelada"], {
                1: (True, "09:00", "20:00", ("12:00", "13:00")),
                5: (True, "14:00", "20:00", None),   # só tarde
            }),
        ],
        "domain": "barba.test",
    },
]

def _email(local, domain):
    return f"{local}@{domain}"


def _get_or_create_superuser(email, password, **defaults):
    """Cria superuser só se inexistente (aplica set_password via create_superuser)."""
    existing = User.objects.filter(email=email).first()
    if existing is not None:
        return existing, False
    return User.objects.create_superuser(email=email, password=password, **defaults), True


def _get_or_create_user(email, password, **defaults):
    """Cria usuário só se inexistente (aplica set_password via create_user).

    Reexecutar o seed NÃO redefine a senha — mantém a da 1ª execução.
    """
    existing = User.objects.filter(email=email).first()
    if existing is not None:
        return existing, False
    return User.objects.create_user(email=email, password=password, **defaults), True


@transaction.atomic
def seed_superadmin():
    """Superadmin SaaS — tenant=null (escopo global, usa is_superuser)."""
    user, created = _get_or_create_superuser(
        "admin@focusbarber.test",
        SEED_PASSWORD,
        role=User.Role.SUPERADMIN,
        is_active=True,
    )
    return user, created


@transaction.atomic
def _time(hhmm):
    h, m = (int(x) for x in hhmm.split(":"))
    from datetime import time as _t
    return _t(h, m)


def seed_barbershop(cfg):
    """Cria 1 barbearia + horários + serviços + profissionais + usuários."""
    public_fields = ("tagline", "description", "phone", "address",
                     "whatsapp", "instagram")
    defaults = {"name": cfg["name"], "is_active": True}
    defaults.update({f: cfg.get(f, "") for f in public_fields})

    tenant, t_created = Tenant.objects.get_or_create(
        slug=cfg["slug"], defaults=defaults,
    )
    if not t_created:
        changed = False
        for f in ("name", *public_fields):
            if getattr(tenant, f) != cfg.get(f, ""):
                setattr(tenant, f, cfg.get(f, ""))
                changed = True
        if changed:
            tenant.save(update_fields=["name", *public_fields])

    # ---- Horário de funcionamento (BusinessHours) ----
    # O signal post_save do Tenant já criou as 7 linhas em dias fechados;
    # aplicamos a config do seed (idempotente — converge p/ o estado).
    bh_open = 0
    for wd, spec in cfg["business_hours"].items():
        bh, _ = BusinessHours.objects.bypass_tenant().get_or_create(
            tenant=tenant, weekday=wd,
        )
        bh.is_open = spec.get("is_open", False)
        if bh.is_open:
            bh.open_time = _time(spec["open"])
            bh.close_time = _time(spec["close"])
            brk = spec.get("break")
            if brk:
                bh.break_start = _time(brk[0])
                bh.break_end = _time(brk[1])
            else:
                bh.break_start = bh.break_end = None
            bh_open += 1
        else:
            bh.break_start = bh.break_end = None
        # full_clean valida intervalo dentro do expediente; usa save() direto
        # para não acionar o filtro de tenant do manager.
        bh.save()
    bh.save()

    # ---- Serviços ----
    set_current_tenant(tenant, bypass=False)
    try:
        svc_created = svc_inactive = 0
        for name, duration, is_active in cfg["services"]:
            svc, created = Service.objects.get_or_create(
                tenant=tenant, name=name,
                defaults={"duration_minutes": duration, "is_active": is_active},
            )
            svc_created += int(created)
            if svc.is_active != is_active:
                svc.is_active = is_active
                svc.save(update_fields=["is_active"])
            if not is_active:
                svc_inactive += 1
    finally:
        set_current_tenant(None, bypass=False)

    # ---- Usuários deste tenant (todos os perfis do PRD §8) ----
    profiles = [
        (User.Role.OWNER,        "dono",      "Carlos",   "Dono",    True),
        (User.Role.MANAGER,      "gerente",   "Marcos",   "Gerente", True),
        (User.Role.PROFESSIONAL, "barbeiro1", "João",     "Navalha", False),
        (User.Role.PROFESSIONAL, "barbeiro2", "Pedro",    "Corte",   False),
        (User.Role.CLIENT,       "cliente1",  "Ricardo",  "Silva",   False),
        (User.Role.CLIENT,       "cliente2",  "Fernanda", "Souza",   False),
    ]
    users = []
    u_created = 0
    for role, local, first, last, is_staff in profiles:
        email = _email(local, cfg["domain"])
        user, created = _get_or_create_user(
            email, SEED_PASSWORD,
            role=role, tenant=tenant, is_staff=is_staff, is_active=True,
            first_name=first, last_name=last, phone="(11) 90000-0000",
        )
        users.append((role, user, created))
        u_created += int(created)

    # ---- TenantMembership (vínculo explícito usuário × barbearia) ----
    # Sprint 5+ — donos/gerentes/profissionais precisam de membership ativa
    # para que o admin mostre suas barbearias e para que Professional.clean()
    # valide o vínculo. Clientes não precisam de membership no MVP.
    membership_role_map = {
        User.Role.OWNER: TenantMembership.Role.OWNER,
        User.Role.MANAGER: TenantMembership.Role.MANAGER,
        User.Role.PROFESSIONAL: TenantMembership.Role.PROFESSIONAL,
    }
    memb_created = 0
    for role, user, _ in users:
        m_role = membership_role_map.get(role)
        if m_role is None:
            continue
        _, created = TenantMembership.objects.bypass_tenant().get_or_create(
            tenant=tenant, user=user, role=m_role,
            defaults={"is_active": True},
        )
        memb_created += int(created)

    # ---- Profissionais + vínculos + disponibilidade ----
    pro_created = vinc_created = pa_created = 0
    set_current_tenant(tenant, bypass=False)
    try:
        svc_by_name = {s.name: s for s in
                       Service.objects.bypass_tenant().filter(tenant=tenant)}
        prof_users = {
            local: User.objects.get(email=_email(local, cfg["domain"]))
            for local in ("barbeiro1", "barbeiro2", "dono")
        }
        for idx, (local, svc_names, disp) in enumerate(
            cfg.get("professionals", []), start=1
        ):
            prof_user = prof_users[local]
            prof, created = Professional.objects.get_or_create(
                tenant=tenant, user=prof_user,
                defaults={"bio": f"{prof_user.first_name} — especialista do tenant {tenant.slug}.",
                          "is_active": True},
            )
            pro_created += int(created)

            # Vínculos profissional × serviço.
            for sname in svc_names:
                svc = svc_by_name.get(sname)
                if svc is None:
                    continue
                _, c = ProfessionalService.objects.get_or_create(
                    tenant=tenant, professional=prof, service=svc,
                )
                vinc_created += int(c)

            # Disponibilidade semanal (ProfessionalAvailability).
            # O signal post_save do Professional já criou as 7 linhas (todas
            # indisponíveis). Para cada weekday configurado, aplica (available,
            # start, end, break) e valida via full_clean (conformidade com o
            # horário da barbearia). Demais weekdays ficam unavailable.
            for wd, (available, start, end, brk) in disp.items():
                pa, _ = ProfessionalAvailability.objects.bypass_tenant().get_or_create(
                    tenant=tenant, professional=prof, weekday=wd,
                )
                pa.available = available
                if available:
                    pa.start_time = _time(start)
                    pa.end_time = _time(end)
                    if brk:
                        pa.break_start = _time(brk[0])
                        pa.break_end = _time(brk[1])
                    else:
                        pa.break_start = pa.break_end = None
                    pa.full_clean()  # valida conformidade com BusinessHours
                    pa.save()
                    pa_created += 1
                else:
                    pa.save()
    finally:
        set_current_tenant(None, bypass=False)

    # Resumo deste tenant
    print("─" * 60)
    print(f"Barbearia : {tenant.name}  (slug={tenant.slug})"
          f"  [{'CRIADA' if t_created else 'existente'}]")
    print(f"Página    : http://localhost:8000/{tenant.slug}/")
    print(f"Expediente: {bh_open} dias abertos (de 7)")
    print(f"Serviços  : {len(cfg['services'])}  ({svc_created} novos, "
          f"{svc_inactive} inativos)")
    print(f"Profissio : {len(cfg.get('professionals', []))}  "
          f"({pro_created} novos, {vinc_created} vínculos, "
          f"{pa_created} dias disponíveis)")
    print("Usuários  :")
    for role, user, created in users:
        tag = "novo" if created else "existente"
        print(f"   - {role:12s} {user.email:32s} [{tag}]")
    print("─" * 60)
    return tenant


def _print_login_table():
    """Imprime tabela resumo para validação MANUAL do login por role."""
    print("\n" + "=" * 70)
    print("CREDENCIAIS PARA TESTE MANUAL — Sprint 3 (login por e-mail + RBAC)")
    print("=" * 70)
    print(f"Senha universal de teste: {SEED_PASSWORD}")
    print("-" * 70)
    print(f"{'Perfil':12s} {'E-mail':34s} {'Acesso esperado'}")
    print("-" * 70)
    rows = [
        ("superadmin", "admin@focusbarber.test", "admin global (vê todos tenants)"),
        ("owner",      "dono@navalha.test",      "admin da própria barbearia"),
        ("manager",    "gerente@navalha.test",   "admin da própria barbearia"),
        ("professional","barbeiro1@navalha.test", "somente /login/ (sem admin)"),
        ("professional","barbeiro2@navalha.test", "somente /login/ (sem admin)"),
        ("client",     "cliente1@navalha.test",   "/login/ -> /perfil/"),
        ("client",     "cliente2@navalha.test",   "/login/ -> /perfil/"),
        ("owner",      "dono@corte.test",          "admin da própria barbearia"),
        ("manager",    "gerente@corte.test",       "admin da própria barbearia"),
        ("owner",      "dono@barba.test",          "admin da própria barbearia"),
        ("manager",    "gerente@barba.test",       "admin da própria barbearia"),
    ]
    for role, email, desc in rows:
        print(f"{role:12s} {email:34s} {desc}")
    print("=" * 70)
    print(
        "Roteiro de validação MANUAL (PRD §26 — Sprint 3 + 4 + 5):\n"
        "  1. login por e-mail funcionando  -> acesse /login/ com cada e-mail.\n"
        "  2. permissões diferentes por role -> entre no /admin/:\n"
        "       • superadmin enxerga TODAS as barbearias e TODOS os usuários.\n"
        "       • owner/manager enxergam APENAS usuários/serviços do seu tenant.\n"
        "       • barbeiro/cliente não conseguem entrar no /admin/ (is_staff=False).\n"
        "  3. isolamento multi-tenant -> owner da Navalha não vê serviços/usuários\n"
        "     da barbearia Corte & Cia nem Barba & Estilo.\n"
        "  4. flag is_active dos serviços -> entre no /admin/core/service/:\n"
        "       • owner/manager podem ativar/inativar (coluna 'Ativo' editável).\n"
        "       • owner/manager NÃO veem ação 'Excluir selecionados'.\n"
        "       • profissional não altera 'Ativo' (campo desativado no form).\n"
        "       • superadmin pode excluir; demais roles só inativam.\n"
        "  5. SPRINT 4 — Barbearia + Página Pública:\n"
        "     (a) Página pública -> acesse no navegador:\n"
        "         http://localhost:8000/navalha-de-ouro/\n"
        "         http://localhost:8000/corte-e-cia/\n"
        "         http://localhost:8000/barba-e-estilo/\n"
        "       • confira layout (nav/hero/services/footer fiel ao design system)\n"
        "       • confira dados corretos (nome, slogan, contato, horário)\n"
        "       • só serviços ATIVOS aparecem (Platinado/Corte Kids não aparecem)\n"
        "       • barbearia inativa (is_active=False) retorna 404.\n"
        "     (b) upload de imagens -> entre no /admin/core/tenant/ como owner\n"
        "         ou superadmin: faça upload de logo/capa (jpg/png/webp, <=4MB);\n"
        "         confira a prévia da imagem; tente upload .pdf/.gif (rejeitado)\n"
        "         e arquivo >4MB (rejeitado) — PRD §13.3.\n"
        "  6. SPRINT 5 — Serviços + Profissionais (CRÍTICO):\n"
        "     (a) criar serviço -> /admin/core/service/add/ (owner/manager):\n"
        "         • serviço novo pertence ao próprio tenant (tenant fixo).\n"
        "         • duração obrigatória e positiva; nome único por barbearia.\n"
        "     (b) vincular profissional -> /admin/core/professional/ como owner\n"
        "         ou manager: crie/edite um Professional. Confira:\n"
        "         • dropdown de usuário só traz role=professional do tenant.\n"
        "         • 'Serviços vinculados' (inline) só lista serviços do tenant.\n"
        "         • ao salvar, serviço e profissional devem ser do mesmo tenant;\n"
        "           vincular serviço de outra barbearia é bloqueado (cross-tenant).\n"
        "     (c) HORÁRIO DA BARBEARIA -> acesse /admin/core/tenant/<sua>/ e role\n"
        "         até 'Horários de funcionamento': há 1 linha por dia da semana\n"
        "         (já criadas pelo signal). Marque 'Aberto?' e ajuste abertura/\n"
        "         fechamento e intervalo (opcional). Ex.: Seg–Sex 09–20 pausa\n"
        "         12–14, Sáb 09–18 sem pausa, Dom fechado.\n"
        "     (d) DISPONIBILIDADE DO PROFISSIONAL -> /admin/core/professional/\n"
        "         (mesmo inline 'Disponibilidade'). Marque 'Disponível?' e ajuste\n"
        "         horário/intervalo. Tentar configurar fora do horário da loja\n"
        "         (ex.: loja fecha 18h, candidato 18–20) é REJEITADO. Dia em que\n"
        "         a loja está fechada também é rejeitado. Se a loja tem pausa,\n"
        "         o profissional precisa ter pausa que a cubra.\n"
        "     (e) página pública /<slug>/ agora exibe o horário formatado por dia.\n"
        "     (f) profissional logado (barbeiro1@navalha.test) só vê o seu\n"
        "         cadastro e sua disponibilidade (read-only); não cria/vincula.\n"
    )


def main():
    print("\n🌱  SEED FICTÍCIO — FocusBarber (Sprint 3)\n")
    try:
        sup, sup_created = seed_superadmin()
        print(f"Superadmin SaaS: {sup.email} [{'CRIADO' if sup_created else 'existente'}]")
        for cfg in BARBERSHOPS:
            seed_barbershop(cfg)
    except Exception as exc:  # noqa: BLE001
        # Em caso de falha revertemos o contexto de tenant p/ não vazar estado.
        set_current_tenant(None, bypass=False)
        print(f"\n❌ Erro ao rodar seed: {exc}", file=sys.stderr)
        raise
    else:
        set_current_tenant(None, bypass=False)
        _print_login_table()
        print("✅ Seed concluído com sucesso.\n")


# Roda tanto via `python manage.py shell < docs/seed_ficticio.py`
# quanto via `python docs/seed_ficticio.py` (ambos com __name__ == "__main__").
if __name__ == "__main__":
    main()