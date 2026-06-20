"""UI helpers stateless usados por várias views.

Tudo aqui é puro Python/Streamlit — nenhum acesso a banco direto. Banco
fica em `database` e dados cacheados em `core.data`. Isso permite que
cada view importe daqui sem trazer dependências pesadas junto.
"""

from __future__ import annotations

import hashlib as _hl
import html as _html
import re as _re
from datetime import datetime

import streamlit as st

import database as db


# ─── INICIALIZAÇÃO DE ESTADO (chamada uma vez no app.py) ─────────────
def _init_etapas():
    """Etapas default pro formulário de Novo Projeto.

    Está em session_state porque o usuário pode adicionar/remover etapas
    dinamicamente antes de submeter.
    """
    if "etapas_form" not in st.session_state:
        st.session_state.etapas_form = [
            {"nome": "Levantamento", "duracao_dias": 5, "dias_offset": 0},
            {"nome": "Projeto", "duracao_dias": 10, "dias_offset": 5},
        ]


# ─── TEMA (claro/escuro) ─────────────────────────────────────────────
def _eh_tema_claro():
    return st.session_state.get("tema", "dark") == "light"


def _cor_fonte_grafico():
    return "#1f2937" if _eh_tema_claro() else "#ffffff"


def _cor_grade_grafico():
    return "rgba(0,0,0,0.08)" if _eh_tema_claro() else "rgba(255,255,255,0.08)"


# ─── PERMISSÕES ──────────────────────────────────────────────────────
def _pode_editar():
    """True se o perfil atual pode criar/editar/excluir. Visualizador é read-only."""
    return st.session_state.get("perfil", "") in ("Gestor", "Projetista")


def _pode_gestor():
    """True somente para perfil Gestor."""
    return st.session_state.get("perfil", "") == "Gestor"


# ─── ESCOPO POR EQUIPE (SERVPEN / SERVPAR / GERAL) ──────────────────
# Controla o isolamento de visão entre equipes de gestão. A `equipe` do
# usuário é carregada na sessão no login/auto-login (ver app.py e
# core/auth_ui.py). Detalhes em docs/PROMPT-controle-equipes.md.
def _equipe_atual():
    """Equipe do usuário logado: 'SERVPEN' | 'SERVPAR' | 'GERAL'.
    Default 'SERVPEN' se ausente (sessão antiga / campo não carregado)."""
    return st.session_state.get("equipe", "SERVPEN")


def _ve_tudo():
    """True se o escopo do usuário NÃO filtra por equipe (Gestor Geral).
    Use antes de qualquer filtro de equipe: se True, mostra tudo."""
    return _equipe_atual() == "GERAL"


# ─── TEMPO ──────────────────────────────────────────────────────────
def _tempo_relativo(dt_input):
    """Converte data/hora em texto relativo: 'agora', 'há 5 min', 'há 2 h',
    'ontem', 'há 3 dias', ou data completa se mais antigo que 7 dias.
    Aceita datetime, ISO string ou 'HH:MM' (assume hoje)."""
    if dt_input is None or dt_input == "":
        return "—"
    agora = datetime.now()
    try:
        if isinstance(dt_input, datetime):
            dt = dt_input
        else:
            s = str(dt_input).strip().replace("T", " ")
            if len(s) <= 5 and ":" in s:
                hh, mm = s.split(":")
                dt = agora.replace(hour=int(hh), minute=int(mm),
                                   second=0, microsecond=0)
            elif "/" in s:
                try:
                    dt = datetime.strptime(s, "%d/%m/%Y")
                except ValueError:
                    dt = datetime.strptime(s, "%d/%m/%Y %H:%M")
            else:
                dt = datetime.fromisoformat(s)
    except Exception:
        return str(dt_input)
    diff = agora - dt
    secs = diff.total_seconds()
    if secs < 0:
        return dt.strftime("%d/%m")
    if secs < 60:
        return "agora"
    if secs < 3600:
        return f"há {int(secs // 60)} min"
    if secs < 86400:
        return f"há {int(secs // 3600)} h"
    if secs < 172800:
        return "ontem"
    if secs < 7 * 86400:
        return f"há {int(secs // 86400)} dias"
    return dt.strftime("%d/%m/%Y")


# ─── BADGES E TAGS ───────────────────────────────────────────────────
def _badge_status(status):
    """<span> HTML estilizado para um status de projeto."""
    s = str(status or "").strip()
    cores = {
        "EM ESPERA":  ("#0056b3", "#ffffff"),
        "🛑 Parado":  ("#d35400", "#ffffff"),
        "Parado":     ("#d35400", "#ffffff"),
        "Cancelado":  ("#801a1a", "#ffffff"),
        "Concluído":  ("#1a661a", "#ffffff"),
        "Concluido":  ("#1a661a", "#ffffff"),
    }
    bg, fg = cores.get(s, ("#4a5568", "#ffffff"))
    return (
        f"<span style='display:inline-block; background:{bg}; color:{fg}; "
        f"padding:2px 10px; border-radius:12px; font-size:11px; "
        f"font-weight:600; letter-spacing:0.5px; text-transform:uppercase;'>"
        f"{s}</span>"
    )


def _cor_tag(tag):
    """Devolve par (bg, fg) determinístico pra uma tag — mesma tag = mesma cor.

    Hash da string lowercased indexa numa paleta curada → cor estável entre
    páginas sem precisar catálogo persistente.
    """
    paleta = [
        ("#2b6cb0", "#ffffff"), ("#2f855a", "#ffffff"),
        ("#b7791f", "#ffffff"), ("#9c4221", "#ffffff"),
        ("#702459", "#ffffff"), ("#2c5282", "#ffffff"),
        ("#276749", "#ffffff"), ("#b03a2e", "#ffffff"),
        ("#553c9a", "#ffffff"), ("#0987a0", "#ffffff"),
    ]
    idx = int(_hl.md5(str(tag).strip().lower().encode()).hexdigest(), 16) % len(paleta)
    return paleta[idx]


