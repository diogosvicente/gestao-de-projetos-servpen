"""Aba Kanban — quadro visual com 3 modos: Kanban, Lista, Resumo.

Inclui a central de edição do projeto (form completo + etapas inline + evolução
técnica por disciplina). Os helpers `_render_lista_kanban` e
`_render_resumo_kanban` estão neste mesmo módulo pois só são usados aqui.
"""

from __future__ import annotations

import time
from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st
import streamlit.components.v1 as _stc

import database as db

from core.data import _invalidar_dados, _load_df_d, _load_df_p, _load_df_u
from core.helpers import (
    _badge_status,
    _empty_state,
    _equipe_atual,
    _estiliza_plotly,
    _pill_select,
    _pode_editar,
    _pode_gestor,
    _render_tag_chips,
    _ve_tudo,
)
from core.ui_feedback import carregando, confirmar_sucesso, erro_humano


usuario = st.session_state.usuario
perfil = st.session_state.get("perfil", "Gestor")
df_p = _load_df_p(usuario, perfil)
df_u = _load_df_u()
df_d = _load_df_d()


# JS robusto de auto-scroll até o form de edição. Rola o SCROLLER REAL do
# Streamlit (section[data-testid="stMain"], com fallbacks) via scrollTo com
# behavior:"auto" (instantâneo, imune a cancelamento por scrollers aninhados),
# num loop curto de retry (~3s) que RE-APLICA o scroll — vencendo o reset de
# scrollTop=0 que o Streamlit faz ao fechar o @st.dialog (issue #14917) e o
# render mais lento de colunas cheias. Antes (setTimeout único + scrollIntoView
# smooth) só a coluna "Em Execução" rolava, por uma corrida de timing.
# `__KB_NONCE__` é trocado a cada abertura pra forçar a reexecução do iframe.
_KB_SCROLL_JS = """
<script>
(function () {
  var NONCE = "__KB_NONCE__";
  var doc = window.parent.document;
  var tries = 0, MAX = 60, stable = 0;
  function pickScroller() {
    return doc.querySelector('section[data-testid="stMain"]')
        || doc.querySelector('[data-testid="stAppViewContainer"]')
        || doc.querySelector('section.main')
        || doc.scrollingElement
        || doc.documentElement;
  }
  function go() {
    tries++;
    var el = doc.getElementById("kanban-edit-top");
    var sc = pickScroller();
    if (el && sc) {
      var r = el.getBoundingClientRect();
      var rs = sc.getBoundingClientRect();
      var delta = r.top - rs.top;
      var target = sc.scrollTop + delta - 12;
      sc.scrollTo({ top: Math.max(0, target), behavior: "auto" });
      if (Math.abs(delta - 12) <= 4) { stable++; if (stable >= 2) return; }
      else { stable = 0; }
    }
    if (tries < MAX) setTimeout(go, 50);
  }
  requestAnimationFrame(go);
})();
</script>
"""


def _data_br(valor):
    """Formata uma data (string ISO do banco, date, Timestamp) para o padrão
    pt-BR dd/mm/yyyy. Retorna '—' se vazio/None/inválido. Usado nos cards do
    Kanban (board/lista/resumo), que mostravam a data crua '2026-06-02'."""
    if valor is None or str(valor).strip() in ("", "—", "None", "NaT"):
        return "—"
    _d = pd.to_datetime(str(valor), errors="coerce")
    return _d.strftime("%d/%m/%Y") if pd.notna(_d) else "—"


def _fmt_hist(valor, is_date=False):
    """Normaliza um valor pra comparar/exibir no histórico de alterações.
    Datas viram dd/mm/yyyy; resto vira string limpa; vazio/None vira ''."""
    if valor is None:
        return ""
    if is_date:
        _d = pd.to_datetime(str(valor), errors="coerce")
        return _d.strftime("%d/%m/%Y") if pd.notna(_d) else ""
    s = str(valor).strip()
    return "" if s in ("", "None", "NaT", "—") else s


