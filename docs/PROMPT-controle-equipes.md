# PROMPT — Controle de acesso por equipe de gestão (SERVPEN / SERVPAR / Geral)

> Documento de especificação para implementar a divisão do sistema entre
> equipes de gestão. Entregue este arquivo inteiro a quem for implementar
> (humano ou agente de IA). Ele descreve **o que fazer, onde e por quê**,
> com base no código atual (Streamlit modular + PostgreSQL).

---

## 1. Contexto do sistema

- App Streamlit **modular**: `app.py` (login + sidebar + navegação),
  `core/` (helpers, dados, auth, sessão), `views/` (uma tela por arquivo).
- Banco **PostgreSQL** (`database.py`). Tabelas relevantes:
  - `usuarios(id, nome, senha, perfil, cargo, email, avatar_path, ...)`
    — `perfil` ∈ {Gestor, Projetista, Visualizador}.
  - `projetos(id, projetista, projeto, status, ...)` — `projetista` é
    **TEXT com nomes separados por vírgula**.
  - `progresso_disciplinas(id, projeto_id, disciplina, concluido, percentual)`
    — evolução por disciplina (NÃO tem dono/grupo hoje; **manter assim**).
  - `etapas_projeto(id, projeto_id, nome, dias_offset, duracao_dias, ordem)`
    — fases do **Gantt** (cronograma do projeto).
  - `agenda(id, titulo, tipo, data_inicio, data_fim, responsaveis, ...)`
    — `responsaveis` é **TEXT com nomes separados por vírgula**.
- Sessão atual expõe `st.session_state.usuario` e `st.session_state.perfil`.

---

## 2. Objetivo

Dividir a operação em **3 escopos de gestão**:

| Gestor | Escopo (o que enxerga) |
|---|---|
| **Gestor Geral** | TUDO — SERVPEN + SERVPAR juntos |
| **Gestor SERVPEN** (ex.: Sara) | só o que pertence à equipe **SERVPEN** |
| **Gestor SERVPAR** (ex.: Jackeline) | só o que pertence à equipe **SERVPAR** |

Os 3 são `perfil = 'Gestor'` e **todos podem**: editar, criar projeto,
ver e inserir pessoas. A diferença é **o que cada um enxerga**.

### O que é COMPARTILHADO (todos os gestores veem igual)
- O **cadastro do projeto** (tabela `projetos`) — projeto é cadastrado **1×**.
- O **gráfico de Gantt** / cronograma (`etapas_projeto`) — progresso do projeto.

### O que é ISOLADO por equipe
- **Pessoas / Equipe** (`usuarios`): cada gestor só vê quem é da sua equipe.
- **Cards "projetos por pessoa"** (dashboard): só conta gente da sua equipe.
- **Evolução por disciplina** (`progresso_disciplinas`): só vê a dos
  projetos atrelados à sua equipe (ver regra derivada no §4).
- **Agenda**: só vê eventos dos projetistas da sua equipe.

---

## 3. Modelo de dados (a ÚNICA mudança de schema)

Adicionar **uma coluna** em `usuarios`:

```
usuarios.equipe  TEXT  DEFAULT 'SERVPEN'   -- valores: 'SERVPEN' | 'SERVPAR' | 'GERAL'
```

Semântica de `equipe`:
- Num **projetista/pessoa**: a qual equipe ela pertence (SERVPEN ou SERVPAR).
  `GERAL` = neutro/visível a todos (usar só se necessário).
- Num **Gestor**: define o escopo de visão:
  - `equipe = 'GERAL'`  → Gestor Geral (vê tudo, sem filtro).
  - `equipe = 'SERVPEN'` → Gestor SERVPEN.
  - `equipe = 'SERVPAR'` → Gestor SERVPAR.

> **Não criar tabela nova. Não tocar em `projetos`, `etapas_projeto`,
> `progresso_disciplinas` ou `agenda` no schema.** O grupo de uma
> disciplina/agenda é **derivado** do projetista (ver §4), conforme
> decidido: *"a evolução da disciplina pertence a quem foi designado o
> projeto; pode continuar como está hoje"*.

