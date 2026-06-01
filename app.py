"""Entry point do app — login + sidebar global + st.navigation.

Esta versão (modularizada) substitui os 6130 linhas anteriores. As 10 abas
viraram 10 arquivos em `views/` e os helpers compartilhados estão em `core/`.

Estrutura desta arquivo:
  1. Logger + imports
  2. set_page_config (PRIMEIRA chamada Streamlit, obrigatória)
  3. init session_state
  4. Query params (?_goto_chat=NOME do toast + ?t=TOKEN de sessão)
  5. DB init (criar tabelas + pasta anexos)
  6. Alertas da agenda do dia (toast)
  7. CSS global (base escuro + tema claro condicional)
  8. Se não autenticado → tela_login() + st.stop()
  9. Sidebar global (avatar, Meu Perfil, Sair, tema, badges, _global_notif)
 10. st.navigation com as 10 (ou 8 se não-Gestor) páginas
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

import pandas as pd
import streamlit as st

import database as db


# ═══════════════════════════════════════════════════════════════════════
# 1. LOGGER (antes de qualquer st.* ou import pesado)
# ═══════════════════════════════════════════════════════════════════════
# Em produção (systemd com StandardOutput=append) o log vai pro arquivo;
# em dev (streamlit run local) vai pro stdout.
_LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    force=True,
)
# Streamlit/Tornado/Plotly são muito verbosos em DEBUG — silencia.
if _LOG_LEVEL != "DEBUG":
    for noisy in (
        "tornado.access", "tornado.application", "watchdog",
        "matplotlib", "PIL", "fontTools", "sqlalchemy.engine",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)
log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# 2. CONFIGURAÇÃO DA PÁGINA (sempre o PRIMEIRO comando Streamlit)
# ═══════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="GESTÃO DE PROJETOS - SERVPEN",
    layout="wide",
    page_icon="🏢",
)


# ═══════════════════════════════════════════════════════════════════════
# 3. INICIALIZAÇÃO DE SESSION STATE
# ═══════════════════════════════════════════════════════════════════════
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
if "usuario" not in st.session_state:
    st.session_state.usuario = None
if "perfil" not in st.session_state:
    st.session_state.perfil = "Gestor"
if "lista_checklist" not in st.session_state:
    st.session_state.lista_checklist = [
        "Água Pluvial", "Arquitetura", "Ar condicionado", "Esgoto",
        "Especificação Técnica", "Estrutura", "Exaustão", "Gás", "HVAC",
        "Incêndio", "Laudo", "Levantamento", "Lógica",
        "Memorial Descritivo", "Planilha", "Topografia",
    ]
if "tema" not in st.session_state:
    st.session_state.tema = "dark"


# ═══════════════════════════════════════════════════════════════════════
# 4. QUERY PARAMS — toast de chat + token de sessão
# ═══════════════════════════════════════════════════════════════════════
# Persistência de login via token na URL:
# A tabela 'sessoes' armazena tokens opacos (24 chars) associados a cada
# usuário logado. Token vai no query param `?t=...` → sobrevive F5 e
# fechar/abrir navegador. Logout deleta a linha do banco (invalidação real).
db.criar_tabela_sessoes()
db.limpar_sessoes_expiradas()

# Toast custom "📨 Ver mensagem" navega via `?_goto_chat=NOME`. Lemos aqui
# (após o parse natural de query params do Streamlit), setamos a flag que
# a view Chat vai consumir e limpamos o param da URL pra não persistir.
#
# `_chat_force_target` é a ÚNICA fonte da pré-seleção de contato no chat.
# Consumido em views/chat.py com `index=` explícito + delete da widget key,
# pra ser à prova de cache interno do Streamlit.
_goto_chat = st.query_params.get("_goto_chat")
if _goto_chat:
    st.session_state["_chat_force_target"] = _goto_chat
    try:
        del st.query_params["_goto_chat"]
    except KeyError:
        pass

# Auto-login por token (sobrevive F5)
if not st.session_state.get("autenticado", False):
    _tok = st.query_params.get("t")
    _sess = db.validar_sessao(_tok)
    if _sess:
        st.session_state.autenticado = True
        st.session_state.usuario = _sess[0]
        st.session_state.perfil = _sess[1]

# ── ANTI-FANTASMA DO TOAST DE CHAT ─────────────────────────────────────
# Bug histórico: clicar em "📨 Ver mensagem" no toast fazia page-reload
# (`<a target="_top">`). Page-reload ZERA o session_state. No primeiro tick
# do fragmento `_global_notif` (a cada 10s), `_chat_ultimas_contagens` volta
# vazio → ele comparava `{Maria: 5}` (atual) vs `{}` (vazio) e concluía
# "Maria tem 5 mensagens novas!" — disparando o toast de novo, MESMO que o
# user acabou de clicar nele e já está no chat.
#
# Fix: inicializar `_chat_ultimas_contagens` com o estado real do banco
# logo após o login. Assim o primeiro tick do fragmento vê (Maria: 5) ==
# (Maria: 5) e NÃO dispara toast falso.
if (
    st.session_state.get("autenticado", False)
    and "_chat_ultimas_contagens" not in st.session_state
):
    try:
        st.session_state["_chat_ultimas_contagens"] = dict(
            db.listar_remetentes_com_nao_lidas(st.session_state.usuario)
        )
    except Exception:
        # Sem ler do banco aqui ainda é OK — pior caso o user vê um toast
        # extra. Não vale travar o boot inteiro por isso.
        st.session_state["_chat_ultimas_contagens"] = {}


# ═══════════════════════════════════════════════════════════════════════
# 5. INICIALIZAÇÃO DO BANCO E PASTAS
# ═══════════════════════════════════════════════════════════════════════
db.criar_tabelas()
db.criar_tabela_agenda()
db.criar_tabela_progresso()
db.criar_tabela_arquivos()
db.criar_tabela_auditoria()
db.criar_tabela_mencoes()
db.criar_tabela_diario_leituras()
db.migrar_status_em_espera()

if not os.path.exists("anexos"):
    os.makedirs("anexos")


# ═══════════════════════════════════════════════════════════════════════
# 6. ALERTAS DA AGENDA DO DIA (toast)
# ═══════════════════════════════════════════════════════════════════════
try:
    df_agenda_boot = pd.read_sql("SELECT * FROM agenda", db.get_engine())
    hoje = datetime.now().date()
    if not df_agenda_boot.empty:
        df_agenda_boot["data_inicio_dt"] = pd.to_datetime(
            df_agenda_boot["data_inicio"],
        ).dt.date
        alertas_hoje = df_agenda_boot[
            df_agenda_boot["data_inicio_dt"] == hoje
        ]
        for _, alerta in alertas_hoje.iterrows():
            st.toast(
                f"🔔 **HOJE:** {alerta['titulo']} ({alerta['tipo']})",
                icon="📅",
            )
except Exception:
    # Sem agenda, sem alertas. Não trava o app.
    pass


# ═══════════════════════════════════════════════════════════════════════
# 7. CSS GLOBAL (base escuro + responsivo)
# ═══════════════════════════════════════════════════════════════════════
st.markdown("""
    <style>
    /* Esconde menu padrão do Streamlit (3 pontinhos) e "Made with Streamlit". */
    [data-testid="stMainMenu"], #MainMenu,
    [data-testid="stDecoration"],
    footer, [data-testid="stStatusWidget"] { display: none !important; }
    [data-testid="stHeader"] { background: transparent !important; }

    /* === RESPIRO VISUAL === */
    .main .block-container {
        padding-top: 1.5rem !important;
        padding-bottom: 4rem !important;
        max-width: 1400px;
    }

    /* Headers de seção com underline sutil */
    .main h1 {
        font-size: 1.85rem !important;
        margin-bottom: 0.6rem !important;
        padding-bottom: 0.5rem;
        border-bottom: 2px solid rgba(0, 86, 179, 0.35);
    }
    .main h2 {
        margin-top: 1.8rem !important;
        margin-bottom: 0.7rem !important;
        font-size: 1.4rem !important;
    }
    .main h3 {
        margin-top: 1.3rem !important;
        margin-bottom: 0.5rem !important;
        font-size: 1.15rem !important;
        opacity: 0.92;
    }

    [data-testid="stDivider"], hr {
        margin: 1.5rem 0 !important;
        opacity: 0.5;
    }

    [data-testid="stVerticalBlockBorderWrapper"] {
        padding: 14px 16px !important;
        margin-bottom: 12px !important;
        border-radius: 10px !important;
    }

    [data-testid="stVerticalBlock"] > [data-testid="stVerticalBlock"] > div {
        margin-bottom: 4px;
    }

    [data-testid="stForm"] {
        padding: 18px !important;
        border-radius: 12px !important;
    }

    [data-testid="stExpander"] {
        border-radius: 10px !important;
        margin-bottom: 12px;
    }
    [data-testid="stExpander"] summary {
        padding: 10px 14px !important;
        font-weight: 500;
    }

    .main .stButton > button,
    .main [data-testid="stFormSubmitButton"] > button {
        border-radius: 8px;
        transition: transform 0.1s, box-shadow 0.2s;
    }
    .main .stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 10px rgba(0,0,0,0.15);
    }

    section[data-testid="stSidebar"] {
        padding-top: 0.5rem;
    }
    section[data-testid="stSidebar"] .stButton > button {
        border-radius: 8px;
    }

    [data-testid="stMetric"] {
        background-color: transparent !important;
        border-radius: 15px;
        padding: 20px !important;
        box-shadow: 4px 4px 10px rgba(0,0,0,0.4) !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
    }
    div[data-testid="stMetric"]:nth-of-type(1) { background-color: #003366 !important; border-left: 8px solid #00d4ff !important; }
    div[data-testid="stMetric"]:nth-of-type(2) { background-color: #8c4a00 !important; border-left: 8px solid #ff9f43 !important; }
    div[data-testid="stMetric"]:nth-of-type(3) { background-color: #660000 !important; border-left: 8px solid #ff4d4d !important; }
    div[data-testid="stMetric"]:nth-of-type(4) { background-color: #1a4314 !important; border-left: 8px solid #2ecc71 !important; }
    [data-testid="stMetricLabel"] > div, [data-testid="stMetricValue"] > div { color: #ffffff !important; }

    /* Cards de status */
    .card-espera {
        background-color: #3b1f6e;
        color: white;
        padding: 18px;
        border-radius: 12px;
        border-left: 10px solid #7c3aed;
        margin-bottom: 15px;
    }
    .card-ativo { background-color: #0056b3; color: white; padding: 18px; border-radius: 12px; border-left: 10px solid #00d4ff; margin-bottom: 15px; }
    .card-parado { background-color: #d35400; color: white; padding: 18px; border-radius: 12px; border-left: 10px solid #ff9f43; margin-bottom: 15px; }
    .card-cancelado { background-color: #801a1a; color: white; padding: 18px; border-radius: 12px; border-left: 10px solid #ff4d4d; margin-bottom: 15px; }
    .card-concluido { background-color: #1a661a; color: white; padding: 18px; border-radius: 12px; border-left: 10px solid #4dff4d; margin-bottom: 15px; }

    .card-projetista {
        background: linear-gradient(145deg, #1e1e1e, #252525);
        border-radius: 15px; padding: 20px; margin-bottom: 20px;
        border: 1px solid rgba(255, 255, 255, 0.05);
        box-shadow: 5px 5px 15px rgba(0, 0, 0, 0.3);
        transition: transform 0.3s;
    }
    .card-projetista:hover { transform: translateY(-5px); }
    .nome-projetista {
        font-size: 1.25rem; font-weight: bold; margin-bottom: 12px;
        display: flex; align-items: center; gap: 10px;
    }
    .demanda-texto { font-size: 0.9rem; color: #cccccc; line-height: 1.5; }
    .badge-projeto {
        background-color: rgba(255, 255, 255, 0.03);
        padding: 4px 10px; border-radius: 8px; font-size: 0.8rem;
        margin-top: 6px; display: inline-block;
        border: 1px solid rgba(255, 255, 255, 0.08);
    }

    /* === RESPONSIVIDADE (tablet) === */
    @media (max-width: 992px) {
        .main .block-container { padding: 1.4rem 1rem !important; }
        [data-testid="stMetric"] { padding: 14px !important; }
        .card-ativo, .card-parado, .card-cancelado, .card-concluido {
            padding: 12px; font-size: 0.9rem;
        }
        .card-espera { padding: 12px; font-size: .9rem; }
        .card-projetista { padding: 14px; }
        .nome-projetista { font-size: 1.05rem; }
        h1 { font-size: 1.7rem !important; }
        h2 { font-size: 1.35rem !important; }
    }

    /* === RESPONSIVIDADE (celular) === */
    @media (max-width: 640px) {
        .main .block-container { padding: 0.9rem 0.55rem !important; }
        [data-testid="stMetric"] { padding: 10px !important; box-shadow: 2px 2px 6px rgba(0,0,0,0.3) !important; }
        [data-testid="stMetricLabel"] > div { font-size: 0.7rem !important; }
        [data-testid="stMetricValue"] > div { font-size: 1.45rem !important; }
        h1 { font-size: 1.35rem !important; }
        h2 { font-size: 1.15rem !important; }
        h3 { font-size: 1rem !important; }
        .card-espera { padding: 10px; }
        .card-projetista { padding: 12px; margin-bottom: 12px; }
        .card-projetista .nome-projetista { font-size: 0.95rem; }
        .demanda-texto { font-size: 0.82rem; }
        .badge-projeto { font-size: 0.72rem; padding: 3px 8px; }
    }
    </style>
""", unsafe_allow_html=True)

# Tema claro: override aplicado sob demanda
from core.helpers import _eh_tema_claro  # noqa: E402 — depende do CSS já injetado

if _eh_tema_claro():
    st.markdown("""
        <style>
        .stApp { background-color: #f4f6f9 !important; color: #1f2937 !important; }
        .stApp > header { background-color: transparent !important; }
        section[data-testid="stSidebar"] { background-color: #ffffff !important; border-right: 1px solid #e5e7eb; }
        section[data-testid="stSidebar"] * { color: #1f2937 !important; }

        .stMarkdown, .stMarkdown p, .stMarkdown li, .stMarkdown span,
        [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] * {
            color: #1f2937 !important;
        }
        h1, h2, h3, h4, h5, h6 { color: #111827 !important; }

        div[data-testid="stMetric"]:nth-of-type(1) { background-color: #1e88e5 !important; }
        div[data-testid="stMetric"]:nth-of-type(2) { background-color: #f57c00 !important; }
        div[data-testid="stMetric"]:nth-of-type(3) { background-color: #e53935 !important; }
        div[data-testid="stMetric"]:nth-of-type(4) { background-color: #43a047 !important; }

        .stTextInput input, .stTextArea textarea,
        .stSelectbox > div > div, .stMultiSelect > div > div,
        .stDateInput input, .stNumberInput input {
            background-color: #ffffff !important;
            color: #1f2937 !important;
            border-color: #d1d5db !important;
        }

        .card-projetista {
            background: #ffffff !important;
            border: 1px solid #e5e7eb !important;
            box-shadow: 0 2px 8px rgba(0,0,0,0.06) !important;
            color: #1f2937;
        }
        .demanda-texto { color: #4b5563 !important; }
        .badge-projeto {
            background-color: rgba(0,0,0,0.04) !important;
            border-color: rgba(0,0,0,0.08) !important;
            color: #1f2937;
        }

        [data-testid="stExpander"] { background-color: #ffffff !important; border: 1px solid #e5e7eb !important; }
        [data-testid="stForm"] { background-color: #fafbfc; border-radius: 12px; padding: 14px; border: 1px solid #e5e7eb; }

        .stButton > button,
        [data-testid="stFormSubmitButton"] > button,
        [data-testid="baseButton-secondary"],
        [data-testid="baseButton-primary"] {
            background-color: #f3f4f6 !important;
            color: #1f2937 !important;
            border: 1px solid #d1d5db !important;
            box-shadow: 0 1px 2px rgba(0,0,0,0.04) !important;
        }
        .stButton > button:hover,
        [data-testid="stFormSubmitButton"] > button:hover {
            background-color: #e5e7eb !important;
            border-color: #9ca3af !important;
            color: #111827 !important;
        }
        section[data-testid="stSidebar"] .stButton > button,
        section[data-testid="stSidebar"] [data-testid="stFormSubmitButton"] > button {
            background-color: #f3f4f6 !important;
            color: #1f2937 !important;
            border: 1px solid #d1d5db !important;
        }

        [data-testid="stAlert"] {
            background-color: #eff6ff !important;
            border-left: 4px solid #3b82f6 !important;
            color: #1f2937 !important;
        }
        [data-testid="stAlert"][kind="success"],
        [data-testid="stNotification"][kind="success"] {
            background-color: #ecfdf5 !important;
            border-left-color: #10b981 !important;
        }
        [data-testid="stAlert"][kind="warning"],
        [data-testid="stNotification"][kind="warning"] {
            background-color: #fffbeb !important;
            border-left-color: #f59e0b !important;
        }
        [data-testid="stAlert"][kind="error"],
        [data-testid="stNotification"][kind="error"] {
            background-color: #fef2f2 !important;
            border-left-color: #ef4444 !important;
        }
        [data-testid="stAlert"] *,
        [data-testid="stAlert"] [data-testid="stMarkdownContainer"] *,
        [data-testid="stNotification"] *,
        [data-testid="stNotificationContent"] * {
            color: #1f2937 !important;
        }

        /* Cards de membros/Diário com background #1E1E1E → claros */
        div[style*="background-color: #1E1E1E"],
        div[style*="background-color:#1E1E1E"] {
            background-color: #ffffff !important;
            border: 1px solid #e5e7eb !important;
            box-shadow: 0 2px 6px rgba(0,0,0,0.05) !important;
        }
        div[style*="background-color: #1E1E1E"] [style*="color: white"],
        div[style*="background-color:#1E1E1E"] [style*="color: white"],
        div[style*="background-color: #1E1E1E"] [style*="color:#fff"],
        div[style*="background-color:#1E1E1E"] [style*="color:#fff"] {
            color: #111827 !important;
        }
        div[style*="background-color: #1E1E1E"] [style*="color: #EEE"],
        div[style*="background-color: #1E1E1E"] [style*="color: #AAA"],
        div[style*="background-color:#1E1E1E"] [style*="color: #EEE"],
        div[style*="background-color:#1E1E1E"] [style*="color: #AAA"] {
            color: #6b7280 !important;
        }

        /* Bolha de chat recebido (#333) → cinza claro */
        div[style*="background: #333"], div[style*="background:#333"] {
            background: #e5e7eb !important;
            border-color: #d1d5db !important;
        }
        div[style*="background: #333"] [style*="color: white"],
        div[style*="background:#333"] [style*="color: white"] {
            color: #1f2937 !important;
        }

        /* Cards coloridos mantêm texto branco */
        .card-ativo, .card-parado, .card-cancelado, .card-concluido,
        .card-ativo *, .card-parado *, .card-cancelado *, .card-concluido * {
            color: white !important;
        }
        [data-testid="stMetric"] *, [data-testid="stMetric"] [data-testid="stMetricLabel"] > div,
        [data-testid="stMetric"] [data-testid="stMetricValue"] > div {
            color: white !important;
        }
        </style>
    """, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════
# 8. TELA DE LOGIN (se não autenticado)
# ═══════════════════════════════════════════════════════════════════════
if not st.session_state.autenticado:
    from core.auth_ui import tela_login
    tela_login()
    st.stop()


# ═══════════════════════════════════════════════════════════════════════
# 9. SIDEBAR GLOBAL (renderiza em TODAS as páginas)
# ═══════════════════════════════════════════════════════════════════════
from core.auth_ui import _avatar_circular_html, _dialog_meu_perfil
from core.helpers import _pode_editar, _pode_gestor
from core.notif import _global_notif

with st.sidebar:
    # Avatar circular + identificação no topo
    _me_side = db.obter_usuario(st.session_state.usuario) or {}
    st.markdown(
        _avatar_circular_html(_me_side.get("avatar_path"), size=88),
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<div style='text-align:center;font-weight:700;font-size:1.05rem;"
        f"margin-top:8px'>{st.session_state.usuario}</div>"
        f"<div style='text-align:center;opacity:0.7;font-size:0.8rem;"
        f"margin-bottom:8px'>"
        f"{st.session_state.get('perfil', 'Gestor')}</div>",
        unsafe_allow_html=True,
    )

    if st.button("👤 Meu Perfil", use_container_width=True,
                 key="btn_meu_perfil"):
        _dialog_meu_perfil()

    if st.button("🔴 Sair do Sistema", use_container_width=True,
                 key="btn_sair"):
        db.log_aud(st.session_state.usuario, "logout", "sessao", None, "")
        db.deletar_sessao(st.query_params.get("t"))
        st.query_params.clear()
        st.session_state.autenticado = False
        st.session_state.usuario = None
        st.session_state.perfil = None
        st.rerun()

    # Toggle de Tema (Claro / Escuro)
    st.divider()
    _label_botao_tema = (
        "☀️ Mudar para Tema Claro" if not _eh_tema_claro()
        else "🌙 Mudar para Tema Escuro"
    )
    if st.button(_label_botao_tema, use_container_width=True,
                 key="btn_tema"):
        st.session_state.tema = (
            "light" if st.session_state.tema == "dark" else "dark"
        )
        st.rerun()
    st.caption(
        f"Tema atual: **{'Claro' if _eh_tema_claro() else 'Escuro'}**"
    )

    # Aviso de Modo Visualização (read-only)
    if not _pode_editar():
        st.warning(
            "👁️ **Modo Visualização**: você não pode criar, editar ou "
            "excluir registros.",
            icon="🔒",
        )

    # ── BADGES DE PENDÊNCIAS (Diário + Chat) ──────────────────
    # Substitui as contagens que ficavam nos labels das tabs. Como
    # st.navigation aceita só título estático, mostramos aqui.
    # Diário respeita visibilidade do usuário (mesma lógica do _load_df_p).
    from core.data import _load_df_p
    _df_p_badge = _load_df_p(
        st.session_state.usuario, st.session_state.get("perfil"),
    )
    _projs_visiveis = (
        None if _pode_gestor()
        else (_df_p_badge["id"].tolist() if not _df_p_badge.empty else [])
    )
    _nao_lidos_diario = db.total_nao_lidos_diario_visivel(
        st.session_state.usuario, _projs_visiveis,
    )
    _mencoes_pend = db.contar_mencoes_pendentes(st.session_state.usuario)
    _total_diario_badge = _nao_lidos_diario + _mencoes_pend
    _qtd_nao_lidas_chat = db.contar_nao_lidas(st.session_state.usuario)

    if _total_diario_badge or _qtd_nao_lidas_chat:
        st.divider()
        st.caption("📬 Pendências:")
        if _total_diario_badge:
            st.markdown(
                f"<div style='padding:6px 10px;background:rgba(239,68,68,0.10);"
                f"border-left:3px solid #ef4444;border-radius:6px;"
                f"margin-bottom:4px;font-size:.85rem;'>"
                f"📝 <b>{_total_diario_badge}</b> no Diário</div>",
                unsafe_allow_html=True,
            )
        if _qtd_nao_lidas_chat:
            st.markdown(
                f"<div style='padding:6px 10px;background:rgba(239,68,68,0.10);"
                f"border-left:3px solid #ef4444;border-radius:6px;"
                f"font-size:.85rem;'>"
                f"💬 <b>{_qtd_nao_lidas_chat}</b> no Chat</div>",
                unsafe_allow_html=True,
            )

    # ── FRAGMENTO GLOBAL DE NOTIFICAÇÕES (toast de msg nova) ───
    # MUITO IMPORTANTE: tem que ficar montado na sidebar, NÃO numa view.
    # Sidebar renderiza em TODAS as páginas do st.navigation, então o
    # fragmento (run_every=10s) continua disparando o toast estilo
    # WhatsApp em qualquer view onde o user esteja.
    _global_notif(st.session_state.usuario)


# ═══════════════════════════════════════════════════════════════════════
# 10. NAVEGAÇÃO (st.navigation + st.Page)
# ═══════════════════════════════════════════════════════════════════════
# Cada st.Page é um SCRIPT independente. Apenas a página ativa é executada
# a cada interação do usuário — esse é o ganho principal vs st.tabs
# (que rodava as 10 abas a cada clique). Streamlit 1.36+ obrigatório.

#
# IMPORTANTE — `url_path` explícito em todas as páginas (exceto a default).
# Sem isso, o Streamlit infere o slug do filename. Funcionaria, mas seria
# implícito. Aqui fixamos pra:
#   1) URL estável mesmo se renomear o arquivo
#   2) Toast de "📨 Ver mensagem" no chat poder navegar pra `<base>/chat`
#      direto (ver core/notif.py — o JS precisa do slug "chat").
#   3) `core/notif.py:KNOWN_SLUGS` reflete EXATAMENTE essa lista. Se mudar
#      um url_path aqui, atualize lá também.
#
# Convenção: lowercase ASCII com underscore (sem acentos, sem hífen). O
# JavaScript do toast detecta "qual é o slug atual" comparando o último
# segmento do pathname com essa lista.
_pages_gerais = [
    st.Page("views/dashboard.py", title="Dashboard", icon="📊",
            default=True),  # default → URL = base do app (sem slug)
    st.Page("views/kanban.py", title="Kanban", icon="📋",
            url_path="kanban"),
    st.Page("views/novo_projeto.py", title="Novo Projeto", icon="➕",
            url_path="novo_projeto"),
    st.Page("views/diario.py", title="Diário", icon="📝",
            url_path="diario"),
    st.Page("views/arquivos.py", title="Arquivos", icon="📁",
            url_path="arquivos"),
    st.Page("views/equipe.py", title="Equipe", icon="👥",
            url_path="equipe"),
    st.Page("views/chat.py", title="Chat", icon="💬",
            url_path="chat"),
    st.Page("views/agenda.py", title="Agenda", icon="📅",
            url_path="agenda"),
]
_pages_gestor = [
    st.Page("views/auditoria.py", title="Auditoria", icon="🛡️",
            url_path="auditoria"),
    st.Page("views/acessos.py", title="Acessos", icon="🔑",
            url_path="acessos"),
]

# Gestor vê todas; Projetista/Visualizador ficam sem Auditoria/Acessos.
pages = (
    _pages_gerais + _pages_gestor if _pode_gestor() else _pages_gerais
)

pg = st.navigation(pages)
pg.run()


# ═══════════════════════════════════════════════════════════════════════
# RODAPÉ (renderiza após a página ativa, em todas as telas logadas)
# ═══════════════════════════════════════════════════════════════════════
st.divider()
st.markdown(
    """
    <div style='text-align: center; color: #808495; font-size: 0.85em; line-height: 1.6; padding-top: 10px; padding-bottom: 20px;'>
        <b>Engenheira Sara Nolasco</b><br>
        Software Gestão de Projetos NB | Versão 1.0<br>
        © 2026 - Todos os direitos reservados
    </div>
    """,
    unsafe_allow_html=True,
)
