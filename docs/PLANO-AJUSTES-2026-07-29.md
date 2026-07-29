# Plano de Ajustes — 29/07/2026 — Agenda, Novo Projeto, Tarefas, Arquivos

Levantamento a partir de 5 prints de tela reais do sistema em produção (Agenda,
Novo Projeto, Tarefas ×2, Arquivos), com anotações da Sara sobre o que
mudar em cada tela.

> **✅ Executado em 29/07/2026.** Todos os 9 itens foram implementados. As
> decisões pendentes foram fechadas assim: Tarefas em **cards agrupados por
> data + contadores no topo**; "Documentações Geradas" como **campo de texto**
> no cadastro; presença exibida **na sidebar e no Chat**; pastas com
> **criação/exclusão só do Gestor**, aninhamento ilimitado e exclusão de pasta
> não-vazia bloqueada. Cada item abaixo tem uma linha **✅** com o que mudou de
> fato. Verificado com `py_compile`, 40 testes de round-trip no Postgres,
> testes de comportamento das telas novas (AppTest, como Gestor **e** como
> Projetista) e o `tests/smoke_tests.py` completo.

> **Como ler.** Cada item começa com a citação literal do pedido da Sara,
> depois **Hoje** (o que o código faz agora, com `arquivo:linha`) e
> **Proposta** (o que mudaria). ⚠️ marca ponto que **não dá pra decidir só
> pelo código** — precisa de confirmação da Sara antes de qualquer linha ser
> escrita. Todos os ⚠️ do documento estão consolidados em
> [Decisões pendentes (resumo)](#decisões-pendentes-resumo) no final, numerados
> pra responder rápido ("sim", "não", "opção B" etc.).

---

## 📅 Agenda

### Item 1 — Clicar em cima do dia abre as atividades daquele dia

> *"Na agenda, eu gostaria de clicar em cima e ela abrir as atividades
> daquele dia."*

**Hoje:** o "Calendário do Mês" inteiro é montado como uma **string HTML
estática** (`html_cal`) e renderizado via `st.markdown(html_cal,
unsafe_allow_html=True)` em `views/agenda.py:379`. A grade é gerada em
`views/agenda.py:284-378`; cada evento vira um `<span class="ev-pill"
title="...">` (`views/agenda.py:361-366`) — isso é só tooltip on-hover do
navegador, não um clique. Não existe `<a href>`, `onclick`, `st.button` nem
qualquer componente interativo dentro das células `<td>`; Streamlit não
despacha clique em HTML injetado com `unsafe_allow_html=True`. Os únicos
elementos clicáveis na visão Mensal são os botões `◀ Anterior` /
`Próximo ▶` (`views/agenda.py:258-271`), que só trocam mês/ano.

Já existem, no mesmo arquivo, três lugares com o padrão "selecionar → abrir"
funcionando (podem servir de modelo técnico):
- Visão Semanal: `st.selectbox` de eventos da semana + botão `📝 Abrir`
  (`views/agenda.py:527-550`) que seta `st.session_state["agenda_edit_id"]`
  e chama `st.rerun()`.
- Visão Resumo: botão `🔍` por linha em "Próximos compromissos"
  (`views/agenda.py:641-645`), mesmo padrão.
- "Compromissos Cadastrados": botão `✏️ Editar` por linha
  (`views/agenda.py:1003-1006`), mesmo padrão.
- Helper reutilizável de pill/segmented-control, `_pill_select`
  (`core/helpers.py:223-244`), já usado no toggle Mensal/Semanal/Lista/Resumo
  (`views/agenda.py:200-206`).

**Proposta:** trocar as células do dia, na grade Mensal, por widgets reais
(um `st.button` por dia, grade 7 colunas × N linhas — mesmo espírito dos
botões de navegação de mês já existentes). Clicar grava o dia escolhido em
`session_state` e dispara `st.rerun()`. Isso precisa de duas peças que **não
existem hoje em nenhuma view da Agenda**: (a) o próprio mecanismo de captura
de clique no dia, e (b) um filtro por **dia exato** na seção "Compromissos
Cadastrados" (hoje ela só filtra por categoria, membro e "só futuros" — ver
Item 2 — nunca por uma data específica).

⚠️ **decisão pendente:** onde o resultado do clique deve aparecer —
(A) expandir a própria seção "Compromissos Cadastrados" já filtrada pro dia
escolhido, (B) abrir um expander/painel dedicado só com os eventos daquele
dia, ou (C) pular direto para a visão "Lista"/"Resumo" filtrada pro dia?

**✅ Resolvido (29/07/2026) — opção (B).** A grade `<table>` HTML virou grade
nativa (`st.columns` + um `st.button` por dia), que é a única forma de o
Streamlit receber o clique; as pills coloridas continuam sendo HTML dentro de
cada célula. Dia de hoje e dia selecionado ficam destacados (`type="primary"`),
e o `help` de cada dia já mostra quantos compromissos tem. Clicar abre um
painel logo abaixo do calendário com os eventos daquele dia (tipo, título,
envolvidos, local) e um 🔍 por linha que abre no formulário — mesmo padrão das
visões Semanal/Resumo. Clicar de novo no mesmo dia fecha o painel
(`views/agenda.py`).