### Migração (em `criar_tabelas`, lista `migracoes`)
```python
("usuarios", "equipe", "TEXT DEFAULT 'SERVPEN'"),
```
Todos os usuários existentes viram **SERVPEN** por padrão. Depois o
Gestor Geral reclassifica quem for SERVPAR na tela de Equipe.

### Configuração inicial dos gestores (rodar 1× após deploy)
```sql
UPDATE usuarios SET equipe='GERAL'   WHERE nome='<Gestor Geral>';
UPDATE usuarios SET equipe='SERVPEN' WHERE nome='Sara';
UPDATE usuarios SET equipe='SERVPAR' WHERE nome='Jackeline';
```

---

## 3.1 Líderes de equipe (o Gestor Geral designa)

Um **líder de equipe** = usuário com **`perfil = 'Gestor'`** +
**`equipe = 'SERVPEN'`** (ou `'SERVPAR'`). Não precisa de tabela nem
campo novo — é a combinação desses dois atributos já existentes.

### Quem o Gestor Geral promove (na tela Equipe)
Editando uma pessoa, o Geral define:

| Campo | Valor | Efeito |
|---|---|---|
| `perfil` | `Gestor` | Vira líder (edita, cria projeto, insere pessoas) |
| `equipe` | `SERVPEN` / `SERVPAR` | Qual equipe ele lidera e enxerga |

- **Vários líderes por equipe**: permitido — basta `perfil='Gestor'` em
  quantas pessoas da mesma equipe quiser. Sem limite.
- **Trocar/remover líder**: o Geral muda `perfil` de volta pra
  `Projetista`/`Visualizador` (a pessoa continua na equipe, mas deixa de
  ser gestor) ou troca a `equipe`.

### Regra de PERMISSÃO (obrigatória — implementar em `views/equipe.py`)

| Ação | Quem pode |
|---|---|
| Definir `perfil = 'Gestor'` (promover a líder) | **Somente Gestor Geral** |
| Alterar a `equipe` de qualquer pessoa | **Somente Gestor Geral** |
| Criar/editar projetistas comuns **da própria equipe** | Gestor Geral **e** líderes de equipe |

Ou seja: um líder SERVPEN cadastra/edita gente do SERVPEN, mas **não**
consegue promover ninguém a Gestor nem mexer em quem é de qual equipe —
isso fica concentrado no Gestor Geral. Impede auto-promoção e invasão
entre equipes.

**Implementação:** no form de cadastro/edição de usuário, os widgets de
`perfil` e `equipe` só aparecem **editáveis** se `_ve_tudo()` (Gestor
Geral). Para líder de equipe, `perfil` fica travado em não-Gestor e
`equipe` fica fixa na própria equipe (read-only). Validar isso **também
no servidor**, antes do UPDATE — não confiar só em esconder o widget.

---

## 4. Regra de derivação do grupo (projetos / disciplinas / agenda)

Como projetos são compartilhados e **um mesmo projeto pode ter projetistas
das duas equipes**, o grupo é derivado assim:

- **Pessoa** → grupo = `usuarios.equipe`.
- **Projeto** → "pertence" a uma equipe se **algum** nome em
  `projetos.projetista` for de um usuário daquela equipe. (Um projeto
  compartilhado pertence às duas.)
- **Disciplina / evolução** (`progresso_disciplinas`) → herda do projeto
  (mesma regra do projeto). **Sem coluna nova** na tabela.
- **Evento de agenda** → "pertence" a uma equipe se **algum** nome em
  `agenda.responsaveis` for um usuário daquela equipe.

**Helper central** (criar em `database.py`):
```python
def nomes_por_equipe(equipe: str) -> set[str]:
    """Nomes de usuários de uma equipe ('SERVPEN'/'SERVPAR').
    Cacheável. Usado pra filtrar projetos/agenda/cards por pertencimento."""
```

**Regra de visibilidade (pseudo):**
```
Gestor Geral (equipe='GERAL')  → vê tudo, sem filtro.
Gestor X (equipe='SERVPEN'|'SERVPAR'):
   pessoas        → usuarios.equipe == X
   projeto visível p/ EVOLUÇÃO/cards → projetista ∩ nomes_por_equipe(X) ≠ ∅
   agenda visível → responsaveis ∩ nomes_por_equipe(X) ≠ ∅
   Kanban board + Gantt → SEMPRE visível (compartilhado)
```