def _render_tag_chips(tags_str, *, small=False):
    """Chips HTML coloridos a partir de string CSV de tags. Vazio se sem tags."""
    if not tags_str:
        return ""
    chips = []
    pad = "1px 6px" if small else "2px 8px"
    fz = "10px" if small else "11px"
    mar = "2px 3px 0 0"
    for t in db.parse_tags(tags_str):
        bg, fg = _cor_tag(t)
        safe = (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        chips.append(
            f"<span style='display:inline-block;background:{bg};color:{fg};"
            f"padding:{pad};border-radius:10px;font-size:{fz};font-weight:600;"
            f"margin:{mar};letter-spacing:0.3px;'>{safe}</span>"
        )
    return "".join(chips)


# ─── HEADER / EMPTY STATE / PILL SELECT ──────────────────────────────
def _section_header(icone, titulo, subtitulo=None, cor="#3b82f6"):
    """Header de seção padronizado — ícone + título + subtítulo opcional."""
    _sub = (
        f"<div style='color:#94a3b8;font-size:.82rem;margin-top:2px;'>{subtitulo}</div>"
        if subtitulo else ""
    )
    st.markdown(
        f"""
        <div style="border-left:4px solid {cor}; padding:6px 12px;
                    margin:4px 0 12px;">
            <div style="font-size:1.05rem; font-weight:700; color:#e5e7eb;
                        display:flex; align-items:center; gap:8px;">
                <span style="font-size:1.25rem;">{icone}</span>{titulo}
            </div>
            {_sub}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _empty_state(icone, titulo, mensagem="", cta_label=None, cta_key=None,
                 cor_borda="#3b82f6"):
    """Empty state convidativo: ícone grande + título + mensagem + CTA opcional.

    Retorna True se o usuário clicou no CTA, False caso contrário.
    """
    st.markdown(
        f"""
        <div style="background:rgba(255,255,255,0.02);
                    border:1px dashed rgba(255,255,255,0.12);
                    border-left:4px solid {cor_borda};
                    border-radius:10px; padding:24px 18px; text-align:center;
                    margin:8px 0;">
            <div style="font-size:2.4rem; margin-bottom:6px;">{icone}</div>
            <div style="font-size:1rem; font-weight:600; color:#e5e7eb;
                        margin-bottom:6px;">{titulo}</div>
            {f'<div style="font-size:.82rem; color:#94a3b8; max-width:520px; margin:0 auto;">{mensagem}</div>' if mensagem else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )
    if cta_label and cta_key:
        c1, c2, c3 = st.columns([1, 2, 1])
        return bool(c2.button(cta_label, key=cta_key, width="stretch"))
    return False


def _pill_select(container, label, options, *, default=None,
                 key=None, label_visibility="visible", help=None):
    """Pill-button select com fallback automático por versão do Streamlit.

    Usa st.segmented_control quando disponível (Streamlit ≥ 1.40);
    caso contrário cai pra st.radio(horizontal=True). API uniforme pra
    o chamador não ter que detectar versão.
    """
    if hasattr(st, "segmented_control"):
        return container.segmented_control(
            label, options=options, default=default,
            key=key, label_visibility=label_visibility, help=help,
        )
    # Fallback: radio horizontal — visual menos polido mas funciona.
    idx = 0
    if default is not None and default in options:
        idx = list(options).index(default)
    return container.radio(
        label, options=options, index=idx, horizontal=True,
        key=key, label_visibility=label_visibility, help=help,
    )


# ─── SANITIZAÇÃO DE TEXTO DO USUÁRIO PRO CHAT ────────────────────────
def _safe_chat_html(texto):
    """Escapa HTML + aplica markdown leve (**bold**, _italic_, `code`, links, \\n).

    Previne XSS no chat permitindo formatação básica.
    """
    t = _html.escape(str(texto or ""))
    t = _re.sub(
        r"`([^`\n]+)`",
        r"<code style='background:rgba(255,255,255,0.18);padding:1px 5px;"
        r"border-radius:4px;font-size:0.9em'>\1</code>",
        t,
    )
    t = _re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", t)
    t = _re.sub(r"(?<!\w)_([^_\n]+)_(?!\w)", r"<i>\1</i>", t)
    t = _re.sub(
        r"(https?://[^\s<]+)",
        r"<a href='\1' target='_blank' rel='noopener noreferrer' "
        r"style='color:#7dd3fc'>\1</a>",
        t,
    )
    return t.replace("\n", "<br>")


# ─── PLOTLY (estilo) ─────────────────────────────────────────────────
def _estiliza_plotly(fig):
    """Aplica fundo transparente + cor de fonte/grade/eixos/legenda/annotations
    conforme o tema atual. Chamar como ÚLTIMO passo de cada figura pra
    sobrescrever cores brancas herdadas do template."""
    cor = _cor_fonte_grafico()
    grade = _cor_grade_grafico()
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=cor),
        legend=dict(font=dict(color=cor), title=dict(font=dict(color=cor))),
    )
    fig.update_xaxes(tickfont=dict(color=cor), title_font=dict(color=cor),
                     gridcolor=grade, linecolor=grade, zerolinecolor=grade)
    fig.update_yaxes(tickfont=dict(color=cor), title_font=dict(color=cor),
                     gridcolor=grade, linecolor=grade, zerolinecolor=grade)
    fig.update_annotations(font_color=cor)
    return fig
