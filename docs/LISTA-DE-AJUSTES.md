# Lista de Ajustes — Gestão de Projetos SERVPEN

Backlog da próxima rodada de ajustes, mapeado contra o código atual
(Streamlit + PostgreSQL). Cada item aponta para o arquivo:linha onde a
regra vive hoje. Consolidado em **18/06/2026** a partir da análise da lista
de demandas + complemento sobre a Agenda.

> **Como ler.** Os itens estão agrupados por natureza (permissões, schema,
> UI, feature nova). ⚠️ marca itens com **decisão pendente** (ver o fim do
> documento). Dependências entre itens estão listadas antes das decisões.

---

## Modelo de papéis (base pra entender o resto)

A lista usa termos ("gestor", "projetista", "usuário padrão", "gestor da
equipe", "gestor geral") que no código mapeiam para **dois eixos distintos**:

**Eixo 1 — perfil (o que pode editar)** — `core/helpers.py:48`
- **Gestor** e **Projetista** → `_pode_editar()` = pode criar/editar/excluir
- **Visualizador** → read-only
- `_pode_gestor()` = só Gestor

**Eixo 2 — equipe (o que pode ver)** — `core/helpers.py:62`
- **GERAL** → `_ve_tudo()` = vê tudo de todas as equipes (= "gestor geral")
- **SERVPEN / SERVPAR** → vê só a própria equipe (Gestor aqui = "gestor da equipe")

| Termo na lista | No sistema |
|---|---|
| gestor geral | perfil Gestor + equipe GERAL |
| gestor da equipe | perfil Gestor + equipe SERVPEN/SERVPAR |
| projetista / usuário padrão | perfil Projetista (ou Visualizador) |

---

## 🔐 Permissões (Gestor × Projetista) — ajuste de regras

### Item 1-topo — "Novo Projeto" só para gestores
- **Hoje:** liberado para `_pode_editar()` (Gestor **e** Projetista criam) em
  `views/novo_projeto.py:27`; link no menu para todos em `app.py:582`.
- **Fazer:** trocar o guard `_pode_editar()` → `_pode_gestor()` na view e
  esconder o item do menu para não-gestores.
- **✅ Resolvido (19/06):** guard em `views/novo_projeto.py` agora exige
  `_pode_gestor()`; item "Novo Projeto" só entra no menu pra Gestor (`app.py`).

### Item 1-lista — no Kanban todos só visualizam, exceto Evolução Técnica por Disciplina
- **Hoje:** no Kanban (`views/kanban.py`) o Projetista também edita (move
  status, edita o formulário completo) — tudo gated por `_pode_editar()`.
- **Fazer:** após o projeto entrar no quadro, não-gestores ficam **read-only**
  no board e no formulário, **exceto** a seção "Evolução Técnica por
  Disciplina" (`views/kanban.py:1346`), onde o projetista designado continua
  marcando progresso. Gestor mantém edição total. Casa com a visibilidade já
  existente em `views/kanban.py:1356-1367`.
- **✅ Resolvido (19/06):** form de edição fica read-only pra não-gestor
  (campos `disabled` + banner "Modo leitura", só botão Fechar); bulk actions e
  seleção da visão Lista também só pra Gestor. A Evolução Técnica (fora do
  form) segue editável pelo designado (`views/kanban.py`).

### Item 2 — "Abrir detalhes / editar" é o único botão para o projetista
- **Hoje:** no popover de cada card (`views/kanban.py:774`) existe "Abrir
  detalhes / editar" e, abaixo (gated por `_pode_editar()`), os botões de
  status (Mover, Pausar, Concluir, Cancelar...).
- **Fazer:** para projetista, só "Abrir detalhes / editar" aparece; botões de
  transição de status somem (ficam só para Gestor). Contraparte do item 1-lista.
- **✅ Resolvido (19/06):** os botões de status no popover agora estão sob
  `_pode_gestor()` (`views/kanban.py`) — projetista vê só "Abrir detalhes".

### Item 4 — "Etapas do Projeto" (edição, só gestor): % concluído + status
- **Atenção a uma confusão de seções:** o % de conclusão hoje só existe em
  "Evolução Técnica por Disciplina" (média dos sliders, `views/kanban.py:1477`).
  A seção "Etapas do Projeto" (`views/kanban.py:1163`) só tem o mini-Gantt
  (nome/duração/offset) — sem marcação de concluído nem status de prazo.
- **Fazer:** na seção de Etapas, visível só para Gestor, exibir um percentual
  concluído e um rótulo de situação (atraso / no prazo / adiantado / concluído).
- **✅ Resolvido/implementado (19/06):** **cruzar datas com progresso.** Cada
  etapa ganhou um campo **% concl.** (`etapas_projeto.percentual`) que o Gestor
  preenche (decisão final: % por etapa, não derivado da Evolução). A
  **situação** compara esse % real com o **% esperado** pela data (janela =
  data de início do projeto + offset, por `duracao_dias`): 100% → **Concluída**;
  data não chegou → **A iniciar**; passou do fim sem 100% → **Atrasada**; senão
  real vs esperado (±10 pts) → **Adiantada / No prazo / Atrasada**. A edição das
  etapas passou a ser **só Gestor** (`views/kanban.py`, `database.py`).

### Item 9 ⚠️ — "Envolvidos" e "Equipe Responsável": gestores veem todas as equipes
- **Hoje:** tanto em Agenda (`views/agenda.py:715`) quanto em Novo Projeto
  (`views/novo_projeto.py:76`), a regra é: GERAL vê todos, qualquer outro vê só
  a própria equipe — sem distinguir Gestor de membro.
- **Fazer (intenção original):** todo Gestor (inclusive de equipe) deve ver
  todos de todas as equipes em "Envolvidos" e "Equipe Responsável"; o membro
  comum continua restrito à própria equipe. A condição muda de "é GERAL?" para
  "é Gestor? (ou GERAL)".
- **✅ Resolvido pelo complemento:** a *seleção* de "Envolvidos" / "Equipe
  Responsável" fica liberada para **todos** (qualquer um marca qualquer um),
  tanto na **Agenda** quanto no **Novo Projeto**. A condição "é GERAL? / é da
  minha equipe?" no seletor cai. A *visibilidade* continua controlada à parte
  (ver complemento da Agenda).
- **✅ Implementado (19/06):** seletores agora listam todos — `equipe_lista`
  em `views/agenda.py` e `_opcoes_eq` em `views/novo_projeto.py`.

### Item 13 (extra, fora do PDF) — Dashboard: Evolução Técnica por perfil/equipe
- **Demanda (18/06):** nos gráficos de **Evolução Técnica** do Dashboard,
  "gestores veem tudo, projetista só vê os seus".
- **Hoje:** a seção "Evolução Técnica por Projeto" (`views/dashboard.py:449`)
  carregava `progresso_disciplinas` de TODOS os projetos, sem filtro por
  perfil/equipe.
- **✅ Resolvido/implementado (18/06):** filtra `df_evolucao` na fonte, mesmo
  critério da Evolução no Kanban — **Gestor Geral vê tudo; gestor de equipe vê
  a sua equipe; projetista/visualizador vê só os projetos em que está
  designado**. Propaga pra heatmap, barras, tabela e multiselect.

---

## 🗄️ Mudança de schema (coluna/tabela nova)

### Item 3 — campo Código/Número do Projeto (string, único) no início do cadastro
- **Hoje:** a tabela `projetos` (`database.py:593`) tem `numero_sei`, mas não
  existe campo `codigo`.
- **Fazer:** criar coluna `codigo TEXT` com constraint `UNIQUE`, posicionar o
  campo no topo do form de Novo Projeto (e de edição), validando duplicidade
  antes de salvar. É a base do item 11.
- **✅ Resolvido (18/06):** **opcional** — pode ficar vazio; quando preenchido,
  precisa ser único (vários nulos são OK no Postgres). Projetos antigos ficam
  sem código até alguém editar (sem backfill).

### Item 10 — Novo Projeto: campo "Local" abaixo de "Endereço da Obra"
- **Hoje:** o form tem "Endereço da Obra" (`views/novo_projeto.py:70`); a
  tabela `projetos` não tem coluna `local` (a tabela `agenda` tem).
- **Fazer:** adicionar campo "Local" logo abaixo do endereço, com coluna no
  banco e refletido no form de edição. Conecta com o item 12.
- **✅ Resolvido (18/06):** "Local" é **complemento do endereço** — texto livre
  (bloco / andar / sala / referência). Não sai do cadastro de endereços.

### Item 12 — cadastro mestre de endereços para usar no cadastro de projetos
- **Fazer:** criar um cadastro mestre de endereços (tabela própria + tela de
  gerência, no estilo do que já existe para Disciplinas — `database.py:771` e o
  expander de `views/novo_projeto.py:41`), para que no cadastro de projeto o
  usuário selecione um endereço de uma lista em vez de digitar texto livre.
  Complemento estrutural dos itens 10 e 3; padroniza os dados.
- **✅ Resolvido (18/06):** o "Endereço da Obra" vira **select + digitar novo** —
  escolhe da lista; se digitar um endereço inédito, ele entra no cadastro. Sem
  migração obrigatória dos antigos (entram conforme forem usados/reeditados).
  Cadastro **gerenciado só por Gestor** (igual Disciplinas).

---

## 🎛️ Ajustes pontuais de UI

### Item 5 — Diário: remover "Envolver outras pessoas na interação"
- **Hoje:** no editor de resposta do diário há duas coisas redundantes — o
  multiselect "Envolver outras pessoas na interação (Opcional)"
  (`views/diario.py:203`) e o popover "@ Mencionar inline" (`views/diario.py:218`).
  O multiselect só escreve um rodapé "(Ref: @X)" e **não** dispara o fluxo de
  menção (acesso + notificação); o @mencionar dispara.
- **Fazer:** remover o multiselect e manter só o "@ Mencionar", que é o
  mecanismo real.
- **✅ Resolvido (19/06):** multiselect removido (`views/diario.py`); o rodapé
  "(Ref: @X)" sai junto. "@ Mencionar inline" segue como único mecanismo.

### Item 7 — Agenda: calendário e listagem com a mesma visibilidade
- **Hoje:** o calendário já respeita a regra via `_agenda_mask` / `_nomes_agenda`
  (`views/agenda.py:116-136`). Mas a tabela de baixo é inconsistente: em
  `views/agenda.py:843` o filtro é só `if perfil_atual != "Gestor"`, então
  qualquer Gestor (mesmo de equipe) vê TUDO na listagem, divergindo do
  calendário (que limita à equipe).
- **Fazer:** alinhar a listagem de baixo à mesma regra do calendário — usuário
  padrão vê só os seus, gestor de equipe só da equipe, gestor geral vê tudo
  (fazer a tabela usar `_agenda_mask`). **Reforçado pelo complemento da Agenda**
  — e a máscara passa a incluir também os compromissos em que o usuário está
  **marcado como envolvido** (ver complemento).
- **✅ Resolvido (19/06):** a listagem de baixo passou a usar `_agenda_mask` (a
  mesma regra do calendário) no lugar de "qualquer Gestor vê tudo"
  (`views/agenda.py`). Gestor de equipe agora vê só a sua equipe na listagem.

### Item 8 — Agenda > Novo Compromisso: adicionar "Outros" na Categoria
- **Hoje:** lista fixa em `views/agenda.py:729`:
  `["Visita Técnica", "Reunião", "Férias", "Licença", "Folga"]`.
- **Fazer:** acrescentar "Outros". Lembrar de dar cor/ícone ao novo tipo nos
  mapas `TIPO_COR` / `TIPO_ICONE` (`views/agenda.py:233`), senão cai no cinza default.
- **✅ Resolvido (19/06):** "Outros" adicionado às categorias + cor (`#0d9488`)
  e ícone (📌) em `TIPO_COR`/`TIPO_ICONE` (`views/agenda.py`).

### Item 11 — Kanban (visão Lista): filtrar por SEI/Código e exibir as colunas
- **Hoje:** a visão Lista (`views/kanban.py:65`) mostra Status, Projeto,
  Projetista, Prazo, Prioridade, Tags — sem SEI nem Código. A busca
  (`views/kanban.py:493`) cobre só projeto/projetista/solicitante.
- **Fazer:** incluir colunas **SEI** e **Código** na tabela e estender a busca
  para casar por esses campos. **Depende do item 3** (Código precisa existir;
  SEI já existe como `numero_sei`).
- **✅ Resolvido/implementado (19/06):** colunas **Código** e **SEI** na tabela
  da visão Lista (logo após "Projeto") e busca estendida pra casar também por
  `codigo` e `numero_sei` (`views/kanban.py`).

---

## 🚀 Feature nova (esforço maior)

### Item 6 — Chat: enviar para "todos" (grupos) + emoji
- **Descompasso com a arquitetura atual:** o Chat (`views/chat.py`) é 1-para-1
  (DM estilo WhatsApp) — não tem grupos, menções nem emoji picker.
- **✅ Fazer (resolvido 18/06):** **grupos de verdade** (não broadcast). Criar
  3 grupos padrão automáticos — **TODOS** (todo mundo), **SERVPEN** e
  **SERVPAR** (membros derivados da equipe) — além das DMs 1-a-1 já existentes.
  Mais um **seletor de emoji** no campo de mensagem.
- **Item de maior esforço da lista** — não é ajuste, é capacidade nova:
  conversas com mais de 2 participantes (mensagens endereçadas a um grupo,
  marcação de leitura por grupo, etc.).
- **✅ Resolvido/implementado (19/06):** 3 grupos padrão por sentinela em
  `chat.destinatario` (`@grupo:TODOS|SERVPEN|SERVPAR`), visíveis **por equipe**;
  não-lidas via tabela `chat_grupo_visto`; toast estendido pra grupos
  (`core/notif.py`); emoji picker em popover (30 emojis, sem dependência).
  Detalhe em [docs/CHAT-GRUPOS-SPEC.md](CHAT-GRUPOS-SPEC.md).

---

## 📌 Complemento — Agenda de marcadores

> Instrução do usuário (18/06/2026): *"na Agenda de marcadores, pode deixar
> todos marcarem todos, mas a visualização deve ser por equipe."*

Isto **refina os itens 7 e 9** na Agenda:

- **Marcar (seleção de "Envolvidos") → liberado para todos.** Diferente do que
  o item 9 propunha (só Gestor vê todas as equipes), na Agenda **qualquer**
  usuário pode marcar **qualquer** pessoa, de qualquer equipe. Some a restrição
  "membro só vê a própria equipe" no seletor de envolvidos da Agenda
  (`views/agenda.py:715`).
- **Visualizar (calendário + listagem) → continua por equipe.** Mantém o item 7
  firme: usuário padrão vê os seus, gestor de equipe vê a equipe, gestor geral
  vê tudo. A listagem (`views/agenda.py:843`) passa a usar `_agenda_mask` igual
  ao calendário.

**✅ Resolvido (18/06/2026):**
- **Escopo:** "todos marcam todos" vale **na Agenda E no Novo Projeto**
  ("Envolvidos" e "Equipe Responsável").
- **Ser marcado dá visibilidade:** se você é marcado num compromisso, passa a
  vê-lo **mesmo sendo de outra equipe**. Regra final da Agenda: **gestor geral
  vê tudo; os demais veem os da sua equipe + aqueles em que estão marcados.**

---

## Visão geral / agrupamento

| Tema | Itens | Natureza |
|---|---|---|
| Permissões (Gestor × Projetista) | 1-topo, 1-lista, 2, 4, 9, 13 | Ajuste de regras (`_pode_gestor`/`_pode_editar`/escopo de equipe) |
| Mudança de schema | 3 (codigo), 10 (local), 12 (endereços) | Banco + UI |
| Ajustes pontuais de UI | 5, 7, 8, 11 | Pequenos, localizados |
| Feature nova (esforço maior) | 6 (chat: grupos + emoji) | Repensar o chat 1-a-1 |

## Dependências entre itens
- **3 → 11** — Código precisa existir antes da coluna/filtro na Lista.
- **10 → 12** — campo Local junto do cadastro mestre de endereços.

## Decisões (resolvidas em 18/06/2026)
1. **Item 6 (chat):** **grupos de verdade**. 3 grupos padrão automáticos —
   **TODOS**, **SERVPEN**, **SERVPAR** (membros por equipe) — além das DMs
   1-a-1. + emoji picker no campo de mensagem.
2. **Item 4 (etapas):** **cruzar datas com progresso** — % real = campo
   **% concl.** por etapa (Gestor preenche) vs % esperado (janela da etapa) →
   atraso / no prazo / adiantado / concluída. Edição das etapas só Gestor.
3. **Complemento da Agenda — escopo:** "todos marcam todos" vale **na Agenda E
   no Novo Projeto** ("Envolvidos" e "Equipe Responsável"). A restrição por
   equipe na *seleção* cai nos dois.
4. **Complemento da Agenda — efeito:** **ser marcado dá visibilidade.** Se A
   marca B, B passa a ver o compromisso, mesmo de outra equipe. Visão final da
   Agenda: **gestor geral vê tudo; os demais veem os da sua equipe + aqueles em
   que estão marcados.**
5. **Item 3 (Código):** **opcional** — único quando preenchido; antigos sem
   código, sem backfill.
6. **Item 10 (Local):** **complemento** do endereço (texto livre: bloco / andar /
   sala). Não vem do cadastro.
7. **Item 12 (cadastro de endereços):** "Endereço da Obra" vira **select +
   digitar novo**; gerenciado só por Gestor. Sem migração obrigatória dos antigos.
8. **Cross-cutting:** colunas novas entram no **histórico**; migrations **rodam
   no deploy** (`deploy-238.sh`); cadastro de endereços só Gestor.

## Pontos em aberto (restantes)

**Nada pendente — todos os itens (1–13 + complemento da Agenda) foram
implementados e verificados (headless via AppTest + smoke-test no Postgres).** 🎉

## Notas do check no código (18/06/2026)

- **Agenda não tem "Envolvidos" separado:** o evento tem o campo
  **`responsaveis`** e o `_agenda_mask` (`views/agenda.py:124`) já filtra por
  ele. Logo "se te marco, você vê" já é o comportamento atual (usuário padrão só
  vê eventos em que é responsável). "Marcar" = adicionar em `responsaveis`;
  falta só **abrir o seletor pra todos** e fazer a **listagem** usar a máscara
  (item 7).
- **Item 1-lista já tem a visibilidade da Evolução:** `views/kanban.py:1356-1367`
  já libera a Evolução Técnica só pra quem está **designado** no projeto — o
  "read-only menos a Evolução" encaixa nessa regra.

## Sugestão de ordem de ataque
1. Schema primeiro: **3 → 10 → 12** (destrava o 11 e padroniza dados).
2. Permissões: **1-topo, 1-lista, 2, 9** + complemento da Agenda.
3. UI pontual: **5, 7, 8, 11**.
4. **Item 4** (cruzar datas × Evolução Técnica; resolver o "% por etapa" no build).
5. **Item 6** (chat) por último — maior esforço; precisa do mini-spec.
