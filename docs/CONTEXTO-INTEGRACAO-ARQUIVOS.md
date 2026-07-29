# Contexto Técnico — Sistema "Gestão de Projetos ServPen/UERJ" para Integração do Novo Módulo de Arquivos

> Documento preparado para o desenvolvedor Everton, responsável por construir um sistema separado e mais completo de gestão de arquivos/pastas/nomenclaturas de projetos, que vai **substituir o menu "Arquivos"** deste sistema e se **integrar** com ele (via banco PostgreSQL compartilhado e/ou vínculo por `projeto_id`). Todas as afirmações técnicas citam `arquivo:linha` do repositório para permitir verificação direta no código.

## Visão geral

O "Gestão de Projetos ServPen/UERJ" é uma aplicação interna **Streamlit + PostgreSQL**, multipáginas, usada pela equipe de engenharia da **SERVPEN** (Serviço de Engenharia da UERJ), vinculada institucionalmente à Universidade do Estado do Rio de Janeiro. A dona funcional do sistema é a engenheira **Sara Nolasco**. O rodapé fixo de toda tela logada identifica o sistema como "Software Gestão de Projetos NB | Versão 1.0 / © 2026" (`app.py:797-807`).

O sistema gerencia o ciclo de vida de projetos de engenharia (obras, laudos, projetos técnicos) através de um Kanban de status, diário de obra, tarefas, agenda de equipe, chat interno, controle de acessos e auditoria. O módulo "Arquivos" — foco central deste documento — é hoje uma "Central de Arquivos" simples, anexada a projetos, que **será substituída** pelo sistema do Everton.

**Stack tecnológica resumida** (`requirements.txt`):

| Camada | Tecnologia | Observação |
|---|---|---|
| Framework web/UI | Streamlit `==1.58.0` | Versão pinada — CPU legada sem AVX2 quebra com `pyarrow` (ver §2) |
| Banco de dados | PostgreSQL, driver `psycopg[binary]>=3.1,<4` (psycopg3) | |
| ORM/pool | `SQLAlchemy>=2.0,<3` | Só para criar `engine` de pool, consumido por `pandas.read_sql` |
| Dados/planilhas | `pandas==2.2.3`, `xlsxwriter==3.2.0`, `openpyxl==3.1.5` | |
| Gráficos | `plotly==5.24.1` | |
| PDF | `reportlab>=4.0`, `fpdf2==2.8.1` | Usados por `relatorios.py` |
| Imagens | `Pillow>=10.0` | Avatares de usuário |
| Autenticação | `passlib[bcrypt]>=1.7.4`, `bcrypt<4` (pin crítico — não remover sem testar) | |

**Onde roda:**
- **Dev local**: WSL + Docker (Postgres via `docker-compose.yml`), Streamlit rodando com `--server.address=0.0.0.0 --server.baseUrlPath=""` via `run-local.sh`.
- **Produção**: servidor apelidado **`prefei-site`**, IP **`152.92.238.40`**. O Streamlit escuta apenas em `127.0.0.1:8501` (`.streamlit/config.toml`) e é exposto ao mundo por um **proxy reverso nginx** (não Apache — ver gotcha na §2), sob o path `/gestao-de-projetos/`, com acesso **restrito à rede da UERJ (`152.92.0.0/16`)** por regra `allow/deny` no nginx.

---

## Arquitetura e infraestrutura

### Estrutura de diretórios

```
app.py                    entry point (login + sidebar + roteamento) — 808 linhas
auth.py                   validar_login() / logout()
database.py               camada de acesso ao Postgres (schema + queries) — ~90KB
relatorios.py              geração de PDF/Excel — ~46KB
core/                      módulos compartilhados (8 arquivos)
views/                     1 arquivo por página (11 arquivos)
anexos/                    armazenamento físico de arquivos (por projeto_id) + avatars/
.streamlit/config.toml     config do servidor Streamlit
docker-compose.yml         Postgres local (dev)
setup-novo-servidor/       infra de deploy DOCUMENTADA (Apache) — hoje desatualizada
```

`views/` (11 páginas): `dashboard.py`, `kanban.py` (78KB, a maior), `novo_projeto.py`, `diario.py`, `tarefas.py`, `arquivos.py` (9.6KB — a que será substituída), `equipe.py`, `chat.py`, `agenda.py`, `auditoria.py`, `acessos.py`.

`core/` (8 arquivos): `helpers.py` (permissões/UI stateless), `data.py` (queries cacheadas), `auth_ui.py` (tela de login/perfil), `sessao.py` (cookie), `chat_utils.py`, `mencoes.py`, `notif.py`, `ui_feedback.py`.

### Boot do app (`app.py`)

Sequência resumida na inicialização:

1. Logger configurado por `LOG_LEVEL` (`app.py:39-58`).
2. `st.set_page_config(page_title="GESTÃO DE PROJETOS - SERVPEN", layout="wide")` (`app.py:64-68`).
3. Inicialização de `session_state` (`autenticado=False`, `perfil="Gestor"` default pré-login, `tema="dark"`) (`app.py:74-84`).
4. `db.criar_tabelas()` — DDL roda **uma única vez por processo** via lock/flag (`app.py:100`; guard em `database.py:35-49`), porque `ALTER TABLE` pega `AccessExclusiveLock` e rodar a cada rerun causava deadlock entre conexões concorrentes.
5. Auto-login por token (cookie/URL `?t=`) via `sessao.ler_token()` + `db.validar_sessao()` (`app.py:127-151`).
6. Criação da pasta `anexos/` se não existir, relativa ao CWD do processo (`app.py:186-187`).
7. Toast de alertas da agenda do dia, só se autenticado (`app.py:193-217`).
8. CSS global injetado (`app.py:220-517`).
9. Tela de login se não autenticado, com `st.stop()` (`app.py:523-530`).
10. Reinjeção do token na URL a cada run (`app.py:534-548`) — necessário porque `st.page_link`/`st.navigation` apagam a query string ao navegar.
11. Refresh de `perfil`/`equipe` a cada run via `db.obter_usuario()` (`app.py:551-567`) — reflete promoções/mudanças sem precisar relogar.
12. Sidebar global (avatar, menu, badges de pendências, toggle de tema, logout) (`app.py:570-772`).
13. Roteamento: `pg = st.navigation(pages, position="hidden"); pg.run()` (`app.py:775-787`) — cada `st.Page` é um script independente, só a página ativa executa por interação.

### Roteamento de páginas (`app.py:585-615`)

Convenção de `url_path`: lowercase ASCII com underscore. Páginas visíveis a todos (exceto "Novo Projeto", restrita a Gestor):

