"""Aba Novo Projeto — formulário de cadastro completo (identificação,
datas, equipe, escopo, etapas com Gantt preview).
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

import database as db

from core.data import _invalidar_dados, _load_df_u
from core.helpers import _estiliza_plotly, _init_etapas, _pode_editar
from core.ui_feedback import carregando


# Visualizador não cadastra
if not _pode_editar():
    st.error("🛑 Visualizadores não podem criar projetos.")
    st.stop()


usuario = st.session_state.usuario
df_u = _load_df_u()


st.header("➕ Cadastrar Novo Projeto")

_init_etapas()

# ── Gerenciar checklist ────────────────────────────────────
with st.expander("⚙️ Gerenciar Disciplinas do Checklist"):
    nova_disc = st.text_input(
        "Nova Disciplina (ex: Gás, Acústica)", key="add_disc",
    )
    if st.button("Adicionar Disciplina", key="btn_add_disc"):
        if nova_disc and nova_disc not in st.session_state.lista_checklist:
            st.session_state.lista_checklist.append(nova_disc)
            st.toast(f"➕ '{nova_disc}' adicionada!", icon="✅")
            st.rerun()

# ── Formulário principal ──────────────────────────────────
with st.form("form_novo_projeto_v2", clear_on_submit=False):

    st.markdown("#### 📌 Identificação")
    r1c1, r1c2 = st.columns(2)
    f_nm = r1c1.text_input("Nome do Projeto / Cliente *")
    f_sei = r1c2.text_input("Nº SEI / Documento",
                            placeholder="ex.: 2024/12345-6")

    r2c1, r2c2 = st.columns(2)
    f_so = r2c1.text_input("Solicitante / Cliente")
    f_co = r2c2.text_input("Contato (Tel/Email)")

    r3c1, r3c2 = st.columns(2)
    f_ed = r3c1.text_input("Endereço da Obra")
    f_li = r3c2.text_input("Link da Pasta (Drive/Nuvem)")

    f_eq = st.multiselect(
        "Equipe Responsável *",
        df_u["nome"].tolist() if not df_u.empty else [],
    )

    r4c1, r4c2 = st.columns([1, 2])
    f_pr = r4c1.selectbox("Prioridade", ["Máxima", "Média", "Mínima"], index=1)
    # Tags livres separadas por vírgula. Mostra as já existentes como hint.
    _tags_existentes = db.listar_tags_existentes()
    _placeholder_tags = (
        ", ".join(_tags_existentes[:3]) if _tags_existentes
        else "Crítico, Aguardando Cliente, Aprovado"
    )
    f_tags = r4c2.text_input(
        "🏷 Tags (separadas por vírgula)",
        value="",
        placeholder=_placeholder_tags,
        help=(
            "Etiquetas livres pra agrupar projetos além do status. "
            "Ex.: setor, fase, urgência, cliente. "
            + (f"Já em uso: {', '.join(_tags_existentes)}."
               if _tags_existentes else "")
        ),
    )

    st.markdown("#### 📅 Datas")
    dc1, dc2, dc3, dc4 = st.columns(4)
    f_drec = dc1.date_input("Data de Recebimento do Pedido",
                            value=datetime.now())
    f_prev = dc2.date_input("Previsão de Início da Execução",
                            value=datetime.now())
    f_di = dc3.date_input("Data de Início", value=datetime.now())
    f_dt = dc4.date_input("Data de Término", value=datetime.now())

    st.markdown("#### 📋 Escopo e Disciplinas")
    f_chk = st.multiselect("Disciplinas do Projeto",
                           st.session_state.lista_checklist)
    f_esc = st.text_area("Descrição do Escopo", height=90)
    f_dem = st.text_area("Checklist Adicional / Demandas", height=70)

    # ── ETAPAS (dentro do form, gerenciadas via session_state) ──
    st.markdown("#### 🏁 Etapas do Projeto")
    st.caption(
        "As etapas são em sequência. O *Início (dias após início do "
        "projeto)* indica quantos dias após a Data de Início a etapa começa. "
        "As barras aparecerão no Gantt."
    )

    # Cabeçalho
    h0, h1, h2, h3, h4 = st.columns([0.35, 2.5, 1.2, 1.2, 0.5])
    h0.markdown("<small style='color:#94a3b8'>Ord.</small>",
                unsafe_allow_html=True)
    h1.markdown("<small style='color:#94a3b8'>Nome da Etapa</small>",
                unsafe_allow_html=True)
    h2.markdown("<small style='color:#94a3b8'>Duração (dias)</small>",
                unsafe_allow_html=True)
    h3.markdown("<small style='color:#94a3b8'>Início (dias offset)</small>",
                unsafe_allow_html=True)
    h4.markdown("<small style='color:#94a3b8'>—</small>",
                unsafe_allow_html=True)

    etapas_validas = []
    _to_delete = None

    for i, et in enumerate(st.session_state.etapas_form):
        c0, c1, c2, c3, c4 = st.columns([0.35, 2.5, 1.2, 1.2, 0.5])
        c0.markdown(
            f"<div style='padding-top:30px;text-align:center;"
            f"color:#64748b;font-weight:700'>{i+1}</div>",
            unsafe_allow_html=True,
        )
        nome_et = c1.text_input("Etapa", value=et["nome"],
                                label_visibility="collapsed",
                                key=f"et_nome_{i}")
        dur_et = c2.number_input("Dias", value=int(et["duracao_dias"]),
                                 min_value=1, max_value=3650,
                                 label_visibility="collapsed",
                                 key=f"et_dur_{i}")
        off_et = c3.number_input("Offset", value=int(et["dias_offset"]),
                                 min_value=0, max_value=3650,
                                 label_visibility="collapsed",
                                 key=f"et_off_{i}")
        if c4.form_submit_button(f"🗑 #{i+1}",
                                 help=f"Remover etapa '{et['nome']}'"):
            _to_delete = i

        etapas_validas.append({
            "nome": nome_et,
            "duracao_dias": dur_et,
            "dias_offset": off_et,
            "ordem": i,
        })

    # Botão de adicionar etapa (dentro do form usando form_submit_button)
    c_add, c_sub = st.columns([1, 3])
    _add_etapa = c_add.form_submit_button("➕ Adicionar Etapa",
                                          use_container_width=True)
    submit_novo = c_sub.form_submit_button("🔨 Registrar Projeto",
                                           use_container_width=True)

# ── Ações dos botões FORA do form ─────────────────────────
if _to_delete is not None:
    st.session_state.etapas_form.pop(_to_delete)
    # Recalcula offsets automaticamente em sequência
    acum = 0
    for et in st.session_state.etapas_form:
        et["dias_offset"] = acum
        acum += et["duracao_dias"]
    st.rerun()

if _add_etapa:
    # Próxima etapa começa após a última
    if st.session_state.etapas_form:
        ultimo = st.session_state.etapas_form[-1]
        novo_offset = ultimo["dias_offset"] + ultimo["duracao_dias"]
    else:
        novo_offset = 0
    st.session_state.etapas_form.append({
        "nome": f"Etapa {len(st.session_state.etapas_form)+1}",
        "duracao_dias": 5,
        "dias_offset": novo_offset,
        "ordem": len(st.session_state.etapas_form),
    })
    st.rerun()

if submit_novo:
    # Sincroniza valores digitados de volta ao session_state
    for i, et in enumerate(etapas_validas):
        if i < len(st.session_state.etapas_form):
            st.session_state.etapas_form[i].update(et)

    if f_nm and f_eq:
        with carregando(f"Criando projeto '{f_nm}'..."):
            checklist_final = (
                ", ".join(f_chk) + (" | " + f_dem if f_dem.strip() else "")
            )
            _tags_csv = db.serializar_tags(db.parse_tags(f_tags)) or None
            dados_sql = (
                ", ".join(f_eq),   # projetista
                f_nm,              # projeto
                f_ed,              # endereco
                f_so,              # solicitante
                f_co,              # contato
                f_sei,             # numero_sei
                f_drec,            # data_recebimento
                f_prev,            # previsao_execucao
                f_di,              # data_inicio
                f_dt,              # data_termino
                f_dt,              # data_fim (compatibilidade Gantt)
                "Em Espera",       # ← STATUS: entra na fila de triagem
                f_li,              # link_projeto
                checklist_final,   # demandas
                f_esc,             # solicitacao
                f_pr,              # prioridade
                _tags_csv,         # tags (string CSV ou None)
            )
            novo_id = db.salvar_projeto(dados_sql)
            if novo_id:
                etapas_para_salvar = [
                    {"nome": et["nome"],
                     "duracao_dias": et["duracao_dias"],
                     "dias_offset": et["dias_offset"],
                     "ordem": i}
                    for i, et in enumerate(etapas_validas)
                    if str(et.get("nome", "")).strip()
                ]
                if etapas_para_salvar:
                    db.salvar_etapas(novo_id, etapas_para_salvar)

                db.log_aud(usuario, "criar", "projeto", novo_id, f_nm)
                st.session_state.etapas_form = [
                    {"nome": "Levantamento", "duracao_dias": 5,
                     "dias_offset": 0},
                    {"nome": "Projeto", "duracao_dias": 10,
                     "dias_offset": 5},
                ]
                _invalidar_dados()
        if novo_id:
            # st.toast em vez de st.success: sobrevive ao st.rerun abaixo
            # (vive ~4s no overlay, fora do script run).
            st.toast(
                f"✅ Projeto **{f_nm}** criado! Está na coluna "
                f"**Em Espera** do Kanban.",
                icon="🎉",
            )
            st.rerun()
        else:
            st.error("Erro técnico ao salvar no banco de dados.")
    else:
        st.warning("⚠️ Campos **Nome** e **Equipe** são obrigatórios.")

# ── Mini-preview do Gantt de etapas enquanto preenche ────
if st.session_state.get("etapas_form") and len(st.session_state.etapas_form) > 0:
    with st.expander("👁️ Pré-visualização do Gantt das Etapas", expanded=False):
        _di_prev = datetime.now()
        _rows_prev = []
        for et in st.session_state.etapas_form:
            if not str(et.get("nome", "")).strip():
                continue
            _ini = _di_prev + pd.Timedelta(days=int(et.get("dias_offset", 0)))
            _fim = _ini + pd.Timedelta(
                days=max(1, int(et.get("duracao_dias", 1))) - 1
            )
            _rows_prev.append(
                {"Etapa": et["nome"], "Início": _ini, "Fim": _fim}
            )

        if _rows_prev:
            _df_prev = pd.DataFrame(_rows_prev)
            _fig_prev = px.timeline(
                _df_prev, x_start="Início", x_end="Fim", y="Etapa",
                color="Etapa",
            )
            _fig_prev.update_yaxes(autorange="reversed", title_text="")
            _fig_prev.update_layout(height=250, showlegend=False,
                                    margin=dict(l=5, r=5, t=20, b=10))
            _estiliza_plotly(_fig_prev)
            st.plotly_chart(_fig_prev, use_container_width=True)
            st.caption("ℹ️ Datas calculadas a partir de hoje como referência.")
