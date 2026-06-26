PRD — FocusBarber (Versão Completa Atualizada com Validação Dupla: CLI + Manual)

1. Visão Geral do Produto

O FocusBarber é um SaaS multi-tenant para gestão completa de barbearias, permitindo múltiplos estabelecimentos operarem de forma isolada dentro de uma única plataforma escalável.

A plataforma cobre:

Agendamentos online públicos
Gestão operacional de barbearias
Controle financeiro completo
Sessões de atendimento
Produtos e serviços
Assinaturas e fidelização
Notificações automatizadas
Dashboards operacionais e financeiros
Arquitetura tecnológica
Backend: Python 3.13 + Django
Banco de dados: PostgreSQL
Cache: Redis
Fila assíncrona: Celery
Broker: RabbitMQ
Infraestrutura: Docker + Docker Compose (dev), Docker Swarm (produção)
Proxy: Traefik
Deploy: GHCR + VPS + Cloudflare DNS

2. Objetivos do Produto

Criar um SaaS multi-barbearia escalável
Garantir isolamento total entre tenants
Automatizar agendamentos e atendimentos
Centralizar finanças e operação
Permitir expansão futura com IA e automações
Garantir arquitetura profissional de produção

3. Problemas que o Produto Resolve

Agendamento manual desorganizado
Falta de controle financeiro integrado
Baixa fidelização de clientes
Ausência de automação
Dificuldade de escalar barbearias digitalmente

4. Público-Alvo

Donos de barbearia
Gerentes
Barbeiros
Clientes finais
Administradores SaaS

5. Personas

Dono da barbearia (gestão completa)
Barbeiro (execução de atendimentos)
Cliente (agendamento rápido)
Admin SaaS (controle global)

6. Escopo do Produto

Inclui:

Multi-tenant
Agendamento
Sessões de atendimento
Pagamentos manuais
Financeiro básico
Dashboards
Página pública

7. Fora do Escopo Inicial

IA avançada
WhatsApp API oficial
Pagamento automático
App mobile
Marketplace

8. Perfis de Usuário e Permissões

Superadmin SaaS
Dono da barbearia
Gerente
Profissional
Cliente
Regra central:

Toda operação depende de tenant_id + role.

9. Módulos do Sistema

Auth
Multi-tenant core
Barbearia
Serviços
Profissionais
Produtos
Agendamento
Sessões
Pagamentos
Financeiro
Notificações
Dashboards
Página pública
Reviews

10. Fluxos Principais

Agendamento

Cliente → Página pública → Profissional → Serviço → Horário → Confirmação

Atendimento

Agendamento → Sessão → Produtos/serviços → Fechamento → Pagamento → Receita

11. Regras de Negócio

Nenhum conflito de horário por profissional
Receita só após pagamento confirmado
Produtos só em atendimento ativo
CPF único por cliente por tenant
Multi-tenant obrigatório em todas queries

12. Requisitos Funcionais

CRUD completo
Agendamento com validação de conflito
Sessões com consumo de serviços/produtos
Pagamento manual
Dashboards
Página pública

13. Requisitos Não Funcionais (ATUALIZADO)

13.1 Responsividade e UX

O sistema deve ser totalmente responsivo (mobile-first)
Deve funcionar perfeitamente em:
smartphones
tablets
desktops
A interface deve respeitar rigorosamente o design system do projeto definido em:
/focusbarber/docs/design_system.md
UX deve priorizar:
fluidez de agendamento
baixa fricção no fluxo de clientes
consistência visual entre telas
Deve haver alto contraste entre:
textos
botões
fundos
Componentes devem ser reutilizáveis e consistentes

13.2 Segurança e Isolamento Multi-Tenant

O sistema deve ser seguro por design (security by design)
Nenhum dado pode vazar entre tenants (barbearias)
Toda query deve obrigatoriamente respeitar tenant_id
Middleware de tenant deve ser obrigatório em todas requisições autenticadas
Dados sensíveis devem ser protegidos:
CPF
telefone
histórico de pagamentos
Rotas administrativas devem ser protegidas por role-based access control (RBAC)

13.3 Segurança de Arquivos e Mídia

