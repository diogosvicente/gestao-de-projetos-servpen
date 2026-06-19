"""Aba Chat — conversa estilo WhatsApp 1-pra-1 com auto-refresh 2s.

Com `st.navigation`, esta view só roda quando o user está nela. O fragmento
`_global_notif` (toast de msg nova) está montado na sidebar do app.py pra
continuar disparando em qualquer view.
"""

from __future__ import annotations

from datetime import datetime

import streamlit as st

import database as db

from core.chat_utils import _render_chat_messages
from core.data import _load_df_u


usuario = st.session_state.usuario
df_u = _load_df_u()


st.header("💬 Chat Interno")
st.caption(
    "🟢 Tempo real — mensagens novas aparecem em até 2 segundos sem "
    "precisar atualizar."
)

# 1. Seleção de Contato/Grupo com badge de não-lidas
# Grupos (item 6) aparecem no topo do seletor; visibilidade por equipe
# (SERVPEN/SERVPAR só pra própria equipe; GERAL vê os 3; TODOS é geral).
_equipe_chat = st.session_state.get("equipe", "SERVPEN")
_grupos_vis = db.grupos_chat_visiveis(_equipe_chat)   # [(sentinela, label)]
_grupo_label = {s: l for s, l in _grupos_vis}
_nao_lidas_grp = db.nao_lidas_grupos(usuario, _equipe_chat)

lista_usuarios = df_u["nome"].tolist() if not df_u.empty else []
if usuario in lista_usuarios:
    lista_usuarios.remove(usuario)
_nao_lidas_por_user = dict(db.listar_remetentes_com_nao_lidas(usuario))
# Pessoas: quem tem não-lidas no topo, depois alfabético.
lista_usuarios.sort(
    key=lambda n: (-int(_nao_lidas_por_user.get(n, 0)), n.lower())
)

# Opções do seletor: grupos primeiro, depois pessoas.
_opcoes_chat = [s for s, _l in _grupos_vis] + lista_usuarios


def _fmt_contato(opcao):
    if opcao in _grupo_label:
        _q = int(_nao_lidas_grp.get(opcao, 0))
        _l = _grupo_label[opcao]
        return f"🔴 {_l} ({_q})" if _q > 0 else _l
    _q = int(_nao_lidas_por_user.get(opcao, 0))
    return f"🔴 {opcao} ({_q})" if _q > 0 else opcao


# ── PRÉ-SELEÇÃO (à prova de bug) ───────────────────────────
# `_chat_force_target` é o único redirect explícito (clique no toast via
# `?_goto_chat=ALVO` ou após enviar msg). Vale p/ grupo (sentinela) e pessoa.
_target = st.session_state.pop("_chat_force_target", None)
_default_index = 0
if _target:
    _hit = _target if _target in _opcoes_chat else None
    if _hit is None:
        _tnorm = str(_target).strip().lower()
        for _op in _opcoes_chat:
            if str(_op).strip().lower() == _tnorm:
                _hit = _op
                break
    if _hit is not None:
        _default_index = _opcoes_chat.index(_hit)
        if "sel_contato_final_v2" in st.session_state:
            del st.session_state["sel_contato_final_v2"]

if not _opcoes_chat:
    st.info("Nenhum contato ou grupo disponível.")
    st.stop()

contato = st.selectbox(
    "Conversar com:",
    _opcoes_chat,
    format_func=_fmt_contato,
    index=_default_index,
    key="sel_contato_final_v2",
)

if not contato:
    st.info("Selecione um contato ou grupo pra iniciar a conversa.")
    st.stop()

_eh_grupo = contato in _grupo_label


# ── MARCADOR "novas mensagens" estilo WhatsApp ─────────────
# Captura os IDs que ESTAVAM não-lidos no momento que o usuário entrou
# nesta conversa. `_render_chat_messages` usa isso pra inserir um separador
# "⬇ N nova(s) mensagem(ns)" acima da primeira mensagem nova.
#
# Sem falso positivo:
#  - Quando o usuário PERMANECE na conversa e chega nova msg pelo fragmento,
#    `_ids_novas` em session_state NÃO é re-capturado (a nova msg fica
#    abaixo do separador, como esperado).
#  - Quando ele TROCA de contato e volta, recapturamos — como tudo já foi
#    marcado lido, `_ids_novas` fica vazio e o separador não aparece.
_chave_nl = "_chat_marcador_novas"
_cur_marc = st.session_state.get(_chave_nl)
if _cur_marc is None or _cur_marc[0] != contato:
    if _eh_grupo:
        _ids_novas = db.ids_nao_vistos_grupo(usuario, contato)
    else:
        _conn_nl = db.conectar()
        _c_nl = _conn_nl.cursor()
        try:
            _c_nl.execute(
                "SELECT id FROM chat "
                "WHERE remetente = %s AND destinatario = %s "
                "AND lido_em IS NULL",
                (contato, usuario),
            )
            _ids_novas = {int(r[0]) for r in _c_nl.fetchall()}
        finally:
            _conn_nl.close()
    st.session_state[_chave_nl] = (contato, _ids_novas)

