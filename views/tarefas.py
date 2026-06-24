"""Aba Tarefas — checklist em formato de TABELA (estilo "Work Checklist").

Layout inspirado em planilha: Data · Nome · Cargo · Tarefa · ✔ (editável via
st.data_editor — rola na horizontal no celular, melhor que colunas espremidas).

Privacidade: cada tarefa nasce 🔒 PRIVADA por padrão (só o dono vê). O dono
pode desmarcar o cadeado na criação OU a qualquer momento (alterna pública).

 - Cada usuário tem sua tabela: edita texto, marca concluída, alterna privada
   e exclui (marca a coluna 🗑️) — tudo de uma vez no botão "💾 Salvar".
 - O Gestor vê numa tabela as tarefas NÃO privadas da equipe e pode atribuir
   novas; remove as que ele mesmo atribuiu.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import database as db
from core.helpers import _pode_gestor
from core.ui_feedback import confirmar_sucesso

usuario = st.session_state.usuario
equipe = st.session_state.get("equipe", "SERVPEN")
_me = db.obter_usuario(usuario) or {}
_meu_cargo = _me.get("cargo") or "—"


def _fmt_data(v):
    """TIMESTAMP -> 'dd/mm/aaaa' (tolerante a None / texto)."""
    try:
        return v.strftime("%d/%m/%Y")
    except Exception:
        s = str(v or "")
        return s[:10] if s else "—"


st.header("✅ Tarefas")
st.caption(
    "Seu checklist. Cada tarefa nasce 🔒 **privada** (só você vê) — desmarque "
    "o cadeado, na criação ou depois, pra que o gestor possa acompanhar."
)

# ── O "+" : nova tarefa (privada por padrão) ──────────────────────────
with st.form("form_nova_tarefa", clear_on_submit=True):
    c1, c2, c3 = st.columns([0.60, 0.20, 0.20])
    _desc = c1.text_input(
        "Nova tarefa", placeholder="O que você precisa fazer?",
        label_visibility="collapsed", key="tarefa_nova_desc",
    )
    _priv = c2.checkbox("🔒 Privada", value=True, key="tarefa_nova_priv",
                        help="Marcada por padrão. Desmarque pra o gestor ver.")
    _add = c3.form_submit_button("➕ Adicionar", width="stretch")
if _add:
    if _desc.strip():
        if db.criar_tarefa(usuario, _desc, privada=_priv,
                           criado_por=usuario, equipe=equipe):
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
        "Data": _fmt_data(t["criado_em"]),
        "Nome": usuario,
        "Cargo": _meu_cargo,
        "Tarefa": t["descricao"],
        "Concluída": bool(t["concluida"]),
        "🔒 Privada": bool(t["privada"]),
        "🗑️": False,
    } for t in _minhas])

    # `key` versionado: depois de salvar, incrementamos a versão pra o editor
    # reiniciar do zero (descarta o delta já aplicado e relê do banco).
    _ver = st.session_state.get("_ed_minhas_ver", 0)
    _edit = st.data_editor(
        _df_my, key=f"ed_minhas_{_ver}", num_rows="fixed", hide_index=True,
        width="stretch",
        column_config={
            "Data": st.column_config.TextColumn("Data", disabled=True,
                                                width="small"),
            "Nome": st.column_config.TextColumn("Nome", disabled=True,
                                                width="small"),
            "Cargo": st.column_config.TextColumn("Cargo", disabled=True,
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
        st.session_state["_ed_minhas_ver"] = _ver + 1  # reinicia o editor
        if _mudou:
            confirmar_sucesso("Tarefas atualizadas", "")
        st.rerun()

    st.caption("Edite o texto, marque ✔ / 🔒 / 🗑️ e clique em **Salvar "
               "alterações**.")

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
            ca, cb, cc = st.columns([0.32, 0.48, 0.20])
            _alvo = ca.selectbox("Para", _membros,
                                 label_visibility="collapsed",
                                 key="tarefa_gestor_alvo")
            _d2 = cb.text_input("Tarefa", placeholder="Atribuir nova tarefa...",
                                label_visibility="collapsed",
                                key="tarefa_atrib_desc")
            _go = cc.form_submit_button("➕ Atribuir", width="stretch")
        if _go:
            if _d2.strip():
                _eqa = (db.obter_usuario(_alvo) or {}).get("equipe") \
                    or "SERVPEN"
                if db.criar_tarefa(_alvo, _d2, privada=False,
                                   criado_por=usuario, equipe=_eqa):
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
            "Data": _fmt_data(t["criado_em"]),
            "Nome": t["usuario"],
            "Cargo": t.get("cargo") or "—",
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
