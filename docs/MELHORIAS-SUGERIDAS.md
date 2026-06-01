# Melhorias Sugeridas

Lista priorizada de melhorias técnicas e de produto pro **Gestão de
Projetos SERVPEN**, baseada no estado real do código em
maio/2026 + observações de uso.

> **Como ler este documento.** Cada categoria está ordenada por impacto.
> A coluna "Esforço" estima quão grande é a mudança (baixo / médio / alto).
> Itens com 🔴 são **urgentes** (segurança ou correção); 🟠 são importantes
> a médio prazo; 🟢 são melhorias de qualidade de vida.

---

## 0. Sobre trocar de banco de dados — resposta honesta

O sistema usa **SQLite com WAL ligado**. A pergunta recorrente é "vale a
pena trocar pra MySQL/PostgreSQL pra ficar mais rápido?".

**Resposta curta:** **não, ainda não.** Trocar agora vai piorar.

**Por quê:**

- O banco **não é o gargalo**. O gargalo é a **CPU do servidor** (AMD
  Athlon II X2 250, de 2009, sem AVX/AVX2) + o **modelo do Streamlit**
  (rerun completo a cada clique).
- SQLite com WAL aguenta **dezenas de usuários** se as escritas forem
  modestas (que é o caso atual: chat, marcação de leitura, notificações).
- MySQL/Postgres adicionam **round-trip de rede** a cada query e um
  **daemon competindo** pela mesma CPU fraca. Em uma máquina já saturada,
  isso piora.
- Base é **pequena** (dezenas/centenas de linhas por tabela). SQLite
  resolve isso trivialmente.

**Quando trocar fará sentido:**
- ≥50 usuários simultâneos **escrevendo**, OU
- Base passou de milhões de linhas, OU
- Múltiplos servidores de app compartilhando o mesmo banco.

**Se migrar um dia, a escolha técnica certa é PostgreSQL** (não MySQL):
melhor concorrência sob contenção, JSONB se precisar, ecossistema Python
maduro (psycopg3), defaults sensatos.

---

## 1. Próximos 5 passos recomendados (na ordem)

| # | Passo | Por que | Status |
|---|---|---|---|
| 1 | **Git + GitHub privado** | Single point of failure absoluto — sumiu o `app.py` = perdeu o sistema. Já vimos isso acontecer | ✅ **Feito** (repo `diogosvicente/gestao-de-projetos-servpen`) |
| 2 | **Backup automático diário do Postgres** | Hoje só faz backup quando o `install.sh` roda. Se algo corromper hoje, último backup foi quando? | ✅ **Feito** (timer systemd `backup-gestao-de-projetos.timer`, retenção 30 dias) |
| 3 | **HTTPS** com Let's Encrypt + certbot | Token de sessão vai em texto puro pela rede. Qualquer sniff captura e rouba sessão | Pendente |
| 4 | **bcrypt** no lugar de SHA-256 puro | Vulnerável a rainbow tables se o `.db` vazar. Migrar hashes existentes incluído no esforço | ✅ **Feito** (`passlib[bcrypt]`, rehash transparente no login — usuários antigos migram sem precisar trocar senha) |
| 5 | **Trocar o servidor** (qualquer CPU dos últimos ~8 anos com AVX2) | Sozinho resolve mais que qualquer mudança de software | Pendente |

---

## 2. Segurança 🔴

| # | Item | Risco atual | Solução | Esforço |
|---|---|---|---|---|
| ✅ | ~~**Senhas em SHA-256 sem salt**~~ Migrado pra **bcrypt** (maio/2026) | — | `passlib[bcrypt]`. Rehash transparente no login — hashes legados migram conforme cada usuário loga. | ✅ Feito |
| 🔴 | **HTTP sem TLS** | Token de sessão em texto puro em URL e cookies. Sniff trivial | Let's Encrypt + certbot no Apache | Baixo |
| ✅ | ~~**Sem rate limiting no login**~~ Implementado em maio/2026 | — | Tabela `login_falhas` + 5 falhas em 15min bloqueiam usuário por 15min. Backup diário purga falhas >24h. | ✅ Feito |
| 🟠 | **Token de sessão no querystring** (`?t=...`) | Aparece em logs do Apache, no histórico do browser, em headers Referer | Migrar pra cookie HttpOnly; precisa sessão server-side real | Médio |
| 🟠 | **Upload de arquivo sem validação** | Aceita qualquer extensão até 100MB. `.html` malicioso? Sem sanitização? | Whitelist de extensões + magic-byte check (`python-magic`) + opcionalmente ClamAV | Baixo |
| 🟠 | **Sem complexidade mínima de senha** | "123" é aceito | Mínimo 8 chars + 1 número ou classe diversa | Baixo |
| ✅ | ~~**XSRF desabilitado**~~ Re-habilitado em maio/2026 | — | `enableXsrfProtection = true` no config.toml. Funciona porque vhost Apache usa `ProxyPreserveHost On` + `X-Forwarded-Host`. | ✅ Feito |
| 🟢 | **Auditoria sem IP** | Loga "Sara fez X" mas não de onde | Adicionar `ip` na tabela `auditoria` (vem do header `X-Forwarded-For`) | Baixo |
| 🟢 | **Sessões de 7 dias sem rotação** | Token roubado vale uma semana inteira | Rotacionar token a cada N horas de uso | Baixo |
| 🟢 | **Sem 2FA** | Para perfis Gestor seria desejável | TOTP (Google Authenticator) via `pyotp` | Médio |