| Título | `url_path` | Arquivo |
|---|---|---|
| Dashboard | *(default)* | `views/dashboard.py` |
| Kanban | `kanban` | `views/kanban.py` |
| Novo Projeto | `novo_projeto` | `views/novo_projeto.py` — só se `_pode_gestor()` |
| Diário | `diario` | `views/diario.py` |
| Tarefas | `tarefas` | `views/tarefas.py` |
| **Arquivos** | `arquivos` | `views/arquivos.py` — **página a ser substituída** |
| Equipe | `equipe` | `views/equipe.py` |
| Chat | `chat` | `views/chat.py` |
| Agenda | `agenda` | `views/agenda.py` |
| Auditoria | `auditoria` | `views/auditoria.py` — só Gestor |
| Acessos | `acessos` | `views/acessos.py` — só Gestor |

Total: 10 páginas para Gestor, 8 para os demais perfis.

### Autenticação e sessão

- `auth.validar_login(usuario, senha)` (`auth.py:10-76`): rate limiting por **nome de usuário** (5 falhas / 15 min, `database.py:431-432`), busca `SELECT nome, perfil, senha FROM usuarios`, verifica hash via `db.verificar_hash()` (aceita bcrypt e SHA-256 legado com rehash transparente).
- Sessão persistente: tabela `sessoes(token PK, usuario, expires_at)` (`database.py:830-834`), token `secrets.token_urlsafe(18)`, validade 7 dias.
- Persistência client-side via cookie `servpen_sessao` (`core/sessao.py`), gravado via JS injetado (`streamlit.components.v1.html`) porque o servidor Streamlit não expõe controle do header `Set-Cookie`.
- Logout completo (usado pela sidebar): `app.py:655-672` — invalida token no banco, limpa cookie, zera `session_state`.

### Banco de dados — como conectar

Variáveis de ambiente (prioridade `DATABASE_URL` > individuais), lidas em `database.py:75-124`:

```
DATABASE_URL=postgresql://user:pass@host:port/dbname
# ou individualmente:
DB_HOST=localhost      # default
DB_PORT=5432           # default
DB_NAME=gestao_servpen # default
DB_USER=gestao_servpen # default
DB_PASSWORD=           # default vazio
```

- `conectar()` (`database.py:63-94`): conexão crua **psycopg3** para escrita (INSERT/UPDATE/DELETE). Roda `SET TIME ZONE 'America/Sao_Paulo'` em toda conexão nova (`database.py:88`) — **`CURRENT_TIMESTAMP` no Postgres já sai em horário de Brasília, não UTC**.
- `get_engine()` (`database.py:127-171`, `@lru_cache(maxsize=1)`): engine SQLAlchemy com pool (`pool_size=5, max_overflow=5, pool_recycle=3600, pool_pre_ping=True`), usado por `pd.read_sql_query`. Mesmo ajuste de timezone via event listener.
- Todo o schema é criado por `criar_tabelas()` em `database.py` (função `_criar_tabelas_impl`, linhas 583-908) — é a **única fonte de verdade do DDL** no repositório.

### Ambiente local vs. produção

| | Dev local (WSL) | Produção |
|---|---|---|
| Postgres | Docker (`postgres:16-alpine`, `docker-compose.yml`), bind `127.0.0.1:5432` | Nativo via systemd (instalado por `install.sh`) |
| Streamlit bind | `0.0.0.0:PORT` (customizável), `baseUrlPath=""` | `127.0.0.1:8501`, `baseUrlPath="gestao-de-projetos"` |
| Proxy | Nenhum (acesso direto) | nginx (ver gotcha abaixo) |
| Scripts | `setup-local.sh`, `run-local.sh`, `py-local.sh` | `deploy-238.sh` (rsync + ssh + systemd restart) |

Config real do Streamlit (`.streamlit/config.toml:1-24`):
```toml
[server]
headless = true
address = "127.0.0.1"
port = 8501
baseUrlPath = "gestao-de-projetos"
enableCORS = true
enableXsrfProtection = true
maxUploadSize = 100
fileWatcherType = "poll"
```
`enableCORS` e `enableXsrfProtection` precisam estar **iguais** (ambos `true`), e o proxy reverso da frente precisa preservar o header `Host`.

### Gotcha crítico — defasagem entre documentação (Apache) e realidade (nginx)

Todo o material versionado no repositório (`setup-novo-servidor/gestao-de-projetos.conf`, `install.sh`, `README.md`, `DEV.md`) descreve o deploy usando **Apache** como proxy reverso, com `ProxyPass`/`ProxyPassReverse` para `127.0.0.1:8501` e `Require ip 152.92.0.0/16` como controle de rede. **Isso está desatualizado.**

Na prática, a produção real (servidor `prefei-site`, `152.92.238.40`) usa **nginx**, configurado em `/etc/nginx/sites-enabled/sisuerj` **fora deste repositório git** (conhecimento operacional, não documentado em nenhum arquivo versionado). O bloco relevante:
- `location /gestao-de-projetos/ { proxy_pass http://127.0.0.1:8501/gestao-de-projetos/; ... }`
- Foi **recentemente adicionado** dentro desse `location`: `allow 152.92.0.0/16; deny all;` — restringindo acesso à rede da UERJ.

**Implicação prática para a integração**: qualquer mudança de roteamento/proxy/controle de acesso por IP para o novo sistema do Everton precisa mexer no `sites-enabled/sisuerj` real do servidor, **não** nos arquivos de `setup-novo-servidor/` do repositório (que devem ser tratados como aspiracionais/legados, não como fonte de verdade do estado atual).

---

## Modelo de dados

Schema completo criado por `_criar_tabelas_impl()` em `database.py` (CREATE TABLE nas linhas 593-846, migrações incrementais 850-908). **Só existe UMA foreign key de fato enforced pelo Postgres em todo o schema**: `etapas_projeto.projeto_id → projetos.id ON DELETE CASCADE`. Todas as demais relações são "lógicas" (por convenção da aplicação), sem constraint no banco.

### `projetos` (tabela central)

