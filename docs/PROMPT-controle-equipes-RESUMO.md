# Controle por equipe (SERVPEN / SERVPAR / Geral) — resumo por tela

**Regra única:** nova coluna `usuarios.equipe` (`SERVPEN` | `SERVPAR` |
`GERAL`). Gestor `GERAL` vê tudo. Gestor de equipe só vê o da sua equipe.
Grupo de projeto/agenda é **derivado** do projetista/responsável (quem é da
minha equipe). **Projeto + Gantt são compartilhados (todos veem).**

Legenda: 🔒 = passa a filtrar por equipe · ➕ = ganha campo de equipe ·
✅ = sem mudança.

| Tela | O que muda |
|---|---|
| **Dashboard** | 🔒 Cards "projetos por pessoa" e o multiselect da pizza contam **só projetistas da minha equipe**. Geral vê todos. Métricas/visões de projeto em si: ✅ (compartilhado). |
| **Kanban** | ✅ Board e **Gantt** continuam mostrando **todos** os projetos. 🔒 Só o painel de **evolução por disciplina** ("Atualizar Progresso") filtra: aparece/edita apenas em projetos com projetista da minha equipe. |
| **Novo Projeto** | ✅ Qualquer gestor cria; projeto é único e visível a todos. ➕ O seletor de **projetistas** lista só gente da minha equipe (Geral lista todas). |
| **Diário** | ✅ Sem mudança (já controla acesso por menção). Só **validar** que não vaza relato entre equipes. |
| **Arquivos** | ✅ Sem mudança — arquivos são do projeto, que é compartilhado. |
| **Equipe** | 🔒 Lista só pessoas da minha equipe. ➕ No cadastro/edição: gestor de equipe grava a **própria** equipe automaticamente; **Geral escolhe** SERVPEN/SERVPAR num seletor. |
| **Chat** | ✅ Sem mudança (fora do escopo). |
| **Agenda** | 🔒 Mostra só eventos cujo **responsável** é da minha equipe (nas 4 visões + métricas do topo). Geral vê tudo. |
| **Auditoria** | ✅ Sem mudança (só Gestor). *Opcional:* restringir ao Geral, se quiserem. |
| **Acessos** | ✅ Sem mudança (recurso de Gestor sobre menções do Diário). |

## Onde mexer no código
- `database.py`: migração `usuarios.equipe` + helper `nomes_por_equipe()` +
  incluir `equipe` em `obter_usuario`/INSERT/UPDATE de usuário.
- `core/helpers.py`: `_equipe_atual()` e `_ve_tudo()` (Geral = sem filtro).
- Login/auto-login (`core/auth_ui.py`, `app.py`): carregar `equipe` na sessão.
- Telas com 🔒/➕ acima: `views/dashboard.py`, `views/kanban.py`,
  `views/novo_projeto.py`, `views/equipe.py`, `views/agenda.py`.

## Migração de dados
Existentes → `SERVPEN` por padrão. Depois rodar 1× em produção:
```sql
UPDATE usuarios SET equipe='GERAL'   WHERE nome='<Gestor Geral>';
UPDATE usuarios SET equipe='SERVPAR' WHERE nome='Jackeline';
-- Sara e demais já ficam SERVPEN pelo default.
```

> Detalhe técnico completo (helpers, regra derivada, cenários de teste) está
> em `docs/PROMPT-controle-equipes.md`.
