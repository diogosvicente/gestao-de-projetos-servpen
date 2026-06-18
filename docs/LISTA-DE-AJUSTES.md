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

### Item 1-lista — no Kanban todos só visualizam, exceto Evolução Técnica por Disciplina
- **Hoje:** no Kanban (`views/kanban.py`) o Projetista também edita (move
  status, edita o formulário completo) — tudo gated por `_pode_editar()`.
- **Fazer:** após o projeto entrar no quadro, não-gestores ficam **read-only**
  no board e no formulário, **exceto** a seção "Evolução Técnica por
  Disciplina" (`views/kanban.py:1346`), onde o projetista designado continua
  marcando progresso. Gestor mantém edição total. Casa com a visibilidade já
  existente em `views/kanban.py:1356-1367`.

### Item 2 — "Abrir detalhes / editar" é o único botão para o projetista
- **Hoje:** no popover de cada card (`views/kanban.py:774`) existe "Abrir
  detalhes / editar" e, abaixo (gated por `_pode_editar()`), os botões de
  status (Mover, Pausar, Concluir, Cancelar...).
- **Fazer:** para projetista, só "Abrir detalhes / editar" aparece; botões de
  transição de status somem (ficam só para Gestor). Contraparte do item 1-lista.

### Item 4 ⚠️ — "Etapas do Projeto" (edição, só gestor): % concluído + status
- **Atenção a uma confusão de seções:** o % de conclusão hoje só existe em
  "Evolução Técnica por Disciplina" (média dos sliders, `views/kanban.py:1477`).
  A seção "Etapas do Projeto" (`views/kanban.py:1163`) só tem o mini-Gantt
  (nome/duração/offset) — sem marcação de concluído nem status de prazo.
- **Fazer:** na seção de Etapas, visível só para Gestor, exibir um percentual
  concluído e um rótulo de situação (atraso / no prazo / adiantado / concluído).
- **Decisão pendente:** fonte do %/status — ver decisões no fim.

### Item 9 ⚠️ — "Envolvidos" e "Equipe Responsável": gestores veem todas as equipes
- **Hoje:** tanto em Agenda (`views/agenda.py:715`) quanto em Novo Projeto
  (`views/novo_projeto.py:76`), a regra é: GERAL vê todos, qualquer outro vê só
  a própria equipe — sem distinguir Gestor de membro.
- **Fazer (intenção original):** todo Gestor (inclusive de equipe) deve ver
  todos de todas as equipes em "Envolvidos" e "Equipe Responsável"; o membro
  comum continua restrito à própria equipe. A condição muda de "é GERAL?" para
  "é Gestor? (ou GERAL)".
- **⚠️ Sobrescrito em parte pelo complemento da Agenda** — ver seção própria
  abaixo (na Agenda, **todos** marcam todos).

---

## 🗄️ Mudança de schema (coluna/tabela nova)

### Item 3 — campo Código/Número do Projeto (string, único) no início do cadastro
- **Hoje:** a tabela `projetos` (`database.py:593`) tem `numero_sei`, mas não
  existe campo `codigo`.
- **Fazer:** criar coluna `codigo TEXT` com constraint `UNIQUE`, posicionar o
  campo no topo do form de Novo Projeto (e de edição), validando duplicidade
  antes de salvar. É a base do item 11.

### Item 10 — Novo Projeto: campo "Local" abaixo de "Endereço da Obra"
- **Hoje:** o form tem "Endereço da Obra" (`views/novo_projeto.py:70`); a
  tabela `projetos` não tem coluna `local` (a tabela `agenda` tem).
- **Fazer:** adicionar campo "Local" logo abaixo do endereço, com coluna no
  banco e refletido no form de edição. Conecta com o item 12.

### Item 12 — cadastro mestre de endereços para usar no cadastro de projetos
- **Fazer:** criar um cadastro mestre de endereços (tabela própria + tela de
  gerência, no estilo do que já existe para Disciplinas — `database.py:771` e o
  expander de `views/novo_projeto.py:41`), para que no cadastro de projeto o
  usuário selecione um endereço de uma lista em vez de digitar texto livre.
  Complemento estrutural dos itens 10 e 3; padroniza os dados.

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

### Item 7 — Agenda: calendário e listagem com a mesma visibilidade
- **Hoje:** o calendário já respeita a regra via `_agenda_mask` / `_nomes_agenda`
  (`views/agenda.py:116-136`). Mas a tabela de baixo é inconsistente: em
  `views/agenda.py:843` o filtro é só `if perfil_atual != "Gestor"`, então
  qualquer Gestor (mesmo de equipe) vê TUDO na listagem, divergindo do
  calendário (que limita à equipe).