---

### Item 2 — Eventos vencidos somem da lista e só voltam se pesquisar

> *"Eventos vencidos somem da lista de compromissos cadastrados e só
> aparecem se eu pesquisar."*

**Hoje:** a query base não tem corte de data —
`SELECT * FROM agenda ORDER BY data_inicio ASC` (`views/agenda.py:100-104`)
traz todo o histórico. Na seção "📋 Compromissos Cadastrados"
(`views/agenda.py:861-862`), os filtros são categoria, membro e o checkbox
**"Só futuros"** (`views/agenda.py:864-874`), com `value=False` por padrão
(`views/agenda.py:874`) — ou seja, por design a tabela deveria mostrar tudo
(passado e futuro) ao abrir a página, só cortando o passado quando esse
checkbox específico está marcado (`views/agenda.py:895-898`). Não há nenhum
outro trecho do repositório que force esse checkbox pra `True` — as únicas
ocorrências de `ag_ffut`/`filtro_futuro` são a própria definição do widget e
seu uso no filtro (`views/agenda.py:871,873,874,895`).

A busca por membro (`filtro_membro`, `views/agenda.py:889-894`) é aplicada
com **AND** sobre o resultado que já sofreu (ou não) o corte de "Só
futuros" — ela nunca reseta ou ignora esse filtro. Ou seja, tecnicamente,
digitar um nome na busca não traz de volta um vencido escondido pelo "Só
futuros".

Duas explicações plausíveis pro que a Sara está vendo — nenhuma 100%
confirmável só pelo código:
- **(a) Statefulness do checkbox:** como `ag_ffut` tem `key` fixa, uma vez
  marcado (mesmo sem querer, inclusive em sessão anterior) o valor `True`
  fica grudado em `session_state` pra toda a sessão do navegador (trocar de
  aba via `st.navigation` não reseta `session_state`) — os vencidos somem
  silenciosamente até alguém desmarcar esse checkbox pequeno.
- **(b) Ela pode estar vendo a visão "Resumo", não "Compromissos
  Cadastrados":** a subseção "📌 Próximos compromissos"
  (`views/agenda.py:582-599`) filtra **incondicionalmente** por data, sem
  checkbox e **sem busca nenhuma** (`views/agenda.py:592-597`) — ali os
  vencidos somem de forma permanente e não há como pesquisá-los de volta.

**Proposta:** ⚠️ **decisão pendente** — antes de mexer em código, confirmar
com a Sara (print/tela exata) qual das duas situações é essa. Se for (a), o
ajuste é simples: revisar o default/persistência desse checkbox (ex.: não
manter marcado entre sessões, ou deixar mais visível/óbvio que ele está
ligado). Se for (b), o ajuste é outro: dar à visão "Resumo" uma forma de
enxergar vencidos (ex.: um link "ver atrasados" ou incluir uma janela de
atraso recente por padrão), já que hoje ali não existe filtro nem busca.

**✅ Resolvido (29/07/2026) — as DUAS causas foram corrigidas**, já que não dava
pra saber qual era sem a tela exata e ambas produzem o mesmo sintoma:
- **(a)** O checkbox "Só futuros" ganhou `help` explicando que fica marcado até
  ser desmarcado; e quando ele está escondendo algo, aparece um aviso
  "⏳ N compromisso(s) já vencido(s) estão ocultos" com um botão
  **👁️ Mostrar vencidos** que desliga o filtro num clique.
- **(b)** A visão "Resumo" ganhou um expander **⏰ Já vencidos (N)** logo abaixo
  dos próximos, com os 20 mais recentes, há quantos dias venceram e o 🔍 pra
  abrir — antes eles sumiam sem nenhuma forma de recuperar (`views/agenda.py`).

---

### Item 3 — Sidebar/Chat mostrando quem está logado agora

> *"Gostaria que na barra lateral aparecesse para mim todas as pessoas que
> estão logadas no programa ou então na própria aba chat."*

**Hoje:** **não existe nenhum conceito de "usuário online" no sistema.** A
tabela `sessoes` (`database.py:830-834`) só tem `token`, `usuario`,
`expires_at` — sem coluna de última atividade/heartbeat. `expires_at` é
fixado no login (`time.time() + 7 dias`, `database.py:527-534`,
`criar_sessao`) e nunca é renovado a cada requisição, então nem serve como
proxy de atividade recente: uma sessão "válida" pode ser de alguém que fez
login há 6 dias e não abre o sistema desde então — indistinguível de quem
está com o app aberto agora. Não existe em lugar nenhum do repositório uma
query tipo `SELECT DISTINCT usuario FROM sessoes WHERE expires_at > agora`.
`core/sessao.py` (108 linhas) só lê/grava o cookie de sessão no navegador —
zero lógica de presença. Em `app.py`, o único mecanismo "em tempo real" é o
fragmento `_global_notif` (`core/notif.py:256-299`,
`@st.fragment(run_every="10s")`), que só faz poll de contagem de não-lidas
(chat/menções) pra disparar toast — não lista quem está online. Em
`views/chat.py`, o fragmento `_render_chat_messages`
(`core/chat_utils.py:76-77`, `run_every="2s"`) faz poll de mensagens, também
não de presença.