# ══════════════════════════════════════════════════════════════════════
# HELPERS (visões alternativas do Kanban)
# ══════════════════════════════════════════════════════════════════════
def _render_lista_kanban(df_kanban, df_d):
    """Visão 'Lista' do Kanban: tabela densa com sort + checkbox por linha
    + toolbar de bulk actions (mover status, adicionar tag em lote).

    Pensada pra triagem rápida quando há muitos projetos. Bulk actions
    aceleram operações típicas tipo "mover 5 finalizados pra Concluído" ou
    "marcar todos com tag Aguardando Cliente".
    """
    if df_kanban.empty:
        _empty_state(
            "📋", "Nenhum projeto pra mostrar",
            "Limpe a busca/filtros acima ou cadastre um projeto novo.",
            cor_borda="#7c3aed",
        )
        return

    # Ordenação
    _opcoes_sort = {
        "Prioridade ↓ → Status":      ["_ord_pri", "status"],
        "Nome (A-Z)":                 ["projeto"],
        "Projetista (A-Z)":           ["projetista"],
        "Prazo (mais próximo)":       ["_prazo_dt"],
        "Status":                     ["status", "projeto"],
    }
    _sort_label = st.selectbox(
        "Ordenar por", list(_opcoes_sort.keys()),
        key="kanban_lista_sort", label_visibility="collapsed",
    )
    df_l = df_kanban.copy()
    _ord_pri_map = {"Máxima": 0, "Média": 1, "Mínima": 2}
    df_l["_ord_pri"] = df_l.get("prioridade", "").map(
        lambda x: _ord_pri_map.get(str(x).strip(), 3)
    )
    df_l["_prazo_dt"] = pd.to_datetime(
        df_l.get("data_termino").fillna(df_l.get("data_fim", "")),
        errors="coerce",
    )
    df_l = df_l.sort_values(_opcoes_sort[_sort_label])

    # ── BULK SELECTION STATE ─────────────────────────────────────
    _ids_visiveis = set(int(x) for x in df_l["id"].tolist())
    sel_ids = st.session_state.setdefault("kanban_bulk_sel", set())
    sel_ids = sel_ids & _ids_visiveis
    st.session_state["kanban_bulk_sel"] = sel_ids

    # ── TOOLBAR DE BULK ACTIONS (só aparece se houver seleção) ──
    # Item 1-lista: ações em lote (mudar status / tag) são só do Gestor.
    if sel_ids and _pode_gestor():
        with st.container(border=True):
            st.markdown(
                f"<div style='color:#3b82f6;font-weight:600;font-size:.9rem;"
                f"margin-bottom:6px;'>"
                f"☑ {len(sel_ids)} projeto(s) selecionado(s)</div>",
                unsafe_allow_html=True,
            )
            with st.form("bulk_actions_form", clear_on_submit=False):
                bc1, bc2, bc3, bc4 = st.columns([2, 2, 1, 1])
                _novo_status = bc1.selectbox(
                    "Mover pra status",
                    options=["— (não mudar)", "Em Espera", "Ativo",
                             "🛑 Parado", "Cancelado", "Concluído"],
                    key="bulk_novo_status",
                )
                _tags_disp = db.listar_tags_existentes()
                _opcoes_tag = ["— (não mudar)"] + _tags_disp
                _tag_add = bc2.selectbox(
                    "Adicionar tag",
                    options=_opcoes_tag,
                    key="bulk_tag_add",
                    help=(
                        "Adiciona a tag a TODOS os projetos selecionados. "
                        "Não remove tags existentes — só acrescenta."
                    ),
                )
                _aplicar = bc3.form_submit_button(
                    "✅ Aplicar", width="stretch",
                )
                _limpar = bc4.form_submit_button(
                    "✖ Limpar", width="stretch",
                )

            if _aplicar:
                _vai_status = (
                    _novo_status and not _novo_status.startswith("—")
                )
                _vai_tag = (_tag_add and not _tag_add.startswith("—"))
                if not _vai_status and not _vai_tag:
                    st.warning("Nada selecionado pra mudar.")
                else:
                    _ids_lista = sorted(sel_ids)
                    _total_bulk = len(_ids_lista)
                    _n = 0
                    _falhas: list[tuple[int, Exception]] = []
                    # Progress bar pra dar feedback quando o user
                    # seleciona 20+ projetos (sem isso, parece travado).
                    _prog = st.progress(
                        0.0,
                        text=(
                            f"Aplicando ação em {_total_bulk} projeto(s)..."
                        ),
                    )
                    for i, _pid in enumerate(_ids_lista):
                        try:
                            if _vai_status:
                                db.atualizar_campo_projeto(
                                    _pid, "status", _novo_status
                                )
                            if _vai_tag:
                                # Adiciona tag sem perder as existentes
                                _conn_t = db.conectar()
                                _c_t = _conn_t.cursor()
                                try:
                                    _c_t.execute(
                                        "SELECT tags FROM projetos "
                                        "WHERE id = %s",
                                        (int(_pid),),
                                    )
                                    _r_t = _c_t.fetchone()
                                    _atuais = db.parse_tags(
                                        _r_t[0] if _r_t else None
                                    )
                                    if _tag_add not in _atuais:
                                        _atuais.append(_tag_add)
                                    _novo_csv = (
                                        db.serializar_tags(_atuais) or None
                                    )
                                    _c_t.execute(
                                        "UPDATE projetos SET tags = %s "
                                        "WHERE id = %s",
                                        (_novo_csv, int(_pid)),
                                    )
                                    _conn_t.commit()
                                finally:
                                    _conn_t.close()
                            _n += 1
                        except Exception as exc:
                            _falhas.append((_pid, exc))
                        _prog.progress(
                            (i + 1) / _total_bulk,
                            text=(
                                f"Aplicando ação... {i+1}/{_total_bulk}"
                            ),
                        )
                    _prog.empty()

                    db.log_aud(
                        usuario, "bulk_acao", "projeto", None,
                        f"{_n} projetos · "
                        f"status={_novo_status if _vai_status else '—'}"
                        f" · tag={_tag_add if _vai_tag else '—'}"
                        + (
                            f" · {len(_falhas)} FALHA(S)"
                            if _falhas else ""
                        ),
                    )
                    st.session_state["kanban_bulk_sel"] = set()
                    _invalidar_dados()
                    if _n:
                        st.success(f"✅ {_n} projeto(s) atualizado(s).")
                    for _pid_f, _exc in _falhas:
                        erro_humano(
                            f"Bulk action no projeto #{_pid_f}", _exc,
                            sugestao=(
                                "Os outros projetos do lote foram "
                                "atualizados normalmente. Tente esse "
                                "projeto individualmente pra ver o erro "
                                "específico."
                            ),
                        )
                    if not _falhas:
                        st.rerun()

            if _limpar:
                st.session_state["kanban_bulk_sel"] = set()
                st.rerun()

    # ── CABEÇALHO DA TABELA ──────────────────────────────────────
    # Colunas: chk, Status, Projeto, Código, SEI, Projetista, Prazo,
    # Prioridade, Tags, botão (Código/SEI = item 11).
    _COLS_ET = [0.35, 1.3, 2.4, 1.2, 1.4, 1.7, 1.3, 1.1, 1.6, 0.5]
    hdr = st.columns(_COLS_ET)
    if _pode_gestor():
        _todos_marcados = (
            len(sel_ids) > 0 and sel_ids >= _ids_visiveis
        )
        _toggle_all = hdr[0].checkbox(
            "", value=_todos_marcados, key="bulk_sel_all",
            help="Selecionar/desmarcar todos os visíveis",
            label_visibility="collapsed",
        )
        if _toggle_all and not _todos_marcados:
            st.session_state["kanban_bulk_sel"] = _ids_visiveis.copy()
            st.rerun()
        elif (not _toggle_all) and _todos_marcados:
            st.session_state["kanban_bulk_sel"] = set()
            st.rerun()
    else:
        hdr[0].markdown(" ")
    for col_obj, txt in zip(
        hdr[1:],
        ["Status", "Projeto", "Código", "SEI", "Projetista", "Prazo",
         "Prioridade", "Tags", ""],
    ):
        col_obj.markdown(
            f"<small style='color:#94a3b8;text-transform:uppercase;"
            f"letter-spacing:.5px;font-weight:600;'>{txt}</small>",
            unsafe_allow_html=True,
        )

    # ── LINHAS DA TABELA ─────────────────────────────────────────
    with st.container(height=720, border=False):
        for _, row in df_l.iterrows():
            cols = st.columns(_COLS_ET)
            pid = int(row["id"])

            if _pode_gestor():
                _checked = cols[0].checkbox(
                    "", value=(pid in sel_ids),
                    key=f"lista_chk_{pid}",
                    label_visibility="collapsed",
                )
                if _checked:
                    sel_ids.add(pid)
                else:
                    sel_ids.discard(pid)
            else:
                cols[0].markdown(" ")

            cols[1].markdown(
                f"<div style='padding-top:6px;'>"
                f"{_badge_status(row.get('status'))}</div>",
                unsafe_allow_html=True,
            )
            cols[2].markdown(
                f"<div style='padding-top:6px;font-weight:600;'>"
                f"{row.get('projeto', '—')} "
                f"<span style='color:#64748b;font-weight:400;font-size:11px;'>"
                f"#{pid}</span></div>",
                unsafe_allow_html=True,
            )
            _cod_cell = str(row.get("codigo") or "").strip()
            _cod_cell = _cod_cell if _cod_cell and _cod_cell.lower() != "nan" else "—"
            cols[3].markdown(
                f"<div style='padding-top:8px;font-size:12px;"
                f"font-family:monospace;opacity:.85;'>{_cod_cell}</div>",
                unsafe_allow_html=True,
            )
            _sei_cell = str(row.get("numero_sei") or "").strip()
            _sei_cell = _sei_cell if _sei_cell and _sei_cell.lower() != "nan" else "—"
            cols[4].markdown(
                f"<div style='padding-top:8px;font-size:12px;opacity:.85;'>"
                f"{_sei_cell}</div>",
                unsafe_allow_html=True,
            )
            cols[5].markdown(
                f"<div style='padding-top:8px;font-size:12px;opacity:.85;'>"
                f"👤 {row.get('projetista', '—')}</div>",
                unsafe_allow_html=True,
            )
            _prazo = _data_br(row.get("data_termino") or row.get("data_fim"))
            cols[6].markdown(
                f"<div style='padding-top:8px;font-size:12px;'>"
                f"📅 {_prazo}</div>",
                unsafe_allow_html=True,
            )
            _pri = str(row.get("prioridade", "")).strip()
            _pri_html = {
                "Máxima": "<span class='kc-pri-max'>▲ MÁX</span>",
                "Média":  "<span class='kc-pri-med'>◆ MÉD</span>",
                "Mínima": "<span class='kc-pri-min'>▼ MÍN</span>",
            }.get(_pri, "")
            cols[7].markdown(
                f"<div style='padding-top:8px;'>{_pri_html}</div>",
                unsafe_allow_html=True,
            )
            cols[8].markdown(
                f"<div style='padding-top:6px;'>"
                f"{_render_tag_chips(row.get('tags'), small=True)}</div>",
                unsafe_allow_html=True,
            )
            if cols[9].button("🔍", key=f"lista_ver_{pid}",
                              help="Abrir detalhes / editar"):
                st.session_state.projeto_em_edicao = pid
                st.rerun()

    st.session_state["kanban_bulk_sel"] = sel_ids


def _render_resumo_kanban(df_kanban, df_d):
    """Visão 'Resumo': dashboard executivo com top urgentes + atrasados +
    distribuição. Pensada como 'visão de cima' pra reuniões/decisão.
    """
    if df_kanban.empty:
        _empty_state(
            "📊", "Nada pra resumir",
            "Limpe a busca/filtros acima — sem projetos visíveis não há resumo.",
            cor_borda="#0891b2",
        )
        return

    hoje = datetime.now().date()
    df_r = df_kanban.copy()
    df_r["_prazo_dt"] = pd.to_datetime(
        df_r.get("data_termino").fillna(df_r.get("data_fim", "")),
        errors="coerce",
    )

    col_esq, col_dir = st.columns([3, 2])

    with col_esq:
        st.markdown("### 🔥 Atenção imediata")

        _maxima = df_r[
            (df_r["status"] == "Em Espera")
            & (df_r["prioridade"].astype(str).str.strip() == "Máxima")
        ]
        _atrasados = df_r[
            (df_r["status"] == "Ativo")
            & (df_r["_prazo_dt"].notna())
            & (df_r["_prazo_dt"].dt.date < hoje)
        ]

        if _maxima.empty and _atrasados.empty:
            st.success(
                "✅ Nenhum projeto urgente no momento — tudo sob controle."
            )
        else:
            if not _maxima.empty:
                st.markdown(f"**▲ Máxima na fila ({len(_maxima)}):**")
                for _, r in _maxima.head(10).iterrows():
                    pid = int(r["id"])
                    c1, c2 = st.columns([5, 1])
                    c1.markdown(
                        f"• **{r['projeto']}** — 👤 {r['projetista']} "
                        f"· 📅 "
                        f"{_data_br(r.get('data_termino') or r.get('data_fim'))}"
                    )
                    if c2.button("🔍", key=f"resumo_max_{pid}",
                                 help="Abrir projeto"):
                        st.session_state.projeto_em_edicao = pid
                        st.rerun()

            if not _atrasados.empty:
                st.markdown(f"**🔴 Atrasados ({len(_atrasados)}):**")
                for _, r in _atrasados.head(10).iterrows():
                    pid = int(r["id"])
                    _dt = (
                        r["_prazo_dt"].date()
                        if pd.notna(r["_prazo_dt"]) else None
                    )
                    _dias_atraso = (hoje - _dt).days if _dt else 0
                    c1, c2 = st.columns([5, 1])
                    c1.markdown(
                        f"• **{r['projeto']}** — 👤 {r['projetista']} "
                        f"· 📅 "
                        f"{_dt.strftime('%d/%m/%Y') if _dt else '—'} "
                        f"<span style='color:#ef4444;font-weight:600;'>"
                        f"(−{_dias_atraso}d)</span>",
                        unsafe_allow_html=True,
                    )
                    if c2.button("🔍", key=f"resumo_atr_{pid}",
                                 help="Abrir projeto"):
                        st.session_state.projeto_em_edicao = pid
                        st.rerun()

    with col_dir:
        st.markdown("### 📊 Distribuição")
        _dist = (
            df_r.groupby("status").size()
            .reset_index(name="qtd")
            .sort_values("qtd", ascending=True)
        )
        if not _dist.empty:
            try:
                fig = px.bar(
                    _dist, x="qtd", y="status", orientation="h",
                    text="qtd", color="status",
                    color_discrete_map={
                        "Em Espera":  "#7c3aed",
                        "Ativo":      "#00d4ff",
                        "🛑 Parado":  "#ff9f43",
                        "Cancelado":  "#ff4d4d",
                        "Concluído":  "#4dff4d",
                    },
                )
                fig.update_traces(textposition="outside")
                fig.update_layout(
                    showlegend=False, height=280,
                    margin=dict(l=0, r=30, t=10, b=10),
                    xaxis_title=None, yaxis_title=None,
                )
                _estiliza_plotly(fig)
                st.plotly_chart(fig, width="stretch")
            except Exception:
                st.info(
                    "Distribuição: "
                    f"{dict(zip(_dist['status'], _dist['qtd']))}"
                )

        # Distribuição por tag (top 5)
        _tag_count = {}
        for _, row in df_r.iterrows():
            for t in db.parse_tags(row.get("tags")):
                _tag_count[t] = _tag_count.get(t, 0) + 1
        if _tag_count:
            st.markdown("**🏷 Top tags em uso:**")
            _top_tags = sorted(
                _tag_count.items(), key=lambda x: -x[1]
            )[:5]
            for tag, qtd in _top_tags:
                st.markdown(
                    f"• {_render_tag_chips(tag, small=True)} — "
                    f"<small>{qtd} projeto(s)</small>",
                    unsafe_allow_html=True,
                )