| Coluna | Tipo | Descrição |
|---|---|---|
| `id` | BIGINT IDENTITY PK | |
| `projetista` | TEXT | CSV de nomes de usuários (`"João Silva, Maria Souza"`) — **não é FK**, é texto livre desmembrado por vírgula em toda a aplicação |
| `projeto` | TEXT | Nome/título do projeto |
| `endereco` | TEXT | Vem de cadastro mestre `enderecos` |
| `solicitante` | TEXT | |
| `contato` | TEXT | Texto livre (tel/email, sem validação) |
| `numero_sei` | TEXT | Nº do processo SEI/documento |
| `data_recebimento` | DATE | |
| `previsao_execucao` | DATE | |
| `data_inicio` | DATE | |
| `data_termino` | DATE | |
| `data_fim` | DATE | Duplicata de `data_termino`, mantida por "compatibilidade Gantt" — sempre gravada com o mesmo valor |
| `status` | TEXT DEFAULT `'Ativo'` | Default nunca exercitado — todo INSERT explicita `"Em Espera"` |
| `link_projeto` | TEXT | "Link da Pasta Drive/Nuvem" — hoje é o único ponto onde o projeto aponta para armazenamento externo de arquivos |
| `demandas` | TEXT | CSV de disciplinas + `" | "` + texto livre extra (ver §5) |
| `solicitacao` | TEXT | Escopo/descrição |
| `prioridade` | TEXT | `"Máxima"`, `"Média"`, `"Mínima"` ou `""` |
| `criado_em` | TIMESTAMP DEFAULT `CURRENT_TIMESTAMP` | |
| `tags` | TEXT | CSV de tags livres (migração) |
| `codigo` | TEXT | Opcional; único quando preenchido (índice único parcial) |
| `local` | TEXT | Complemento livre do endereço (bloco/andar/sala) |
| `data_pedido` | DATE | Coluna **órfã** — adicionada por migração, sem nenhuma leitura/escrita encontrada no código |

Índices: `idx_projetos_status_prior (status, prioridade)`; `idx_projetos_codigo` — único parcial `ON projetos(codigo) WHERE codigo IS NOT NULL`.

### `usuarios`

| Coluna | Tipo | Descrição |
|---|---|---|
| `id` | BIGINT IDENTITY PK | |
| `nome` | TEXT UNIQUE | Funciona como "username" — login é por nome |
| `senha` | TEXT | Hash bcrypt (ou SHA-256 legado, com rehash transparente) |
| `perfil` | TEXT | `"Gestor"`, `"Projetista"`, `"Visualizador"` — sem CHECK constraint |
| `cargo` | TEXT | Texto livre |
| `pergunta_secreta` / `resposta_secreta` | TEXT | Recuperação de senha; resposta hasheada |
| `email` | TEXT | |
| `avatar_path` | TEXT | `anexos/avatars/{nome}_{ts}.jpg` |
| `equipe` | TEXT DEFAULT `'SERVPEN'` | `'SERVPEN'`, `'SERVPAR'`, `'GERAL'` |

### `arquivos` (tabela hoje usada pelo módulo a ser substituído)

```sql
CREATE TABLE IF NOT EXISTS arquivos (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    projeto_id BIGINT NOT NULL,
    nome_original TEXT NOT NULL,
    path_arquivo TEXT NOT NULL,
    descricao TEXT,
    autor TEXT,
    data_upload TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    tamanho_bytes BIGINT,
    mime_type TEXT
)
```
(`database.py:712-722`) — sem migrações adicionais, sem FK declarada para `projetos`, sem índice em `projeto_id`. Detalhamento completo na §6.

### Demais tabelas (resumo)

| Tabela | Chave/PK | Propósito | Vínculo a `projetos` |
|---|---|---|---|
| `sessoes` | `token` (PK é o próprio token) | Sessão de login persistente (7 dias) | — |
| `login_falhas` | `id` | Rate limiting de login | — |
| `chat` | `id` | Mensagens 1:1 e de grupo (soft-delete + edição) | — |
| `chat_grupo_visto` | PK composta `(usuario, grupo)` | Controle de não-lidas de grupo | — |
| `diario` | `id` | Relatos de diário de obra (atividade/dúvida/impedimento) | `projeto_id` (lógica) |
| `diario_leituras` | `id`, `UNIQUE(diario_id, usuario)` | Controle de "lido" por usuário | `diario_id` (lógica) |
| `mencoes_acesso` | `id`, `UNIQUE(usuario_mencionado, projeto_id)` | Acesso permanente concedido por menção `@"Nome"` | `projeto_id` (lógica) |
| `mencoes_notificacoes` | `id` | Notificações de menção | `projeto_id` (lógica) |
| `agenda` | `id` | Eventos de calendário (não tem `projeto_id`) | — |
| `etapas_projeto` | `id` | Cronograma/Gantt do projeto — **única FK real** | `projeto_id` FK `ON DELETE CASCADE` |
| `progresso_disciplinas` | `id` | % de conclusão por disciplina | `projeto_id` (lógica) |
| `disciplinas` | `id`, `nome UNIQUE` | Checklist mestre de disciplinas (19 seed) | — |
| `enderecos` | `id`, `endereco UNIQUE` | Cadastro mestre de endereços | — |
| `auditoria` | `id` | Log genérico de ações (`log_aud`) | `entidade_id` genérico |
| `projeto_alteracoes` | `id` | Histórico campo-a-campo de edição de projeto | `projeto_id` (lógica) |
| `tarefas` | `id` | To-do pessoal/atribuído, com recorrência | `projeto_id` opcional (lógica) |

### Relacionamentos (resumo)

**FK real (enforced):** `etapas_projeto.projeto_id → projetos.id ON DELETE CASCADE`.

**FK lógicas (não enforced, responsabilidade da aplicação):** `arquivos.projeto_id`, `diario.projeto_id`, `diario_leituras.diario_id`, `progresso_disciplinas.projeto_id`, `mencoes_acesso.projeto_id`, `mencoes_notificacoes.projeto_id`, `tarefas.projeto_id`, `projeto_alteracoes.projeto_id` → todas para `projetos.id`. `usuarios.nome` é referenciado por igualdade de string (não FK) a partir de `sessoes.usuario`, `chat.remetente/destinatario`, `diario.autor`, `arquivos.autor`, `tarefas.usuario/criado_por`, `auditoria.usuario`, entre outros.

`excluir_projeto(id_p)` (`database.py:1219-1229`) faz cascade **manual** só para `etapas_projeto`, `mencoes_acesso`, `mencoes_notificacoes` — **não** para `arquivos`, `diario`, `progresso_disciplinas`, `tarefas`. Ao excluir um projeto hoje, os arquivos físicos em `anexos/<projeto_id>/` e as linhas em `arquivos` **ficam órfãos**.

---

## Perfis de usuário e permissões

### Perfis (`usuarios.perfil`)

Três valores usados por convenção de aplicação (sem CHECK no banco): `"Gestor"`, `"Projetista"`, `"Visualizador"`. Duas funções centrais de checagem, em `core/helpers.py:48-55`:

```python
def _pode_editar():
    """True se o perfil atual pode criar/editar/excluir. Visualizador é read-only."""
    return st.session_state.get("perfil", "") in ("Gestor", "Projetista")

def _pode_gestor():
    """True somente para perfil Gestor."""
    return st.session_state.get("perfil", "") == "Gestor"
```

| Perfil | Pode | Não pode |
|---|---|---|
| **Gestor** | Criar/editar/clonar/excluir projeto; mudar status (Kanban); ações em lote; gerenciar equipe (CRUD de usuário, conforme escopo de equipe); ver Auditoria/Acessos; revogar acesso por menção; excluir qualquer arquivo | — |
| **Projetista** | Postar no Diário; upload de arquivo (sem guard explícito — ver §6); editar apenas os próprios arquivos | Criar/editar/excluir projeto; páginas Novo Projeto/Equipe/Auditoria/Acessos; ações em lote |
| **Visualizador** | Upload de arquivo (**inconsistência** — ver §6, deveria ser read-only mas não há guard) | Postar no Diário; qualquer criação/edição/exclusão nas demais telas |

### Segmentação por "equipe" (`usuarios.equipe`)

Coluna `usuarios.equipe TEXT DEFAULT 'SERVPEN'`, valores `'SERVPEN'`, `'SERVPAR'`, `'GERAL'`. Comentário de schema: *"Define isolamento de visão. Num projetista = a qual equipe pertence. Num Gestor = escopo (GERAL = vê tudo, sem filtro)"* (`database.py:862-866`).

```python
# core/helpers.py:62-71
def _equipe_atual():
    return st.session_state.get("equipe", "SERVPEN")

def _ve_tudo():
    """True se o escopo do usuário NÃO filtra por equipe (Gestor Geral)."""
    return _equipe_atual() == "GERAL"
```

**Ponto crítico**: a segmentação por equipe **não** filtra a lista de projetos visíveis no Kanban/Dashboard/Tarefas/Arquivos. `core/data.py:37-55` (`_load_df_p`) só filtra por `perfil`: qualquer `Gestor` (mesmo de equipe SERVPEN, não só GERAL) vê e pode editar **todos** os projetos do sistema, de qualquer equipe. A equipe só restringe: a lista de membros gerenciáveis em `views/equipe.py`, a visibilidade da seção "Evolução Técnica por Disciplina" dentro do card do Kanban, e as métricas "por pessoa" da Agenda/Dashboard.

### Como a sessão expõe perfil/equipe

`session_state` populado em 3 pontos distintos: (1) login manual (`auth.py:73-75`) seta só `autenticado/usuario/perfil` — **não seta `equipe`**; (2) auto-login por token (`app.py:130-151`) busca `equipe` separadamente via `db.obter_usuario()`; (3) refresh a cada rerun (`app.py:551-567`) recarrega `perfil`/`equipe` do banco em **todo** run autenticado, garantindo que promoções feitas por outro Gestor reflitam sem precisar relogar.

Visibilidade de subconjunto de projetos para Projetista/Visualizador: união de (a) presença do nome no CSV `projetos.projetista`, e (b) linhas em `mencoes_acesso` (concedidas por menção `@"Nome"` no Diário, revogáveis só por Gestor em `views/acessos.py`).

---

## O módulo Projetos (objeto central)

Todo arquivo/pasta do novo sistema do Everton se vincula a um `projetos.id`. Campos completos do formulário de criação (`views/novo_projeto.py`, exclusivo de Gestor — guard `views/novo_projeto.py:25-27`):

| Campo UI | Obrigatório | Coluna no banco |
|---|---|---|
| Código do Projeto | Não | `codigo` (único quando preenchido) |
| Nome do Projeto / Cliente | **Sim** | `projeto` |
| Nº SEI / Documento | Não | `numero_sei` |
| Solicitante / Cliente | Não | `solicitante` |
| Contato | Não | `contato` |
| Link da Pasta (Drive/Nuvem) | Não | `link_projeto` — candidato natural a virar deep-link para o novo sistema |
| Endereço da Obra | Não | `endereco` |
| Local | Não | `local` |
| Equipe Responsável | **Sim** | `projetista` (CSV, lista TODOS os usuários, sem filtro por equipe de gestão) |
| Prioridade | — | `prioridade` (default `"Média"`) |
| Tags | Não | `tags` (CSV) |
| Datas (recebimento, previsão, início, término) | — | `data_recebimento`, `previsao_execucao`, `data_inicio`, `data_termino`/`data_fim` |
| Disciplinas do Projeto + Checklist Adicional | Não | `demandas` (CSV disciplinas `" | "` texto livre) |
| Descrição do Escopo | Não | `solicitacao` |
| Etapas do Projeto | Não | tabela `etapas_projeto` |

### Status válidos do Kanban

Definidos em `CONFIG_COLUNAS` (`views/kanban.py:764-775`) — **não há CHECK constraint no banco**, é `TEXT` livre por convenção:

| Valor gravado no banco | Rótulo UI |
|---|---|
| `"Em Espera"` | ⏳ Em Espera |
| `"Ativo"` | 🚀 Em Execução |
| `"🛑 Parado"` | 🛑 Parados *(o emoji faz parte do valor gravado)* |
| `"Cancelado"` | ❌ Cancelados |
| `"Concluído"` | ✅ Concluídos |

Status inicial de todo projeto criado: sempre `"Em Espera"` (hardcoded no INSERT, `views/novo_projeto.py:270`). Transições são feitas por botões de ação (não drag-and-drop), restritas a Gestor.

### Relação equipe/projeto

Não existe coluna `projetos.equipe`. O vínculo de "quem trabalha no projeto" é só o CSV `projetista`, que pode conter nomes de qualquer equipe de gestão — comentário explícito no código: *"'Equipe Responsável' lista TODOS (qualquer um marca qualquer um, de qualquer equipe). O projeto em si continua compartilhado"* (`views/novo_projeto.py:99-100`). Ou seja, **"projeto" é uma entidade compartilhada entre equipes**, não pertence a uma equipe específica.

Ações destrutivas sobre projeto relevantes à integração: `excluir_projeto()` não remove `arquivos`/`diario`/`progresso_disciplinas` (ficam órfãos); `clonar_projeto()` explicitamente **não copia** arquivos, diário nem progresso de disciplinas ao duplicar um projeto.

---

## O módulo Arquivos atual (a ser substituído)

### Armazenamento físico em disco

