"""Aba Auditoria (somente Gestor) — trilha cronológica de ações.

Listagem com filtros por usuário/ação + export CSV. Usa HTML manual em vez
de st.dataframe porque essa CPU (Athlon II) não tem AVX2 pro pyarrow.
"""

from __future__ import annotations

import csv as _csv
import html as _html
import io as _io
from datetime import datetime

import pandas as pd
import streamlit as st

import database as db
import relatorios

from core.data import _load_df_u
from core.helpers import _pode_gestor, _tempo_relativo


# Guard de perfil — Gestor-only
if not _pode_gestor():
    st.error("🛑 Você não tem permissão para acessar Auditoria.")
    st.stop()

df_u = _load_df_u()

st.header("🛡️ Trilha de Auditoria")
st.caption(
    "Registro cronológico de quem fez o quê — login/logout, criação, edição "
    "e exclusão de projetos, usuários e arquivos."
)

col_af1, col_af2, col_af3 = st.columns([2, 2, 1])
usuarios_filtro = ["(todos)"] + (df_u["nome"].tolist() if not df_u.empty else [])
filtro_aud_user = col_af1.selectbox("Usuário", usuarios_filtro, key="aud_user")
filtro_aud_acao = col_af2.text_input(
    "Ação contém", placeholder="ex.: excluir, login, upload", key="aud_acao",
)
filtro_aud_limit = col_af3.number_input(
    "Linhas", min_value=20, max_value=2000, value=200, step=20, key="aud_limit",
)

linhas = db.listar_auditoria(
    limit=int(filtro_aud_limit),
    filtro_usuario=None if filtro_aud_user == "(todos)" else filtro_aud_user,
    filtro_acao=filtro_aud_acao or None,
)

col_m1, col_m2 = st.columns([3, 1])
col_m1.metric("Eventos exibidos", len(linhas))
if linhas:
    # Export CSV (Python puro — sem pandas/pyarrow)
    _buf = _io.StringIO()
    _w = _csv.writer(_buf)
    _w.writerow(["ID", "Quando", "Usuário", "Ação", "Entidade", "ID Entidade",
                 "Detalhes"])
    _w.writerows(linhas)
    col_m2.download_button(
        "📥 Exportar CSV", _buf.getvalue().encode("utf-8"),
        file_name=f"auditoria_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv", width="stretch",
    )
    st.divider()

    # Cor por tipo de ação
    def _cor_acao(a):
        a = (a or "").lower()
        if "excluir" in a or "falha" in a:
            return "#ef4444"
        if "login" in a or "logout" in a:
            return "#6366f1"
        if "editar" in a:
            return "#f59e0b"
        if "upload" in a:
            return "#10b981"
        return "#6b7280"

    # Tabela HTML manual (pyarrow não roda em Athlon II — SIGILL).
    linhas_html = []
    for id_l, data_l, usuario_l, acao_l, ent_l, eid_l, det_l in linhas:
        cor = _cor_acao(acao_l)
        linhas_html.append(
            f"<tr>"
            f"<td style='white-space:nowrap;opacity:0.7;font-size:0.85em'>"
            f"{_tempo_relativo(data_l)}</td>"
            f"<td><b>{_html.escape(str(usuario_l or '—'))}</b></td>"
            f"<td><span style='background:{cor};color:#fff;padding:2px 8px;"
            f"border-radius:8px;font-size:0.78em;font-weight:600'>"
            f"{_html.escape(str(acao_l))}</span></td>"
            f"<td>{_html.escape(str(ent_l or ''))}</td>"
            f"<td style='opacity:0.7'>"
            f"{eid_l if eid_l is not None else ''}</td>"
            f"<td style='font-size:0.85em;opacity:0.85'>"
            f"{_html.escape(str(det_l or ''))}</td>"
            f"</tr>"
        )
    tabela = (
        "<div style='max-height:560px;overflow-y:auto;"
        "border:1px solid rgba(128,128,128,0.2);border-radius:8px'>"
        "<table style='width:100%;border-collapse:collapse;font-size:0.9rem'>"
        "<thead style='position:sticky;top:0;background:rgba(0,86,179,0.12);"
        "backdrop-filter:blur(4px)'>"
        "<tr>"
        "<th style='padding:8px 10px;text-align:left'>Quando</th>"
        "<th style='padding:8px 10px;text-align:left'>Usuário</th>"
        "<th style='padding:8px 10px;text-align:left'>Ação</th>"
        "<th style='padding:8px 10px;text-align:left'>Entidade</th>"
        "<th style='padding:8px 10px;text-align:left'>ID</th>"
        "<th style='padding:8px 10px;text-align:left'>Detalhes</th>"
        "</tr></thead><tbody>"
        + "".join(linhas_html) +
        "</tbody></table></div>"
    )
    st.markdown(tabela, unsafe_allow_html=True)