# ══════════════════════════════════════════════════════════════════════
# UI principal da aba Kanban
# ══════════════════════════════════════════════════════════════════════
st.header("📋 Controle de Fluxo")

# ── BUSCA + FILTRO DE TAGS ───────────────────────────────────
col_busca, col_tags = st.columns([3, 2])
busca_kanban = col_busca.text_input(
    "🔍 Buscar por nome, projetista, cliente, SEI ou código",
    placeholder="ex.: residencial silva, joão, 2024/12345, COD-001...",
    key="kanban_search",
)
_todas_tags_kanban = db.listar_tags_existentes()
tags_filtro = col_tags.multiselect(
    "🏷 Filtrar por tags",
    options=_todas_tags_kanban,
    default=[],
    key="kanban_tags_filter",
    help=(
        "Mostra apenas projetos que contêm TODAS as tags selecionadas. "
        "Vazio = não filtra."
    ),
    placeholder=(
        "(qualquer tag)" if _todas_tags_kanban
        else "Nenhuma tag cadastrada ainda"
    ),
    disabled=not _todas_tags_kanban,
)

if busca_kanban:
    termo = busca_kanban.lower().strip()

    def _col_busca(nome):
        """Coluna como série de strings, ou série vazia se a coluna não
        existir (robusto contra df sem `codigo`/`numero_sei`)."""
        return (
            df_p[nome].astype(str) if nome in df_p.columns
            else pd.Series("", index=df_p.index)
        )

    mask = (
        _col_busca("projeto").str.lower().str.contains(termo, na=False)
        | _col_busca("projetista").str.lower().str.contains(termo, na=False)
        | _col_busca("solicitante").str.lower().str.contains(termo, na=False)
        | _col_busca("numero_sei").str.lower().str.contains(termo, na=False)
        | _col_busca("codigo").str.lower().str.contains(termo, na=False)
    )
    df_kanban = df_p[mask].copy()
else:
    df_kanban = df_p.copy() if not df_p.empty else pd.DataFrame()

# Filtro de tags: projeto deve conter TODAS as tags selecionadas (AND).
if tags_filtro and not df_kanban.empty:
    sel_lower = {t.lower() for t in tags_filtro}

    def _tem_todas(s):
        proj_tags = {t.lower() for t in db.parse_tags(s)}
        return sel_lower.issubset(proj_tags)

    _col_tags = (
        df_kanban["tags"] if "tags" in df_kanban.columns
        else pd.Series([""] * len(df_kanban), index=df_kanban.index)
    )
    df_kanban = df_kanban[_col_tags.apply(_tem_todas)].copy()

# ── 4 CARDS DE MÉTRICAS (visão executiva sobre o filtro atual) ──
_df_metricas = (
    df_kanban if not df_kanban.empty
    else pd.DataFrame(columns=df_p.columns)
)
_hoje_metricas = datetime.now().date()


def _eh_atrasado(row):
    if row.get("status") != "Ativo":
        return False
    dt_str = row.get("data_termino") or row.get("data_fim")
    if not dt_str:
        return False
    try:
        return pd.to_datetime(str(dt_str)).date() < _hoje_metricas
    except Exception:
        return False


_qtd_andamento = (
    int((_df_metricas["status"] == "Ativo").sum())
    if not _df_metricas.empty else 0
)
_qtd_espera = (
    int((_df_metricas["status"] == "Em Espera").sum())
    if not _df_metricas.empty else 0
)
_qtd_atrasados = (
    int(_df_metricas.apply(_eh_atrasado, axis=1).sum())
    if not _df_metricas.empty else 0
)
_qtd_prio_max_espera = int(
    ((_df_metricas["status"] == "Em Espera")
     & (_df_metricas["prioridade"].astype(str).str.strip() == "Máxima")).sum()
) if not _df_metricas.empty else 0

m1, m2, m3, m4 = st.columns(4)
m1.metric("🚀 Em Andamento", _qtd_andamento,
          help="Projetos com status Ativo no filtro atual.")
m2.metric("⏳ Em Espera", _qtd_espera,
          help="Projetos aguardando triagem no filtro atual.")
m3.metric("🔴 Atrasados", _qtd_atrasados,
          delta=f"de {_qtd_andamento}" if _qtd_andamento else None,
          delta_color="off",
          help="Ativos cuja data de término já passou.")
m4.metric("▲ Máxima na fila", _qtd_prio_max_espera,
          help="Em Espera com prioridade Máxima (precisa de triagem).")

st.divider()

# ── TOGGLE DE VISÃO: Kanban / Lista / Resumo ─────────────────
visao = _pill_select(
    st, "Visão",
    options=["Kanban", "Lista", "Resumo"],
    default="Kanban",
    key="kanban_visao",
    label_visibility="collapsed",
) or "Kanban"


# Ações do card em MODAL (em vez de popover): clicar "⚙️ Ações" abre um
# st.dialog; cada ação dá st.rerun(), que FECHA o modal — resolve o "popover
# que ficava aberto após mudar de coluna".
@st.dialog("Ações do projeto")
def _acoes_card(pid, status_db, nome):
    st.markdown(f"**{nome}**")

    if st.button("🔍 Abrir detalhes / editar", key=f"dlg_ver_{pid}",
                 width="stretch"):
        st.session_state.projeto_em_edicao = pid
        st.rerun()

    if not _pode_gestor():
        return

    def _pedir(novo, label, aud=None):
        # Fecha o modal de Ações e abre o de confirmação (tratado no board).
        # TODA ação de status passa por aqui → sempre confirma com o usuário.
        st.session_state["_kb_acao_req"] = {
            "pid": pid, "nome": nome, "novo": novo,
            "label": label, "aud": aud,
        }
        st.rerun()

    st.divider()
    if status_db == "Em Espera":
        if st.button("▶️ Mover para Em Execução", key=f"dlg_ativ_{pid}",
                     width="stretch"):
            _pedir("Ativo", "mover para Em Execução", "Em Espera → Ativo")
        if st.button("❌ Cancelar projeto", key=f"dlg_cesp_{pid}",
                     width="stretch"):
            _pedir("Cancelado", "cancelar")
    elif status_db == "Ativo":
        if st.button("⏸️ Pausar projeto", key=f"dlg_pause_{pid}",
                     width="stretch"):
            _pedir("🛑 Parado", "pausar")
        if st.button("✅ Concluir projeto", key=f"dlg_concl_{pid}",
                     width="stretch"):
            _pedir("Concluído", "concluir")
    elif status_db == "🛑 Parado":
        if st.button("▶️ Retomar → Em Execução", key=f"dlg_ret_{pid}",
                     width="stretch"):
            _pedir("Ativo", "retomar")
        if st.button("❌ Cancelar", key=f"dlg_canc_{pid}",
                     width="stretch"):
            _pedir("Cancelado", "cancelar")
    elif status_db == "Cancelado":
        if st.button("🔓 Reativar → Em Espera", key=f"dlg_reat_{pid}",
                     width="stretch"):
            _pedir("Em Espera", "reativar")
    elif status_db == "Concluído":
        if st.button("🔓 Reabrir → Em Execução", key=f"dlg_reab_{pid}",
                     width="stretch"):
            _pedir("Ativo", "reabrir")


