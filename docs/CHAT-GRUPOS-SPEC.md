# Mini-spec — Chat com grupos + emoji (item 6)

Spec da única feature nova do pacote de ajustes. Hoje o chat é **1-a-1**
(`views/chat.py` + `core/chat_utils.py`), tabela `chat(remetente, destinatario,
mensagem, data, lido_em, editado_em, excluida_em)`. O objetivo é adicionar **3
grupos padrão** (TODOS / SERVPEN / SERVPAR) e um **seletor de emoji**, com o
menor atrito possível sobre o que já existe.

> Status: **✅ implementado e verificado (19/06/2026).** As decisões tomadas
> estão registradas no fim.

---

## 1. Modelo de dados (menor atrito)

Reaproveita a tabela `chat`. Mensagem de grupo = uma linha com `destinatario`
sendo um **sentinela**:

- `@grupo:TODOS`
- `@grupo:SERVPEN`
- `@grupo:SERVPAR`

O prefixo `@grupo:` não colide com nome de usuário real. `remetente` continua
sendo quem enviou. Edição/exclusão (`editado_em`/`excluida_em`) funcionam
igual — é uma linha só por mensagem.

**Leitura por usuário (não-lidas):** o `lido_em` atual é 1 campo só por linha,
não serve pra grupo (vários leem a mesma mensagem). Nova tabela enxuta:

```
chat_grupo_visto(
    usuario          TEXT,
    grupo            TEXT,          -- '@grupo:TODOS' etc.
    ultimo_id_visto  BIGINT,
    PRIMARY KEY (usuario, grupo)
)
```

- **Não-lidas(U, grupo)** = `COUNT(*) FROM chat WHERE destinatario=grupo AND
  id > ultimo_id_visto AND remetente <> U`.
- Ao **abrir** um grupo, grava `ultimo_id_visto = MAX(id)` daquele grupo.
- Usa o `id` (monotônico) em vez da `data` (que é string `DD/MM/YYYY HH:MM`).

DMs continuam exatamente como hoje (`lido_em`). Zero mudança no fluxo 1-a-1.

## 2. Membros dos grupos (derivado, sem tabela)

- **TODOS** → todo mundo.
- **SERVPEN / SERVPAR** → usuários com `usuarios.equipe` correspondente.
- Membros são **derivados em tempo real** de `usuarios.equipe` (quem muda de
  equipe entra/sai do grupo automaticamente). Sem tabela de membros.

## 3. UI (views/chat.py)

- No `selectbox` "Conversar com:", **prepend** dos grupos visíveis ao usuário,
  acima dos contatos 1-a-1:
  `👥 TODOS · 👥 SERVPEN · 👥 SERVPAR · ──── · <pessoas>`
  com badge `🔴 (N)` de não-lidas igual aos contatos.
- Selecionou um grupo → render por grupo (query por `destinatario=grupo`,
  mostrando o nome de cada remetente — o `wa-who` já existe). Ao abrir, atualiza
  `chat_grupo_visto`.
- Enviar pra grupo → `INSERT` com `remetente=U, destinatario=<sentinela>`.
- Editar/apagar a própria mensagem de grupo → já funciona (popover "⋯" aparece
  pras mensagens `sou_eu`).

## 4. Helpers novos no `database.py`

- `listar_grupos_visiveis(usuario, equipe)` → lista de sentinelas que o user vê.
- `nao_lidas_grupo(usuario, grupo)` / estende o mapa de não-lidas do topo.
- `marcar_grupo_visto(usuario, grupo)` → upsert do `ultimo_id_visto`.
- `_render_chat_messages` ganha um modo grupo (query por `destinatario=grupo`);
  o resto do render é reusado.

## 5. Emoji picker (Streamlit 1.58, sem dependência nova)

Streamlit não tem picker nativo. Proposta: um `st.popover("😀")` ao lado do
campo de envio com uma **grade de ~30 emojis comuns** (botões). Clicar **anexa**
o emoji a um rascunho em `st.session_state["chat_draft"]`; o `text_area` do envio
passa a usar `key="chat_draft"`. No envio, grava e limpa o rascunho.

> Detalhe técnico: os botões de emoji ficam **fora** do `st.form` (botão dentro
> de form submeteria o form). Por isso o `text_area` sai do `clear_on_submit` e
> a limpeza passa a ser manual (`chat_draft = ""` após enviar). Sem libs novas.

## 6. Notificação (toast) de mensagem nova

O toast global (`core/notif.py`) hoje detecta DM nova. Estender pra também
contar não-lidas de grupo (somando `chat_grupo_visto`). É trabalho extra no
`notif.py` — ver decisão abaixo.

---

## Fora de escopo (não muda)
- Criação de grupos pelo usuário (são só os 3 padrão).
- Mudança no fluxo 1-a-1 existente.

## Decisões tomadas (19/06/2026)
1. **Acesso aos grupos de equipe:** **por equipe** — SERVPEN/SERVPAR só pros
   membros (+ Gestor Geral vê os 3). Isolamento entre equipes mantido. ✅
2. **Toast pra grupo:** **incluído agora** (`core/notif.py` estendido com
   `alvo` pro clique abrir o grupo certo). ✅
3. **Emoji:** **popover com grade de ~30 emojis comuns**, sem dependência nova
   (anexam ao rascunho `chat_msg_draft`). ✅