**Proposta — isto é feature nova do zero**, não um ajuste incremental. Duas
abordagens técnicas leves, reaproveitando o que já existe:

- **Abordagem 1 (recomendada):** somar uma coluna `ultima_atividade
  TIMESTAMP` à tabela `sessoes`, atualizada a cada rerun de página (um hook
  central, ex. em `app.py`, que faz um `UPDATE sessoes SET
  ultima_atividade = now() WHERE token = ...`). "Online" = sessão válida
  (`expires_at > agora`) **e** `ultima_atividade` dentro de uma janela de N
  minutos. Exibição via fragmento com `run_every` (mesmo padrão já usado em
  `core/notif.py:256` e `core/chat_utils.py:76-77`), atualizando a lista sem
  refresh manual.
- **Abordagem 2 (mais grosseira, menor esforço):** sem nova coluna, listar
  como "logados" todo mundo com `expires_at > agora` — mais simples de
  implementar, mas mistura "com o app aberto agora" com "fez login há
  dias e nunca deslogou", o que provavelmente não é o que ela quer ver.

⚠️ **decisão pendente:** (i) onde exibir — barra lateral do app inteiro, só
dentro da aba Chat, ou os dois? (ii) qual janela de inatividade conta como
"online" (sugestão: 5 minutos sem interação)? (iii) topa a Abordagem 1 (mais
precisa, exige nova coluna) ou prefere a 2 (mais rápida, menos precisa)?

**✅ Resolvido (29/07/2026) — Abordagem 1, janela de 5 min, nos dois lugares.**
- Coluna `sessoes.ultima_atividade BIGINT` (migração) + `db.tocar_sessao()`
  chamado no boot do `app.py` com **throttle de 60s** — sem o throttle seria um
  UPDATE por rerun do Streamlit, o que encheria o banco de escrita à toa.
- `db.usuarios_online()` só conta sessão não expirada **e** com heartbeat dentro
  de `db.JANELA_ONLINE_MIN` (5 min); ambas as funções são best-effort (presença
  nunca derruba o app se o banco engasgar).
- **Sidebar:** bloco "🟢 Online agora (N)" num `@st.fragment(run_every="30s")`,
  que se atualiza sozinho sem recarregar a página.
- **Chat:** 🟢 do lado do nome no seletor de contato, status "● online agora /
  ● offline" abaixo do cabeçalho da conversa, e quem está online sobe na
  ordenação da lista (`app.py`, `views/chat.py`, `database.py`).

---

## 🗂️ Novo Projeto

### Item 4 — Campo "Checklist Adicional / Demandas": vestigial ou em uso?

> *"Verificar a função de campos. Acho que ele ficou a mais da estrutura
> anterior, depois eu tinha mudado e retirei."* (campo circulado no print:
> Checklist Adicional / Demandas)

**Hoje — veredito da investigação: o campo está ATIVO, não é vestigial.**
Não existe como coluna própria — o textarea "Checklist Adicional /
Demandas" (`views/novo_projeto.py:143-144`) é concatenado com as disciplinas
selecionadas num único texto (`" | "` como delimitador manual,
`views/novo_projeto.py:254-256`) e gravado na coluna `demandas TEXT`
(`database.py:608`). Esse valor é lido/escrito em pelo menos 5 frentes
reais:
- formulário de edição do Kanban, que espelha o mesmo campo e a mesma lógica
  de concatenação (`views/kanban.py:1152-1177,1225-1228`);
- clonagem de projeto — `demandas` está explicitamente na lista do que é
  copiado (`database.py:1232-1286`, doc em `database.py:1237`);
- histórico de alterações/auditoria do projeto (`views/kanban.py:1263-1264`);
- "Evolução Técnica por Disciplina" **depende dele** para saber quais
  disciplinas rastrear (`views/kanban.py:1668-1672`) — se o campo sumisse,
  essa feature perderia a fonte de disciplinas;
- exports Excel (`relatorios.py:257`) e PDF (`relatorios.py:607-611`).

(Descartado um falso positivo: `views/dashboard.py:829-842` tem uma
variável também chamada `demandas`, mas é só a lista de nomes de projetos de
um colaborador — sem relação com a coluna do banco.)

**Proposta:** manter o campo — está ativo, com dependências reais, e
removê-lo quebraria a Evolução Técnica por Disciplina, o histórico e os
exports.