- **Fazer:** alinhar a listagem de baixo à mesma regra do calendário — usuário
  padrão vê só os seus, gestor de equipe só da equipe, gestor geral vê tudo
  (fazer a tabela usar `_agenda_mask`). **Reforçado pelo complemento da Agenda.**

### Item 8 — Agenda > Novo Compromisso: adicionar "Outros" na Categoria
- **Hoje:** lista fixa em `views/agenda.py:729`:
  `["Visita Técnica", "Reunião", "Férias", "Licença", "Folga"]`.
- **Fazer:** acrescentar "Outros". Lembrar de dar cor/ícone ao novo tipo nos
  mapas `TIPO_COR` / `TIPO_ICONE` (`views/agenda.py:233`), senão cai no cinza default.

### Item 11 — Kanban (visão Lista): filtrar por SEI/Código e exibir as colunas
- **Hoje:** a visão Lista (`views/kanban.py:65`) mostra Status, Projeto,
  Projetista, Prazo, Prioridade, Tags — sem SEI nem Código. A busca
  (`views/kanban.py:493`) cobre só projeto/projetista/solicitante.
- **Fazer:** incluir colunas **SEI** e **Código** na tabela e estender a busca
  para casar por esses campos. **Depende do item 3** (Código precisa existir;
  SEI já existe como `numero_sei`).

---

## 🚀 Feature nova (esforço maior)

### Item 6 ⚠️ — Chat: "select all" para mencionar todos + emoji
- **Descompasso com a arquitetura atual:** o Chat (`views/chat.py`) é 1-para-1
  (DM estilo WhatsApp) — não tem grupos, menções nem emoji picker.
- **Fazer (duas features novas):** (a) forma de enviar/mencionar "todos" de uma
  vez e (b) um seletor de emoji no campo de mensagem.
- **Item de maior esforço da lista** — não é ajuste, é capacidade nova.
- **Decisão pendente:** broadcast vs. grupo de verdade — ver decisões no fim.

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

**Em aberto (ver decisões):** o escopo do "todos marcam todos" (só Agenda ou
também o "Equipe Responsável" do Novo Projeto) e se ser marcado por alguém de
outra equipe faz o compromisso aparecer pra essa pessoa.

---

## Visão geral / agrupamento

| Tema | Itens | Natureza |
|---|---|---|
| Permissões (Gestor × Projetista) | 1-topo, 1-lista, 2, 4, 9 | Ajuste de regras (`_pode_gestor`/`_pode_editar`/escopo de equipe) |
| Mudança de schema | 3 (codigo), 10 (local), 12 (endereços) | Banco + UI |
| Ajustes pontuais de UI | 5, 7, 8, 11 | Pequenos, localizados |
| Feature nova (esforço maior) | 6 (chat: mencionar todos + emoji) | Repensar o chat 1-a-1 |

## Dependências entre itens
- **3 → 11** — Código precisa existir antes da coluna/filtro na Lista.
- **10 → 12** — campo Local junto do cadastro mestre de endereços.

## Decisões pendentes (antes de implementar)
1. **Item 6 (chat):** broadcast (mensagem para todos de uma vez) ou **grupo de
   verdade** (conversa em grupo com "selecionar todos")?
2. **Item 4 (etapas):** o %/status vem **(a)** das datas (offset/duração vs.
   hoje), **(b)** de uma marcação de "concluído" por etapa, ou **(c)** dos dois?
3. **Complemento da Agenda — escopo:** o "todos marcam todos" vale **só na
   Agenda**, ou também no "Equipe Responsável" do Novo Projeto (item 9)?
4. **Complemento da Agenda — efeito colateral:** se A (Servpen) marca B
   (Servpar) num compromisso, **B passa a ver esse compromisso** (visão por
   envolvimento) ou não vê (visão estritamente por equipe)?

## Sugestão de ordem de ataque
1. Schema primeiro: **3 → 10 → 12** (destrava o 11 e padroniza dados).
2. Permissões: **1-topo, 1-lista, 2, 9** + complemento da Agenda.
3. UI pontual: **5, 7, 8, 11**.
4. **Item 4** (depois de decidir a fonte do %/status).
5. **Item 6** (chat) por último — maior esforço e exige decisão de arquitetura.
