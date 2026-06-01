"""Renderização do painel de mensagens do chat (fragmento que polla a cada 2s).

`_render_chat_messages` é decorada com `@st.fragment(run_every="2s")` — só ela
re-roda a cada 2s, sem rerodar a página inteira. É o "tempo real barato" do chat.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st
import streamlit.components.v1 as _components

import database as db

from core.helpers import _safe_chat_html, _tempo_relativo
from core.ui_feedback import erro_humano


# CSS injetado uma vez por sessão (Streamlit deduplica HTML idêntico).
_CHAT_CSS = """
<style>
/* Bubbles estilo WhatsApp */
.wa-row { display:flex; margin: 2px 0; align-items:flex-end; }
.wa-row.mine { justify-content:flex-end; }
.wa-row.theirs { justify-content:flex-start; }
.wa-bub {
    max-width: 78%;
    padding: 6px 10px 4px;
    border-radius: 10px;
    font-size: 13.5px; line-height: 1.35;
    word-wrap: break-word; overflow-wrap: anywhere;
    box-shadow: 0 1px 2px rgba(0,0,0,0.25);
}
.wa-bub.mine   { background: #005c4b; color: #e9edef;
                 border-bottom-right-radius: 2px; }
.wa-bub.theirs { background: #202c33; color: #e9edef;
                 border-bottom-left-radius: 2px; }
.wa-meta { font-size: 10px; opacity: .6; margin-top: 2px;
           text-align: right; }
.wa-who  { font-size: 11px; font-weight: 600; color: #6ab1ff;
           margin-bottom: 1px; }
.wa-date-sep { text-align: center; margin: 12px 0 6px; }
.wa-date-sep span { background: rgba(255,255,255,0.06);
                    color: #94a3b8; font-size: 11px; padding: 2px 10px;
                    border-radius: 10px; }
.wa-empty { color: #6b7280; text-align: center;
            font-size: 13px; padding: 24px; }

/* COLAPSA gaps entre rows e dentro de st.columns no chat — o que causava
   o "monstrengo vertical" entre msgs próprias era a altura padrão das
   columns + popover esticando. Escopo: container do chat. */