# ── Confirmação de QUALQUER ação de status (modal próprio) ───────────
# Aberto DEPOIS que o modal de Ações fecha (via flag `_kb_acao_req`). Chamado
# a cada run enquanto o flag existe → o corpo roda e os botões registram o
# clique de forma confiável (não depende de auto-rerun de dialog). Voltar/
# Confirmar limpam o flag e fecham.
if st.session_state.get("_kb_acao_req"):
    _a = st.session_state["_kb_acao_req"]
    _a_label = {
        "Ativo": "Em Execução", "🛑 Parado": "Parado",
        "Concluído": "Concluído", "Cancelado": "Cancelado",
        "Em Espera": "Em Espera",
    }.get(_a["novo"], _a["novo"])

    @st.dialog("Confirmar ação")
    def _dlg_confirmar_acao():
        st.markdown(
            "<div style='text-align:center;padding:2px 0 6px;'>"
            "<div style='width:52px;height:52px;border-radius:50%;"
            "background:rgba(59,130,246,.14);color:#60a5fa;display:flex;"
            "align-items:center;justify-content:center;margin:0 auto 12px;"
            "font-size:24px;'>❓</div>"
            f"<p style='margin:0 0 4px;font-weight:600;'>Deseja <b>"
            f"{_a['label']}</b> o projeto “{_a['nome']}”?</p>"
            f"<p style='margin:0;color:#94a3b8;font-size:13.5px;'>Vai para a "
            f"coluna <b>{_a_label}</b>.</p></div>",
            unsafe_allow_html=True,
        )
        _q1, _q2 = st.columns(2)
        if _q1.button("Voltar", key="kb_acao_volta",
                      width="stretch"):
            st.session_state.pop("_kb_acao_req", None)
            st.rerun()
        if _q2.button("✅ Confirmar", type="primary",
                      key="kb_acao_ok", width="stretch"):
            st.session_state.pop("_kb_acao_req", None)
            db.atualizar_campo_projeto(_a["pid"], "status", _a["novo"])
            if _a["aud"]:
                db.log_aud(usuario, "status", "projeto", _a["pid"], _a["aud"])
            _invalidar_dados()
            confirmar_sucesso("Projeto atualizado",
                              f"'{_a['nome']}' agora está em {_a_label}.")
            st.rerun()

    _dlg_confirmar_acao()


if visao == "Lista":
    _render_lista_kanban(df_kanban, df_d)
elif visao == "Resumo":
    _render_resumo_kanban(df_kanban, df_d)
else:
    # ════════════════════════════════════════════════════════════
    #  KANBAN TRADICIONAL (default)
    # ════════════════════════════════════════════════════════════
    ORDEM_PRIORIDADE = {"Máxima": 0, "Média": 1, "Mínima": 2, "": 3}

    CONFIG_COLUNAS = [
        {"status_db": "Em Espera",  "label_ui": "⏳ Em Espera",
         "card_cls": "kc-espera",   "ordenar_por_prioridade": True},
        {"status_db": "Ativo",      "label_ui": "🚀 Em Execução",
         "card_cls": "kc-ativo",    "ordenar_por_prioridade": False},
        {"status_db": "🛑 Parado",  "label_ui": "🛑 Parados",
         "card_cls": "kc-parado",   "ordenar_por_prioridade": False},
        {"status_db": "Cancelado",  "label_ui": "❌ Cancelados",
         "card_cls": "kc-cancel",   "ordenar_por_prioridade": False},
        {"status_db": "Concluído",  "label_ui": "✅ Concluídos",
         "card_cls": "kc-conc",     "ordenar_por_prioridade": False},
    ]

    # CSS uniforme para os cards do Kanban
    st.markdown("""
    <style>
    .kc {
        border-radius: 8px;
        border-left: 4px solid var(--kc-border, #888);
        color: #fff;
        background: var(--kc-bg, #444);
        overflow: hidden;
    }
    .kc.kc-d-c { padding: 6px 8px; font-size: 11px;   line-height: 1.3;
                 margin-bottom: 5px; }
    .kc.kc-d-n { padding: 9px 11px; font-size: 12.5px; line-height: 1.4;
                 margin-bottom: 7px; }
    .kc.kc-d-e { padding: 12px 14px; font-size: 13.5px; line-height: 1.5;
                 margin-bottom: 10px; }
    .kc.kc-d-c .nome { font-size:11.5px; }
    .kc.kc-d-n .nome { font-size:13px; }
    .kc.kc-d-e .nome { font-size:14.5px; }
    .kc.kc-d-c .meta { font-size:10px; }
    .kc.kc-d-n .meta { font-size:11.5px; }
    .kc.kc-d-e .meta { font-size:12.5px; }

    .kc-espera { --kc-bg:#3b1f6e; --kc-border:#7c3aed; }
    .kc-ativo  { --kc-bg:#0d3d75; --kc-border:#00d4ff; }
    .kc-parado { --kc-bg:#7c3a0a; --kc-border:#ff9f43; }
    .kc-cancel { --kc-bg:#5c1414; --kc-border:#ff4d4d; }
    .kc-conc   { --kc-bg:#143d14; --kc-border:#4dff4d; }
    .kc .row1 { display:flex; gap:4px; flex-wrap:wrap; align-items:center;
                margin-bottom: 3px; min-height: 14px; }
    .kc .nome { font-weight:700; margin:2px 0; word-break: break-word; }
    .kc .meta { opacity:.85; margin-top:2px; word-break: break-word; }
    .kc .tags { margin-top:4px; line-height:1.6; }
    .kc-pri-max  { background:#ef4444; color:#fff; font-size:9px;
                   font-weight:700; padding:1px 6px; border-radius:5px;
                   letter-spacing:.3px; }
    .kc-pri-med  { background:#f59e0b; color:#fff; font-size:9px;
                   font-weight:700; padding:1px 6px; border-radius:5px;
                   letter-spacing:.3px; }
    .kc-pri-min  { background:#10b981; color:#fff; font-size:9px;
                   font-weight:700; padding:1px 6px; border-radius:5px;
                   letter-spacing:.3px; }
    .kc-alerta   { background:#ff4d4d; color:#fff; font-size:9px;
                   font-weight:700; padding:1px 6px; border-radius:5px;
                   letter-spacing:.3px; }
    .kc-col-header {
        position: sticky; top: 0;
        background: var(--background-color, #0e1117);
        z-index: 5;
        font-size: 13px; font-weight:700; margin: 0 0 6px;
        padding: 6px 4px;
        border-bottom: 1px solid rgba(255,255,255,.08);
    }
    </style>
    """, unsafe_allow_html=True)

    # ── TOOLBAR: densidade + collapse finalizados ────────────────
    tb1, tb2, _tb3 = st.columns([1.2, 1.2, 2])
    densidade = _pill_select(
        tb1, "Densidade",
        options=["Compacto", "Normal", "Expandido"],
        default="Normal",
        key="kanban_densidade",
        label_visibility="collapsed",
        help="Espaçamento dos cards. Compacto = mais cards visíveis.",
    )
    _density_cls_map = {
        "Compacto": "kc-d-c", "Normal": "kc-d-n", "Expandido": "kc-d-e",
    }
    _density_cls = _density_cls_map.get(densidade or "Normal", "kc-d-n")

    mostrar_finalizados = tb2.toggle(
        "Mostrar finalizados",
        value=False,
        key="kanban_show_done",
        help="Inclui colunas ❌ Cancelados e ✅ Concluídos no quadro.",
    )

    # ── COLUNAS DO KANBAN (3 ou 5, dependendo do toggle) ─────────
    COLUNAS_FINAIS = {"Cancelado", "Concluído"}
    configs_visiveis = [
        c for c in CONFIG_COLUNAS
        if mostrar_finalizados or c["status_db"] not in COLUNAS_FINAIS
    ]
    colunas_ui = st.columns(len(configs_visiveis))

    # Altura do container scrollable. 75vh aprox = cada coluna rola sozinha.
    ALTURA_COL = 700

    for cfg, coluna in zip(configs_visiveis, colunas_ui):
        with coluna:
            if not df_kanban.empty:
                items = df_kanban[df_kanban["status"] == cfg["status_db"]].copy()
            else:
                items = pd.DataFrame()

            # Ordenação por prioridade na coluna Em Espera
            if cfg["ordenar_por_prioridade"] and not items.empty:
                items["_ord_pri"] = items["prioridade"].map(
                    lambda x: ORDEM_PRIORIDADE.get(str(x).strip(), 3)
                )
                items = items.sort_values("_ord_pri")

            # Header da coluna FORA do container scrollable
            st.markdown(
                f"<div class='kc-col-header'>{cfg['label_ui']} "
                f"<span style='opacity:.6;font-weight:500;'>"
                f"({len(items)})</span></div>",
                unsafe_allow_html=True,
            )

            with st.container(height=ALTURA_COL, border=False):
                if items.empty:
                    st.markdown(
                        "<div style='color:#6b7280;font-size:11px;"
                        "border:1px dashed rgba(255,255,255,0.1);"
                        "border-radius:6px;padding:8px;text-align:center;'>"
                        "Nenhum projeto</div>",
                        unsafe_allow_html=True,
                    )

                for _, p in items.iterrows():
                    pend_abertas = (
                        df_d[
                            (df_d["projeto_id"] == p["id"])
                            & (df_d["resolvido"] == 0)
                        ] if not df_d.empty else pd.DataFrame()
                    )
                    texto_diario = (
                        " ".join(pend_abertas["executado"].astype(str))
                        if not pend_abertas.empty else ""
                    )
                    tem_trava = any(
                        x in texto_diario
                        for x in ["Impedimento", "Dúvida", "🛑", "❓"]
                    )
                    badge_alerta = (
                        "<span class='kc-alerta'>⚠ TRAVA</span>"
                        if tem_trava else ""
                    )

                    pri = str(p.get("prioridade", "")).strip()
                    if pri == "Máxima":
                        badge_pri = "<span class='kc-pri-max'>▲ MÁX</span>"
                    elif pri == "Média":
                        badge_pri = "<span class='kc-pri-med'>◆ MÉD</span>"
                    elif pri == "Mínima":
                        badge_pri = "<span class='kc-pri-min'>▼ MÍN</span>"
                    else:
                        badge_pri = ""

                    prazo_str = _data_br(
                        p.get("data_fim") or p.get("data_termino")
                    )

                    _tags_html = _render_tag_chips(p.get("tags"), small=True)
                    _tags_wrap = (
                        f'<div class="tags">{_tags_html}</div>'
                        if _tags_html else ""
                    )

                    card_html = (
                        f'<div class="kc {cfg["card_cls"]} {_density_cls}">'
                        f'<div class="row1">{badge_alerta}{badge_pri}</div>'
                        f'<div class="nome">{p["projeto"]}</div>'
                        f'<div class="meta">👤 {p["projetista"]} · 📅 {prazo_str}</div>'
                        f'{_tags_wrap}'
                        f'</div>'
                    )
                    st.markdown(card_html, unsafe_allow_html=True)

                    # Ações do card num MODAL (item: o popover ficava aberto
                    # após mudar de coluna; o @st.dialog fecha no st.rerun).
                    status_db = cfg["status_db"]
                    if st.button("⚙️ Ações", key=f"acoes_{p['id']}",
                                 width="stretch",
                                 help="Abrir detalhes / mudar status"):
                        _acoes_card(int(p["id"]), status_db, p["projeto"])

