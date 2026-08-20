"""Aba Tarefas — checklist em CARDS agrupados por data.

Desenho (pedido de 29/07/2026):
 - **Um único formulário de cadastro.** O campo "👤 Atribuir a" (só o Gestor
   vê) decide o destino: vazio = tarefa minha; preenchido = tarefa de outra
   pessoa. Antes eram dois formulários separados fazendo a mesma chamada.
 - **Contadores clicáveis** no topo funcionam como filtro (Todas / Atrasadas
   / Hoje / Semana / Concluídas).
 - **Cards agrupados por data** (Atrasadas · Hoje · Amanhã · Esta semana ·
   Depois · Sem data · Concluídas), cada card com faixa lateral colorida por
   urgência.
 - Toda tarefa nasce 🔒 privada (só o dono vê); o dono desmarca quando quiser.
   Tarefa atribuída pelo Gestor nasce pública — senão ele não acompanharia.
 - Exclusão segue **um padrão único** nas duas seções (minhas e da equipe):
   popover de confirmação no próprio card.
"""

from __future__ import annotations

import html as _html
from datetime import date, timedelta

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
_REC_NOME = {"nenhuma": "", "diaria": "🔁 Diária", "semanal": "🔁 Semanal",
             "mensal": "🔁 Mensal"}
_REC_LABEL_INV = {v: k for k, v in _REC_LABEL.items()}  # código -> rótulo

_HOJE = date.today()
_EU = "— Eu mesmo —"

# Cores da faixa lateral por urgência (mesma paleta usada na Agenda).
_COR = {
    "atrasadas": "#ef4444", "hoje": "#f59e0b", "amanha": "#0ea5e9",
    "semana": "#0ea5e9", "depois": "#64748b", "sem_data": "#64748b",
    "concluidas": "#22c55e",
}
# Ordem de exibição dos blocos + rótulo do cabeçalho de cada um.
_GRUPOS = [
    ("atrasadas", "🔴 Atrasadas"), ("hoje", "🟡 Hoje"),
    ("amanha", "🔵 Amanhã"), ("semana", "🔵 Esta semana"),
    ("depois", "⚪ Depois"), ("sem_data", "⚪ Sem data"),
    ("concluidas", "✅ Concluídas"),
]


def _proj_label(t):
    """Rótulo do projeto da tarefa (nome se visível p/ mim, senão Nenhum)."""
    _pn = t.get("projeto_nome")
    return _pn if _pn in _PROJ_MAP else "— Nenhum —"


def _fmt_data(v):
    """date/TIMESTAMP -> 'dd/mm/aaaa' (tolerante a None / texto)."""
    try:
        return v.strftime("%d/%m/%Y")
    except Exception:
        s = str(v or "")
        return s[:10] if s else "—"


def _grupo_de(t):
    """Em qual bloco a tarefa cai (só depende de concluída + data)."""
    if t["concluida"]:
        return "concluidas"
    d = t["data"]
    if not d:
        return "sem_data"
    if d < _HOJE:
        return "atrasadas"
    if d == _HOJE:
        return "hoje"
    if d == _HOJE + timedelta(days=1):
        return "amanha"
    if d <= _HOJE + timedelta(days=7):
        return "semana"
    return "depois"


def _chip(txt, cor="#334155"):
    """Etiqueta pequena usada dentro do card (projeto, recorrência...)."""
    return (f"<span style='background:{cor};color:#e2e8f0;padding:2px 8px;"
            f"border-radius:10px;font-size:11px;margin-right:5px;"
            f"display:inline-block;white-space:nowrap;'>"
            f"{_html.escape(str(txt))}</span>")


def _toggle_concluida(tid, chave):
    """Callback do checkbox: grava na hora e gera a próxima ocorrência."""
    novo = bool(st.session_state.get(chave))
    db.alternar_tarefa(tid, novo)
    if novo:
        db.criar_proxima_ocorrencia(tid)


