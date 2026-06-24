"""Aba Tarefas — checklist em formato de TABELA (estilo "Work Checklist").

Layout inspirado em planilha: Data · Nome · Tarefa · ✔ (editável via
st.data_editor — rola na horizontal no celular, melhor que colunas espremidas).

 - A coluna **Data** é a data PLANEJADA, escolhida por você (não é a data de
   criação): dá pra definir ao criar e mudar depois, direto na tabela.
 - Cada tarefa nasce 🔒 PRIVADA por padrão (só o dono vê); o dono pode desmarcar
   o cadeado na criação OU a qualquer momento (alterna pública).
 - Cada usuário tem sua tabela: edita data/texto, marca concluída, alterna
   privada e exclui (coluna 🗑️) — tudo de uma vez no botão "💾 Salvar".
 - O Gestor vê numa tabela as tarefas NÃO privadas da equipe e pode atribuir
   novas (com data); remove as que ele mesmo atribuiu.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

import database as db
from core.helpers import _pode_gestor
from core.ui_feedback import confirmar_sucesso

usuario = st.session_state.usuario
equipe = st.session_state.get("equipe", "SERVPEN")


def _fmt_data(v):
    """date/TIMESTAMP -> 'dd/mm/aaaa' (tolerante a None / texto)."""
    try:
        return v.strftime("%d/%m/%Y")
    except Exception:
        s = str(v or "")
        return s[:10] if s else "—"


st.header("✅ Tarefas")
st.caption(
    "Seu checklist. Escolha a **data** de cada tarefa. Toda tarefa nasce 🔒 "
    "**privada** (só você vê) — desmarque o cadeado, na criação ou depois, "
    "pra que o gestor possa acompanhar."
)

# ── O "+" : nova tarefa (com data; privada por padrão) ────────────────
with st.form("form_nova_tarefa", clear_on_submit=True):
    _desc = st.text_input(
        "Nova tarefa", placeholder="O que você precisa fazer?",
        label_visibility="collapsed", key="tarefa_nova_desc",
    )
    fc1, fc2, fc3 = st.columns([0.40, 0.30, 0.30])
    _dt = fc1.date_input("Data", value=date.today(), format="DD/MM/YYYY",
                         key="tarefa_nova_data")
    _priv = fc2.checkbox("🔒 Privada", value=True, key="tarefa_nova_priv",
                         help="Marcada por padrão. Desmarque pra o gestor ver.")
    _add = fc3.form_submit_button("➕ Adicionar", width="stretch")
if _add:
    if _desc.strip():
        if db.criar_tarefa(usuario, _desc, privada=_priv, criado_por=usuario,
                           equipe=equipe, data=_dt):
            confirmar_sucesso("Tarefa adicionada", _desc.strip())
            st.rerun()
        else:
            st.warning("Não consegui salvar a tarefa. Tente novamente.")
    else:
        st.warning("Escreva a tarefa antes de adicionar.")

# ── Minhas tarefas (tabela editável) ──────────────────────────────────
_minhas = db.listar_tarefas_de(usuario, incluir_privadas=True)
_pend = sum(1 for t in _minhas if not t["concluida"])
st.subheader(f"📋 Minhas tarefas — {_pend} pendente(s)")

if not _minhas:
    st.info("Nenhuma tarefa ainda. Adicione a primeira no campo acima. 🚀")
else:
    _df_my = pd.DataFrame([{
        "Data": t["data"],
        "Nome": usuario,
        "Tarefa": t["descricao"],
        "Concluída": bool(t["concluida"]),
        "🔒 Privada": bool(t["privada"]),
        "🗑️": False,
    } for t in _minhas])
    _df_my["Data"] = pd.to_datetime(_df_my["Data"], errors="coerce")

    # `key` versionado: depois de salvar, incrementamos a versão pra o editor
    # reiniciar do zero (descarta o delta já aplicado e relê do banco).
    _ver = st.session_state.get("_ed_minhas_ver", 0)
    _edit = st.data_editor(
        _df_my, key=f"ed_minhas_{_ver}", num_rows="fixed", hide_index=True,
        width="stretch",
        column_config={
            "Data": st.column_config.DateColumn(
                "Data", format="DD/MM/YYYY", width="small",
                help="Data planejada — pode mudar quando quiser."),
            "Nome": st.column_config.TextColumn("Nome", disabled=True,
                                                width="small"),
            "Tarefa": st.column_config.TextColumn("Tarefa", width="large"),
            "Concluída": st.column_config.CheckboxColumn("✔", width="small"),
            "🔒 Privada": st.column_config.CheckboxColumn(
                "🔒", width="small",
                help="Privada (só você). Desmarque pra o gestor ver."),
            "🗑️": st.column_config.CheckboxColumn(
                "🗑️", width="small",
                help="Marque e clique em Salvar pra excluir."),
        },
    )

    if st.button("💾 Salvar alterações", key="salvar_minhas", width="stretch"):
        _mudou = False
        for i, t in enumerate(_minhas):
            _r = _edit.iloc[i]
            if bool(_r["🗑️"]):
                db.excluir_tarefa(t["id"]); _mudou = True
                continue
            if bool(_r["Concluída"]) != bool(t["concluida"]):
                db.alternar_tarefa(t["id"], bool(_r["Concluída"]))
                _mudou = True
            if bool(_r["🔒 Privada"]) != bool(t["privada"]):
                db.definir_privada_tarefa(t["id"], bool(_r["🔒 Privada"]))
                _mudou = True
            _nt = str(_r["Tarefa"] or "").strip()
            if _nt and _nt != t["descricao"]:
                db.atualizar_descricao_tarefa(t["id"], _nt)
                _mudou = True
            _nd = _r["Data"]
            _nd = _nd.date() if pd.notna(_nd) else None
            if _nd != t["data"]:
                db.atualizar_data_tarefa(t["id"], _nd)
                _mudou = True
        st.session_state["_ed_minhas_ver"] = _ver + 1  # reinicia o editor
        if _mudou:
            confirmar_sucesso("Tarefas atualizadas", "")
        st.rerun()

    st.caption("Edite a data/o texto, marque ✔ / 🔒 / 🗑️ e clique em "
               "**Salvar alterações**.")

# ── GESTOR: tabela da equipe + atribuição ─────────────────────────────
if _pode_gestor():
    st.divider()
    st.subheader("👥 Tarefas da equipe")
    st.caption(
        "Tabela com as tarefas **não privadas** da equipe. As 🔒 privadas dos "
        "projetistas não aparecem aqui."
    )

    _membros = [m for (m, _e) in db.membros_para_gestor(equipe) if m != usuario]
    if _membros:
        with st.form("form_atribuir_tarefa", clear_on_submit=True):
            _alvo = st.selectbox("Para quem", _membros,
                                 key="tarefa_gestor_alvo")
            _d2 = st.text_input("Tarefa",
                                placeholder="Nova tarefa pra atribuir...",
                                label_visibility="collapsed",
                                key="tarefa_atrib_desc")
            gc1, gc2 = st.columns([0.5, 0.5])
            _dt2 = gc1.date_input("Data", value=date.today(),
                                  format="DD/MM/YYYY", key="tarefa_atrib_data")
            _go = gc2.form_submit_button("➕ Atribuir", width="stretch")
        if _go:
            if _d2.strip():
                _eqa = (db.obter_usuario(_alvo) or {}).get("equipe") \
                    or "SERVPEN"
                if db.criar_tarefa(_alvo, _d2, privada=False,
                                   criado_por=usuario, equipe=_eqa, data=_dt2):
                    confirmar_sucesso("Tarefa atribuída",
                                      f"“{_d2.strip()}” → {_alvo}")
                    st.rerun()
                else:
                    st.warning("Não consegui atribuir. Tente novamente.")
            else:
                st.warning("Escreva a tarefa antes de atribuir.")
    else:
        st.info("Nenhum outro membro na sua equipe ainda.")

    _eq = db.listar_tarefas_equipe(equipe)
    if not _eq:
        st.info("Ninguém da equipe tem tarefas públicas no momento "
                "(as 🔒 privadas não aparecem aqui).")
    else:
        _df_eq = pd.DataFrame([{
            "Data": _fmt_data(t["data"]),
            "Nome": t["usuario"],
            "Tarefa": t["descricao"],
            "Status": "✅ Concluída" if t["concluida"] else "⬜ Pendente",
            "Atribuída por": ("você" if t.get("criado_por") == usuario
                              else (t.get("criado_por") or "—")),
        } for t in _eq])
        st.dataframe(_df_eq, hide_index=True, width="stretch")

        _minhas_atrib = [t for t in _eq if t.get("criado_por") == usuario]
        if _minhas_atrib:
            with st.expander("🗑️ Remover tarefa que você atribuiu"):
                _opts = {f"{t['usuario']}: {t['descricao']}": t["id"]
                         for t in _minhas_atrib}
                _sel = st.selectbox("Selecione", list(_opts.keys()),
                                    key="tarefa_remover_sel")
                if st.button("Remover", key="tarefa_remover_btn"):
                    db.excluir_tarefa(_opts[_sel])
                    confirmar_sucesso("Atribuição removida", _sel)
                    st.rerun()
