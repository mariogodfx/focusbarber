# Profissionais Multi-Barbearia e Donos Multi-Unidade

## Objetivo

Permitir que um mesmo profissional trabalhe em varias barbearias, com horarios proprios por barbearia e sem conflitos entre agendas. Permitir tambem que um mesmo dono gerencie varias barbearias/unidades com um unico login.

O MVP sera implementado no admin Django.

## Decisoes Aprovadas

- A primeira versao sera no admin Django.
- O profissional tera horario por barbearia.
- Um unico usuario dono podera acessar varias barbearias/unidades.

## Modelo De Dados

### TenantMembership

Novo modelo para representar o vinculo de um usuario com uma barbearia.

Campos principais:

- `tenant`: barbearia/unidade.
- `user`: usuario vinculado.
- `role`: `owner`, `manager` ou `professional`.
- `is_active`: controla se o vinculo esta ativo.
- timestamps padrao.

Regras:

- Um mesmo usuario pode ter vinculos com varias barbearias.
- Um dono pode ter `role=owner` em varias barbearias.
- Um profissional pode ter `role=professional` em varias barbearias.
- Deve haver unicidade por `tenant + user + role`.
- O campo atual `User.tenant` sera mantido inicialmente como tenant principal/legado para reduzir refatoracao imediata.

### ProfessionalInvitation

Novo modelo para convite de profissional existente.

Campos principais:

- `tenant`: barbearia que esta convidando.
- `professional_user`: usuario profissional convidado.
- `invited_by`: usuario dono/gerente que enviou o convite.
- `status`: `pending`, `accepted`, `rejected`, `cancelled`.
- timestamps padrao.

Regras:

- Dono/gerente envia convite para um usuario existente com role `professional`.
- Enquanto `pending`, aparece como aguardando aprovacao para o dono.
- Para o profissional, aparece como convite pendente para aceitar ou rejeitar.
- Ao aceitar, cria ou ativa `TenantMembership(role=professional)` e cria ou ativa o `Professional` daquela barbearia.
- Ao rejeitar, nao cria vinculo.
- Convites duplicados pendentes para o mesmo `tenant + professional_user` devem ser bloqueados.

### Professional

O modelo continua representando o perfil do profissional dentro de uma barbearia especifica.

Mudanca de regra:

- Deixa de exigir que `user.tenant_id == professional.tenant_id`.
- Passa a exigir que exista `TenantMembership` ativa com `role=professional` ou `role=owner` para `professional.user + professional.tenant`.

Isso preserva horarios, servicos e disponibilidade por barbearia, sem transformar `Professional` em perfil global.

## Regras De Agenda

`ProfessionalAvailability` continua sendo por barbearia/profissional.

Validacoes mantidas:

- O horario do profissional precisa estar dentro do `BusinessHours` da barbearia.
- Se a barbearia esta fechada no dia, o profissional nao pode estar disponivel.
- O intervalo do profissional nao pode permitir atendimento durante intervalo fechado da barbearia.

Nova validacao:

- Para o mesmo `user`, uma disponibilidade ativa em uma barbearia nao pode se sobrepor a outra disponibilidade ativa em outra barbearia no mesmo dia da semana.
- A comparacao deve usar os intervalos efetivos de trabalho, considerando `break_start` e `break_end`.
- Disponibilidades inativas (`available=False`) nao entram no conflito.

Exemplo valido:

- Barbearia A, segunda, 09:00-12:00.
- Barbearia B, segunda, 14:00-18:00.

Exemplo invalido:

- Barbearia A, segunda, 09:00-13:00.
- Barbearia B, segunda, 12:00-18:00.

## Admin Django

### TenantMembershipAdmin

- Superadmin ve tudo.
- Dono ve vinculos das barbearias onde tem membership `owner`.
- Profissional ve seus proprios vinculos, preferencialmente somente leitura.

### ProfessionalInvitationAdmin

- Dono/gerente cria convite para sua barbearia.
- Dono/gerente ve status dos convites enviados pela barbearia: aguardando, aceito, rejeitado ou cancelado.
- Profissional ve convites direcionados a ele.
- Profissional pode alterar somente convites pendentes dele para `accepted` ou `rejected`.
- Ao salvar `accepted`, o admin executa a criacao/ativacao do membership e do `Professional`.

### ProfessionalAdmin

- Deve permitir listar profissionais por barbearia usando membership ativa.
- Dono so gerencia profissionais das barbearias em que e owner.
- Ao criar `Professional`, o usuario selecionado deve ter membership ativa naquela barbearia, exceto quando o fluxo vem da aceitacao de convite.

## Permissoes E Tenant Atual

O `User.tenant` atual sera mantido como tenant principal para compatibilidade.

Para o admin, o escopo de barbearias do usuario devera ser calculado por `TenantMembership`:

- `owner`: barbearias onde possui membership owner ativa.
- `manager`: barbearias onde possui membership manager ativa.
- `professional`: barbearias onde possui membership professional ativa.

Como etapa inicial, o middleware atual pode continuar definindo `request.tenant` pelo `User.tenant`. As telas admin novas devem consultar memberships explicitamente quando precisarem listar multiplas unidades.

## Fora Do Escopo Inicial

- Telas publicas/customizadas fora do admin.
- Notificacao por email/WhatsApp.
- Agenda com datas especificas; o MVP valida por dia da semana.
- Migracao completa removendo `User.tenant`.

## Testes Esperados

- Dono com uma conta consegue ter membership owner em duas barbearias.
- Profissional aceita convite e passa a ter membership professional na barbearia.
- Convite rejeitado nao cria membership nem Professional.
- Convite pendente duplicado e bloqueado.
- Professional nao pode ser criado sem membership ativa na barbearia.
- Disponibilidade conflitante do mesmo usuario em duas barbearias e rejeitada.
- Disponibilidade em horarios distintos no mesmo dia e aceita.
- Disponibilidade continua respeitando horario de funcionamento da barbearia.
