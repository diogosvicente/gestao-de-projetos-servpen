"""Aba Tarefas — checklist pessoal (estilo "TO DO") + atribuição pelo gestor.

Modelo:
 - Cada usuário cria e gere as SUAS tarefas (marca concluída, exclui).
 - Uma tarefa pode ser 🔒 privada: só o dono vê — nem o gestor.
 - O Gestor vê as tarefas NÃO privadas dos usuários da sua equipe
   (GERAL = todas as equipes) e pode ATRIBUIR novas; a tarefa atribuída
   aparece na lista da pessoa marcada como "atribuída por <gestor>".

Permissões:
 - dono: criar / concluir / reabrir / excluir as próprias (privadas ou não).
 - gestor: ver não-privadas da equipe + atribuir + remover as que ELE atribuiu.
"""

from __future__ import annotations

import streamlit as st

import database as db
from core.helpers import _pode_gestor
from core.ui_feedback import confirmar_sucesso

usuario = st.session_state.usuario
perfil = st.session_state.get("perfil", "Projetista")
equipe = st.session_state.get("equipe", "SERVPEN")


def _linha_tarefa_propria(t):
    """Linha da MINHA lista: checkbox (concluir) + texto + excluir."""
    col_main, col_del = st.columns([0.92, 0.08])

    _label = t["descricao"]
    _extra = []
    if t.get("privada"):
        _extra.append("🔒")
    if t.get("criado_por") and t["criado_por"] != usuario:
        _extra.append(f"_atribuída por {t['criado_por']}_")
    if _extra:
        _label += "  ·  " + "  ".join(_extra)
    if t["concluida"]:
        _label = f"~~{_label}~~"

    novo = col_main.checkbox(_label, value=bool(t["concluida"]),
                             key=f"chk_prop_{t['id']}")
    if novo != bool(t["concluida"]):
        db.alternar_tarefa(t["id"], novo)
        st.rerun()
    if col_del.button("🗑️", key=f"del_prop_{t['id']}", help="Excluir tarefa"):
        db.excluir_tarefa(t["id"])
        st.rerun()


def _linha_tarefa_gestor(t):
    """Linha na visão do gestor: status (somente leitura) + texto. O lixo só
    aparece nas tarefas que o PRÓPRIO gestor atribuiu."""
    col_main, col_del = st.columns([0.92, 0.08])

    _icone = "✅" if t["concluida"] else "⬜"
    _label = f"{_icone} {t['descricao']}"
    _eu_atribui = (t.get("criado_por") == usuario)
    if _eu_atribui:
        _label += "  ·  _você atribuiu_"
    elif t.get("criado_por") and t["criado_por"] != t["usuario"]:
        _label += f"  ·  _atribuída por {t['criado_por']}_"
    if t["concluida"]:
        _label = f"~~{_label}~~"

    col_main.markdown(_label)
    if _eu_atribui:
        if col_del.button("🗑️", key=f"del_gest_{t['id']}",
                          help="Remover a tarefa que você atribuiu"):
            db.excluir_tarefa(t["id"])
            st.rerun()


# ══════════════════════════════════════════════════════════════════════
st.header("✅ Tarefas")
st.caption(
    "Seu checklist pessoal — anote o que precisa fazer e marque ao concluir. "
    "Marque 🔒 **Privada** se não quiser que o gestor veja."
)

# ── O "+" : adicionar tarefa pra mim ──────────────────────────────────
with st.form("form_nova_tarefa", clear_on_submit=True):
    c1, c2, c3 = st.columns([0.62, 0.18, 0.20])
    _desc = c1.text_input(
        "Nova tarefa", placeholder="O que você precisa fazer?",
        label_visibility="collapsed", key="tarefa_nova_desc",
    )
    _priv = c2.checkbox("🔒 Privada", key="tarefa_nova_priv",
                        help="Só você vê. Nem o gestor enxerga.")
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

# ── Minhas tarefas ────────────────────────────────────────────────────
_minhas = db.listar_tarefas_de(usuario, incluir_privadas=True)
_pend = [t for t in _minhas if not t["concluida"]]
_feitas = [t for t in _minhas if t["concluida"]]

st.subheader(f"📋 Minhas tarefas — {len(_pend)} pendente(s)")
if not _minhas:
    st.info("Nenhuma tarefa ainda. Use o campo acima pra adicionar a primeira. 🚀")
else:
    for t in _pend:
        _linha_tarefa_propria(t)
    if _feitas:
        with st.expander(f"✔️ Concluídas ({len(_feitas)})", expanded=False):
            for t in _feitas:
                _linha_tarefa_propria(t)

# ── Visão do GESTOR: tarefas da equipe ────────────────────────────────
if _pode_gestor():
    st.divider()
    st.subheader("👥 Tarefas da equipe")
    st.caption(
        "Você vê as tarefas **não privadas** da equipe e pode atribuir novas. "
        "Tarefas privadas dos projetistas não aparecem aqui."
    )

    _membros = [m for (m, _eq) in db.membros_para_gestor(equipe) if m != usuario]
    if not _membros:
        st.info("Nenhum outro membro na sua equipe ainda.")
    else:
        _alvo = st.selectbox("Membro da equipe", _membros,
                             key="tarefa_gestor_alvo")

        with st.form("form_atribuir_tarefa", clear_on_submit=True):
            ca, cb = st.columns([0.80, 0.20])
            _d2 = ca.text_input(
                "Atribuir tarefa",
                placeholder=f"Nova tarefa para {_alvo}...",
                label_visibility="collapsed", key="tarefa_atrib_desc",
            )
            _go = cb.form_submit_button("➕ Atribuir", width="stretch")
        if _go:
            if _d2.strip():
                _eq_alvo = (db.obter_usuario(_alvo) or {}).get("equipe") \
                    or "SERVPEN"
                if db.criar_tarefa(_alvo, _d2, privada=False,
                                   criado_por=usuario, equipe=_eq_alvo):
                    confirmar_sucesso("Tarefa atribuída",
                                      f"“{_d2.strip()}” → {_alvo}")
                    st.rerun()
                else:
                    st.warning("Não consegui atribuir. Tente novamente.")
            else:
                st.warning("Escreva a tarefa antes de atribuir.")

        _do_membro = db.listar_tarefas_de(_alvo, incluir_privadas=False)
        _mp = [t for t in _do_membro if not t["concluida"]]
        _mf = [t for t in _do_membro if t["concluida"]]
        st.markdown(
            f"**{_alvo}** — {len(_mp)} pendente(s) · {len(_mf)} concluída(s)"
        )
        if not _do_membro:
            st.caption("Sem tarefas visíveis para este membro.")
        else:
            for t in _mp:
                _linha_tarefa_gestor(t)
            if _mf:
                with st.expander(f"✔️ Concluídas de {_alvo} ({len(_mf)})",
                                 expanded=False):
                    for t in _mf:
                        _linha_tarefa_gestor(t)
