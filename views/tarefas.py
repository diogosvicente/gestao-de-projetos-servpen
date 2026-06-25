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

import html as _html
from datetime import date

import pandas as pd
import streamlit as st

import database as db
from core.data import _load_df_p
from core.helpers import _pode_gestor
from core.ui_feedback import confirmar_sucesso

usuario = st.session_state.usuario
perfil = st.session_state.get("perfil", "Projetista")
equipe = st.session_state.get("equipe", "SERVPEN")

# Abrir a aba marca como vistas as tarefas atribuídas → some o badge/toast.
db.marcar_tarefas_vistas(usuario)

# Projetos visíveis pro vínculo opcional "📁 Projeto": {nome: id}.
_df_proj_tar = _load_df_p(usuario, perfil)
_PROJ_MAP = ({} if _df_proj_tar.empty else {
    str(r["projeto"]): int(r["id"]) for _, r in _df_proj_tar.iterrows()
    if str(r.get("projeto") or "").strip()
})
_PROJ_NOMES = ["— Nenhum —"] + sorted(_PROJ_MAP.keys())
_REC_LABEL = {"Não repetir": "nenhuma", "Diária": "diaria",
              "Semanal": "semanal", "Mensal": "mensal"}
_REC_NOME = {"nenhuma": "—", "diaria": "🔁 Diária", "semanal": "🔁 Semanal",
             "mensal": "🔁 Mensal"}
_REC_LABEL_INV = {v: k for k, v in _REC_LABEL.items()}  # código -> rótulo


def _proj_label(t):
    """Rótulo do projeto da tarefa (nome se visível p/ mim, senão Nenhum) —
    usado pra exibir E comparar na hora de salvar."""
    _pn = t.get("projeto_nome")
    return _pn if _pn in _PROJ_MAP else "— Nenhum —"


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
        key="tarefa_nova_desc",
    )
    fc1, fc2 = st.columns(2, vertical_alignment="bottom")
    _dt = fc1.date_input("📅 Data", value=date.today(), format="DD/MM/YYYY",
                         key="tarefa_nova_data")
    _rep = fc2.selectbox("🔁 Repetir",
                         ["Não repetir", "Diária", "Semanal", "Mensal"],
                         key="tarefa_nova_rep")
    fc3, fc4 = st.columns(2, vertical_alignment="bottom")
    _proj_sel = fc3.selectbox("📁 Projeto (opcional)", _PROJ_NOMES,
                              key="tarefa_nova_proj")
    _priv = fc4.checkbox("🔒 Manter privada", value=True,
                         key="tarefa_nova_priv",
                         help="Marcada por padrão. Desmarque pra o gestor ver.")
    _add = st.form_submit_button("➕ Adicionar", width="stretch")
if _add:
    if _desc.strip():
        if db.criar_tarefa(usuario, _desc, privada=_priv, criado_por=usuario,
                           equipe=equipe, data=_dt,
                           projeto_id=_PROJ_MAP.get(_proj_sel),
                           recorrencia=_REC_LABEL.get(_rep, "nenhuma")):
            confirmar_sucesso("Tarefa adicionada", _desc.strip())
            st.rerun()
        else:
            st.warning("Não consegui salvar a tarefa. Tente novamente.")
    else:
        st.warning("Escreva a tarefa antes de adicionar.")

# ── Minhas tarefas (tabela editável) ──────────────────────────────────
_minhas = db.listar_tarefas_de(usuario, incluir_privadas=True)
_pend = sum(1 for t in _minhas if not t["concluida"])

_ca, _cb = st.columns([0.68, 0.32], vertical_alignment="bottom")
_ca.subheader(f"📋 Minhas tarefas — {_pend} pendente(s)")
_so_hoje = _cb.toggle("📅 Só hoje", key="tarefa_so_hoje",
                      help="Mostra só as tarefas com data de hoje.")

# Aplica o filtro "Hoje" ANTES de montar a tabela — a lista filtrada (`_vis`)
# alimenta o editor E o loop de salvar (índices precisam estar alinhados).
_vis = [t for t in _minhas
        if (not _so_hoje) or (t["data"] == date.today())]