- Pasta base: `PASTA_ANEXOS = 'anexos'` (`database.py:1944`), caminho **relativo ao working directory do processo Streamlit** (não é caminho absoluto fixo, não é URL, não é bucket/storage externo). Em produção isso resolve para `/var/www/gestao-de-projetos/anexos/` no servidor `152.92.238.40`.
- Criada no boot se não existir (`app.py:186-187`). Está no `.gitignore` — nunca vai para o git. Preservada entre deploys via rsync (`deploy-238.sh`).
- **Estrutura de subpastas**: `anexos/<id_projeto>/<nome_no_disco>` — o `<id_projeto>` é o `id` **numérico** (BIGINT) da tabela `projetos`, não o `codigo` amigável.
- A pasta `anexos/` **não é exclusiva** do módulo Arquivos: também abriga `anexos/avatars/` (fotos de perfil de usuário, tabela `usuarios.avatar_path`, totalmente desacoplado da tabela `arquivos`).

### Convenção de nomenclatura atual (arquivo físico)

O nome original **não é preservado como está** no disco. Lógica completa (`database.py:1983-1988`):

```python
def caminho_seguro_para_anexo(projeto_id, nome_original):
    nome_seguro = re.sub(r'[^A-Za-z0-9._\-]', '_', nome_original)[:120]
    ts = time.strftime('%Y%m%d_%H%M%S')
    pasta = os.path.join(PASTA_ANEXOS, str(int(projeto_id)))
    return pasta, os.path.join(pasta, f"{ts}_{nome_seguro}")
```