st.header("✅ Tarefas")
st.caption(
    "Seu checklist. Toda tarefa nasce 🔒 **privada** (só você vê) — desmarque "
    "o cadeado pra que o gestor possa acompanhar."
    + ("  Como Gestor, você também atribui tarefas a outras pessoas no mesmo "
       "formulário abaixo." if _pode_gestor() else "")
)

# ── Cards coloridos por urgência ──────────────────────────────────────
# st.container(border=True) não aceita estilo, então cada card imprime um
# marcador invisível (.tk-<grupo>) e o CSS pinta o container que o contém,
# via `:has()`. Mesma paleta dos cards do Kanban, pra o sistema inteiro ter
# a mesma linguagem visual. Como o fundo é colorido nos DOIS temas, os
# textos/ícones dentro vão sempre em tom claro.
_CARD_BG = {
    "atrasadas":  ("#5c1414", "#ff4d4d"),
    "hoje":       ("#7c3a0a", "#ff9f43"),
    "amanha":     ("#0d3d75", "#00d4ff"),
    "semana":     ("#0d3d75", "#00d4ff"),
    "depois":     ("#3b1f6e", "#7c3aed"),
    "sem_data":   ("#334155", "#94a3b8"),
    "concluidas": ("#143d14", "#4dff4d"),
}
# O container com borda do Streamlit 1.58 é um `div[data-testid=
# "stVerticalBlock"]` — mas esse MESMO testid também envolve os blocos
# externos da página. Por isso o `:has()` precisa ser ancorado no filho
# direto (`> stElementContainer`), senão ele casa também com os blocos de
# fora e a página inteira sai colorida. Verificado no DOM real: com o
# ancoramento casa exatamente 1 elemento, e é o que tem a borda.
def _sel_card(marca):
    return ('div[data-testid="stVerticalBlock"]'
            f':has(> div[data-testid="stElementContainer"] .{marca})')


_css_cards = "".join(
    f'{_sel_card("tk-" + _k)}'
    f'{{background:{_bg} !important;border:1px solid rgba(255,255,255,.10)'
    f' !important;border-left:5px solid {_bd} !important;'
    f'border-radius:10px !important;}}'
    for _k, (_bg, _bd) in _CARD_BG.items()
)
st.markdown(
    "<style>"
    ".tk-marca{display:none;}"
    + _css_cards +
    # Texto/ícones dos widgets nativos dentro do card (checkbox, botões)
    # precisam ficar claros — o padrão do tema claro os deixaria escuros.
    f'{_sel_card("tk-marca")} label p,'
    f'{_sel_card("tk-marca")} [data-testid="stCaptionContainer"] p'
    '{color:#e2e8f0 !important;}'
    "</style>",
    unsafe_allow_html=True,
)

# ── Formulário ÚNICO de cadastro ──────────────────────────────────────
# O antigo "Tarefas da equipe > atribuir" foi fundido aqui: a diferença é só
# quem vai no parâmetro `usuario` da chamada a db.criar_tarefa.
_membros = ([m for (m, _e) in db.membros_para_gestor(equipe) if m != usuario]
            if _pode_gestor() else [])