[data-testid="stVerticalBlockBorderWrapper"]
    [data-testid="stHorizontalBlock"] {
    gap: 4px !important;
    margin-bottom: 0 !important;
}
[data-testid="stVerticalBlockBorderWrapper"]
    [data-testid="stHorizontalBlock"] > div {
    padding-top: 0 !important;
    padding-bottom: 0 !important;
}
/* Botão do popover compacto */
[data-testid="stVerticalBlockBorderWrapper"]
    [data-testid="stPopover"] button {
    min-height: 28px !important;
    padding: 2px 6px !important;
    font-size: 14px !important;
    line-height: 1 !important;
}
</style>
"""


@st.fragment(run_every="2s")
def _render_chat_messages(usuario, contato_nome):
    """Renderiza as bolhas estilo WhatsApp da conversa atual.

    Re-roda a cada 2s graças a `@st.fragment(run_every="2s")` — sem rerodar a
    página. Implementa: separador de dia (Hoje/Ontem/DD/MM), separador
    "⬇ N novas mensagens" (igual WhatsApp), edição inline, exclusão,
    marca "(editado)" e auto-scroll inteligente.
    """
    try:
        df_m = pd.read_sql_query(
            "SELECT * FROM chat WHERE (remetente = %s AND destinatario = %s) "
            "OR (remetente = %s AND destinatario = %s) ORDER BY id ASC",
            db.get_engine(),
            params=(usuario, contato_nome, contato_nome, usuario),
        )
    except Exception as exc:
        erro_humano(
            "Carregar mensagens do chat", exc,
            sugestao=(
                "A lista de mensagens vai recarregar automaticamente "
                "em 2 segundos. Pode continuar enviando — suas mensagens "
                "vão pro banco normalmente."
            ),
        )
        df_m = pd.DataFrame()

    st.markdown(_CHAT_CSS, unsafe_allow_html=True)

    chat_box = st.container(border=True, height=520)
    with chat_box:
        if df_m.empty:
            st.markdown(
                "<div class='wa-empty'>"
                "Nenhuma mensagem por aqui ainda — manda um oi 👋"
                "</div>",
                unsafe_allow_html=True,
            )
            return

        # Render: agrupa por dia com separador "hoje / ontem / DD/MM"
        _hoje_chat = datetime.now().date()
        _ultimo_dia = None

        # Marcador "novas mensagens" estilo WhatsApp — set de IDs que estavam
        # não-lidos quando o usuário entrou nesta conversa. Capturado pela
        # view do chat ANTES do db.marcar_lidas.
        _marc_state = st.session_state.get("_chat_marcador_novas")
        _ids_novas_marc = (
            _marc_state[1] if _marc_state and _marc_state[0] == contato_nome
            else set()
        )
        _separador_inserido = False

        # `enumerate` pra ter índice único como salvaguarda nos keys
        # (defensivo: se df_m tiver linha duplicada por bug de query/migração,
        # keys colidem; índice torna unique).
        for _idx_m, (_, m) in enumerate(df_m.iterrows()):
            sou_eu = m["remetente"] == usuario
            _msg_id = int(m["id"])
            _kfx = f"{_msg_id}_{_idx_m}"  # sufixo de key

            # ── SEPARADOR "novas mensagens" ────────────────────
            if (_ids_novas_marc and not _separador_inserido
                    and _msg_id in _ids_novas_marc):
                _qtd_novas = len(_ids_novas_marc)
                _txt_novas = (
                    f"{_qtd_novas} mensagem nova" if _qtd_novas == 1
                    else f"{_qtd_novas} mensagens novas"
                )
                st.markdown(
                    f"<div style='text-align:center;margin:14px 0 6px;"
                    f"display:flex;align-items:center;gap:8px;'>"
                    f"<div style='flex:1;height:1px;"
                    f"background:rgba(59,130,246,0.35);'></div>"
                    f"<span style='background:#1e3a5f;color:#93c5fd;"
                    f"font-size:11px;font-weight:700;padding:3px 12px;"
                    f"border-radius:12px;border:1px solid #3b82f6;'>"
                    f"⬇ {_txt_novas}</span>"
                    f"<div style='flex:1;height:1px;"
                    f"background:rgba(59,130,246,0.35);'></div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                _separador_inserido = True

            # Separador de dia
            try:
                _dt_msg = pd.to_datetime(str(m["data"]), errors="coerce")
                _dia = _dt_msg.date() if pd.notna(_dt_msg) else None
            except Exception:
                _dia = None
            if _dia and _dia != _ultimo_dia:
                if _dia == _hoje_chat:
                    _lbl_dia = "Hoje"
                elif _dia == _hoje_chat - pd.Timedelta(days=1):
                    _lbl_dia = "Ontem"
                else:
                    _lbl_dia = _dia.strftime("%d/%m/%Y")
                st.markdown(
                    f"<div class='wa-date-sep'><span>{_lbl_dia}</span></div>",
                    unsafe_allow_html=True,
                )
                _ultimo_dia = _dia

            # Está em modo edição?
            _em_edit = st.session_state.get(f"edit_mode_{_msg_id}", False)

            # Bolha + horário compactos
            _horario = (
                _dt_msg.strftime("%H:%M")
                if _dia is not None and pd.notna(_dt_msg)
                else _tempo_relativo(m["data"])
            )
            _who_html = (
                f"<div class='wa-who'>{m['remetente']}</div>"
                if not sou_eu else ""
            )
            _classe = "mine" if sou_eu else "theirs"

            # Marca "(editado)" se a mensagem foi modificada — estilo WhatsApp.
            # Coluna editado_em populada por editar_mensagem_chat.
            _edit_marker = ""
            _ed_raw = m.get("editado_em") if "editado_em" in m else None
            if _ed_raw is not None and not (
                isinstance(_ed_raw, float) and pd.isna(_ed_raw)
            ):
                try:
                    _ed_dt = pd.to_datetime(_ed_raw, errors="coerce")
                    if pd.notna(_ed_dt):
                        _edit_marker = (
                            " <span style='opacity:.55;font-style:italic;"
                            "font-size:9.5px;' "
                            f"title='Editado em "
                            f"{_ed_dt.strftime('%d/%m/%Y %H:%M')}'>"
                            "(editado)</span>"
                        )
                except Exception:
                    pass

            _bolha_html = (
                f"<div class='wa-row {_classe}'>"
                f"<div class='wa-bub {_classe}'>"
                f"{_who_html}"
                f"{_safe_chat_html(m['mensagem'])}"
                f"<div class='wa-meta'>{_edit_marker}{_horario}</div>"
                f"</div></div>"
            )

            if sou_eu:
                # Layout: bolha (95%) + popover ⋯ pequeno (5%).
                # SEM use_container_width no popover — assim ele fica com
                # altura natural (≈28px) em vez de esticar pra altura da
                # coluna.
                cm_main, cm_act = st.columns([0.95, 0.05])
                cm_main.markdown(_bolha_html, unsafe_allow_html=True)
                with cm_act:
                    with st.popover("⋯", help="Ações da mensagem"):
                        if st.button("✏️ Editar", key=f"ed_{_kfx}",
                                     use_container_width=True):
                            st.session_state[f"edit_mode_{_msg_id}"] = True
                            st.rerun(scope="fragment")
                        if st.button("🗑️ Apagar", key=f"del_{_kfx}",
                                     use_container_width=True):
                            db.excluir_mensagem_chat(_msg_id)
                            st.rerun(scope="fragment")
            else:
                st.markdown(_bolha_html, unsafe_allow_html=True)

            # Editor inline (logo abaixo da mensagem)
            if sou_eu and _em_edit:
                with st.container(border=True):
                    _novo_txt = st.text_input(
                        "Corrigir mensagem",
                        value=str(m["mensagem"]),
                        key=f"inp_{_kfx}",
                        label_visibility="collapsed",
                    )
                    ec1, ec2 = st.columns(2)
                    if ec1.button("✅ Salvar", key=f"sv_{_kfx}",
                                  use_container_width=True):
                        db.editar_mensagem_chat(_msg_id, _novo_txt)
                        st.session_state[f"edit_mode_{_msg_id}"] = False
                        st.rerun(scope="fragment")
                    if ec2.button("✖ Cancelar", key=f"cn_{_kfx}",
                                  use_container_width=True):
                        st.session_state[f"edit_mode_{_msg_id}"] = False
                        st.rerun(scope="fragment")

        # ── ÂNCORA + AUTO-SCROLL ─────────────────────────────
        # Comportamento (igual WhatsApp):
        #  - 1ª render desta conversa (ou troca de contato): força fim.
        #  - Refresh do fragmento (2s): só rola se já está perto do fim
        #    (≤ 200px). Se está lendo histórico no meio, não bagunça.
        st.markdown(
            "<div id='wa-bot-anchor'></div>", unsafe_allow_html=True,
        )

    # Detecta "primeiro render deste contato" comparando com o último contato
    # renderizado. Se mudou (ou nunca renderizou nada), força scroll pro fim.
    _chave_ult_render = "_chat_ult_render_contato"
    _eh_primeiro_render = (
        st.session_state.get(_chave_ult_render) != contato_nome
    )
    st.session_state[_chave_ult_render] = contato_nome
    _force_js = "true" if _eh_primeiro_render else "false"

    # Script vai DEPOIS de fechar o container, pra rodar quando o DOM da lista
    # já está montado. Roda dentro de iframe, então acessa o DOM principal via
    # window.parent.document.
    _components.html(
        f"""
        <script>
        (function () {{
            try {{
                var FORCE_BOTTOM = {_force_js};
                var doc = window.parent.document;
                var anchor = doc.getElementById('wa-bot-anchor');
                if (!anchor) return;

                // Acha o ancestor scrollable (st.container(height=N) põe
                // overflow-y:auto num div interno).
                var node = anchor.parentElement;
                var scrollable = null;
                while (node && node !== doc.body) {{
                    var cs = window.parent.getComputedStyle(node);
                    if (cs.overflowY === 'auto' || cs.overflowY === 'scroll') {{
                        scrollable = node;
                        break;
                    }}
                    node = node.parentElement;
                }}
                if (!scrollable) return;

                var diff = scrollable.scrollHeight
                         - scrollable.scrollTop
                         - scrollable.clientHeight;
                if (FORCE_BOTTOM || diff < 200) {{
                    scrollable.scrollTop = scrollable.scrollHeight;
                }}
            }} catch (e) {{ /* silencia erro de JS */ }}
        }})();
        </script>
        """,
        height=0,
    )