Arquivos (uploads, imagens, documentos) devem:
ser vinculados ao tenant
ter controle de permissão por usuário
nunca serem acessíveis diretamente sem validação
URLs públicas de mídia não podem expor dados sensíveis
Media deve ser servida via camada controlada (ex: view protegida ou proxy)
Validação obrigatória de:
tipo de arquivo
tamanho máximo (4MB)
escopo de acesso

13.4 Infraestrutura Docker Swarm (Produção)

O sistema em produção deve operar com Docker Swarm altamente resiliente:

13.4.1 Restart Policy obrigatória

Todos os serviços devem ter:

condition: on-failure
delay
max_attempts
window

Objetivo:

evitar crash-loop
garantir auto-recuperação

13.4.2 Limites de Recursos

Todos os serviços devem definir:

CPU limits
CPU reservations
Memory limits
Memory reservations

Objetivo:

evitar starvation da VPS
garantir estabilidade do cluster

13.4.3 Deploy sem downtime (zero downtime)

O serviço web (Django app) deve usar:

update_config
order: start-first
failure_action: rollback

Regras:

nova réplica sobe antes da antiga ser removida
se healthcheck falhar → rollback automático
não pode haver downtime perceptível

13.4.4 Ordem de inicialização segura

O sistema deve ser auto-recuperável e ordenado:

banco de dados pode não estar pronto no boot
broker pode não estar pronto no boot

Para isso:

healthchecks obrigatórios
wait_for_db no entrypoint do Django
retry automático dos serviços dependentes

13.4.5 Healthchecks obrigatórios

Todos os serviços devem possuir healthcheck:

Django → /health/
PostgreSQL → pg_isready
Redis → redis-cli ping
RabbitMQ → rabbitmq-diagnostics check_port_connectivity

13.4.6 Bootstrap seguro de serviços

Nenhum serviço pode entrar em crash-loop por dependência:

dependências devem ser verificadas antes do start completo
retry progressivo obrigatório
delay entre tentativas obrigatório

13.5 Static Files e Deploy seguro

Durante deploy:

collectstatic deve sempre usar:
--clear
Motivo técnico:
evita arquivos antigos com hash quebrado
previne FileNotFoundError
garante reconstrução limpa do STATIC_ROOT

13.6 Segurança de Segredos

Segredos NÃO podem ser expostos:

Proibido:
senha em docker-compose
token Cloudflare em texto puro versionado
credenciais no repositório
Obrigatório:
Docker Secrets (produção)
.env gitignored (desenvolvimento e VPS)

Segredos incluem:

Cloudflare API Token
senhas de banco
credenciais de broker (RabbitMQ)
chaves de serviços externos

13.7 Performance e Escalabilidade
sistema deve suportar crescimento horizontal (Swarm)
agendamentos devem ter baixa latência
queries de calendário devem ser otimizadas
uso de cache (Redis) quando aplicável
dashboards devem usar agregações eficientes

13.8 Logs e Auditoria
todas ações críticas devem ser logadas:
pagamentos
cancelamentos
alterações de sessão
acessos administrativos
logs devem ser rastreáveis por tenant
auditoria deve permitir reconstrução de eventos

14. Modelo de Dados

Entidades principais:

Tenant (Barbearia)
User
Professional
Client
Service
Product
Appointment
Session
Payment
Revenue
Expense

Todos com:

created_at
updated_at
tenant_id obrigatório
15. Arquitetura Técnica
Django modular (apps por domínio)
PostgreSQL centralizado
Redis cache
Celery async tasks
RabbitMQ broker
Traefik reverse proxy
Docker Swarm produção

16. Estratégia Multi-Tenant

Modelo:

Shared database + tenant_id obrigatório

Implementação:

Middleware de resolução de tenant
QuerySet global filtrado
Proteção contra cross-tenant access
Auditoria de acesso

17. Segurança, LGPD e Auditoria

CPF como dado sensível
Logs de ações críticas
Isolamento total por tenant
Upload validation (<4MB)
HTTPS obrigatório via Traefik
Auditoria de pagamentos e sessões

18. Integrações Externas

Email Django SMTP
WhatsApp (futuro API)
SMS (futuro gateway)
Cloudflare DNS
GHCR registry

19. Pagamentos

MVP
Pagamento manual
Futuro
Pix automático
Cartão
Webhooks

20. Notificações

MVP
Email Django
Link WhatsApp manual
Futuro
WhatsApp Business API
SMS automatizado
Celery triggers