with st.form("form_nova_tarefa", clear_on_submit=True):
    _desc = st.text_input(
        "Nova tarefa", placeholder="O que precisa ser feito?",
        key="tarefa_nova_desc",
    )
    fc1, fc2 = st.columns(2, vertical_alignment="bottom")
    _dt = fc1.date_input("📅 Data", value=_HOJE, format="DD/MM/YYYY",
                         key="tarefa_nova_data")
    _rep = fc2.selectbox("🔁 Repetir",
                         ["Não repetir", "Diária", "Semanal", "Mensal"],
                         key="tarefa_nova_rep")
    fc3, fc4 = st.columns(2, vertical_alignment="bottom")
    _proj_sel = fc3.selectbox("📁 Projeto (opcional)", _PROJ_NOMES,
                              key="tarefa_nova_proj")
    if _membros:
        _alvo_sel = fc4.selectbox(
            "👤 Atribuir a", [_EU] + _membros, key="tarefa_nova_alvo",
            help="Deixe em 'Eu mesmo' pra uma tarefa sua. Escolhendo outra "
                 "pessoa, ela recebe a tarefa (e fica pública, pra você "
                 "acompanhar).",
        )
    else:
        _alvo_sel = _EU
    _priv = st.checkbox(
        "🔒 Manter privada", value=True, key="tarefa_nova_priv",
        help="Vale só pras suas tarefas. Tarefa atribuída a outra pessoa "
             "nasce pública por definição.",
    )
    _add = st.form_submit_button("➕ Adicionar", width="stretch")

if _add:
    if _desc.strip():
        _para_mim = (_alvo_sel == _EU)
        _dono = usuario if _para_mim else _alvo_sel
        _eq_dono = (equipe if _para_mim
                    else ((db.obter_usuario(_alvo_sel) or {}).get("equipe")
                          or "SERVPEN"))
        if db.criar_tarefa(_dono, _desc, privada=(_priv and _para_mim),
                           criado_por=usuario, equipe=_eq_dono, data=_dt,
                           projeto_id=_PROJ_MAP.get(_proj_sel),
                           recorrencia=_REC_LABEL.get(_rep, "nenhuma")):
            if _para_mim:
                confirmar_sucesso("Tarefa adicionada", _desc.strip())
            else:
                db.log_aud(usuario, "atribuir_tarefa", "tarefa", None,
                           f"para {_dono}: {_desc.strip()[:120]}")
                confirmar_sucesso("Tarefa atribuída",
                                  f"“{_desc.strip()}” → {_dono}")
            st.rerun()
        else:
            st.warning("Não consegui salvar a tarefa. Tente novamente.")
    else:
        st.warning("Escreva a tarefa antes de adicionar.")

# ── Minhas tarefas ────────────────────────────────────────────────────
_minhas = db.listar_tarefas_de(usuario, incluir_privadas=True)
_pend = sum(1 for t in _minhas if not t["concluida"])
_n_atras = sum(1 for t in _minhas if _grupo_de(t) == "atrasadas")
_n_hoje = sum(1 for t in _minhas if _grupo_de(t) == "hoje")
_n_sem = sum(1 for t in _minhas
             if _grupo_de(t) in ("hoje", "amanha", "semana"))
_n_ok = sum(1 for t in _minhas if t["concluida"])

_sc1, _sc2 = st.columns([0.62, 0.38], vertical_alignment="bottom")
_sc1.subheader(f"📋 Minhas tarefas — {_pend} pendente(s)")

# Como os blocos são montados: por data (Atrasadas/Hoje/...) ou por projeto.
# Vale pras duas listas (minhas e da equipe).
_MODO_GRUPO = _sc2.radio(
    "Agrupar por",
    options=["data", "projeto"],
    format_func=lambda x: ("📅 Data" if x == "data" else "📁 Projeto"),
    horizontal=True,
    key="_tar_modo_grupo",
    help="Por data mostra Atrasadas/Hoje/Amanhã…; por projeto junta as "
         "tarefas de cada projeto num bloco só.",
)

# Contadores clicáveis = filtro. `type="primary"` marca o que está ativo.
_filtro = st.session_state.get("_tar_filtro", "todas")
_tiles = [
    ("todas", f"📋 Todas · {len(_minhas)}"),
    ("atrasadas", f"🔴 Atrasadas · {_n_atras}"),
    ("hoje", f"🟡 Hoje · {_n_hoje}"),
    ("semana", f"🔵 Semana · {_n_sem}"),
    ("concluidas", f"✅ Concluídas · {_n_ok}"),
]
_cols_t = st.columns(len(_tiles))
for _col, (_chave, _rot) in zip(_cols_t, _tiles):
    if _col.button(_rot, key=f"tile_{_chave}", width="stretch",
                   type=("primary" if _filtro == _chave else "secondary")):
        # Clicar no filtro ativo volta pra "todas" (funciona como toggle).
        st.session_state["_tar_filtro"] = (
            "todas" if _filtro == _chave else _chave
        )
        st.rerun()