# ══════════════════════════════════════════════════════════════════════
# CENTRAL DE EDIÇÃO (com todo o detalhamento)
# ══════════════════════════════════════════════════════════════════════
# Edição fechada → zera o marcador de scroll (assim reabrir o MESMO projeto,
# ex.: um "Em Espera", rola de novo até o form).
if "projeto_em_edicao" not in st.session_state:
    st.session_state.pop("_kb_edit_open_for", None)

if "projeto_em_edicao" in st.session_state:
    st.divider()
    id_ed = st.session_state.projeto_em_edicao

    # Recarrega sempre do banco para ter dados frescos
    _df_ed = pd.read_sql_query(
        "SELECT * FROM projetos WHERE id = %s",
        db.get_engine(), params=(int(id_ed),),
    )

    if _df_ed.empty:
        st.warning("Projeto não encontrado.")
        del st.session_state.projeto_em_edicao
        st.rerun()

    dados = _df_ed.fillna("").iloc[0]

    # Rola até o form a CADA abertura (marcador zerado quando a edição fecha,
    # acima — reabrir o MESMO projeto também rola). Âncora <div> estável +
    # JS robusto (_KB_SCROLL_JS) que rola o scroller real em loop curto.
    if st.session_state.get("_kb_edit_open_for") != id_ed:
        st.session_state["_kb_edit_open_for"] = id_ed
        st.markdown(
            "<div id='kanban-edit-top' "
            "style='height:0;scroll-margin-top:12px;'></div>",
            unsafe_allow_html=True,
        )
        _nonce = f"{id_ed}-{int(time.time() * 1000)}"
        _stc.html(_KB_SCROLL_JS.replace("__KB_NONCE__", _nonce), height=0)

    st.subheader(f"📝 Detalhamento e Edição: {dados['projeto']}")
    st.markdown(_badge_status(dados.get("status", "")),
                unsafe_allow_html=True)

    def _parse_d(val):
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(str(val).strip(), fmt).date()
            except Exception:
                pass
        return datetime.now().date()

    # ════════════════════════════════════════════════════════
    #  FORMULÁRIO ESPELHANDO O CADASTRO DE NOVO PROJETO
    # ════════════════════════════════════════════════════════
    with st.form("form_edicao_v6"):
        # Item 1-lista: não-gestor é read-only no formulário (campos
        # desabilitados + sem botões de escrita). A exceção é a Evolução
        # Técnica por Disciplina, renderizada FORA deste form (abaixo).
        _ro_edit = not _pode_gestor()

        st.markdown("#### 📌 Identificação")
        rc01, rc02 = st.columns(2)
        ed_cod = rc01.text_input(
            "Código do Projeto",
            value=str(dados.get("codigo", "")),
            placeholder="opcional — único",
            help="Opcional; se preenchido, precisa ser único.",
            disabled=_ro_edit,
        )
        ed_nm = rc02.text_input("Nome do Projeto / Cliente *",
                                value=str(dados["projeto"]),
                                disabled=_ro_edit)

        r1c1, r1c2 = st.columns(2)
        ed_sei = r1c1.text_input("Nº SEI / Documento",
                                 value=str(dados.get("numero_sei", "")),
                                 placeholder="ex.: 2024/12345-6",
                                 disabled=_ro_edit)
        ed_so = r1c2.text_input("Solicitante / Cliente",
                                value=str(dados["solicitante"]),
                                disabled=_ro_edit)

        r2c1, r2c2 = st.columns(2)
        ed_co = r2c1.text_input("Contato (Tel/Email)",
                                value=str(dados["contato"]),
                                disabled=_ro_edit)
        ed_li = r2c2.text_input("Link da Pasta (Drive/Nuvem)",
                                value=str(dados["link_projeto"]),
                                disabled=_ro_edit)

        # Endereço: select do cadastro mestre (item 12) + digitar novo;
        # "Local" é complemento livre (item 10).
        _end_atual = str(dados.get("endereco", "")).strip()
        _end_opts = db.listar_enderecos()
        if _end_atual and _end_atual not in _end_opts:
            _end_opts = [_end_atual] + _end_opts
        r3c1, r3c2 = st.columns(2)
        ed_ed = r3c1.selectbox(
            "Endereço da Obra",
            options=_end_opts,
            index=(_end_opts.index(_end_atual) if _end_atual in _end_opts
                   else None),
            accept_new_options=True,
            placeholder="Selecione ou digite um novo…",
            disabled=_ro_edit,
        )
        ed_lo = r3c2.text_input(
            "Local",
            value=str(dados.get("local", "")),
            placeholder="bloco / andar / sala / referência",
            help="Complemento do endereço.",
            disabled=_ro_edit,
        )

        list_u = df_u["nome"].tolist()
        def_u = [
            x.strip() for x in str(dados["projetista"]).split(",")
            if x.strip() in list_u
        ]
        ed_eq = st.multiselect("Equipe Responsável *", list_u,
                               default=def_u, disabled=_ro_edit)

        lista_pri = ["Máxima", "Média", "Mínima"]
        pri_atual = str(dados.get("prioridade", "Média")).strip()

        ed_r4c1, ed_r4c2 = st.columns([1, 2])
        ed_pr = ed_r4c1.selectbox(
            "Prioridade", lista_pri,
            index=lista_pri.index(pri_atual) if pri_atual in lista_pri else 1,
            disabled=_ro_edit,
        )

        _tags_existentes_e = db.listar_tags_existentes()
        _tags_atuais_csv = str(dados.get("tags") or "")
        ed_tags = ed_r4c2.text_input(
            "🏷 Tags (separadas por vírgula)",
            value=_tags_atuais_csv,
            placeholder=(
                ", ".join(_tags_existentes_e[:3]) if _tags_existentes_e
                else "Crítico, Aprovado"
            ),
            help=(
                "Etiquetas livres pra agrupar projetos. "
                + (f"Já em uso: {', '.join(_tags_existentes_e)}."
                   if _tags_existentes_e else "")
            ),
            disabled=_ro_edit,
        )

        st.markdown("#### 📅 Datas")
        dc1, dc2, dc3, dc4 = st.columns(4)
        ed_drec = dc1.date_input(
            "Data de Recebimento",
            value=_parse_d(dados.get("data_recebimento")),
            format="DD/MM/YYYY",
            disabled=_ro_edit,
        )
        ed_prev = dc2.date_input(
            "Previsão de Execução",
            value=_parse_d(dados.get("previsao_execucao")),
            format="DD/MM/YYYY",
            disabled=_ro_edit,
        )
        ed_di = dc3.date_input(
            "Data de Início",
            value=_parse_d(dados.get("data_inicio")),
            format="DD/MM/YYYY",
            disabled=_ro_edit,
        )
        ed_dt = dc4.date_input(
            "Data de Término",
            value=_parse_d(
                dados.get("data_termino") or dados.get("data_fim")
            ),
            format="DD/MM/YYYY",
            disabled=_ro_edit,
        )

        st.markdown("#### 📋 Escopo e Disciplinas")
        _discs_salvas = [
            d.strip() for d in
            str(dados.get("demandas", "")).split("|")[0].split(",")
            if d.strip()
        ]
        _lista_chk = list(dict.fromkeys(
            st.session_state.get("lista_checklist", []) + _discs_salvas
        ))
        ed_chk = st.multiselect(
            "Disciplinas do Projeto",
            options=_lista_chk,
            default=[d for d in _discs_salvas if d in _lista_chk],
            disabled=_ro_edit,
        )

        ed_esc = st.text_area("Descrição do Escopo",
                              value=str(dados["solicitacao"]), height=90,
                              disabled=_ro_edit)
        _dem_extra = (
            str(dados.get("demandas", "")).split("|")[-1].strip()
            if "|" in str(dados.get("demandas", "")) else ""
        )
        ed_dem = st.text_area("Checklist Adicional / Demandas",
                              value=_dem_extra, height=70,
                              disabled=_ro_edit)

        # ── BOTÕES ──────────────────────────────────────────
        # Item 1-lista: só Gestor vê Salvar/Clonar/Excluir. Não-gestor fica
        # em modo leitura (campos desabilitados acima) + só "Fechar".
        _salvar = _clonar = _excluir = False
        confirmar_del = False
        if _ro_edit:
            st.info(
                "🔒 Modo leitura — edição do projeto é exclusiva do Gestor. "
                "Use a seção **Evolução Técnica por Disciplina** abaixo para "
                "marcar seu progresso."
            )
            _fechar = st.form_submit_button("❌ Fechar",
                                            width="stretch")
        else:
            f_c1, f_c2, f_c3, f_c4 = st.columns(4)
            _salvar = f_c1.form_submit_button("💾 Salvar e Sair",
                                              width="stretch")
            _clonar = f_c2.form_submit_button(
                "📋 Clonar projeto",
                width="stretch",
                help=(
                    "Cria um novo projeto copiando dados básicos + estrutura "
                    "de etapas. Não copia diário, arquivos nem progresso."
                ),
            )
            _excluir = f_c3.form_submit_button("🗑️ Excluir Projeto",
                                               width="stretch")
            _fechar = f_c4.form_submit_button("❌ Fechar",
                                              width="stretch")

    # ── Ações dos botões ─────────────────────────────────────
    if _salvar:
        _cod_save = (ed_cod or "").strip()
        _end_save = (ed_ed or "").strip()
        if _cod_save and not db.codigo_disponivel(_cod_save, ignorar_id=id_ed):
            st.warning(
                f"⚠️ O código **{_cod_save}** já está em uso por outro "
                "projeto. Use um código único ou deixe em branco."
            )
            st.stop()
        # `with carregando(...)` envolve as chamadas de banco — mostra
        # spinner "💾 Salvando projeto..." na tela DURANTE a operação.
        # Sem isso, em latência alta (Postgres remoto, rsync de anexo),
        # o user clica "Salvar" e a tela fica congelada parecendo bug.
        with carregando(f"Salvando projeto '{ed_nm}'..."):
            equipe_str = ", ".join(ed_eq)
            checklist_final = (
                ", ".join(ed_chk)
                + (" | " + ed_dem if ed_dem.strip() else "")
            )
            dados_finais = (
                equipe_str, ed_nm, _end_save, ed_so, ed_co,
                ed_sei, ed_drec, ed_di, ed_dt, ed_dt,
                ed_li, checklist_final, ed_esc, ed_pr,
            )
            # Tags (CSV) — calculado aqui pra entrar no diff do histórico.
            _tags_csv_save = (
                db.serializar_tags(db.parse_tags(ed_tags)) or None
            )
            # ── HISTÓRICO DE ALTERAÇÕES (antes/depois) ───────────
            # Compara o estado ANTIGO (`dados`) com os novos valores do
            # form. Só registra se o projeto está INICIADO (status !=
            # 'Em Espera') — projeto não iniciado não gera histórico.
            _campos_hist = [
                ("Responsável",        dados.get("projetista"),
                 equipe_str, False),
                ("Nome do Projeto",    dados.get("projeto"), ed_nm, False),
                ("Código",             dados.get("codigo"), _cod_save, False),
                ("Endereço",           dados.get("endereco"), _end_save, False),
                ("Local",              dados.get("local"), ed_lo, False),
                ("Solicitante",        dados.get("solicitante"),
                 ed_so, False),
                ("Contato",            dados.get("contato"), ed_co, False),
                ("Nº SEI",             dados.get("numero_sei"),
                 ed_sei, False),
                ("Data de Recebimento", dados.get("data_recebimento"),
                 ed_drec, True),
                ("Data de Início",     dados.get("data_inicio"),
                 ed_di, True),
                ("Data de Término",
                 dados.get("data_termino") or dados.get("data_fim"),
                 ed_dt, True),
                ("Link",               dados.get("link_projeto"),
                 ed_li, False),
                ("Demandas/Checklist", dados.get("demandas"),
                 checklist_final, False),
                ("Solicitação",        dados.get("solicitacao"),
                 ed_esc, False),
                ("Prioridade",         dados.get("prioridade"),
                 ed_pr, False),
                ("Tags",               dados.get("tags"),
                 _tags_csv_save, False),
            ]
            _alteracoes = []
            for _lbl, _ant, _nov, _isd in _campos_hist:
                _a = _fmt_hist(_ant, _isd)
                _n = _fmt_hist(_nov, _isd)
                if _a != _n:
                    _alteracoes.append((_lbl, _a, _n))

            db.atualizar_projeto_completo(id_ed, dados_finais)
            # Tags num UPDATE separado (assinatura fixa de
            # atualizar_projeto_completo — 14 valores, compat).
            db.atualizar_campo_projeto(id_ed, "tags", _tags_csv_save)
            # Código e Local (itens 3/10) — UPDATE separado, mesmo padrão das
            # tags (atualizar_projeto_completo tem assinatura fixa de 14).
            db.atualizar_campo_projeto(id_ed, "codigo", _cod_save or None)
            db.atualizar_campo_projeto(
                id_ed, "local", (ed_lo or "").strip() or None
            )
            # Endereço usado entra no cadastro mestre (item 12).
            if _end_save:
                db.adicionar_endereco(_end_save)

            # Grava o histórico (gatilho: projeto iniciado).
            if str(dados.get("status", "")).strip() != "Em Espera":
                db.registrar_alteracoes_projeto(
                    id_ed, ed_nm, _alteracoes, usuario,
                )

            db.log_aud(
                usuario, "editar", "projeto", id_ed,
                f"nome='{ed_nm}' tags='{_tags_csv_save or ''}'",
            )
            del st.session_state.projeto_em_edicao
            _invalidar_dados()
        # st.toast sobrevive ao st.rerun (vive no overlay, fora do script
        # run). st.success aqui apareceria por <300ms antes do rerun zerar
        # — efeito "pisca" reclamado pelo user.
        confirmar_sucesso("Projeto salvo",
                          f"{ed_nm} — alterações registradas no histórico.")
        st.rerun()

    # Ação crítica: confirmação em MODAL (@st.dialog) em vez de checkbox.
    @st.dialog("Excluir projeto")
    def _dlg_excluir_projeto():
        _nome = dados["projeto"]
        st.markdown(
            "<div style='text-align:center;padding:2px 0 6px;'>"
            "<div style='width:54px;height:54px;border-radius:50%;"
            "background:rgba(239,68,68,.14);color:#ef4444;display:flex;"
            "align-items:center;justify-content:center;margin:0 auto 12px;"
            "font-size:26px;'>🗑️</div>"
            f"<p style='margin:0 0 4px;font-weight:600;font-size:15px;'>"
            f"Excluir “{_nome}”?</p>"
            "<p style='margin:0;color:#94a3b8;font-size:13.5px;'>Esta ação é "
            "<b>irreversível</b> — o projeto e seu histórico serão removidos."
            "</p></div>",
            unsafe_allow_html=True,
        )
        _dc1, _dc2 = st.columns(2)
        if _dc1.button("Cancelar", width="stretch",
                       key=f"dlg_canc_{id_ed}"):
            st.rerun()
        if _dc2.button("🗑️ Excluir definitivamente", type="primary",
                       width="stretch", key=f"dlg_conf_{id_ed}"):
            with carregando(f"Excluindo projeto '{_nome}'..."):
                db.excluir_projeto(id_ed)
                db.log_aud(usuario, "excluir", "projeto", id_ed,
                           f"nome='{_nome}'")
                del st.session_state.projeto_em_edicao
                _invalidar_dados()
            confirmar_sucesso("Projeto excluído", f"'{_nome}' foi removido.")
            st.rerun()

    if _excluir:
        _dlg_excluir_projeto()

    if _clonar:
        with carregando(f"Clonando '{dados['projeto']}'..."):
            novo_id = db.clonar_projeto(id_ed)
            if novo_id:
                db.log_aud(
                    usuario, "clonar", "projeto", id_ed,
                    f"origem='{dados['projeto']}' -> novo_id={novo_id}",
                )
                _invalidar_dados()
        if novo_id:
            # st.toast em vez de st.success — sobrevive ao rerun abaixo.
            confirmar_sucesso(
                "Projeto clonado",
                f"Cópia criada (id {novo_id}). Abrindo a edição.",
            )
            st.session_state.projeto_em_edicao = int(novo_id)
            st.rerun()
        else:
            st.error(
                "Não foi possível clonar o projeto. "
                "Veja o log do servidor pra detalhes."
            )

    if _fechar:
        del st.session_state.projeto_em_edicao
        st.rerun()

    # ════════════════════════════════════════════════════════
    #  ETAPAS DO PROJETO (edição inline)
    # ════════════════════════════════════════════════════════
    st.markdown("### 🏁 Etapas do Projeto")

    _key_et = f"etapas_edit_{id_ed}"
    if _key_et not in st.session_state:
        st.session_state[_key_et] = db.listar_etapas(id_ed)

    _et_list = st.session_state[_key_et]
    _ro_etapas = not _pode_gestor()   # item 4 / 1-lista: edição só Gestor

    # ── Situação por etapa (item 4) ──────────────────────────────
    # Cruza o % REAL (campo "% concl." preenchido pelo Gestor) com o %
    # ESPERADO pela data: janela da etapa = data de início do projeto +
    # offset, por `duracao_dias`. Classifica em A iniciar / No prazo /
    # Adiantada / Atrasada / Concluída.
    _di_proj_et = dados.get("data_inicio") or dados.get("data_fim")
    _base_et = (
        pd.to_datetime(str(_di_proj_et), errors="coerce")
        if _di_proj_et else pd.NaT
    )
    _hoje_et = pd.Timestamp(datetime.now().date())

    def _situacao_etapa(offset, duracao, percentual):
        real = max(0, min(100, int(percentual or 0)))
        if pd.isna(_base_et):
            return (("Concluída", "#16a34a", None) if real >= 100
                    else ("—", "#6b7280", None))
        _ini = _base_et + pd.Timedelta(days=int(offset or 0))
        _fim = _ini + pd.Timedelta(days=max(1, int(duracao or 1)) - 1)
        _total = max(1, (_fim - _ini).days)
        esperado = max(0, min(100, round((_hoje_et - _ini).days / _total * 100)))
        if real >= 100:
            return ("Concluída", "#16a34a", esperado)
        if _hoje_et < _ini:
            return ("A iniciar", "#6b7280", esperado)
        if _hoje_et > _fim:
            return ("Atrasada", "#dc2626", esperado)
        _diff = real - esperado
        if _diff >= 10:
            return ("Adiantada", "#2563eb", esperado)
        if _diff <= -10:
            return ("Atrasada", "#dc2626", esperado)
        return ("No prazo", "#16a34a", esperado)

    def _badge_sit(lbl, cor):
        return (
            f"<span style='background:{cor};color:#fff;font-size:.68rem;"
            f"font-weight:700;padding:2px 8px;border-radius:10px;'>{lbl}</span>"
        )

    if _ro_etapas:
        # Não-gestor: read-only — vê etapas + % + situação, sem editar.
        if not _et_list:
            st.caption("Nenhuma etapa cadastrada.")
        else:
            for i, et in enumerate(_et_list):
                _lbl, _cor, _esp = _situacao_etapa(
                    et.get("dias_offset", 0), et.get("duracao_dias", 1),
                    et.get("percentual", 0),
                )
                _esp_txt = f" · esperado {_esp}%" if _esp is not None else ""
                st.markdown(
                    "<div style='display:flex;justify-content:space-between;"
                    "align-items:center;border:1px solid "
                    "rgba(255,255,255,0.08);border-radius:8px;padding:8px 12px;"
                    "margin-bottom:6px;'>"
                    f"<span><b>{i+1}. {et.get('nome', '—')}</b> "
                    f"<small style='color:#94a3b8'>· "
                    f"{int(et.get('percentual', 0) or 0)}% concl.{_esp_txt}"
                    "</small></span>"
                    f"{_badge_sit(_lbl, _cor)}</div>",
                    unsafe_allow_html=True,
                )
        st.caption("🔒 Edição das etapas é exclusiva do Gestor.")
    else:
        _COLS_ET = [0.4, 2.1, 1.0, 1.3, 1.0, 1.5, 0.6]

        with st.form(f"form_etapas_{id_ed}"):
            novas_etapas = []
            _del_et = None

            if not _et_list:
                st.markdown(
                    "<div style='border:1px dashed rgba(255,255,255,0.12);"
                    "border-radius:8px;padding:18px;text-align:center;"
                    "color:#6b7280;font-size:13px;'>"
                    "Nenhuma etapa cadastrada ainda.<br>"
                    "<small>Clique em <b>+ Adicionar Etapa</b> abaixo pra "
                    "começar.</small></div>",
                    unsafe_allow_html=True,
                )
            else:
                _h = st.columns(_COLS_ET)
                for _col, _txt in zip(_h, [
                    "Ord.", "Nome da Etapa", "Duração", "Início (offset)",
                    "% concl.", "Situação", "Ação",
                ]):
                    _col.markdown(
                        f"<small style='color:#94a3b8'>{_txt}</small>",
                        unsafe_allow_html=True,
                    )

                for i, et in enumerate(_et_list):
                    c0, c1, c2, c3, c4, c5, c6 = st.columns(_COLS_ET)
                    c0.markdown(
                        f"<div style='padding-top:28px;text-align:center;"
                        f"color:#64748b;font-weight:700;'>{i+1}</div>",
                        unsafe_allow_html=True,
                    )
                    n = c1.text_input("Nome", value=str(et.get("nome", "")),
                                      label_visibility="collapsed",
                                      key=f"etn_{id_ed}_{i}")
                    d = c2.number_input("Dur",
                                        value=int(et.get("duracao_dias", 1)),
                                        min_value=1,
                                        label_visibility="collapsed",
                                        key=f"etd_{id_ed}_{i}")
                    o = c3.number_input("Off",
                                        value=int(et.get("dias_offset", 0)),
                                        min_value=0,
                                        label_visibility="collapsed",
                                        key=f"eto_{id_ed}_{i}")
                    pc = c4.number_input(
                        "%", value=int(et.get("percentual", 0) or 0),
                        min_value=0, max_value=100, step=5,
                        label_visibility="collapsed",
                        key=f"etp_{id_ed}_{i}",
                    )
                    _lbl, _cor, _esp = _situacao_etapa(o, d, pc)
                    _esp_txt = (
                        f" <small style='color:#94a3b8'>(esp. {_esp}%)</small>"
                        if _esp is not None else ""
                    )
                    c5.markdown(
                        f"<div style='padding-top:6px;'>"
                        f"{_badge_sit(_lbl, _cor)}{_esp_txt}</div>",
                        unsafe_allow_html=True,
                    )
                    if c6.form_submit_button(f"🗑 #{i+1}",
                                             width="stretch"):
                        _del_et = i
                    novas_etapas.append({
                        "nome": n, "duracao_dias": d, "dias_offset": o,
                        "percentual": pc, "ordem": i,
                    })

            btn_add, btn_salvar_et = st.columns(2)
            _add_et = btn_add.form_submit_button("➕ Adicionar Etapa",
                                                 width="stretch")
            _salv_et = btn_salvar_et.form_submit_button(
                "💾 Salvar Etapas",
                width="stretch",
                disabled=not _et_list,
                help=(
                    "Disponível quando há etapas pra salvar"
                    if not _et_list else None
                ),
            )

        if _del_et is not None:
            st.session_state[_key_et].pop(_del_et)
            acum = 0
            for et in st.session_state[_key_et]:
                et["dias_offset"] = acum
                acum += et["duracao_dias"]
            st.rerun()

        if _add_et:
            _ult = (
                st.session_state[_key_et][-1] if st.session_state[_key_et]
                else {"dias_offset": 0, "duracao_dias": 0}
            )
            st.session_state[_key_et].append({
                "nome": f"Etapa {len(st.session_state[_key_et])+1}",
                "duracao_dias": 5,
                "dias_offset": _ult["dias_offset"] + _ult["duracao_dias"],
                "percentual": 0,
                "ordem": len(st.session_state[_key_et]),
            })
            st.rerun()

        if _salv_et:
            with carregando("Salvando etapas..."):
                db.salvar_etapas(
                    id_ed,
                    [e for e in novas_etapas if str(e["nome"]).strip()],
                )
                st.session_state[_key_et] = db.listar_etapas(id_ed)
            confirmar_sucesso("Etapas salvas",
                              "Cronograma do projeto atualizado.")
            st.rerun()

    # Mini-Gantt das etapas
    _et_salvas = db.listar_etapas(id_ed)
    _di_proj = dados.get("data_inicio") or dados.get("data_fim")
    if _et_salvas and _di_proj:
        try:
            _base = pd.to_datetime(str(_di_proj))
            _rows_g2 = []
            for et in _et_salvas:
                _ini = _base + pd.Timedelta(days=int(et["dias_offset"]))
                _fim = _ini + pd.Timedelta(
                    days=max(1, int(et["duracao_dias"])) - 1
                )
                _rows_g2.append({"Etapa": et["nome"],
                                 "Início": _ini, "Fim": _fim})
            _df_g2 = pd.DataFrame(_rows_g2)
            _fig_g2 = px.timeline(_df_g2, x_start="Início",
                                  x_end="Fim", y="Etapa", color="Etapa")
            _fig_g2.update_yaxes(autorange="reversed", title_text="")
            _fig_g2.update_layout(
                height=max(200, len(_rows_g2) * 32 + 60),
                showlegend=False,
                margin=dict(l=5, r=5, t=15, b=10),
            )
            _estiliza_plotly(_fig_g2)
            st.plotly_chart(_fig_g2, width="stretch")
        except Exception:
            pass

    # ════════════════════════════════════════════════════════
    #  HISTÓRICO DE ALTERAÇÕES DO PROJETO
    #  (só projetos iniciados geram registro — ver salvar acima)
    # ════════════════════════════════════════════════════════
    with st.expander("🕓 Histórico de Alterações"):
        _df_hist = pd.read_sql(
            "SELECT data, campo, valor_anterior, valor_novo, autor "
            "FROM projeto_alteracoes WHERE projeto_id = %s "
            "ORDER BY data DESC LIMIT 200",
            db.get_engine(), params=(int(id_ed),),
        )
        if _df_hist.empty:
            st.caption(
                "Nenhuma alteração registrada. O histórico passa a ser "
                "gravado quando o projeto sai de **Em Espera** (iniciado)."
            )
        else:
            for _, _h in _df_hist.iterrows():
                _quando = _data_br(_h["data"])
                _hora = ""
                _dt_h = pd.to_datetime(_h["data"], errors="coerce")
                if pd.notna(_dt_h):
                    _quando = _dt_h.strftime("%d/%m/%Y")
                    _hora = _dt_h.strftime(" %H:%M")
                _ant = _h.get("valor_anterior") or "—"
                _nov = _h.get("valor_novo") or "—"
                st.markdown(
                    f"<div style='border-left:3px solid #0056b3;"
                    f"padding:2px 0 2px 10px;margin:4px 0;font-size:.86rem;'>"
                    f"<b>{_h['campo']}</b>: "
                    f"<span style='color:#ef4444;'>{_ant}</span> → "
                    f"<span style='color:#10b981;'>{_nov}</span><br>"
                    f"<span style='opacity:.6;font-size:.76rem;'>"
                    f"{_quando}{_hora} · {_h.get('autor') or '—'}</span></div>",
                    unsafe_allow_html=True,
                )

    # ════════════════════════════════════════════════════════
    #  EVOLUÇÃO TÉCNICA POR DISCIPLINA
    #  Checklist: slider 100% → checkbox marcado automaticamente
    # ════════════════════════════════════════════════════════
    st.markdown("### 📊 Evolução Técnica por Disciplina")

    # ── ISOLAMENTO POR EQUIPE ──────────────────────────────────
    # Regra de visibilidade da EVOLUÇÃO (só ela — board e Gantt são abertos
    # a todos, projeto compartilhado):
    #   • Gestor Geral .......... vê tudo.
    #   • Gestor de equipe ....... vê se ALGUÉM da sua equipe está designado
    #                              no projeto (interseção projetista×equipe).
    #   • Projetista/Visualizador  vê SÓ se ELE PRÓPRIO está designado no
    #                              projeto ("somente as pessoas envolvidas").
    _proj_nomes = {
        n.strip() for n in str(dados.get("projetista", "")).split(",")
        if n.strip()
    }
    if _ve_tudo():
        _pode_ver_evolucao = True
    elif _pode_gestor():
        _pode_ver_evolucao = bool(
            _proj_nomes & db.nomes_por_equipe(_equipe_atual())
        )
    else:
        _pode_ver_evolucao = usuario in _proj_nomes

    if not _pode_ver_evolucao:
        st.info(
            "🔒 A evolução técnica só é visível para quem está designado no "
            "projeto (e, para gestores, quando alguém da sua equipe está "
            "envolvido). O projeto e o cronograma continuam visíveis."
        )
        st.stop()

    # Disciplinas vêm do campo demandas (parte antes do "|")
    _dem_raw = str(dados.get("demandas", "")).split("|")[0]
    disciplinas_projeto = [
        d.strip() for d in _dem_raw.split(",") if d.strip()
    ]

    if not disciplinas_projeto:
        st.info(
            "Nenhuma disciplina vinculada. Adicione-as no campo "
            "**Disciplinas do Projeto** acima e salve."
        )
    else:
        df_prog = pd.read_sql(
            "SELECT * FROM progresso_disciplinas WHERE projeto_id = %s",
            db.get_engine(), params=(int(id_ed),),
        )

        disciplinas_no_banco = df_prog["disciplina"].tolist()

        # Sincroniza disciplinas (adiciona novas, remove obsoletas)
        _sync_needed = False
        for _d in disciplinas_projeto:
            if _d not in disciplinas_no_banco:
                _c = db.conectar()
                _cu = _c.cursor()
                _cu.execute(
                    "INSERT INTO progresso_disciplinas "
                    "(projeto_id, disciplina, concluido, percentual) "
                    "VALUES (%s,%s,%s,%s)",
                    (int(id_ed), _d, 0, 0),
                )
                _c.commit()
                _c.close()
                _sync_needed = True

        for _d in disciplinas_no_banco:
            if _d not in disciplinas_projeto:
                _c = db.conectar()
                _cu = _c.cursor()
                _cu.execute(
                    "DELETE FROM progresso_disciplinas "
                    "WHERE projeto_id=%s AND disciplina=%s",
                    (int(id_ed), _d),
                )
                _c.commit()
                _c.close()
                _sync_needed = True

        if _sync_needed:
            st.rerun()

        with st.form(key=f"check_evolucao_{id_ed}"):
            c_check, c_prog = st.columns([1.3, 1])
            novos_vals = []

            with c_check:
                st.markdown(
                    "<div style='margin-bottom:6px;font-size:.78rem;"
                    "color:#94a3b8;display:flex;gap:32px;padding-left:4px;'>"
                    "<span>✔ Concluído</span>"
                    "<span style='margin-left:8px'>Progresso (%)</span>"
                    "</div>",
                    unsafe_allow_html=True,
                )
                for _, row in df_prog.iterrows():
                    if row["disciplina"] not in disciplinas_projeto:
                        continue

                    _st_banco = bool(row["concluido"])
                    _per_banco = int(row["percentual"])

                    col_cb, col_sl = st.columns([0.38, 0.62])

                    _n_st = col_cb.checkbox(
                        f"**{row['disciplina']}**",
                        value=_st_banco,
                        key=f"ch_{row['id']}",
                    )
                    _n_per = col_sl.slider(
                        "Prog", 0, 100, _per_banco,
                        key=f"sl_{row['id']}",
                        label_visibility="collapsed",
                    )

                    # Sincronização: 100% ↔ marcado
                    _cb_mudou = (_n_st != _st_banco)
                    _sl_mudou = (_n_per != _per_banco)

                    if _cb_mudou:
                        _n_per = 100 if _n_st else 0
                    elif _sl_mudou:
                        _n_st = (_n_per == 100)

                    novos_vals.append((
                        1 if _n_st else 0,
                        _n_per,
                        int(row["id"]),
                    ))

            with c_prog:
                _media = (
                    df_prog["percentual"].mean()
                    if not df_prog.empty else 0
                )
                _cor_prog = (
                    "#10b981" if _media >= 70
                    else "#f59e0b" if _media >= 40
                    else "#ef4444"
                )

                with st.container(border=True):
                    st.markdown(
                        f"<div style='text-align:center; padding:10px 0;'>"
                        f"<div style='font-size:2rem;font-weight:700;"
                        f"color:{_cor_prog};line-height:1'>"
                        f"{_media:.0f}%</div>"
                        f"<div style='font-size:.72rem;color:#94a3b8;"
                        f"margin-top:5px;'>progresso geral</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                    st.progress(min(_media / 100, 1.0))

                if _media >= 100:
                    st.success("🎉 CONCLUÍDO!")

            if st.form_submit_button("🔄 Atualizar Progresso",
                                     width="stretch"):
                with carregando("Salvando evolução..."):
                    _c = db.conectar()
                    _cu = _c.cursor()
                    for _s, _p, _i in novos_vals:
                        _cu.execute(
                            "UPDATE progresso_disciplinas "
                            "SET concluido=%s, percentual=%s WHERE id=%s",
                            (_s, _p, _i),
                        )
                    _c.commit()
                    _c.close()
                confirmar_sucesso("Evolução salva",
                                  "Progresso das disciplinas atualizado.")
                st.rerun()
