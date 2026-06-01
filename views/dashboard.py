"""Aba Dashboard — visão executiva da carteira de projetos.

Seções:
 - KPIs (4 métricas dinâmicas por perfil)
 - Gantt integrado (toggle projeto inteiro ↔ por etapas)
 - Pizza de volume por pessoa
 - Evolução técnica (Heatmap / Barras / Tabela)
 - Cards de detalhamento da equipe (ou "minha carga")
 - Exportar relatórios (Excel, PDF completo, PDF Gantt)
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

import database as db
import relatorios

from core.data import _load_df_d, _load_df_p, _load_df_u
from core.helpers import (
    _empty_state,
    _estiliza_plotly,
    _pill_select,
    _section_header,
)
from core.ui_feedback import carregando, erro_humano


usuario = st.session_state.usuario
perfil = st.session_state.get("perfil", "Gestor")
df_p = _load_df_p(usuario, perfil)
df_u = _load_df_u()
df_d = _load_df_d()


st.markdown(
    """
    <div style="display:flex;justify-content:space-between;align-items:flex-end;
                padding-bottom:6px;border-bottom:1px solid rgba(255,255,255,0.06);
                margin-bottom:14px;">
        <div>
            <div style="font-size:1.6rem;font-weight:800;color:#e5e7eb;
                        letter-spacing:.3px;line-height:1.1;">
                📊 Painel Gerencial
            </div>
            <div style="font-size:.85rem;color:#94a3b8;margin-top:2px;">
                Visão executiva da carteira de projetos, equipe e progresso técnico.
            </div>
        </div>
        <div style="font-size:.75rem;color:#94a3b8;text-align:right;">
            Atualizado em<br>
            <b style="color:#cbd5e1;">""" + datetime.now().strftime("%d/%m/%Y %H:%M") + """</b>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# 1. SEGURANÇA E LIMPEZA DE DADOS
df_p_limpo = (
    df_p[df_p["projeto"].notna() & (df_p["projeto"] != "")].copy()
    if not df_p.empty else pd.DataFrame()
)

# ── SEÇÃO 1: KPIs ──────────────────────────────────────────
_section_header(
    "📌", "Indicadores Principais",
    "Métricas do estado atual respeitando seu perfil de acesso.",
    cor="#0891b2",
)

# 2. MÉTRICAS DINÂMICAS
c1, c2, c3, c4 = st.columns(4)

if perfil == "Projetista":
    c1.metric(
        "Meus Projetos Ativos",
        len(df_p_limpo[df_p_limpo["status"] == "Ativo"])
        if not df_p_limpo.empty else 0,
    )
    c2.metric(
        "Meus Projetos Parados",
        len(df_p_limpo[df_p_limpo["status"] == "🛑 Parado"])
        if not df_p_limpo.empty else 0,
    )
    meus_ids = df_p_limpo["id"].tolist() if not df_p_limpo.empty else []
    minhas_duvidas = (
        df_d[df_d["projeto_id"].isin(meus_ids) & (df_d["resolvido"] == 0)]
        if not df_d.empty else pd.DataFrame()
    )
    c3.metric("Minhas Dúvidas", len(minhas_duvidas))
    c4.metric("Equipe Online", len(df_u))
else:
    c1.metric(
        "Em Execução",
        len(df_p_limpo[df_p_limpo["status"] == "Ativo"])
        if not df_p_limpo.empty else 0,
    )
    c2.metric(
        "Em Espera",
        len(df_p_limpo[df_p_limpo["status"] == "Em Espera"])
        if not df_p_limpo.empty else 0,
    )
    c3.metric(
        "Dúvidas Pendentes",
        len(df_d[df_d["resolvido"] == 0]) if not df_d.empty else 0,
    )
    c4.metric("Membros na Equipe", len(df_u))

st.divider()


# 3. GRÁFICO DE GANTT
_section_header(
    "📅", "Cronograma Integrado (Gantt)",
    "Linha do tempo dos projetos no recorte selecionado. Toggle abaixo "
    "alterna entre projeto inteiro e detalhamento por etapas.",
    cor="#3b82f6",
)