21. Dashboards

Receita por período
Ticket médio
Profissionais mais ativos
Cancelamentos
Produtos mais vendidos

22. Fidelidade e Assinaturas

MVP
Cupons simples
Futuro
Cashback
Pontos
Assinaturas recorrentes

23. Critérios de Aceite (GERAL)

Nenhum conflito de agendamento permitido
Dados isolados por tenant
Receita só após pagamento confirmado
Sessões devem registrar histórico completo
Página pública < 2s carregamento

24. MVP

Inclui:

Cadastro barbearia
Serviços
Profissionais
Produtos
Agendamento
Sessão
Pagamento manual
Dashboard básico
Página pública

25. ROADMAP

Pix automático
Cartão
WhatsApp API
IA recomendações
App mobile
Marketplace SaaS

26. BACKLOG + SPRINTS COM VALIDAÇÃO DUPLA (CLI + MANUAL)

CONVENÇÃO GLOBAL

Cada item possui:

( ) pendente
(⚙️ DEV) em execução
(✓ CLI) validado automaticamente
(✓ USER) validado por você manualmente

🧪 SPRINT 1 — Base do Projeto
Implementação
Setup Django + PostgreSQL ( )
Apps core/base ( )
Docker Compose dev ( )
Settings + .env ( )
Auth base Django ( )
Validação CLI
Django sobe corretamente ( )
DB conecta ( )
Admin acessível ( )
Validação MANUAL (VOCÊ)
Consigo logar no admin
Consigo criar usuário
Containers sobem sem erro

🧪 SPRINT 2 — Multi-Tenant Core
Implementação
Tenant model ( )
Middleware tenant ( )
QuerySet filtrado ( )
Proteção cross-tenant ( )
CLI
Isolamento validado ( )
MANUAL
Criar 2 barbearias
Confirmar isolamento total de dados

🧪 SPRINT 3 — Usuários e Permissões
CLI
login email funcionando ( )
MANUAL
testar login por roles
validar permissões diferentes

🧪 SPRINT 4 — Barbearia + Página Pública
CLI
upload imagens OK ( )
MANUAL
acessar página pública
validar layout e dados corretos

🧪 SPRINT 5 — Serviços + Profissionais
MANUAL (CRÍTICO)
criar serviço
vincular profissional
validar regras de disponibilidade

🧪 SPRINT 6 — AGENDAMENTO (CORE)
CLI
bloqueio de conflito ( )
MANUAL (CRÍTICO)
tentar dois agendamentos no mesmo horário
validar bloqueio
fluxo completo cliente → agendamento

🧪 SPRINT 7 — SESSÕES
MANUAL
iniciar atendimento
adicionar produtos
fechar conta
validar cálculo final

🧪 SPRINT 8 — PAGAMENTOS
MANUAL
pagamento manual
confirmação receita
validar regra: sem pagamento = sem receita

🧪 SPRINT 9 — DASHBOARD
MANUAL
criar dados reais
validar métricas coerentes

🧪 SPRINT 10 — NOTIFICAÇÕES + CELERY
CLI
worker ativo ( )
tasks executam ( )
MANUAL
disparo de email
evento de agendamento

🧪 SPRINT 11 — DEPLOY PRODUÇÃO
CLI
Swarm ativo ( )
Traefik funcionando ( )
MANUAL (CRÍTICO)
acessar domínio
HTTPS válido
healthcheck externo OK

🧪 SPRINT 12 — HARDENING FINAL
MANUAL
validar segurança multi-tenant
testar logs
testar backup

27. RISCOS
Complexidade de agendamento
Falha de isolamento tenant
Overengineering inicial
Infra Docker Swarm complexa

28. DECISÕES PENDENTES
Evoluir Swarm → Kubernetes futuro
IA após MVP
WhatsApp API fase 2

29. GLOSSÁRIO
Tenant = barbearia isolada
Session = atendimento
Slot = intervalo de tempo
Worker = Celery process

30. CONCLUSÃO

O FocusBarber é um SaaS completo com arquitetura moderna e escalável.

A introdução de validação dupla (CLI + manual) garante:

qualidade técnica automatizada
validação funcional humana
redução de bugs em produção
rastreabilidade por sprint

O sistema evolui de MVP simples para plataforma SaaS enterprise-ready com segurança, escalabilidade e extensibilidade.