if _filtro == "atrasadas":
    _vis = [t for t in _minhas if _grupo_de(t) == "atrasadas"]
elif _filtro == "hoje":
    _vis = [t for t in _minhas if _grupo_de(t) == "hoje"]
elif _filtro == "semana":
    _vis = [t for t in _minhas
            if _grupo_de(t) in ("hoje", "amanha", "semana")]
elif _filtro == "concluidas":
    _vis = [t for t in _minhas if t["concluida"]]
else:
    _vis = list(_minhas)

if _n_atras and _filtro != "atrasadas":
    st.warning(f"⏰ Você tem **{_n_atras}** tarefa(s) **atrasada(s)** "
               "(data passou e ainda não concluída).")


def _card_tarefa(t, *, dono_visivel=False, pode_excluir=True,
                 pode_editar=True, prefixo="my"):
    """Um card de tarefa: faixa colorida + checkbox + chips + ações.

    `dono_visivel` mostra de quem é a tarefa (usado na visão da equipe).
    """
    _g = _grupo_de(t)
    _tid = t["id"]
    with st.container(border=True):
        # Marcador invisível que dá a cor ao card inteiro. O CSS lá em cima
        # pinta o container através do `:has(.tk-<grupo>)` — é a forma de
        # colorir um st.container, que não aceita estilo direto. Precisa vir
        # ANTES das colunas pra já estar no DOM do container.
        st.markdown(f"<span class='tk-marca tk-{_g}'></span>",
                    unsafe_allow_html=True)
        c_chk, c_txt, c_act = st.columns(
            [0.07, 0.73, 0.20], vertical_alignment="center")

        _k_chk = f"chk_{prefixo}_{_tid}"
        c_chk.checkbox(
            "Concluída", value=bool(t["concluida"]), key=_k_chk,
            label_visibility="collapsed",
            disabled=not pode_editar,
            on_change=_toggle_concluida, args=(_tid, _k_chk),
            help="Marcar como concluída",
        )

        with c_txt:
            _txt = _html.escape(str(t["descricao"]))
            if t["concluida"]:
                _txt = (f"<span style='text-decoration:line-through;"
                        f"opacity:.6'>{_txt}</span>")
            # Cor explícita: o card tem fundo colorido nos dois temas, então
            # não dá pra deixar o texto herdar (no tema claro sairia escuro
            # sobre fundo escuro).
            st.markdown(
                f"<div style='font-size:0.95rem;line-height:1.3;"
                f"color:#f8fafc;font-weight:600'>{_txt}</div>",
                unsafe_allow_html=True)

            _chips = ""
            if t["data"]:
                _cd = "#7f1d1d" if _g == "atrasadas" else "#334155"
                _chips += _chip(f"📅 {_fmt_data(t['data'])}", _cd)
            if dono_visivel:
                _chips += _chip(f"👤 {t['usuario']}", "#1e3a5f")
            if t.get("projeto_nome"):
                _chips += _chip(f"📁 {t['projeto_nome']}", "#3730a3")
            _rec = _REC_NOME.get(t.get("recorrencia", "nenhuma"), "")
            if _rec:
                _chips += _chip(_rec, "#155e75")
            if t.get("privada"):
                _chips += _chip("🔒 Privada", "#4c1d95")
            if t.get("criado_por") and t["criado_por"] != t["usuario"]:
                _chips += _chip(f"↪ de {t['criado_por']}", "#334155")
            if t["concluida"] and t.get("concluida_em"):
                _chips += _chip(f"✔ {_fmt_data(t['concluida_em'])}", "#14532d")
            if _chips:
                st.markdown(f"<div style='margin-top:4px'>{_chips}</div>",
                            unsafe_allow_html=True)

        with c_act:
            a1, a2 = st.columns(2)
            if pode_editar:
                with a1.popover("✏️", width="stretch", help="Editar"):
                    with st.form(f"form_ed_{prefixo}_{_tid}"):
                        _nd = st.text_input("Tarefa", value=t["descricao"],
                                            key=f"ed_d_{prefixo}_{_tid}")
                        _ndt = st.date_input(
                            "📅 Data", value=t["data"] or _HOJE,
                            format="DD/MM/YYYY", key=f"ed_dt_{prefixo}_{_tid}")
                        _npj = st.selectbox(
                            "📁 Projeto", _PROJ_NOMES,
                            index=_PROJ_NOMES.index(_proj_label(t)),
                            key=f"ed_pj_{prefixo}_{_tid}")
                        _nrec = st.selectbox(
                            "🔁 Repetir", list(_REC_LABEL.keys()),
                            index=list(_REC_LABEL.keys()).index(
                                _REC_LABEL_INV.get(
                                    t.get("recorrencia", "nenhuma"),
                                    "Não repetir")),
                            key=f"ed_rc_{prefixo}_{_tid}")
                        _npv = st.checkbox(
                            "🔒 Privada", value=bool(t["privada"]),
                            key=f"ed_pv_{prefixo}_{_tid}")
                        if st.form_submit_button("💾 Salvar",
                                                 width="stretch"):
                            if _nd.strip() and _nd.strip() != t["descricao"]:
                                db.atualizar_descricao_tarefa(_tid,
                                                              _nd.strip())
                            if _ndt != t["data"]:
                                db.atualizar_data_tarefa(_tid, _ndt)
                            if _npj != _proj_label(t):
                                db.atualizar_projeto_tarefa(
                                    _tid, _PROJ_MAP.get(_npj))
                            _rc_novo = _REC_LABEL.get(_nrec, "nenhuma")
                            if _rc_novo != t.get("recorrencia", "nenhuma"):
                                db.atualizar_recorrencia_tarefa(_tid, _rc_novo)
                            if bool(_npv) != bool(t["privada"]):
                                db.definir_privada_tarefa(_tid, bool(_npv))
                            confirmar_sucesso("Tarefa atualizada", "")
                            st.rerun()
            if pode_excluir:
                with a2.popover("🗑️", width="stretch", help="Excluir"):
                    st.markdown("**Excluir esta tarefa?**")
                    st.caption(f"“{t['descricao'][:80]}”")
                    if st.button("✅ Sim, excluir", type="primary",
                                 key=f"del_{prefixo}_{_tid}", width="stretch"):
                        db.excluir_tarefa(_tid)
                        confirmar_sucesso("Tarefa excluída", "")
                        st.rerun()