---

## 3. Performance

| # | Item | Por que | Esforço |
|---|---|---|---|
| 🔴 | **Trocar o servidor** | CPU de 2009 sem AVX é o ceiling de tudo. Sozinho rende mais que qualquer software-change | Baixo (custo de hardware) |
| ✅ | ~~**Modularizar `app.py`**~~ Concluído em maio/2026. App quebrado em `core/` (6 módulos compartilhados) + `views/` (10 páginas). Entry point caiu de **6130 → 618 linhas**. `st.tabs` substituído por `st.navigation` + `st.Page`. Sidebar global hospeda `_global_notif` (toast continua disparando em qualquer página) e badges de pendências. Apenas a página ativa roda a cada interação → ~60% menos work por clique. | ✅ Feito |
| ✅ | ~~**`@st.cache_resource` pra conexão SQLite**~~ Substituído por **engine SQLAlchemy + pool** (maio/2026) | — | `db.get_engine()` com `lru_cache` retorna engine SQLAlchemy compartilhado; `pd.read_sql_query(..., db.get_engine())` em vez de conn psycopg crua → resolve warning pandas + reuso de conexão via pool. | ✅ Feito |
| 🟢 | **Static assets via Apache** (em vez de Streamlit servir tudo) | Apache é mais rápido pra static. Streamlit fica só pro dinâmico | Baixo |

---

## 4. UX (experiência do usuário)

| # | Item | Por que dói hoje | Esforço |
|---|---|---|---|
| ✅ | ~~**Autocomplete no `@` mention**~~ Implementado em maio/2026: popover **@ Mencionar** ao lado de cada `st.text_area` do Diário (novo relato + resposta). Selectbox com filtro nativo + botão "➕ Inserir menção" appenda `@"Nome"` no fim do texto. Sem deps externas, sem JS injection. | ✅ Feito |
| 🟠 | **Notificação por e-mail** | Quem não tá logado perde menções/respostas. Painel persistente ajuda, mas e-mail é o canal definitivo | Médio (SMTP + template) |
| 🟠 | **Loading states / spinners** em operações lentas (PDF, upload, geração de relatório) | Sem feedback, usuário clica de novo achando que travou | Baixo |
| 🟠 | **Mensagens de erro humanas** | Hoje vaza stack trace pro usuário em vários pontos | Baixo |
| ✅ | ~~**Calendário visual da Agenda**~~ Já existia desde antes (grid 7 colunas HTML). **Agenda Enterprise** em maio/2026: 4 métricas no topo (Próximos 7d / Visitas no mês / Ausentes hoje / Total no mês) + toggle **Mensal / Semanal / Lista / Resumo** via `_pill_select` portátil (radio em 1.39, segmented_control em 1.40+). Cada visão tem render dedicado: Semanal = 7 cards com chips + nav semana, Lista = stats da seleção visível, Resumo = próximos 5 + distribuição por tipo + top membros. | ✅ Feito |
| 🟢 | **Inline edit em campos do projeto** | Hoje precisa abrir form gigante pra mudar 1 prioridade | Médio |
| ✅ | ~~**Bulk actions**~~ Implementado em maio/2026 na **Lista do Kanban**: checkbox por linha + "Selecionar todos" no header + toolbar contextual com selectbox de status, selectbox de tag e botões `✅ Aplicar` / `✖ Limpar`. Log de auditoria com qtd + ação. Só aparece pra perfil que pode editar. | ✅ Feito |
| ✅ | ~~**Tags/labels nos projetos**~~ Implementado em maio/2026: coluna `tags` CSV, input nos forms novo+editar, chips coloridos no Kanban (cor determinística por hash), filtro AND no topo do Kanban | ✅ Feito |
| ✅ | ~~**Empty states com CTA**~~ Implementado em maio/2026: helper `_empty_state(icone, titulo, mensagem, cta_label, cta_key, cor_borda)` renderiza card decorativo com ícone grande + título + mensagem. Aplicado em 8 lugares visíveis (Kanban Lista/Resumo sem projetos, Agenda sem compromissos, Equipe sem busca match, Gantt sem projetos/etapas, etc.). | ✅ Feito |
| 🟢 | **Atalhos de teclado** | Esc fecha modal, Ctrl+S salva form, etc. | Baixo |

---

## 5. Código / DevOps