- Qualquer caractere fora de `[A-Za-z0-9._-]` (espaços, acentos, `/`, `\`, parênteses etc.) vira `_`.
- Nome sanitizado truncado a 120 caracteres, **antes** de prefixar o timestamp.
- Timestamp `YYYYMMDD_HHMMSS` (resolução de 1 segundo) prefixado com `_`.
- Exemplo: `"Memorial de Cálculo (rev.2).pdf"` → `anexos/42/20260708_143205_Memorial_de_C_lculo__rev.2_.pdf`.
- **Sem deduplicação nem versionamento**: reenviar arquivo com mesmo nome cria novo arquivo físico + nova linha na tabela. **Colisão possível**: dois arquivos de mesmo nome enviados no mesmo lote/segundo geram o mesmo `path_final` — o segundo sobrescreve o conteúdo físico do primeiro no disco, mas ambas as linhas continuam na tabela `arquivos` (uma delas aponta para conteúdo errado).
- **Não há convenção de nomenclatura de engenharia** (código de disciplina, revisão, tipo de documento etc.) — é puramente sanitização defensiva + timestamp anti-colisão.

### Schema da tabela `arquivos`

Já detalhado em §3. Recapitulando os pontos operacionais: `projeto_id NOT NULL` mas sem FK enforced; `mime_type` é gravado mas **nunca lido de volta** pela UI (o `SELECT` de `listar_arquivos()` nem sequer o inclui); sem coluna de pasta/categoria/tipo de documento — a única segmentação é `projeto_id` (1 nível, lista plana, sem hierarquia).

### Fluxo completo de upload

Componente `st.file_uploader(accept_multiple_files=True)` dentro de `st.form("form_upload_arquivo", clear_on_submit=True)` (`views/arquivos.py:47-64`).

- **Sem whitelist/blacklist de extensão** — nenhum `type=` passado ao uploader, qualquer extensão é aceita. Sem validação de magic bytes/MIME sniffing (item pendente conhecido no backlog do projeto, `docs/MELHORIAS-SUGERIDAS.md:65`).
- Limite: `maxUploadSize = 100` MB (config global do Streamlit, `.streamlit/config.toml:12`).
- Vínculo obrigatório a um projeto via `selectbox` "Vincular ao Projeto*", que só lista projetos já visíveis ao usuário (via `_load_df_p`).
- Processamento por item, com barra de progresso e coleta individual de falhas (um arquivo falhar não aborta os demais do lote):
  1. `pasta, path_final = db.caminho_seguro_para_anexo(proj_alvo_id, arq.name)`
  2. `os.makedirs(pasta, exist_ok=True)`
  3. `open(path_final, "wb").write(arq.getbuffer())` — grava o binário primeiro.
  4. `db.salvar_arquivo(...)` — só então insere a linha no banco.
  5. `db.log_aud(usuario, "upload", "arquivo", proj_alvo_id, f"nome='{arq.name}', {arq.size}B")` — **atenção**: `entidade_id` logado é o **id do projeto**, não da linha de arquivo (porque `salvar_arquivo` não usa `RETURNING id`).
- Se a escrita em disco tiver sucesso mas o INSERT falhar, fica um arquivo órfão no disco sem linha no banco (situação inversa ao "Arquivo perdido").

### Listagem

- `db.listar_arquivos(projeto_id=None)` chamada **a cada rerun, sem cache** (`@st.cache_data` não é usado aqui, diferente de outras queries do sistema).
- Lista linear (não agrupada visualmente por projeto), ordenada por `data_upload DESC`.
- Cada card mostra: ícone por **extensão do nome** (não por `mime_type`), nome original, projeto/autor/data/tamanho formatado, descrição, botão de download (só aparece se o arquivo físico ainda existir em disco — senão mostra "⚠️ Arquivo perdido", mas a linha do banco continua listável).

### Exclusão

```python
def excluir_arquivo(id_arq):
    # lê path_arquivo, tenta os.remove() (best-effort, engole exceção),
    # depois DELETE FROM arquivos WHERE id=%s
```
- **Não é soft delete** — DELETE físico da linha + tentativa de remoção do arquivo em disco. Falha silenciosa de `os.remove` não impede o DELETE do banco (pode deixar arquivo órfão em disco).
- Sem lixeira/histórico/undo.
- Permissão: `pode_excluir = (perfil == "Gestor" or autor == usuario)` (`views/arquivos.py:223`) — comparação simples de string contra `autor` (campo texto livre gravado no momento do upload).

### Proteção contra path traversal

Não é uma blacklist de `..` — é uma **whitelist de caracteres** (`[A-Za-z0-9._-]`). Qualquer separador de diretório (`/`, `\`) vira `_`, então o nome sanitizado nunca contém múltiplos segmentos de caminho, mesmo que o `nome_original` contenha `../../etc/passwd`. `projeto_id` é protegido por `int(projeto_id)` (força numérico). **Não há** normalização posterior (`os.path.normpath`/`realpath`) nem checagem de que o `path_final` está de fato dentro de `PASTA_ANEXOS` — a proteção depende inteiramente da sanitização de caracteres.

### Regras de permissão específicas deste módulo

- **Upload**: `views/arquivos.py` **não chama `_pode_editar()` em nenhum ponto** (confirmado por grep — só `app.py`, `views/diario.py`, `views/kanban.py` usam esse gate). Na prática, um usuário `Visualizador` (nominalmente read-only) **consegue fazer upload de arquivo** — é uma inconsistência do sistema atual em relação ao padrão do resto do app.
- **Exclusão**: Gestor exclui qualquer arquivo; demais perfis só os que enviaram (`autor == usuario`).
- **Gap de permissão na listagem "Todos os projetos"**: quando o filtro é `None` (opção default do seletor), `listar_arquivos(None)` executa `SELECT * FROM arquivos ORDER BY data_upload DESC` **sem nenhum filtro de projeto/perfil/equipe** — um Projetista com acesso restrito a poucos projetos consegue ver e baixar arquivos de **qualquer** projeto do sistema ao escolher essa opção.
- Sem FK/cascade entre `arquivos` e `projetos`: excluir um projeto não remove seus arquivos (ficam órfãos, exibidos com "(projeto removido)" na UI, mas continuam baixáveis/excluíveis).

### Métricas exibidas

Calculadas em **Python**, não em SQL, sobre a lista já filtrada (`views/arquivos.py:150-152`):

```python
arquivos_lista = db.listar_arquivos(projeto_id=filtro_proj_id)
tamanho_total = sum((r[7] or 0) for r in arquivos_lista)
col_f2.metric("Arquivos", len(arquivos_lista))
col_f3.metric("Tamanho total", f"{tamanho_total / (1024*1024):.1f} MB")
```

Reflete apenas o filtro atual (1 projeto ou "todos"); não há breakdown por projeto simultâneo, nem métricas históricas (uploads por mês), nem exibição em nenhum outro lugar do sistema (Kanban/Dashboard não mostram contagem de arquivos por projeto hoje).

### Funções de `database.py` usadas pelo módulo

| Função | Assinatura | Propósito |
|---|---|---|
| `PASTA_ANEXOS` | constante `= 'anexos'` | Raiz relativa de armazenamento |
| `salvar_arquivo` | `(projeto_id, nome_original, path_arquivo, descricao, autor, tamanho_bytes, mime_type='') -> None` | INSERT puro; **não retorna o `id` gerado** (sem `RETURNING id`) |
| `listar_arquivos` | `(projeto_id=None) -> list[tuple(id, projeto_id, nome_original, path_arquivo, descricao, autor, data_upload, tamanho_bytes)]` | Sem cache; `mime_type` não incluído no SELECT; `projeto_id=None` retorna tudo sem filtro de permissão |
| `excluir_arquivo` | `(id_arq) -> None` | DELETE físico + tenta remover do disco (best-effort) |
| `caminho_seguro_para_anexo` | `(projeto_id, nome_original) -> (pasta, path_final)` | Sanitiza nome + monta caminho; **não cria a pasta** (quem chama faz `os.makedirs`) |
| `log_aud` | `(usuario, acao, entidade='', entidade_id=None, detalhes='') -> None` | Auditoria genérica (usada por todo o sistema, best-effort, silencia exceções) |
| `criar_tabela_arquivos` | `()` | Stub de compatibilidade — só chama `criar_tabelas()` |

### Terceiro caminho de arquivo desalinhado — `diario.anexo`

O Diário tem seu **próprio** mecanismo de anexo, independente e desacoplado da tabela `arquivos`: grava em `anexos/<timestamp>_<nome_original>` (sem subpasta por projeto — diferente do padrão `anexos/<projeto_id>/...`), e **não cria linha em `arquivos`** — só grava o caminho como string em `diario.anexo`. Existem hoje, portanto, **três pontos de entrada de arquivo desalinhados**: a tabela `arquivos` (Central de Arquivos), a coluna `diario.anexo` (anexo solto de relato), e `usuarios.avatar_path` (avatar de perfil).

### O que muda com a integração

O menu **"Arquivos"** (`views/arquivos.py`, registrado em `app.py:598-599`) será **desativado e substituído** pelo sistema construído pelo Everton. Na prática isso significa que os usuários deixarão de usar esta tela — upload, listagem, download e exclusão de documentos de projeto passarão a acontecer no novo programa. A tabela `arquivos` do Postgres (e a pasta física `anexos/<projeto_id>/`) hoje contêm os dados/arquivos existentes; cabe a essa integração decidir como eles migram, são referenciados ou substituídos pelo novo sistema (ver §8, pontos de atenção).

---

## Demais módulos do sistema (mapa geral)

| Módulo | Arquivo | Resumo |
|---|---|---|
| **Diário** | `views/diario.py` (869 linhas) | Log cronológico de relatos por projeto (Atividade/Dúvida/Impedimento), com thread de interações num campo TEXT único (`resposta_gestor`), menções `@"Nome"` (concedem acesso a projeto via `mencoes_acesso`), time tracking (`horas`), edição com marcador "(editado)", e **anexo próprio desacoplado** da Central de Arquivos (`diario.anexo`). Gera PDF por projeto via `relatorios.gerar_pdf_diario`. |
| **Tarefas** | `views/tarefas.py` (360 linhas) | To-do estilo planilha (`st.data_editor`), privado por padrão, pode ser atribuído por Gestor a outro membro, com recorrência (diária/semanal/mensal) e vínculo opcional a `projeto_id` (aparece também no Kanban). Sem relação com arquivos. |
| **Agenda** | `views/agenda.py` (1013 linhas) | Calendário compartilhado (visitas técnicas, reuniões, férias, licença, folga). **Não tem `projeto_id`** — vincula-se só a pessoas (`responsaveis`, CSV). Export `.ics`. Visibilidade por equipe. |
| **Chat** | `views/chat.py` (221 linhas) | Chat interno estilo WhatsApp (DM 1:1 + 3 grupos por equipe: `TODOS`, `SERVPEN`, `SERVPAR`), auto-refresh 2s, edição e soft-delete de mensagem. Sem `projeto_id`/arquivos. |
| **Equipe** | `views/equipe.py` (434 linhas) | CRUD de usuários (Gestor-only): nome, senha, perfil, cargo, equipe, pergunta secreta. Regra de escopo: só Gestor `GERAL` promove a Gestor/move entre equipes; líder de equipe só gerencia Projetista/Visualizador da própria equipe. É a tela-fonte de todo `nome` usado em `projetista`, `autor`, `responsaveis` no resto do sistema. |
| **Acessos** | `views/acessos.py` (89 linhas) | Gestor-only. **Não** é cadastro de usuário — é a tela de revogação de acessos concedidos por menção (`mencoes_acesso`). Concessão é permanente até revogação manual. |
| **Auditoria** | `views/auditoria.py` (189 linhas) | Gestor-only. Duas seções: log genérico de ações (`auditoria`, via `log_aud`) e histórico específico de alterações de campo de projeto (`projeto_alteracoes`, só populado quando o projeto já saiu de "Em Espera"). Renderizado em HTML manual (não `st.dataframe`) por causa de restrição de hardware legado (pyarrow/AVX2). |
| **Dashboard** | `views/dashboard.py` (956 linhas) | Painel gerencial só-leitura: KPIs por perfil, Gantt integrado (projeto inteiro ou por etapas), pizza de volume por pessoa, heatmap/barras/tabela de Evolução Técnica por Disciplina, cards de carga por pessoa, e botões de exportação (Excel completo, PDF completo, PDF Gantt) via `relatorios.py`. Nenhuma relação com arquivos. |
| **Relatórios** | `relatorios.py` (1018 linhas) | Geração de Excel (`xlsxwriter`) e PDF (`reportlab`): lista de projetos+etapas+progresso, histórico de alterações, PDF completo da carteira, PDF Gantt (paisagem), PDF do Diário por projeto. **Não existe hoje nenhum relatório que liste/exporte os arquivos anexados de um projeto** — gap relevante para o novo módulo do Everton preencher. |

---

## Pontos de atenção para a integração

Síntese de decisões técnicas e pontos de acoplamento que o Everton precisa resolver ao projetar o novo módulo, com base no que as notas de pesquisa revelam sobre o estado atual do sistema.

**Identidade do projeto e chave de junção**
- `projetos.id` (BIGINT identity) é a chave usada por toda relação lógica hoje (`arquivos.projeto_id`, `diario.projeto_id`, `tarefas.projeto_id` etc.) — é o candidato natural e já validado para o novo módulo usar como `projeto_id`.
- Existem dois identificadores "amigáveis" adicionais: `codigo` (único quando preenchido, mas **opcional** — pode ser `NULL`) e `projeto` (nome, texto livre, **não único**). Se o novo sistema for gerar nomenclatura de pasta/arquivo baseada em identificador legível, `codigo` é o mais adequado, mas é preciso decidir o que fazer com projetos sem código definido (a maioria pode não ter, já que não é obrigatório no cadastro).
- Decisão em aberto: o novo sistema vai usar o mesmo `id` numérico do Postgres compartilhado, ou terá seu próprio esquema de IDs com um mapeamento para `projeto_id`?

**Reuso vs. substituição da tabela `arquivos`**
- A tabela `arquivos` (schema em §3/§6) é minimalista de propósito: sem versionamento, sem pastas/hierarquia, sem categorias/tipos de documento, sem soft-delete, sem FK enforced, sem índice em `projeto_id`. Não parece adequada como base estrutural para "um programa muito mais completo" — provavelmente o Everton vai criar schema próprio.
- Se criar tabelas novas: como ficam os ~poucos arquivos já existentes hoje em `anexos/<projeto_id>/` e nas linhas de `arquivos`? É preciso decidir entre (a) script de migração que copia arquivo físico + metadados para o novo esquema, (b) deixar os arquivos antigos "congelados" e só documentar como acessá-los, ou (c) importar só os metadados e manter os binários no lugar atual.
- Se reusar a tabela `arquivos` como estava: ela precisa de ALTER TABLE para suportar os novos requisitos (pastas, categorias, versionamento) — e qualquer mudança de schema precisa coexistir com o guard de `criar_tabelas()` (`database.py:35-49`), que roda 1x por processo e usa `ADD COLUMN IF NOT EXISTS` para migrações incrementais.

**Perfis e permissões**
- O novo módulo replica os mesmos 3 perfis (`Gestor`/`Projetista`/`Visualizador`) e a mesma tabela `usuarios`? Isso é o caminho mais direto para consistência, mas exige que o programa do Everton também leia `session_state`/tabela `usuarios` do mesmo banco (ou reimplemente sua própria checagem contra a mesma tabela, já que não há API — é acesso direto ao Postgres).
- **Gaps de permissão do sistema atual que não devem ser copiados sem decisão consciente**: (a) `views/arquivos.py` não verifica `_pode_editar()` no upload — Visualizador consegue subir arquivo hoje; (b) `listar_arquivos(projeto_id=None)` ("Todos os projetos") não filtra por visibilidade do usuário — vaza arquivos de projetos que o usuário normalmente não veria; (c) Gestor de equipe (não-GERAL) vê/edita projetos de **todas** as equipes, não só a própria, porque `_load_df_p` não filtra por equipe. Se o novo módulo herdar a mesma base de "quais projetos existem", ele herda esse comportamento por padrão — vale decidir explicitamente se a segmentação por equipe (SERVPEN/SERVPAR/GERAL) deve valer para arquivos, já que hoje o "PROMPT-controle-equipes" do próprio repo já declara intencionalmente que "arquivos são do projeto, que é compartilhado" (ou seja, não filtrado por equipe) — o Everton deve confirmar se essa intenção de produto continua valendo no novo sistema.

**Desativação do menu atual em `app.py`**
- O registro da página fica em `app.py:598-599` (`st.Page("views/arquivos.py", title="Arquivos", icon="📁", url_path="arquivos")`), dentro da lista `_pages_gerais` usada em `st.navigation` (`app.py:585-615`). Para desativar, o mecanismo mais simples é remover esse `st.Page` da lista (ou substituí-lo por um `st.Page` que redirecione/exiba um link externo para o novo sistema, já que Streamlit permite páginas com apenas um `st.link_button` para uma URL externa). Como o roteamento roda cada `st.Page` como script independente (`st.navigation`, `app.py:775-787`), a forma mais limpa é decidir entre: (a) apagar a entrada do menu totalmente, (b) manter a entrada mas trocar o conteúdo de `views/arquivos.py` por um link/iframe para o novo sistema, ou (c) manter os dois lado a lado durante uma transição.
- A sidebar também renderiza o menu via `st.page_link()` manual em loop (`app.py:570-772`) — qualquer mudança na lista de páginas precisa ser refletida lá também (é o mesmo array `pages` usado em ambos os lugares, então uma alteração na fonte já propaga).

**Rede e acesso**
- A produção roda atrás de nginx restrito à rede UERJ (`152.92.0.0/16`), configurado fora do repositório (`/etc/nginx/sites-enabled/sisuerj` no servidor). Pergunta em aberto: **o novo programa do Everton vai rodar como processo separado, precisando de sua própria entrada de proxy nginx com a mesma restrição de rede?** Se sim, é preciso coordenar essa mudança diretamente no servidor (não há automação versionada para isso hoje — reforça o gotcha da §2).
- Se o novo sistema acessar o mesmo Postgres, ele precisa das mesmas credenciais/rede de banco — hoje isso é feito via `DATABASE_URL` ou variáveis `DB_HOST/PORT/NAME/USER/PASSWORD` (`database.py:75-124`), e em produção o Postgres roda nativo (não Docker) no mesmo servidor.

**Convenção de nomenclatura**
- A convenção física atual (`anexos/<projeto_id>/<timestamp>_<nome_sanitizado>`) é puramente defensiva (sanitização de caracteres + anti-colisão por timestamp), sem nenhuma semântica de engenharia (sem código de disciplina, revisão, tipo de documento). Não há razão técnica para o Everton preservar esse padrão exato — mas se decidir migrar arquivos existentes, precisa mapear esse layout físico para o que o novo sistema propuser.
- Pontos a decidir: o novo sistema vai introduzir uma convenção de nomenclatura mais rica (ex.: código de projeto + disciplina + revisão)? Isso teria implicações em `projetos.codigo` ser tratado como obrigatório (hoje é opcional).

**Outras dependências e riscos identificados**
- **Relatórios não cobrem arquivos hoje**: nenhum PDF/Excel gerado por `relatorios.py` lista os arquivos anexados de um projeto — se esse for um requisito do novo sistema, é funcionalidade nova a construir, não uma migração.
- **Sem contadores de arquivo no Kanban/Dashboard hoje**: não há badge "N arquivos" em nenhum card — se o Everton quiser expor isso, é preciso decidir se o Kanban (`views/kanban.py`) vai consultar o novo esquema de dados do Everton (cross-schema) para exibir essa contagem, o que é outro ponto de acoplamento a desenhar.
- **`diario.anexo`**: mecanismo de anexo do Diário é hoje independente da Central de Arquivos (path sem subpasta por projeto, sem linha em `arquivos`). Decidir se o novo sistema também absorve esses anexos ou os deixa como estão (mecanismo separado, fora do escopo da integração).
- **`link_projeto`**: campo hoje usado para apontar manualmente para uma pasta externa (Drive/Nuvem) — pode ser reaproveitado como o link automático para o projeto correspondente no novo sistema do Everton, evitando duplicar a necessidade de um campo novo em `projetos`.
- **Exclusão de projeto não é cascata para arquivos**: `excluir_projeto()` não limpa `arquivos`/`diario`/`progresso_disciplinas`. Se o novo sistema reusar `projeto_id` como chave, precisa decidir sua própria política de cascade (não pode assumir que o Postgres vai fazer isso automaticamente, já que hoje não há FK declarada nem trigger).
- **Guard de schema (`criar_tabelas()`)**: se o Everton for evoluir o schema do mesmo banco (nova tabela, ou `ALTER TABLE arquivos`), precisa estar ciente do padrão de guard usado aqui (lock + flag por processo, `database.py:35-49`) para evitar deadlocks de `ALTER TABLE` — mas esse guard é local ao processo do `database.py` atual; se o novo sistema for um processo Python separado, ele precisará do próprio mecanismo de proteção (ou uma migração coordenada tipo Alembic/flyway) para não colidir com o `criar_tabelas()` deste app quando ambos sobem ao mesmo tempo.
- **Timezone**: toda conexão do sistema atual roda `SET TIME ZONE 'America/Sao_Paulo'` — se o novo sistema gravar timestamps (ex. `data_upload`) sem fazer o mesmo, pode haver inconsistência de fuso entre os dois programas ao exibir/comparar datas.

---

## Glossário rápido

| Termo | Significado |
|---|---|
| **SERVPEN** | Serviço de Engenharia da UERJ — equipe/instituição dona do sistema. Também é um dos 3 valores possíveis de `usuarios.equipe`. |
| **SERVPAR** | Outra equipe de gestão dentro do sistema (irmã de SERVPEN), valor de `usuarios.equipe`. |
| **GERAL** | Valor de `usuarios.equipe` que significa "escopo sem filtro" — um Gestor com `equipe=GERAL` vê/gerencia tudo, de todas as equipes. |
| **Projetista** (perfil) | Um dos 3 perfis de usuário (`usuarios.perfil`), com permissão de criar/editar conteúdo (Diário, Tarefas, Arquivos) mas não de gerenciar projetos/usuários. Não confundir com o campo `projetos.projetista` (§ próxima entrada). |
| **`projetista`** (campo de projeto) | Coluna `projetos.projetista` — CSV de nomes de usuários designados como "Equipe Responsável" por um projeto específico. É texto livre, não FK, e pode conter pessoas de qualquer equipe de gestão. |
| **Relato** | Registro individual no Diário de Obra (tabela `diario`) — pode ser do tipo "Relato de Atividade", "❓ Dúvida Técnica" ou "🛑 Impedimento". |
| **Interação** | Resposta/comentário dentro da thread de um relato do Diário, armazenada concatenada no campo texto único `diario.resposta_gestor` (não é uma tabela normalizada). |
| **Menção** (`@"Nome"`) | Sintaxe usada no Diário para citar um usuário; ao salvar, concede a esse usuário acesso permanente ao projeto (grava em `mencoes_acesso`) e dispara notificação. |
| **Acesso por menção** | Mecanismo de `mencoes_acesso` — dá a um Projetista/Visualizador visibilidade de um projeto específico mesmo sem estar no CSV `projetista`. Revogável só por Gestor, na tela **Acessos**. |
| **Central de Arquivos** | Nome informal do módulo atual "Arquivos" (`views/arquivos.py` + tabela `arquivos`) — o que será substituído pelo sistema do Everton. |
| **Kanban** | Board de status dos projetos (`views/kanban.py`), com colunas Em Espera / Em Execução / Parados / Cancelados / Concluídos. |
| **Gantt** | Visualização de cronograma (etapas de projeto ao longo do tempo), presente no Dashboard e exportável em PDF paisagem. |
| **Etapa** | Registro em `etapas_projeto` — um passo do cronograma de um projeto, com offset/duração em dias e percentual de conclusão. |
| **Disciplina** | Especialidade técnica de engenharia (ex.: Elétrica, Hidráulica, Estrutura) — cadastro mestre em `disciplinas`, usado tanto no campo `demandas` do projeto quanto no progresso técnico (`progresso_disciplinas`). |
| **`prefei-site`** | Apelido do servidor de produção, IP `152.92.238.40`. |
| **Rede UERJ** | Faixa de IP `152.92.0.0/16` — único range autorizado a acessar o sistema em produção (regra aplicada no proxy nginx do servidor). |
| **`baseUrlPath`** | Configuração do Streamlit que prefixa todas as rotas do app (`/gestao-de-projetos/...`) — necessário para coexistir com outros sistemas no mesmo domínio/servidor via proxy reverso. |