⚠️ **decisão pendente:** como a investigação não achou nenhum sinal de
sobra/dead code neste campo específico, é provável que a lembrança da Sara
seja sobre **outro** campo ou formulário (ex.: algo do multiselect de
disciplinas em si, ou um campo de outra tela). Confirmar com ela o que
exatamente lembra de ter retirado antes de mexer neste campo — se for
confirmado que é este mesmo, a alternativa não seria remover, e sim um
refactor maior (separar disciplinas e texto livre em duas colunas reais em
vez do delimitador `"|"` manual), o que é um projeto à parte, não um
"remover".

**✅ Resolvido (29/07/2026) — campo MANTIDO, nada foi removido.** A investigação
mostrou 5 dependências reais (form do Kanban, clonagem, histórico de
alterações, Evolução Técnica por Disciplina e os exports Excel/PDF); remover
quebraria a Evolução Técnica, que tira dele a lista de disciplinas do projeto.
**Continua em aberto para a Sara:** se a lembrança dela for mesmo deste campo,
o caminho não é excluir e sim separar "disciplinas" e "texto livre" em duas
colunas de verdade — refactor à parte, fora do escopo desta rodada.

---

### Item 5 — Novos campos: Fonte de Recurso, Observações, Documentações Geradas

> *"Incluir nessa aba os campos: Fonte de Recurso, Observações,
> Documentações geradas"*

**Hoje:** nenhuma das 3 colunas existe na tabela `projetos`
(`CREATE TABLE`, `database.py:593-612`) nem na lista de migrações
incrementais já aplicadas (`database.py:850-907`). Confirmado por grep no
schema e no código de app.

**Proposta — nome de coluna, tipo e posição no formulário:**

| Campo | Coluna sugerida | Tipo | Onde entra no form |
|---|---|---|---|
| Fonte de Recurso | `fonte_recurso` | `TEXT` | Bloco **Identificação**, perto de SEI/Solicitante (`views/novo_projeto.py:75-77`) ou na linha de Prioridade/Tags (hoje 2 colunas, `views/novo_projeto.py:109-127`, viraria 3) |
| Observações | `observacoes` | `TEXT` | Bloco **Escopo e Disciplinas**, como terceiro `text_area` logo após "Checklist Adicional/Demandas" (`views/novo_projeto.py:144`) |
| Documentações Geradas | `documentacoes_geradas` | `TEXT` | Ambíguo — ver decisão abaixo |