> ⚠️ **Consequência de projeto compartilhado:** se um projeto tem projetista
> das DUAS equipes, sua evolução por disciplina aparece para os DOIS
> gestores (é a "fatia comum"). Isso é coerente com *"a única coisa em comum
> são os projetos"*. Se no futuro quiserem isolar disciplina-a-disciplina,
> aí sim será preciso vincular cada `progresso_disciplinas` a um projetista
> — fora do escopo atual.

---

## 5. Helpers a adicionar (`core/helpers.py`)

```python
def _equipe_atual() -> str:
    """Equipe do usuário logado ('SERVPEN'|'SERVPAR'|'GERAL')."""
    return st.session_state.get("equipe", "SERVPEN")

def _ve_tudo() -> bool:
    """True se o escopo do usuário não filtra por equipe (Gestor Geral)."""
    return _equipe_atual() == "GERAL"
```

Carregar `equipe` na sessão **no login e no auto-login** (onde hoje se
setam `usuario`/`perfil`):
- `core/auth_ui.py` (login) e `app.py` (auto-login por token):
  `st.session_state.equipe = db.obter_usuario(nome).get("equipe", "SERVPEN")`.

---

## 6. Mudanças por tela (views)

### 6.1 `views/equipe.py` — cadastro e listagem de pessoas
- **Listagem**: se `not _ve_tudo()`, filtrar `df_u` para
  `df_u["equipe"] == _equipe_atual()`. Gestor Geral vê todos + mostra a
  coluna/badge da equipe de cada um.
- **Cadastro de pessoa**: ao criar usuário, gravar `equipe`:
  - Gestor SERVPEN/SERVPAR → grava **a própria** equipe (sem perguntar).
  - Gestor Geral → mostra um **selectbox "Equipe" (SERVPEN/SERVPAR)** e
    grava a escolhida.
- **Edição de pessoa**: Gestor Geral pode trocar a equipe de qualquer um
  (selectbox). Gestores de equipe não trocam a equipe.
- **Promover líder / permissões**: os campos `perfil` e `equipe` só são
  **editáveis pelo Gestor Geral** (`_ve_tudo()`). Líder de equipe vê o
  `perfil` travado (não promove a Gestor) e a `equipe` fixa na própria.
  **Validar no servidor** antes do UPDATE, não só escondendo o widget.
  Detalhes e tabela de permissões em **§3.1 (Líderes de equipe)**.

### 6.2 `views/dashboard.py` — cards "projetos por pessoa"
- O agregado por projetista deve considerar **só pessoas da equipe** do
  gestor (`not _ve_tudo()` → filtra os nomes por `nomes_por_equipe(...)`).
- Gestor Geral vê todos (opcional: separar visualmente SERVPEN | SERVPAR).
- O multiselect `pizza_projetistas_selecionados` deve listar só os
  projetistas visíveis ao escopo.

### 6.3 `views/kanban.py` — board, Gantt e evolução por disciplina
- **Board (cards de projeto) + Gantt**: **NÃO filtrar** — compartilhado,
  todos veem todos os projetos.
- **Painel de evolução por disciplina** (`progresso_disciplinas`,
  "🔄 Atualizar Progresso"): exibir/permitir editar conforme a regra do §4
  — se `not _ve_tudo()`, mostrar a evolução só dos projetos cujo
  `projetista` intersecta `nomes_por_equipe(_equipe_atual())`. Para projeto
  só da outra equipe, ocultar/desabilitar o painel de evolução (mas o card
  e o Gantt continuam visíveis).

### 6.4 `views/agenda.py` — calendário
- Já existe filtro `if perfil_atual != "Gestor": filtra por usuario`.
  Estender: se `not _ve_tudo()`, manter só eventos cujo `responsaveis`
  intersecta `nomes_por_equipe(_equipe_atual())`. Gestor Geral vê tudo.
- Vale para as 4 visões (Mensal/Semanal/Lista/Resumo) e para os cards de
  métrica do topo.

### 6.5 (Verificar) `views/diario.py`
- O Diário já tem visibilidade por menção/acesso. **Não mexer** salvo se
  testes revelarem vazamento entre equipes. Anotar como item de validação.