if not _minhas:
    st.info("Nenhuma tarefa ainda. Adicione a primeira no campo acima. 🚀")
elif not _vis:
    st.info("Nada para hoje. 🎉 Desmarque **Só hoje** pra ver todas.")
else:
    _df_my = pd.DataFrame([{
        "Data": t["data"],
        "Nome": usuario,
        "Tarefa": t["descricao"],
        "📁 Projeto": _proj_label(t),
        "Concluída": bool(t["concluida"]),
        "✔ Feito em": _fmt_data(t["concluida_em"]) if t.get("concluida_em")
                      else "",
        "🔒 Privada": bool(t["privada"]),
        "🔁 Repete": _REC_LABEL_INV.get(t.get("recorrencia", "nenhuma"),
                                        "Não repetir"),
        "🗑️": False,
    } for t in _vis])
    _df_my["Data"] = pd.to_datetime(_df_my["Data"], errors="coerce")

    # `key` versionado: depois de salvar, incrementamos a versão pra o editor
    # reiniciar do zero (descarta o delta já aplicado e relê do banco).
    _ver = st.session_state.get("_ed_minhas_ver", 0)
    _edit = st.data_editor(
        _df_my, key=f"ed_minhas_{_ver}", num_rows="fixed", hide_index=True,
        width="stretch",
        column_config={
            "Data": st.column_config.DateColumn(
                "📅 Data", format="DD/MM/YYYY", width="small",
                help="Data planejada — pode mudar quando quiser."),
            "Nome": st.column_config.TextColumn("👤 Nome", disabled=True,
                                                width="small"),
            "Tarefa": st.column_config.TextColumn("📝 Tarefa", width="large"),
            "📁 Projeto": st.column_config.SelectboxColumn(
                "📁 Projeto", options=_PROJ_NOMES, width="medium",
                help="Vincular a um projeto (aparece no Kanban)."),
            "Concluída": st.column_config.CheckboxColumn("✅ Concluída",
                                                         width="medium"),
            "✔ Feito em": st.column_config.TextColumn(
                "✔ Feito em", disabled=True, width="small",
                help="Data em que foi concluída."),
            "🔒 Privada": st.column_config.CheckboxColumn(
                "🔒 Privada", width="medium",
                help="Privada (só você). Desmarque pra o gestor ver."),
            "🔁 Repete": st.column_config.SelectboxColumn(
                "🔁 Repete", options=list(_REC_LABEL.keys()), width="small",
                help="Recorrência. 'Não repetir' = para de repetir."),
            "🗑️": st.column_config.CheckboxColumn(
                "❌ Excluir", width="medium",
                help="Marque e clique em Salvar pra excluir."),
        },
    )

    if st.button("💾 Salvar alterações", key="salvar_minhas", width="stretch"):
        _mudou = False
        for i, t in enumerate(_vis):
            _r = _edit.iloc[i]
            if bool(_r["🗑️"]):
                db.excluir_tarefa(t["id"]); _mudou = True
                continue
            if bool(_r["Concluída"]) != bool(t["concluida"]):
                db.alternar_tarefa(t["id"], bool(_r["Concluída"]))
                _mudou = True
                # Recorrência: ao concluir, gera a próxima ocorrência.
                if bool(_r["Concluída"]):
                    db.criar_proxima_ocorrencia(t["id"])
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
            _np_lbl = str(_r["📁 Projeto"])
            if _np_lbl != _proj_label(t):
                db.atualizar_projeto_tarefa(t["id"], _PROJ_MAP.get(_np_lbl))
                _mudou = True
            _nr_lbl = str(_r["🔁 Repete"])
            if _nr_lbl != _REC_LABEL_INV.get(t.get("recorrencia", "nenhuma"),
                                             "Não repetir"):
                db.atualizar_recorrencia_tarefa(
                    t["id"], _REC_LABEL.get(_nr_lbl, "nenhuma"))
                _mudou = True
        st.session_state["_ed_minhas_ver"] = _ver + 1  # reinicia o editor
        if _mudou:
            confirmar_sucesso("Tarefas atualizadas", "")
        st.rerun()

    st.caption("Edite a data/o texto, marque ✔ / 🔒 / 🗑️ e clique em "
               "**Salvar alterações**.")

    # Visão "planilha" só-leitura com cabeçalhos CENTRALIZADOS e coloridos (o
    # data_editor acima é canvas e não permite centralizar). Mostra também
    # Projeto / Recorrência / Feito em.
    with st.expander("🖥️ Ver como planilha (cabeçalhos centralizados)"):
        _th = ("padding:7px 8px;text-align:center;font-weight:700;"
               "font-size:12px;color:#fff;background:#0f766e;"
               "border:1px solid rgba(255,255,255,.12);")
        _td = ("padding:6px 8px;border:1px solid rgba(255,255,255,.08);"
               "font-size:13px;")
        _linhas = ""
        for t in _vis:
            _stt = "✅ Concluída" if t["concluida"] else "⬜ Pendente"
            _linhas += (
                "<tr>"
                f"<td style='{_td}text-align:center'>{_fmt_data(t['data'])}</td>"
                f"<td style='{_td}'>{_html.escape(str(t['descricao']))}</td>"
                f"<td style='{_td}text-align:center'>"
                f"{_html.escape(str(t.get('projeto_nome') or '—'))}</td>"
                f"<td style='{_td}text-align:center'>{_stt}</td>"
                f"<td style='{_td}text-align:center'>"
                f"{'🔒' if t['privada'] else '—'}</td>"
                f"<td style='{_td}text-align:center'>"
                f"{_REC_NOME.get(t.get('recorrencia', 'nenhuma'), '—')}</td>"
                f"<td style='{_td}text-align:center'>"
                f"{_fmt_data(t['concluida_em']) if t.get('concluida_em') else '—'}"
                "</td></tr>"
            )
        st.markdown(
            "<table style='width:100%;border-collapse:collapse;'>"
            "<thead><tr>"
            f"<th style='{_th}'>📅 Data</th>"
            f"<th style='{_th}'>📝 Tarefa</th>"
            f"<th style='{_th}'>📁 Projeto</th>"
            f"<th style='{_th}'>✅ Status</th>"
            f"<th style='{_th}'>🔒 Privada</th>"
            f"<th style='{_th}'>🔁 Repete</th>"
            f"<th style='{_th}'>✔ Feito em</th>"
            "</tr></thead><tbody>" + _linhas + "</tbody></table>",
            unsafe_allow_html=True,
        )

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
                                key="tarefa_atrib_desc")
            gc1, gc2 = st.columns(2, vertical_alignment="bottom")
            _dt2 = gc1.date_input("📅 Data", value=date.today(),
                                  format="DD/MM/YYYY", key="tarefa_atrib_data")
            _rep2 = gc2.selectbox("🔁 Repetir",
                                  ["Não repetir", "Diária", "Semanal",
                                   "Mensal"], key="tarefa_atrib_rep")
            _proj2 = st.selectbox("📁 Projeto (opcional)", _PROJ_NOMES,
                                  key="tarefa_atrib_proj")
            _go = st.form_submit_button("➕ Atribuir", width="stretch")
        if _go:
            if _d2.strip():
                _eqa = (db.obter_usuario(_alvo) or {}).get("equipe") \
                    or "SERVPEN"
                if db.criar_tarefa(_alvo, _d2, privada=False,
                                   criado_por=usuario, equipe=_eqa, data=_dt2,
                                   projeto_id=_PROJ_MAP.get(_proj2),
                                   recorrencia=_REC_LABEL.get(_rep2,
                                                              "nenhuma")):
                    db.log_aud(usuario, "atribuir_tarefa", "tarefa", None,
                               f"para {_alvo}: {_d2.strip()[:120]}")
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
            "Projeto": t.get("projeto_nome") or "—",
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