def _render_grupos(lista, *, dono_visivel=False, pode_excluir_fn=None,
                   pode_editar=True, prefixo="my"):
    """Renderiza os cards em blocos — por data ou por projeto, conforme o
    modo escolhido no seletor do topo (`_MODO_GRUPO`)."""
    if _MODO_GRUPO == "projeto":
        # Um bloco por projeto; quem não tem projeto cai em "Sem projeto",
        # sempre por último. Dentro do bloco, pendentes primeiro e depois
        # por data — mesma leitura do modo por data.
        _por_proj = {}
        for t in lista:
            _por_proj.setdefault(t.get("projeto_nome") or "", []).append(t)
        _ordem = sorted([p for p in _por_proj if p], key=str.lower) + (
            [""] if "" in _por_proj else [])
        for _nome_p in _ordem:
            _itens = _por_proj[_nome_p]
            _itens.sort(key=lambda x: (bool(x["concluida"]),
                                       x["data"] is None,
                                       x["data"] or _HOJE, -int(x["id"])))
            _rot = f"📁 {_nome_p}" if _nome_p else "⚪ Sem projeto"
            _cor_b = "#3730a3" if _nome_p else "#64748b"
            st.markdown(
                f"<div style='margin:14px 0 6px;font-weight:700;"
                f"font-size:0.9rem;color:{_cor_b}'>"
                f"{_rot} · {len(_itens)}</div>",
                unsafe_allow_html=True)
            for t in _itens:
                _card_tarefa(
                    t, dono_visivel=dono_visivel,
                    pode_excluir=(pode_excluir_fn(t) if pode_excluir_fn
                                  else True),
                    pode_editar=pode_editar, prefixo=prefixo)
        return

    _por_grupo = {}
    for t in lista:
        _por_grupo.setdefault(_grupo_de(t), []).append(t)
    for _chave, _rotulo in _GRUPOS:
        _itens = _por_grupo.get(_chave)
        if not _itens:
            continue
        # Dentro do bloco: por data (as sem data no fim) e depois por id.
        _itens.sort(key=lambda x: (x["data"] is None, x["data"] or _HOJE,
                                   -int(x["id"])))
        st.markdown(
            f"<div style='margin:14px 0 6px;font-weight:700;font-size:0.9rem;"
            f"color:{_COR[_chave]}'>{_rotulo} · {len(_itens)}</div>",
            unsafe_allow_html=True)
        for t in _itens:
            _card_tarefa(
                t, dono_visivel=dono_visivel,
                pode_excluir=(pode_excluir_fn(t) if pode_excluir_fn else True),
                pode_editar=pode_editar, prefixo=prefixo)