| # | Item | Por que urgente | Esforço |
|---|---|---|---|
| 🔴 | **Git versionando o código** | Single point of failure absoluto. Já visto na conversa real | ✅ Feito |
| 🔴 | **Backup automático diário** do Postgres (timer systemd) | Hoje só backup quando `install.sh` roda. Se corromper hoje, recupera de quando? | ✅ Feito |
| ✅ | ~~**Modularizar `app.py`** em `views/`~~ Feito em maio/2026. Ver seção **3. Performance** acima. | ✅ Feito |
| 🟠 | **Testes automatizados** (pelo menos smoke tests) | Zero coverage. Quebra calado ao mexer em qualquer coisa | Médio |
| ✅ | ~~**Logs estruturados**~~ Implementado em maio/2026 | `logging.basicConfig` no boot do `app.py` com timestamp+nível+módulo. `LOG_LEVEL` env var controla verbosidade (default INFO; DEBUG pra investigar). | ✅ Feito |
| 🟠 | **Monitoramento** (uptime, error rate) | Quando o serviço cai, ninguém sabe até alguém reclamar | Baixo (UptimeRobot grátis serve) |
| 🟠 | **Config por env var**, não hardcoded | IPs no código, paths no código. Mudar de servidor exige editar código | Baixo |
| 🟢 | **Migrations de DB em arquivos separados** (não ALTER inline em código) | Hoje migração é "tente ALTER, ignore erro". Difícil saber o estado real do schema | Médio |
| ✅ | ~~**Linter + formatador**~~ ruff configurado em `pyproject.toml` (maio/2026). Rodar: `ruff check .` (lint) + `ruff format .` (format). | ✅ Feito |
| 🟢 | **Dockerizar** | Reprodutibilidade real. `docker compose up` em qualquer Linux funciona | Médio |

---

## 6. Produto / Features

| # | Item | Por que | Esforço |
|---|---|---|---|
| 🟢 | **Comentários encadeados no diário** | Hoje é tudo concatenado num `resposta_gestor` separado por `\n` — feio e sem edição/exclusão individual | Médio (nova tabela `comentarios_diario`) |
| ✅ | ~~**Time tracking**~~ Implementado em maio/2026: input `⏱ Horas` no form, chip no card de cada relato, expander "Horas registradas" agregando minhas/equipe × hoje/semana/mês + top 5 projetos do mês + breakdown por projetista | ✅ Feito |
| ✅ | ~~**Templates de projeto**~~ Implementado em maio/2026: botão **📋 Clonar projeto** no painel de edição. Copia dados básicos (projetista, endereço, contato, demandas, prioridade, tags, link, escopo) + estrutura de etapas. Não copia diário, arquivos nem progresso. Novo projeto entra em "Em Espera" e abre direto na edição pra ajustar. | ✅ Feito |
| 🟢 | **Histórico de versões** dos relatos | Hoje editar relato sobrescreve sem rastro. Útil pra auditoria | Médio (nova tabela ou versionar via JSON) |
| 🟢 | **PWA / mobile-first** | Streamlit não é ideal pra isso. Vale considerar app web nativo se mobile virar prioridade | Alto (reescreve frontend) |

---

## 7. Como decidir o que fazer próximo

Pergunte primeiro:

1. **O sistema vai pra produção pública/aberta?**
   → Faça TUDO da seção **Segurança** antes (HTTPS + bcrypt + rate limit).

2. **A equipe vai dobrar (10 → 20+ usuários)?**
   → **Trocar o servidor** antes de qualquer outra coisa. Software não
   conserta CPU de 2009.

3. **Sara/equipe quer iterar rápido no produto?**
   → Modularizar `app.py` + testes + linter. Sem isso cada mudança vira
   risco de quebrar algo que funciona.

4. **Usuários se queixam de algo específico?**
   → Atacar o item correspondente em UX direto, sem se perder em
   prioridades teóricas.

5. **Vai parar de mexer por um tempo?**
   → Garanta o **backup diário** e **HTTPS**, pelo menos. São os dois
   que protegem o sistema "sozinho" enquanto ninguém olha.

---

## Apêndice: pequenas dívidas técnicas conhecidas

- `app.py` tem **imports duplicados** no topo (`import streamlit as st`
  aparece 2x). Inofensivo, mas feio.
- `seed.py` ainda referencia `servpen.db` (split-brain antigo já corrigido
  em outros lugares). Se rodar de novo, melhor revisar.
- A coluna `email` em `usuarios` foi adicionada mas só usada hoje pelo
  campo do `Meu Perfil`. Sem validação de formato.
- `pyarrow` está **intencionalmente ausente** (CPU sem AVX2). Consequência:
  `st.dataframe`, `st.table` e Parquet não funcionam. Por isso a aba
  Auditoria usa tabela HTML manual.
- O `database.py` tem nome de tabela `mencoes_notificacoes` + `mencoes_acesso`
  duplicando responsabilidade (acesso permanente vs evento). Funciona, mas
  poderia ser 1 tabela com `dispensado_em IS NULL`.
- Várias chamadas `c.execute("...?...", (val,))` deixam connection aberta
  em alguns paths de erro. Considerar `with conn:` em vez de `try/finally`
  manual.