_toggle_etapas = st.toggle(
    "Detalhar por etapas",
    value=False,
    key="gantt_toggle_etapas",
    help=(
        "Ativado: mostra cada etapa como barra separada. Desativado: "
        "mostra o projeto inteiro."
    ),
)

if not df_p_limpo.empty:
    todos_projetos_gantt = df_p_limpo["projeto"].unique().tolist()

    # Persistência da seleção do Gantt entre reruns.
    # Usamos chave SEPARADA (com underline) — não a key do widget — pra
    # evitar conflito Session State API ↔ default implícito (warning amarelo).
    _key_gantt_user = "_gantt_projetos_selecionados_user"
    _gantt_atual = st.session_state.get(_key_gantt_user, todos_projetos_gantt[:])
    _gantt_atual = [it for it in _gantt_atual if it in todos_projetos_gantt]
    if not _gantt_atual:
        _gantt_atual = todos_projetos_gantt[:]

    projetos_selecionados_gantt = st.multiselect(
        "Selecione os projetos para o Gantt:",
        options=todos_projetos_gantt,
        default=_gantt_atual,
        help="Selecione os projetos que deseja visualizar no cronograma.",
    )

    st.session_state[_key_gantt_user] = projetos_selecionados_gantt

    if not projetos_selecionados_gantt:
        _empty_state(
            "📊", "Nenhum projeto selecionado pro Gantt",
            "Use o multiselect acima pra escolher os projetos que você "
            "quer ver no cronograma.",
            cor_borda="#3b82f6",
        )
    else:
        df_p_filtrado_gantt = df_p_limpo[
            df_p_limpo["projeto"].isin(projetos_selecionados_gantt)
        ].copy()

        if _toggle_etapas:
            _etapas_todas = db.listar_etapas_todos_projetos()
            if _etapas_todas:
                _rows_g = []
                for et in _etapas_todas:
                    if et["projeto"] not in projetos_selecionados_gantt:
                        continue
                    try:
                        _d_ini = pd.to_datetime(et["data_inicio"])
                        if pd.isna(_d_ini):
                            continue
                        _et_ini = _d_ini + pd.Timedelta(
                            days=int(et["dias_offset"])
                        )
                        _et_fim = _et_ini + pd.Timedelta(
                            days=max(1, int(et["duracao_dias"])) - 1
                        )
                        _rows_g.append({
                            "projeto": et["projeto"],
                            "etapa": f"  ↳ {et['nome']}",
                            "data_inicio": _et_ini,
                            "data_fim": _et_fim,
                            "tipo": "Etapa",
                        })
                    except Exception:
                        continue

                df_gantt_et = pd.DataFrame(_rows_g)
                if not df_gantt_et.empty:
                    fig_gantt = px.timeline(
                        df_gantt_et,
                        x_start="data_inicio", x_end="data_fim", y="etapa",
                        color="projeto",
                        hover_data=["projeto"],
                        labels={
                            "etapa": "Etapa", "projeto": "Projeto",
                            "data_inicio": "Início", "data_fim": "Fim",
                        },
                    )
                    fig_gantt.update_yaxes(autorange="reversed",
                                           title_text="")
                    fig_gantt.update_xaxes(title_text="Período")
                    fig_gantt.update_layout(
                        height=max(350, len(df_gantt_et) * 28 + 80),
                        legend=dict(orientation="h", yanchor="bottom",
                                    y=1.02, xanchor="right", x=1),
                        margin=dict(l=10, r=10, t=60, b=40),
                    )
                    _estiliza_plotly(fig_gantt)
                    st.plotly_chart(fig_gantt, use_container_width=True)
                else:
                    _empty_state(
                        "🏁", "Sem etapas nos projetos escolhidos",
                        "Os projetos selecionados ainda não têm etapas. "
                        "Abra cada um pelo Kanban → ⚙️ Detalhes → 🏁 "
                        "Etapas pra cadastrar.",
                        cor_borda="#3b82f6",
                    )
            else:
                _empty_state(
                    "🏁", "Nenhuma etapa cadastrada",
                    "Pra cadastrar etapas de um projeto: Kanban → "
                    "**⚙️ Detalhes** no card → seção **🏁 Etapas do Projeto**.",
                    cor_borda="#3b82f6",
                )
        else:
            df_plot = df_p_filtrado_gantt.copy()
            df_plot["data_inicio"] = pd.to_datetime(df_plot["data_inicio"])
            df_plot["data_fim"] = pd.to_datetime(df_plot["data_fim"])
            df_plot = df_plot.dropna(subset=["data_inicio", "data_fim"])

            if not df_plot.empty:
                fig_gantt = px.timeline(
                    df_plot, x_start="data_inicio", x_end="data_fim",
                    y="projeto",
                    color="prioridade", hover_data=["projetista", "status"],
                    labels={
                        "projeto": "Projeto", "data_inicio": "Início",
                        "data_fim": "Entrega prevista",
                        "prioridade": "Prioridade",
                        "projetista": "Projetista", "status": "Status",
                    },
                    color_discrete_map={
                        "Máxima": "#ff4d4d", "Média": "#ff9f43",
                        "Mínima": "#2ecc71",
                    },
                )
                fig_gantt.update_yaxes(autorange="reversed", title_text="")
                fig_gantt.update_xaxes(title_text="Período")
                fig_gantt.update_layout(
                    height=420,
                    legend=dict(title=dict(text="<b>Prioridade</b>"),
                                orientation="h", yanchor="bottom",
                                y=1.02, xanchor="right", x=1),
                    margin=dict(l=10, r=10, t=60, b=40),
                )
                _estiliza_plotly(fig_gantt)
                st.plotly_chart(fig_gantt, use_container_width=True)
            else:
                st.info(
                    "Nenhum projeto com datas válidas para exibir no Gantt."
                )