Para "Documentações Geradas", dois sentidos possíveis: (i) um campo de texto
curto/lista dentro do próprio cadastro do projeto (ex.: "Memorial
descritivo, ART, Planta baixa"), caindo perto de "Link da Pasta
(Drive/Nuvem)" (`views/novo_projeto.py:81`) no bloco Identificação; (ii) ela
estar pensando na aba **Arquivos** (`views/arquivos.py`, módulo separado de
anexos por projeto) e querendo um resumo/atalho dela aparecendo em Novo
Projeto — solução bem diferente da (i).

**Nota de implementação (padrão já usado no código):** colunas "tardias"
como `codigo`, `local`, `tags` não entraram na tupla posicional fixa de
`salvar_projeto`/`atualizar_projeto_completo` (assinatura fixa de 16/17 e 14
valores, `database.py:1046-1050,1085-1087`) — em vez disso, usam o setter
genérico `atualizar_campo_projeto` (`database.py:1099-1105`, uso em
`views/kanban.py:1282,1285-1288`). É provavelmente o caminho de menor
atrito pros 3 campos novos. Qualquer um deles, se virar coluna real,
também precisaria (pelo padrão observado) entrar na lista `migracoes`
(`database.py:850-907`) e, se a Sara quiser refletido em clone/relatórios/
edição no Kanban, ser replicado em `clonar_projeto`
(`database.py:1232-1286`), `relatorios.py:239-259,580-611` e no espelho do
formulário de edição em `views/kanban.py:1090-1177`.

⚠️ **decisões pendentes:** (i) "Documentações Geradas" é campo de texto novo
no cadastro, ou atalho/resumo pra aba Arquivos? (ii) os 3 campos novos
devem entrar também em clonagem de projeto, relatórios Excel/PDF e edição
no Kanban (recomendação: sim, pra manter consistência com os demais campos
do cadastro) ou só no cadastro/edição básica?

**✅ Resolvido (29/07/2026) — (i) campo de texto; (ii) sim, entram em tudo.**
Colunas `fonte_recurso`, `observacoes` e `documentacoes_geradas` (TEXT) criadas
por migração. Onde aparecem:
- **Novo Projeto:** 💰 Fonte de Recurso e 📄 Documentações Geradas na
  Identificação (linha nova sob Contato/Link); 📝 Observações em Escopo.
- **Edição no Kanban:** mesmos 3 campos, nas mesmas posições, gravados via
  `atualizar_campo_projeto` (o mesmo padrão já usado por código/local/tags,
  porque `atualizar_projeto_completo` tem assinatura posicional fixa).
- **Histórico de alterações:** os 3 entram em `_campos_hist`, então mudança
  neles vira linha na Auditoria.
- **Clonagem:** copiados junto com o resto (`clonar_projeto`).
- **Excel:** 3 colunas novas; **PDF:** Fonte de Recurso na Identificação e
  duas seções próprias para Documentações Geradas e Observações — cada uma só
  sai se estiver preenchida (`database.py`, `views/novo_projeto.py`,
  `views/kanban.py`, `relatorios.py`).

---

## ✅ Tarefas

### Item 6 — Unificar as duas formas de cadastro de tarefa

> *"Acho que na aba tarefa não precisa ter 2 formas de cadastro. Acho que
> poderia ter um campo para atribuir a alguém. Aí sim, a lista vai estar
> minhas tarefas e tarefas da equipe."*

**Hoje:** dois formulários distintos. (a) "Nova tarefa" pessoal
(`views/tarefas.py:74-103`) sempre cria a tarefa pro próprio usuário
logado — sem seletor de destinatário — com checkbox "🔒 Manter privada"
(default `True`). (b) "Tarefas da equipe" — atribuição do gestor
(`views/tarefas.py:298-330`), só visível pra quem passa `_pode_gestor()`
(`core/helpers.py:53-55`), com `st.selectbox("Para quem", _membros)`
(`views/tarefas.py:296`) e **sem** checkbox de privacidade — a tarefa nasce
sempre pública.

Ambos os formulários chamam a **mesma função de banco**,
`criar_tarefa(usuario, descricao, *, privada, criado_por, equipe, data,
projeto_id, recorrencia)` (`database.py:1607-1640`). A regra de negócio já
está toda no backend (`database.py:1618-1622`): se `criado_por != usuario`,
a tarefa é forçada `privada=False` e nasce `vista=0` (dispara badge/toast);
se o próprio dono cria, nasce `vista=1`. **A separação em duas telas é só de
front-end** — unificar não exige mudança de schema nem nova função de
banco, só trocar quem popula os argumentos `usuario`/`criado_por` na
chamada já existente a `db.criar_tarefa`.

**Proposta — desenho do formulário único:**
- Campos comuns (iguais aos dois forms de hoje): Descrição, 📅 Data,
  🔁 Repetir, 📁 Projeto (opcional).
- Campo novo **"Atribuir a"** — `selectbox` opcional, populado por
  `membros_para_gestor(equipe)`, **visível apenas para quem `_pode_gestor()`**
  (quem não é gestor nem vê o campo — o form fica idêntico ao "Nova tarefa"
  pessoal de hoje). Vazio/"Eu mesmo" (default) = tarefa pessoal
  (`criado_por == usuario`); preenchido com outro nome = tarefa atribuída
  (`criado_por` = quem está logado, `usuario` = destinatário escolhido) —
  reaproveita a regra de privacidade já existente em
  `database.py:1618-1619`, sem inventar regra nova.
- Checkbox **"🔒 Manter privada"** — fica habilitada só quando "Atribuir a"
  está vazio (tarefa pessoal); some/desabilita quando um destinatário é
  escolhido, já que o backend força `privada=False` nesse caso de qualquer
  forma.
- Log de auditoria (`log_aud("atribuir_tarefa", ...)`,
  `views/tarefas.py:322`) mantido quando a tarefa é atribuída a terceiro.
- As **listas** continuam duas, como ela mesma descreveu — "Minhas tarefas"
  (`views/tarefas.py:105-250`) e "Tarefas da equipe"
  (`views/tarefas.py:334-360`) seguem existindo como estão, só passam a ser
  alimentadas por um único ponto de cadastro em vez de dois.

Sem ⚠️ estrutural aqui — o desenho é direto e não depende de escolha externa,
só de validar o rótulo final ("Atribuir a" / "Atribuir a (opcional)").

**✅ Resolvido (29/07/2026).** Ficou um formulário só, com o campo
**"👤 Atribuir a"** (rótulo escolhido) visível **apenas para o Gestor** — quem
não é gestor vê exatamente o formulário pessoal de antes. Default "— Eu mesmo —"
= tarefa minha; escolher outra pessoa manda a tarefa pra ela e dispara o
`log_aud("atribuir_tarefa")` que existia no form antigo. A regra de privacidade
não mudou (ela já morava no backend, `database.py`): tarefa atribuída a
terceiro nasce pública e com `vista=0`, alimentando o badge/toast. O segundo
formulário ("Nova tarefa pra atribuir...") deixou de existir
(`views/tarefas.py`). Testado: como Gestor o campo aparece e a tarefa vai
mesmo parar no destinatário, pública e com `criado_por` correto; como
Projetista o campo não é renderizado.

---

### Item 7 — Agrupar tarefas por data

> *"Deixar agrupado por datas as tarefas."*

**Hoje:** não há agrupamento visual em nenhuma das três visões — é sempre
lista/tabela plana ordenada por SQL. "Minhas tarefas":
`listar_tarefas_de` ordena por `t.concluida ASC, COALESCE(t.data,
t.criado_em::date) ASC, t.id DESC` (`database.py:1657-1658`), renderizada em
`st.data_editor` (`views/tarefas.py:145-165`), que preserva essa ordem mas
não agrupa nativamente. O toggle "📅 Só hoje" (`views/tarefas.py:111-112,
123-124`) só restringe a exibição a um dia, não agrupa; o aviso de
atrasadas é um `st.warning` de contagem agregada (`views/tarefas.py:117-119`),
não uma seção separada. O expander "🖥️ Ver como planilha"
(`views/tarefas.py:210-250`) renderiza a mesma lista em HTML manual, também
sem agrupamento. "Tarefas da equipe": `listar_tarefas_equipe` ordena
**primeiro por usuário**, depois `concluida`, depois `id DESC`
(`database.py:1830,1833`) — ordenação por pessoa, não por data — em
`st.dataframe` simples (`views/tarefas.py:339-348`), sem cor nem
agrupamento.

**Proposta — duas formas de resolver, dado que a tabela principal hoje é
`st.data_editor` (que não tem agrupamento nativo com cabeçalho de seção):**

- **Opção A — cabeçalhos de seção reais:** quebrar a renderização em blocos
  por data (ex.: "Atrasadas", "Hoje", "Amanhã", "Esta semana", "Depois"),
  cada bloco com seu próprio cabeçalho visual. Visualmente mais parecido com
  apps de tarefas (Todoist/Things), mas implica abrir mão de uma única
  grade editável — a edição em lote passaria a ser por bloco, ou a interação
  por linha mudaria de padrão.
- **Opção B — tabela única ordenada + destaque de virada de dia:** manter o
  `st.data_editor` único (preserva a edição em lote como está hoje), mas
  inserir um separador visual (linha/cor de fundo) toda vez que a data muda
  em relação à linha anterior. Mais leve de implementar, mas é mais um
  "separador" do que um "agrupamento" no sentido literal do pedido.

⚠️ **decisões pendentes:** (i) Opção A (blocos reais, abre mão do
data_editor único) ou Opção B (tabela única + separador de dia, mecânica
atual quase intacta)? (ii) isso vale também pra "Tarefas da equipe" — hoje
agrupada por pessoa — ou só pra "Minhas tarefas"?

**✅ Resolvido (29/07/2026) — Opção A (blocos reais), nas DUAS listas.** Os
blocos são **Atrasadas · Hoje · Amanhã · Esta semana · Depois · Sem data ·
Concluídas**, cada um com cabeçalho colorido e contagem. "Tarefas da equipe"
passou a usar os mesmos blocos por data (era ordenada por pessoa) — o nome de
quem é a tarefa virou um chip 👤 dentro do card, então não se perdeu a
informação. Como o `st.data_editor` saiu de cena, a edição virou por card:
✏️ abre um popover com descrição, data, projeto, recorrência e privada
(`views/tarefas.py`).

---

### Item 8 — Visual "mais bonitinho" (proposta do "tio Claudio")

> *"Acho que o visual dessa aba poderia ser mais bonitinho. De repente o
> tio Claudio sugira algo"*

**Hoje:** sem CSS específico da aba além de dois trechos inline dentro do
expander opt-in "Ver como planilha" — cabeçalho teal sólido `#0f766e` com
texto branco negrito (`views/tarefas.py:212-213`), borda sutil
`rgba(255,255,255,.08)` (`views/tarefas.py:214-215`) e destaque de atraso em
vermelho `#ef4444` negrito (`views/tarefas.py:221`) — únicas cores
hardcoded do arquivo, e só aparecem nessa visão alternativa, não na tabela
principal. `st.data_editor` (tabela principal) e `st.dataframe` (tabela da
equipe) usam formatação padrão do tema Streamlit, sem cor por coluna; os
"ícones" são só emojis nos `label`/`help` do `column_config`
(`views/tarefas.py:149-163`). O CSS global do app
(`app.py:222-294,426`) estiliza forms/expanders/botões de forma genérica em
todas as abas, nada pensado especificamente pra Tarefas.

**Proposta — 3 ideias concretas, coerentes com o resto do app (tema
escuro, cards já usados em Arquivos/Kanban, paleta de cores por tipo já
usada na Agenda):**

1. **Cards por tarefa com faixa lateral colorida por urgência.** Trocar (ou
   complementar) o `data_editor` por um layout de cards empilhados — um
   container por tarefa, no mesmo espírito dos cards já usados em Arquivos
   (`views/arquivos.py:190-244`) e no Kanban — cada card com uma borda/faixa
   lateral: vermelho para atrasada, âmbar para hoje, teal/verde para
   futura, cinza riscado para concluída. Dentro do card: checkbox de
   concluir, descrição, chips pequenos de data/projeto/repetição. É a opção
   de maior impacto visual, mas custa a edição em grade rápida do
   `data_editor` (edição vira por card/linha, não em lote).
2. **Badges de urgência dentro do `data_editor` atual.** Mantém a tabela
   editável como está (sem perder a edição em lote), só colore o rótulo/
   célula de Data com um badge (pill) por urgência, reaproveitando a mesma
   paleta que já existe no calendário da Agenda (`TIPO_COR`/`TIPO_ICONE`,
   `views/agenda.py:233`) — dá consistência visual entre as duas abas.
   Esforço baixo/médio, ganho moderado.
3. **Cabeçalho com mini-dashboard de contadores.** Acima da tabela, uma
   fileira de 3-4 "stat tiles" (no estilo já usado no Dashboard) com
   contadores clicáveis — Atrasadas / Hoje / Esta semana / Concluídas —
   cada um filtrando a lista abaixo ao clicar. Dá sensação mais "produto"
   sem alterar a mecânica da tabela.

⚠️ **decisão pendente:** qual das 3 prefere? As opções 2 e 3 combinam bem
entre si com esforço baixo/médio; a opção 1 é a mais "bonitinha" mas exige
abrir mão do `data_editor` único em favor de cards.

**✅ Resolvido (29/07/2026) — ideias 1 + 3 (cards + contadores).** Cada tarefa
virou um card com **faixa lateral colorida por urgência** (vermelho atrasada,
âmbar hoje, azul futura, verde concluída) e **chips** de data, projeto,
recorrência, 🔒 privada e "↪ de fulano" quando foi atribuída. Concluída fica
riscada e esmaecida. No topo, **contadores clicáveis** (📋 Todas · 🔴 Atrasadas ·
🟡 Hoje · 🔵 Semana · ✅ Concluídas) que funcionam como filtro — clicar no filtro
ativo volta pra "Todas". O toggle "📅 Só hoje" e a visão "Ver como planilha"
saíram: viraram redundantes com os contadores e os blocos por data
(`views/tarefas.py`).

---

## 📁 Arquivos

### Item 9 — Pastas e subpastas na aba Arquivos

> *"Acho que na aba arquivos a gente cria uma pasta e poderia ter
> subpastas."*

**Hoje:** lista plana, sem hierarquia. Schema de `arquivos`
(`database.py:712-722`) não tem coluna de pasta, categoria ou `parent_id`.
Armazenamento em disco é um único nível,
`anexos/<id_projeto>/<timestamp>_<nome>` (`database.py:1983-1988`) — a
"pasta" que existe hoje é implicitamente o próprio projeto. `listar_arquivos`
(`database.py:1956-1969`) sempre retorna lista cronológica plana por
projeto, sem `GROUP BY`. Na UI (`views/arquivos.py:136-244`), o único filtro
é "Filtrar por projeto" (`views/arquivos.py:139-147`); os arquivos aparecem
em cards sequenciais (`views/arquivos.py:190-244`) sem agrupamento além do
ícone por extensão. O upload (`views/arquivos.py:47-67`) só pede projeto
(obrigatório) e descrição (opcional) — sem campo de pasta.

**Proposta — schema:**
- Nova tabela `pastas`: `id` BIGINT IDENTITY PK, `projeto_id` BIGINT NOT
  NULL, `nome` TEXT NOT NULL, `pasta_pai_id` BIGINT NULL (auto-referenciada;
  `NULL` = pasta na raiz do projeto), `criado_por` TEXT, `criado_em`
  TIMESTAMP DEFAULT CURRENT_TIMESTAMP. Índice em `(projeto_id,
  pasta_pai_id)` pra listar subpastas de uma pasta rápido.
- `arquivos` ganha uma coluna nova `pasta_id BIGINT NULL` — `NULL` = arquivo
  solto na raiz do projeto, que é exatamente o estado de **todos os arquivos
  já existentes hoje** (compatível sem precisar migrar nada).
- Pastas ficam **só no banco** (não viram diretório de verdade em
  `anexos/`) — o arquivo físico continua caindo direto em
  `anexos/<projeto_id>/...` como hoje; mover um arquivo de pasta é só um
  `UPDATE arquivos SET pasta_id = ...`, sem tocar em disco. Mais simples e
  sem risco de mover/perder arquivo físico.

**Proposta — UI (`views/arquivos.py`):**
- Breadcrumb da pasta atual (Projeto ▸ Pasta ▸ Subpasta) com botões pra
  subir de nível; pasta atual guardada em `session_state`.
- Botão "➕ Nova pasta" — miniform com nome; pasta atual vira o pai.
- Listagem passa a mostrar primeiro as subpastas da pasta atual (como
  cards/botões clicáveis pra entrar), depois os arquivos que estão
  diretamente nela (`pasta_id = <atual>` ou `IS NULL` se for a raiz).
- Upload ganha a pasta atual como destino implícito.

⚠️ **decisões pendentes:**
1. **Exclusão de pasta não-vazia:** bloquear (recomendado — mais seguro),
   mover o conteúdo pra pasta pai antes de excluir, ou excluir em cascata
   (apaga arquivos e subpastas dentro)?
2. **Profundidade de aninhamento:** ilimitada (recomendado — o schema
   auto-referenciado já suporta sem custo extra) ou travada em N níveis?
3. **Quem pode criar/excluir pasta:** mesma regra de hoje pra excluir
   arquivo (Gestor exclui qualquer uma; demais só as que criaram), ou
   restringir a criação/exclusão de pasta só a Gestor?

**✅ Resolvido (29/07/2026) — pastas implementadas.** Decisões: (1) pasta com
conteúdo **não pode ser excluída** — precisa esvaziar antes, nada é apagado em
cascata; (2) aninhamento **ilimitado**; (3) criar/renomear/excluir pasta é
**só do Gestor** (projetista usa as pastas existentes e segue enviando e
baixando arquivo normalmente).
- **Schema:** tabela `pastas` + coluna `arquivos.pasta_id`, como proposto
  acima. Os arquivos que já existiam ficam com `pasta_id = NULL`, ou seja,
  **na raiz do projeto — zero migração de dados**.
- **Disco não mudou:** continua tudo plano em `anexos/<projeto_id>/`. Mover
  arquivo entre pastas é só `UPDATE arquivos.pasta_id`, sem tocar no binário.
- **UI:** breadcrumb clicável (🏠 Raiz / pasta / subpasta), subpastas como cards
  com contagem de conteúdo, upload caindo na pasta atual, e **📦 Mover** por
  arquivo (destinos listados com caminho completo, pra não confundir pastas de
  mesmo nome em níveis diferentes).
- Nome duplicado é bloqueado **no mesmo nível** (em níveis diferentes pode
  repetir) e o breadcrumb tem trava de 50 níveis contra ciclo acidental
  (`database.py`, `views/arquivos.py`).

---

## Decisões pendentes (resumo) — ✅ todas fechadas em 29/07/2026

| # | Item | Decisão tomada |
|---|---|---|
| 1 | Agenda — clicar no dia | **(B)** painel dedicado abaixo do calendário |
| 2 | Agenda — vencidos somem | **as duas causas** corrigidas (não dava pra saber qual era sem a tela exata) |
| 3 | Agenda — pessoas logadas | **Abordagem 1** (coluna `ultima_atividade`), janela de **5 min**, exibido **na sidebar E no Chat** |
| 4 | Checklist Adicional/Demandas | campo **mantido** — está ativo, com 5 dependências reais |
| 5 | Documentações Geradas | **campo de texto** no cadastro |
| 6 | 3 campos novos em clone/relatórios/Kanban | **sim**, entram em tudo |
| 7 | Tarefas — agrupar por data | **Opção A** (blocos reais), valendo também pra "Tarefas da equipe" |
| 8 | Tarefas — visual | **ideias 1 + 3** (cards com faixa de urgência + contadores no topo) |
| 9 | Arquivos — pastas | criar/excluir **só Gestor**; aninhamento **ilimitado**; pasta não-vazia **bloqueada** |

**Continua em aberto (não bloqueia nada):** no item 4, se a lembrança da Sara
for mesmo do campo "Checklist Adicional / Demandas", o caminho não é remover e
sim separar "disciplinas" e "texto livre" em duas colunas de verdade — refactor
à parte, fora desta rodada.

---

## Execução

**✅ Executado em 29/07/2026, na ordem sugerida abaixo.** Arquivos alterados:
`database.py`, `app.py`, `relatorios.py`, `views/novo_projeto.py`,
`views/kanban.py`, `views/tarefas.py`, `views/agenda.py`, `views/arquivos.py`,
`views/chat.py`.

1. **Novo Projeto** — Item 5 (3 colunas novas) primeiro, porque relatórios,
   clone e edição no Kanban dependem delas. Item 4 não exigiu mudança.
2. **Tarefas** — Item 6 (formulário único) e, na sequência, 7 e 8 juntos, já
   que ambos mexiam na mesma área de renderização.
3. **Agenda** — Item 2 (vencidos), Item 1 (clique no dia) e Item 3 (presença).
4. **Arquivos** — Item 9 (pastas/subpastas), o de maior esforço.

**Verificação:** `py_compile` em todos os arquivos alterados; **40 testes de
round-trip no Postgres** (schema novo, 3 campos em salvar/clonar/atualizar,
CRUD de pastas com todas as regras de bloqueio, filtro de arquivo por pasta,
heartbeat entrando e saindo da janela de presença); **testes de comportamento
das telas** via AppTest, como Gestor **e** como Projetista (formulário único de
tarefa realmente atribuindo, dias do calendário clicáveis abrindo o painel,
controles de pasta aparecendo só pro Gestor); e o `tests/smoke_tests.py`
completo (11 views renderizando sem exceção + helpers de Tarefas).

**Lembrete de deploy:** as colunas novas entram sozinhas pelas migrações
incrementais (`ADD COLUMN IF NOT EXISTS`) no primeiro boot após o deploy — nada
manual no banco. O app precisa ser **reiniciado** pra carregar os `.py` novos.