# Marca como lidas (DM) / visto (grupo)
if _eh_grupo:
    db.marcar_grupo_visto(usuario, contato)
else:
    db.marcar_lidas(usuario, contato)

# Render do painel de mensagens (auto-refresh 2s via fragmento)
_render_chat_messages(usuario, contato, is_grupo=_eh_grupo)

# Campo de Envio (fora do fragmento; submete a página).
# Layout: text_area baixo (uma linha) + botão "➤" do mesmo tamanho ao lado.
st.markdown(
    """
    <style>
    /* Form do chat: borda fina, sem padding interno gordo */
    div[data-testid="stForm"].chat-send-form,
    form.chat-send-form {
        padding: 8px !important;
    }
    /* Botão Enviar: mesma altura do textarea, fonte grande no ➤, centralizado. */
    .chat-send-form div[data-testid="stFormSubmitButton"] button {
        font-size: 1.5rem !important;
        font-weight: 600 !important;
        height: 68px !important;
        padding: 0 !important;
        line-height: 1 !important;
        display: flex; align-items: center; justify-content: center;
    }
    /* Reduz padding interno do textarea (default é gordo demais aqui). */
    .chat-send-form textarea {
        min-height: 68px !important;
        padding: 10px 12px !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
# Limpa o rascunho após enviar (flag setada no envio). Tem que ser ANTES do
# text_area — não dá pra alterar a key de um widget já instanciado no mesmo run.
if st.session_state.pop("_chat_clear_draft", False):
    st.session_state["chat_msg_draft"] = ""

# Emoji picker (FORA do form — botão dentro de form submeteria o form).
# Clicar anexa o emoji ao rascunho (`chat_msg_draft`) e rerroda.
_EMOJIS = [
    "😀", "😁", "😂", "🤣", "😊", "😉", "😍", "😎", "👍", "👎",
    "🙏", "👏", "🎉", "🔥", "✅", "❌", "⚠️", "❓", "❗", "💡",
    "📌", "📎", "📅", "⏰", "✏️", "🚀", "💪", "🤝", "❤️", "🙂",
]
with st.popover("😀 Emoji"):
    _eg = st.columns(8)
    for _i, _e in enumerate(_EMOJIS):
        if _eg[_i % 8].button(_e, key=f"chat_emoji_{_i}"):
            st.session_state["chat_msg_draft"] = (
                st.session_state.get("chat_msg_draft", "") + _e
            )
            st.rerun()

with st.form("f_chat_v3_final", border=False):
    # Wrapper pra escopar o CSS via classe própria. Streamlit não deixa passar
    # `className` em st.form — workaround é wrapping via st.markdown anchor.
    st.markdown("<div class='chat-send-form'>", unsafe_allow_html=True)
    in_c1, in_c2 = st.columns([6, 1], gap="small")
    # text_area com key= (sem value=) pra o emoji conseguir anexar via
    # session_state. A limpeza no envio é feita pela flag `_chat_clear_draft`.
    in_c1.text_area(
        "Digite uma mensagem...",
        height=68,
        label_visibility="collapsed",
        placeholder="Digite uma mensagem...",
        key="chat_msg_draft",
    )
    _enviar = in_c2.form_submit_button(
        "➤", use_container_width=True, help="Enviar mensagem",
    )
    st.markdown("</div>", unsafe_allow_html=True)
    if _enviar:
        _msg = (st.session_state.get("chat_msg_draft", "") or "").strip()
        if _msg:
            # Timestamp completo "DD/MM/YYYY HH:MM" p/ separador de dias.
            conn = db.conectar()
            c = conn.cursor()
            _agora_iso = datetime.now().strftime("%d/%m/%Y %H:%M")
            c.execute(
                "INSERT INTO chat (remetente, destinatario, mensagem, data) "
                "VALUES (%s,%s,%s,%s)",
                (usuario, contato, _msg, _agora_iso),
            )
            conn.commit()
            conn.close()
            # Reabre na mesma conversa (grupo ou pessoa) + limpa o rascunho.
            st.session_state["_chat_force_target"] = contato
            st.session_state["_chat_clear_draft"] = True
            st.rerun()