else:
    _empty_state(
        "🛠️", "Nenhum projeto ativo no momento",
        "Cadastre projetos novos pela aba **➕ Novo Projeto** e mova pra "
        "status **Ativo** no Kanban quando começar.",
        cor_borda="#3b82f6",
    )

st.divider()

# ── 4. GRÁFICO DE PIZZA: VOLUME POR PESSOA ───────────────────
_section_header(
    "🥧", "Volume de Trabalho por Pessoa",
    "Quantos projetos cada projetista carrega no momento. Útil pra "
    "balancear a carga e identificar sobrecarga.",
    cor="#7c3aed",
)

if not df_p_limpo.empty and not df_u.empty:
    lista_oficial = df_u["nome"].tolist()

    contagem_bruta = (
        df_p_limpo["projetista"]
        .str.split(", ")
        .explode()
        .pipe(lambda s: s[s.isin(lista_oficial)])
        .value_counts()
        .reset_index()
    )
    contagem_bruta.columns = ["Projetista", "Qtd"]

    if not contagem_bruta.empty:
        todos_projetistas_pizza = contagem_bruta["Projetista"].unique().tolist()

        _key_pizza_sel = "pizza_projetistas_selecionados"
        if _key_pizza_sel not in st.session_state:
            st.session_state[_key_pizza_sel] = todos_projetistas_pizza[:]

        # Limpa opções que sumiram
        st.session_state[_key_pizza_sel] = [
            it for it in st.session_state[_key_pizza_sel]
            if it in todos_projetistas_pizza
        ]

        projetistas_selecionados_pizza = st.multiselect(
            "Selecione os projetistas para o gráfico de pizza:",
            options=todos_projetistas_pizza,
            default=st.session_state[_key_pizza_sel],
            key=_key_pizza_sel,
            help=(
                "Selecione os projetistas que deseja incluir no gráfico "
                "de volume de trabalho."
            ),
        )

        if not projetistas_selecionados_pizza:
            st.info("Nenhum projetista selecionado para o gráfico de pizza.")
        else:
            contagem = contagem_bruta[
                contagem_bruta["Projetista"].isin(
                    projetistas_selecionados_pizza
                )
            ].copy()

            if not contagem.empty:
                PALETA_PIZZA = [
                    "#0056b3", "#00a8cc", "#f59e0b", "#10b981",
                    "#8b5cf6", "#ef4444", "#ec4899", "#14b8a6",
                    "#f97316", "#6366f1",
                ]

                fig_pizza = px.pie(
                    contagem,
                    names="Projetista",
                    values="Qtd",
                    color="Projetista",
                    color_discrete_sequence=PALETA_PIZZA,
                    hole=0.42,
                    custom_data=["Qtd"],
                )
                fig_pizza.update_traces(
                    textposition="outside",
                    textinfo="label+percent",
                    textfont_size=13,
                    hovertemplate=(
                        "<b>%{label}</b><br>%{value} projeto(s) — "
                        "%{percent}<extra></extra>"
                    ),
                    pull=[0.04] * len(contagem),
                    marker=dict(line=dict(color="rgba(0,0,0,0.15)",
                                          width=1.5)),
                )
                total_proj = int(contagem["Qtd"].sum())
                fig_pizza.add_annotation(
                    text=(
                        f"<b>{total_proj}</b><br>"
                        f"<span style='font-size:10px'>projetos</span>"
                    ),
                    x=0.5, y=0.5,
                    font_size=18,
                    showarrow=False,
                    xref="paper", yref="paper",
                )
                fig_pizza.update_layout(
                    height=420,
                    legend=dict(
                        title=dict(text="<b>Projetista</b>"),
                        orientation="v",
                        yanchor="middle", y=0.5,
                        xanchor="left", x=1.02,
                        font=dict(size=12),
                        bgcolor="rgba(0,0,0,0)",
                    ),
                    margin=dict(l=20, r=160, t=30, b=30),
                )
                _estiliza_plotly(fig_pizza)
                st.plotly_chart(fig_pizza, use_container_width=True)

                # Cards resumo abaixo da pizza
                cols_resumo = st.columns(min(len(contagem), 5))
                for i, (_, row) in enumerate(contagem.iterrows()):
                    cor = PALETA_PIZZA[i % len(PALETA_PIZZA)]
                    with cols_resumo[i % len(cols_resumo)]:
                        st.markdown(
                            f"<div style='border-left:4px solid {cor};"
                            f"padding:8px 12px;border-radius:6px;"
                            f"background:rgba(255,255,255,0.03);"
                            f"margin-bottom:6px;'>"
                            f"<div style='font-size:.75rem;color:#94a3b8;'>"
                            f"{row['Projetista']}</div>"
                            f"<div style='font-size:1.4rem;font-weight:700;"
                            f"color:{cor};'>{row['Qtd']}</div>"
                            f"<div style='font-size:.7rem;color:#6b7280;'>"
                            f"projeto(s)</div>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )
            else:
                st.info(
                    "Nenhum dado de projetista para exibir com a seleção atual."
                )
    else:
        st.info("Nenhum dado de projetista para exibir.")
else:
    st.info(
        "Cadastre projetos e membros para ver a distribuição de carga."
    )

st.divider()

# ── 5. EVOLUÇÃO TÉCNICA COM SELEÇÃO DE PROJETOS ──────────────
_section_header(
    "📉", "Evolução Técnica por Projeto",
    "Progresso de cada disciplina dentro de cada projeto. Use o toggle "
    "abaixo pra escolher entre **Barras**, **Heatmap** ou **Tabela**.",
    cor="#16a34a",
)

try:
    df_evolucao = pd.read_sql("""
        SELECT p.id as projeto_id, p.projeto, p.projetista,
               pd.disciplina, pd.percentual
        FROM progresso_disciplinas pd
        JOIN projetos p ON pd.projeto_id = p.id
        ORDER BY p.projeto, pd.disciplina
    """, db.get_engine())

    if not df_evolucao.empty:
        projetos_com_dados = df_evolucao["projeto"].unique().tolist()

        # Default: todos os projetos com dados (heatmap escala bem)
        _default_sel = st.session_state.get(
            "evolucao_sel_projetos", projetos_com_dados
        )
        _default_sel = [p for p in _default_sel if p in projetos_com_dados]
        if not _default_sel:
            _default_sel = projetos_com_dados

        projetos_sel = st.multiselect(
            "Projetos exibidos no heatmap",
            options=projetos_com_dados,
            default=_default_sel,
            key="evolucao_sel_projetos",
            help=(
                "O heatmap aceita N projetos; ordena os mais avançados "
                "no topo. Mais avançado = verde · Mais atrasado = vermelho."
            ),
        )

        if not projetos_sel:
            _empty_state(
                "📊", "Nenhum projeto selecionado",
                "Use o multiselect acima pra escolher os projetos que "
                "quer comparar.",
                cor_borda="#3b82f6",
            )
        else:
            df_graf = df_evolucao[
                df_evolucao["projeto"].isin(projetos_sel)
            ].copy()

            # Pivot reutilizado por Heatmap e Tabela
            _pivot = df_graf.pivot_table(
                index="projeto", columns="disciplina",
                values="percentual", aggfunc="mean",
            )
            # Ordena projetos por progresso médio (mais completos no topo)
            _ordem_proj = (
                _pivot.mean(axis=1).sort_values(ascending=True).index
            )
            _pivot = _pivot.loc[_ordem_proj]
            _pivot = _pivot.reindex(sorted(_pivot.columns), axis=1)

            _modo_viz = _pill_select(
                st, "Visualização",
                options=["Heatmap", "Barras", "Tabela"],
                default="Barras",
                key="evolucao_modo_viz",
                label_visibility="collapsed",
            ) or "Barras"

            # ── HEATMAP ────────────────────────────────────────
            if _modo_viz == "Heatmap":
                _z = _pivot.values
                _text = [
                    [f"{v:.0f}%" if pd.notna(v) else "—" for v in row]
                    for row in _z
                ]
                import plotly.graph_objects as go
                fig_disc = go.Figure(data=go.Heatmap(
                    z=_z,
                    x=_pivot.columns.tolist(),
                    y=_pivot.index.tolist(),
                    text=_text,
                    texttemplate="%{text}",
                    textfont={"size": 11, "color": "#fff"},
                    colorscale=[
                        [0.00, "#7f1d1d"], [0.25, "#b91c1c"],
                        [0.50, "#d97706"], [0.75, "#65a30d"],
                        [1.00, "#16a34a"],
                    ],
                    zmin=0, zmax=100,
                    colorbar=dict(
                        title=dict(text="Progresso (%)", side="right"),
                        tickvals=[0, 25, 50, 75, 100],
                        ticktext=["0%", "25%", "50%", "75%", "100%"],
                        thickness=14, len=0.85,
                    ),
                    hovertemplate=(
                        "<b>%{y}</b><br>Disciplina: %{x}<br>"
                        "Progresso: %{z:.0f}%<extra></extra>"
                    ),
                    xgap=2, ygap=2,
                ))
                fig_disc.update_layout(
                    height=max(280, 36 * len(_pivot.index) + 120),
                    margin=dict(t=20, b=60, l=10, r=10),
                    xaxis=dict(side="bottom", tickangle=-30,
                               title=None, fixedrange=True),
                    yaxis=dict(title=None, fixedrange=True,
                               autorange="reversed"),
                )
                _estiliza_plotly(fig_disc)
                st.plotly_chart(fig_disc, use_container_width=True)

            # ── BARRAS POR PROJETO (subplots arrumados) ───────
            elif _modo_viz == "Barras":
                # Filtra projetos sem dados (zeros ou NaN) pra não
                # desperdiçar subplots vazios.
                _proj_com_dados = (
                    df_graf.groupby("projeto")["percentual"]
                    .sum().pipe(lambda s: s[s > 0]).index.tolist()
                )
                if not _proj_com_dados:
                    _empty_state(
                        "📉", "Sem progresso registrado",
                        "Os projetos selecionados ainda não têm "
                        "percentual de progresso lançado em nenhuma "
                        "disciplina.",
                        cor_borda="#d97706",
                    )
                else:
                    df_graf_v = df_graf[
                        df_graf["projeto"].isin(_proj_com_dados)
                    ].copy()

                    # Layout: 2 cols se até 4 projetos, senão 3 cols.
                    n_cols_f = 2 if len(_proj_com_dados) <= 4 else 3
                    n_linhas_f = -(-len(_proj_com_dados) // n_cols_f)

                    fig_disc = px.bar(
                        df_graf_v,
                        x="disciplina", y="percentual",
                        color="disciplina",
                        facet_col="projeto",
                        facet_col_wrap=n_cols_f,
                        facet_row_spacing=0.18,
                        facet_col_spacing=0.05,
                        text_auto=".0f",
                        range_y=[0, 110],
                        labels={
                            "disciplina": "",
                            "percentual": "Progresso (%)",
                        },
                        hover_data={"projetista": True, "projeto": False},
                        category_orders={
                            "projeto": _proj_com_dados,
                            "disciplina": sorted(
                                df_graf_v["disciplina"].unique()
                            ),
                        },
                    )
                    fig_disc.update_traces(
                        textposition="outside",
                        textfont_size=10,
                        cliponaxis=False,
                    )
                    fig_disc.update_xaxes(
                        matches=None,
                        showticklabels=True,
                        tickangle=-30,
                        title_text="",
                        tickfont_size=10,
                    )
                    fig_disc.update_yaxes(
                        matches=None,
                        range=[0, 115],
                        showticklabels=False,
                        title_text="",
                    )
                    # Re-mostra ticks só nos eixos Y da coluna esquerda
                    for facet_i in range(len(_proj_com_dados)):
                        _coluna_atual = facet_i % n_cols_f
                        if _coluna_atual == 0:
                            _ax_key = (
                                "yaxis" if facet_i == 0
                                else f"yaxis{facet_i+1}"
                            )
                            fig_disc.update_layout(
                                **{_ax_key: dict(
                                    showticklabels=True,
                                    title_text="Progresso (%)",
                                    title_font_size=10,
                                )}
                            )

                    fig_disc.for_each_annotation(
                        lambda a: a.update(
                            text=f"<b>{a.text.split('=')[-1]}</b>",
                            font=dict(size=11, color="#cbd5e1"),
                        )
                    )
                    fig_disc.update_layout(
                        height=max(360, n_linhas_f * 330 + 100),
                        margin=dict(t=40, b=110, l=50, r=10),
                        legend=dict(
                            title=dict(text="<b>Disciplina</b>"),
                            orientation="h",
                            yanchor="top", y=-0.12 / n_linhas_f,
                            xanchor="center", x=0.5,
                            font=dict(size=10),
                        ),
                        bargap=0.25,
                    )
                    _estiliza_plotly(fig_disc)
                    st.plotly_chart(fig_disc, use_container_width=True)

            # ── TABELA (pivot HTML compacto) ──────────────────
            else:  # Tabela
                def _cor_cel(v):
                    if pd.isna(v):
                        return "#1f2937"
                    v = float(v)
                    if v >= 75:
                        return "#16a34a"
                    if v >= 50:
                        return "#65a30d"
                    if v >= 25:
                        return "#d97706"
                    return "#b91c1c"

                _ths = "".join(
                    f"<th style='padding:6px 10px;font-size:11px;"
                    f"color:#94a3b8;text-align:center;"
                    f"border-bottom:1px solid #1f2937;'>{c}</th>"
                    for c in _pivot.columns
                )
                _media_row = _pivot.mean(axis=1)
                _rows_html = ""
                for proj, row in _pivot.iterrows():
                    _cells = "".join(
                        f"<td style='padding:6px;text-align:center;"
                        f"background:{_cor_cel(v)};color:#fff;"
                        f"font-weight:600;font-size:12px;'>"
                        f"{'—' if pd.isna(v) else f'{v:.0f}%'}</td>"
                        for v in row
                    )
                    _med = _media_row[proj]
                    _rows_html += (
                        f"<tr>"
                        f"<td style='padding:6px 10px;font-weight:600;"
                        f"color:#e5e7eb;border-bottom:1px solid #1f2937;'>"
                        f"{proj}</td>{_cells}"
                        f"<td style='padding:6px;text-align:center;"
                        f"background:{_cor_cel(_med)};color:#fff;"
                        f"font-weight:700;font-size:12px;'>"
                        f"{_med:.0f}%</td>"
                        f"</tr>"
                    )
                st.markdown(
                    f"<div style='overflow-x:auto;'>"
                    f"<table style='width:100%;border-collapse:separate;"
                    f"border-spacing:2px;'>"
                    f"<thead><tr>"
                    f"<th style='padding:6px 10px;font-size:11px;"
                    f"color:#94a3b8;text-align:left;border-bottom:"
                    f"1px solid #1f2937;'>Projeto</th>{_ths}"
                    f"<th style='padding:6px 10px;font-size:11px;"
                    f"color:#fbbf24;text-align:center;border-bottom:"
                    f"1px solid #1f2937;'>MÉDIA</th>"
                    f"</tr></thead>"
                    f"<tbody>{_rows_html}</tbody>"
                    f"</table></div>",
                    unsafe_allow_html=True,
                )

            # Sumário de leitura — sempre embaixo (qualquer visualização)
            _media_geral = (
                float(_pivot.stack().mean())
                if not _pivot.stack().empty else 0.0
            )
            _top_proj = (
                _pivot.mean(axis=1).idxmax() if not _pivot.empty else "—"
            )
            _top_pct = (
                float(_pivot.mean(axis=1).max()) if not _pivot.empty else 0
            )
            _gap_proj = (
                _pivot.mean(axis=1).idxmin() if not _pivot.empty else "—"
            )
            _gap_pct = (
                float(_pivot.mean(axis=1).min()) if not _pivot.empty else 0
            )

            cR1, cR2, cR3 = st.columns(3)
            cR1.metric("📈 Progresso médio (todos)",
                       f"{_media_geral:.0f}%")
            cR2.metric("🏆 Mais avançado", _top_proj,
                       delta=f"{_top_pct:.0f}%", delta_color="off")
            cR3.metric("🐢 Mais atrasado", _gap_proj,
                       delta=f"{_gap_pct:.0f}%", delta_color="off")

            # Cards de resumo
            st.markdown("**Progresso médio por projeto:**")
            res_cols = st.columns(len(projetos_sel))
            for i, proj in enumerate(projetos_sel):
                _media = df_graf[
                    df_graf["projeto"] == proj
                ]["percentual"].mean()
                _cor = (
                    "#10b981" if _media >= 80
                    else "#f59e0b" if _media >= 40
                    else "#ef4444"
                )
                with res_cols[i]:
                    st.markdown(
                        f"<div style='border:1px solid {_cor};"
                        f"border-top:4px solid {_cor};border-radius:8px;"
                        f"padding:10px;text-align:center;"
                        f"background:rgba(255,255,255,.02);'>"
                        f"<div style='font-size:.72rem;color:#94a3b8;"
                        f"margin-bottom:4px;overflow:hidden;"
                        f"text-overflow:ellipsis;white-space:nowrap;'"
                        f" title='{proj}'>"
                        f"{proj[:22]}{'…' if len(proj)>22 else ''}</div>"
                        f"<div style='font-size:1.6rem;font-weight:700;"
                        f"color:{_cor};'>{_media:.0f}%</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                    st.progress(float(_media) / 100.0)
except Exception as exc:
    erro_humano(
        "Carregar evolução técnica", exc,
        sugestao=(
            "A seção será reaberta no próximo refresh. Se persistir, pode "
            "haver dado inconsistente em `progresso_disciplinas`."
        ),
    )

# 5. CARDS COLORIDOS
if perfil == "Gestor":
    _section_header(
        "👥", "Detalhamento da Equipe",
        "Distribuição dos projetos por projetista e visão da carga atual.",
        cor="#7c3aed",
    )
    lista_exibicao = df_u["nome"].tolist() if not df_u.empty else []
else:
    _section_header(
        "👤", "Minha Carga de Trabalho",
        "Seus projetos, pendências e ações imediatas.",
        cor="#7c3aed",
    )
    lista_exibicao = [usuario]

cols_eq = st.columns(3)
cores_equipe = [
    "#00d4ff", "#ff9f43", "#ff4d4d", "#2ecc71", "#a29bfe", "#fd79a8",
]

for i, user in enumerate(lista_exibicao):
    cor_atual = cores_equipe[i % len(cores_equipe)]
    with cols_eq[i % 3]:
        projs_user = (
            df_p_limpo[df_p_limpo["projetista"].str.contains(user, na=False)]
            if not df_p_limpo.empty else pd.DataFrame()
        )
        demandas = (
            projs_user["projeto"].tolist() if not projs_user.empty else []
        )
        demandas_html = (
            "".join([
                f'<div class="badge-projeto" '
                f'style="border-left: 3px solid {cor_atual};">📌 {d}</div><br>'
                for d in demandas
            ]) if demandas else "Sem projetos"
        )
        st.markdown(f"""
            <div class="card-projetista" style="border-top: 5px solid {cor_atual};">
                <div class="nome-projetista" style="color: {cor_atual}; margin-bottom: 10px; font-weight: bold;">👤 {user}</div>
                <div class="demanda-texto"><b>Demandas Atuais:</b><br><div style="margin-top: 10px;">{demandas_html}</div></div>
            </div>
        """, unsafe_allow_html=True)

st.markdown("---")
_section_header(
    "📥", "Exportar Relatórios",
    "Baixa snapshots do estado atual em Excel, PDF e CSV.",
    cor="#d97706",
)

# Carrega dados auxiliares para os relatórios
try:
    _eng_rel = db.get_engine()
    _df_etapas_rel = pd.read_sql("""
        SELECT e.*, p.projeto, p.data_inicio
        FROM etapas_projeto e
        JOIN projetos p ON e.projeto_id = p.id
        ORDER BY e.projeto_id, e.ordem
    """, _eng_rel)
    _df_prog_rel = pd.read_sql("""
        SELECT pd.*, p.projeto, p.id as projeto_id
        FROM progresso_disciplinas pd
        JOIN projetos p ON pd.projeto_id = p.id
    """, _eng_rel)
except Exception:
    _df_etapas_rel = pd.DataFrame()
    _df_prog_rel = pd.DataFrame()

c_r1, c_r2, c_r3 = st.columns(3)

# Excel
with c_r1:
    try:
        with carregando("Preparando planilha Excel..."):
            dados_ex = relatorios.gerar_excel(
                df_p_limpo,
                df_etapas=_df_etapas_rel if not _df_etapas_rel.empty else None,
                df_progresso=_df_prog_rel if not _df_prog_rel.empty else None,
            )
        st.download_button(
            label="📊 Baixar Excel Completo",
            data=dados_ex,
            file_name=f"projetos_servpen_{datetime.now().strftime('%d_%m_%Y')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            help="Abas: Projetos · Etapas · Progresso Técnico",
        )
    except Exception as exc:
        erro_humano(
            "Geração do Excel", exc,
            sugestao=(
                "Tente recarregar a página. Se persistir, pode haver dado "
                "inválido em algum projeto — avise o administrador."
            ),
        )

# PDF completo
with c_r2:
    try:
        with carregando("Preparando PDF completo..."):
            dados_pdf = relatorios.gerar_pdf(
                df_p_limpo,
                df_etapas=_df_etapas_rel if not _df_etapas_rel.empty else None,
                df_progresso=_df_prog_rel if not _df_prog_rel.empty else None,
            )
        if dados_pdf:
            st.download_button(
                label="📄 Baixar PDF Completo",
                data=dados_pdf,
                file_name=f"relatorio_servpen_{datetime.now().strftime('%d_%m_%Y')}.pdf",
                mime="application/pdf",
                use_container_width=True,
                help=(
                    "Ficha detalhada de cada projeto + etapas + progresso"
                ),
            )
        else:
            st.warning("Dados insuficientes para PDF.")
    except Exception as exc:
        erro_humano(
            "Geração do PDF completo", exc,
            sugestao="Tente recarregar a página em alguns segundos.",
        )

# PDF Gantt
with c_r3:
    try:
        if not _df_etapas_rel.empty:
            with carregando("Preparando Gantt PDF..."):
                dados_gantt = relatorios.gerar_pdf_gantt(
                    df_p_limpo, _df_etapas_rel,
                )
            st.download_button(
                label="📅 Baixar Gantt PDF",
                data=dados_gantt,
                file_name=f"gantt_servpen_{datetime.now().strftime('%d_%m_%Y')}.pdf",
                mime="application/pdf",
                use_container_width=True,
                help=(
                    "Cronograma visual de todas as etapas em paisagem A4"
                ),
            )
        else:
            st.info(
                "Cadastre etapas nos projetos para gerar o Gantt PDF."
            )
    except Exception as exc:
        erro_humano(
            "Geração do Gantt PDF", exc,
            sugestao=(
                "Confira se os projetos têm datas de início válidas "
                "(Kanban → ⚙️ Detalhes do projeto)."
            ),
        )