if not _minhas:
    st.info("Nenhuma tarefa ainda. Adicione a primeira no campo acima. 🚀")
elif not _vis:
    st.info("Nada neste filtro. 🎉 Clique em **📋 Todas** pra ver o resto.")
else:
    _render_grupos(_vis, prefixo="my")

# Limpeza em lote das concluídas (mantida do desenho anterior).
if _n_ok:
    if not st.session_state.get("_confirma_limpar"):
        if st.button(f"🧹 Limpar concluídas ({_n_ok})",
                     key="tarefa_limpar_btn", width="stretch"):
            st.session_state["_confirma_limpar"] = True
            st.rerun()
    else:
        st.warning(f"Excluir as **{_n_ok}** tarefas concluídas? "
                   "Não dá pra desfazer.")
        _cl1, _cl2 = st.columns(2)
        if _cl1.button("Sim, limpar", key="tarefa_limpar_sim",
                       width="stretch"):
            db.excluir_tarefas_concluidas(usuario)
            st.session_state.pop("_confirma_limpar", None)
            confirmar_sucesso("Concluídas removidas", "")
            st.rerun()
        if _cl2.button("Cancelar", key="tarefa_limpar_nao", width="stretch"):
            st.session_state.pop("_confirma_limpar", None)
            st.rerun()

# ── GESTOR: tarefas da equipe (mesmos cards, agrupados por data) ──────
if _pode_gestor():
    st.divider()
    st.subheader("👥 Tarefas da equipe")
    st.caption(
        "Tarefas **não privadas** da equipe, nos mesmos blocos por data. As "
        "🔒 privadas dos projetistas não aparecem aqui. Você remove as que "
        "atribuiu — no 🗑️ do próprio card, igual às suas."
    )

    _eq = db.listar_tarefas_equipe(equipe)
    if not _eq:
        st.info("Ninguém da equipe tem tarefas públicas no momento "
                "(as 🔒 privadas não aparecem aqui).")
    else:
        # Só edita/conclui a própria tarefa; aqui o Gestor apenas acompanha e
        # remove o que ele mesmo atribuiu.
        _render_grupos(
            _eq, dono_visivel=True, pode_editar=False,
            pode_excluir_fn=lambda t: t.get("criado_por") == usuario,
            prefixo="eq",
        )