else:
    st.info("🔍 Nenhum evento encontrado para os filtros atuais.")


# ══════════════════════════════════════════════════════════════════════
# HISTÓRICO DE ALTERAÇÕES DE PROJETOS (antes/depois)
# ══════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("🕓 Histórico de Alterações de Projetos")
st.caption(
    "Mudanças em campos de projetos JÁ INICIADOS (responsável, prazos e "
    "demais campos), com valor anterior e novo. Projetos 'Em Espera' não "
    "geram histórico."
)

_df_alt = pd.read_sql(
    "SELECT data, projeto_nome, campo, valor_anterior, valor_novo, autor "
    "FROM projeto_alteracoes ORDER BY data DESC LIMIT 2000",
    db.get_engine(),
)

_ca1, _ca2 = st.columns([3, 1])
_ca1.metric("Alterações registradas", len(_df_alt))
if not _df_alt.empty:
    _ca2.download_button(
        "📊 Exportar Excel",
        data=relatorios.gerar_excel_historico(_df_alt),
        file_name=f"historico_alteracoes_"
                  f"{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument."
             "spreadsheetml.sheet",
        width="stretch",
    )

    _linhas_alt = []
    for _, _r in _df_alt.iterrows():
        _dt = pd.to_datetime(_r["data"], errors="coerce")
        _quando = _dt.strftime("%d/%m/%Y %H:%M") if pd.notna(_dt) else "—"
        _linhas_alt.append(
            f"<tr>"
            f"<td style='white-space:nowrap;opacity:.7;font-size:.85em'>"
            f"{_quando}</td>"
            f"<td>{_html.escape(str(_r.get('projeto_nome') or '—'))}</td>"
            f"<td><b>{_html.escape(str(_r.get('campo') or ''))}</b></td>"
            f"<td style='color:#ef4444'>"
            f"{_html.escape(str(_r.get('valor_anterior') or '—'))}</td>"
            f"<td style='color:#10b981'>"
            f"{_html.escape(str(_r.get('valor_novo') or '—'))}</td>"
            f"<td style='opacity:.8'>"
            f"{_html.escape(str(_r.get('autor') or '—'))}</td>"
            f"</tr>"
        )
    st.markdown(
        "<div style='max-height:480px;overflow-y:auto;"
        "border:1px solid rgba(128,128,128,0.2);border-radius:8px'>"
        "<table style='width:100%;border-collapse:collapse;font-size:0.9rem'>"
        "<thead style='position:sticky;top:0;background:rgba(0,86,179,0.12);"
        "backdrop-filter:blur(4px)'><tr>"
        "<th style='padding:8px 10px;text-align:left'>Quando</th>"
        "<th style='padding:8px 10px;text-align:left'>Projeto</th>"
        "<th style='padding:8px 10px;text-align:left'>Campo</th>"
        "<th style='padding:8px 10px;text-align:left'>Anterior</th>"
        "<th style='padding:8px 10px;text-align:left'>Novo</th>"
        "<th style='padding:8px 10px;text-align:left'>Autor</th>"
        "</tr></thead><tbody>"
        + "".join(_linhas_alt) +
        "</tbody></table></div>",
        unsafe_allow_html=True,
    )
else:
    st.info("Nenhuma alteração de projeto registrada ainda.")