---

## 7. O que NÃO mudar (importante)
- **`projetos`** e o fluxo de **Novo Projeto** (`views/novo_projeto.py`):
  projeto é único e visível a todos. Qualquer gestor cria/edita.
- **`etapas_projeto`** / Gantt: compartilhado.
- **`progresso_disciplinas`**: estrutura permanece (sem coluna de equipe).
- **Chat**: fora do escopo desta tarefa (não isolar por equipe agora).

---

## 8. Critérios de aceite (cenários de teste)

Pré-condição: Sara=`SERVPEN`, Jackeline=`SERVPAR`, um Gestor Geral=`GERAL`.
Cadastrar 2 projetistas SERVPEN (ex.: Ana, Bia) e 2 SERVPAR (Carla, Davi).
Criar projetos: P1 (projetista Ana), P2 (Carla), P3 (Ana, Carla — compartilhado).

1. **Equipe**: Sara vê só {Ana, Bia, Sara}. Jackeline vê só {Carla, Davi,
   Jackeline}. Gestor Geral vê todos.
2. **Cadastro**: Sara cadastra "Eva" → Eva entra como SERVPEN automaticamente
   e some pra Jackeline. Gestor Geral cadastra "Fred" escolhendo SERVPAR →
   aparece só pra Jackeline e pro Geral.
3. **Cards por pessoa** (dashboard): Sara vê contagem de Ana/Bia, **não** de
   Carla/Davi. Jackeline o inverso. Geral vê todos.
4. **Evolução por disciplina**: Sara vê evolução de P1 e P3; **não** vê P2.
   Jackeline vê P2 e P3; não vê P1. Geral vê P1, P2, P3.
5. **Agenda**: evento com responsável Ana aparece pra Sara e pro Geral, não
   pra Jackeline. Evento com Carla aparece pra Jackeline e Geral, não Sara.
6. **Compartilhado**: P1, P2, P3 aparecem no **Kanban board** e no **Gantt**
   para os 3 gestores igualmente.
7. **Migração**: usuários antigos viram SERVPEN; nada some pro Gestor Geral.
8. **Designar líder** (§3.1): Gestor Geral edita "Bia" → `perfil=Gestor` +
   `equipe=SERVPEN` → Bia vira líder SERVPEN (vê o escopo SERVPEN ao logar).
   Vários líderes na mesma equipe funcionam.
9. **Permissão**: logada como Sara (líder SERVPEN), os campos `perfil` e
   `equipe` aparecem **travados** — ela não consegue promover ninguém a
   Gestor nem mudar a equipe de alguém. Tentar burlar via request mesmo
   assim é **bloqueado no servidor**.

---

## 9. Roteiro sugerido de implementação
1. `database.py`: migração `usuarios.equipe` + helper `nomes_por_equipe()`
   (cacheado) + incluir `equipe` em `obter_usuario` e no INSERT/UPDATE de
   usuário.
2. Sessão: carregar `equipe` no login e auto-login.
3. `core/helpers.py`: `_equipe_atual()` + `_ve_tudo()`.
4. `views/equipe.py`: filtro + selectbox de equipe no cadastro/edição.
5. `views/dashboard.py`: filtrar cards/pizza por equipe.
6. `views/kanban.py`: filtrar painel de evolução (board/Gantt intactos).
7. `views/agenda.py`: filtrar eventos por equipe.
8. Rodar os 7 cenários do §8 em `./run-local.sh` com 3 logins distintos.
9. SQL de configuração dos gestores (§3) em produção após deploy.

---

## 10. Observações de segurança
- Filtragem é **no servidor (Python/SQL)**, nunca só escondendo no front.
- Cuidado com **caches** `@st.cache_data` por usuário: as queries
  `_load_df_*` em `core/data.py` podem precisar de chave por `equipe`
  pra não vazar dados entre escopos (validar/invalidar por usuário).
- Nomes em `projetista`/`responsaveis` são CSV — comparar por conjunto,
  com `strip()`, e tratar nome que aparece em mais de uma equipe (não
  deveria, mas validar unicidade de `nome` já garante 1 equipe por pessoa).
```
