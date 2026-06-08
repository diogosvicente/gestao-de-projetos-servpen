"""Aba Equipe — gestão de membros (somente Gestor).

Cadastro/edição/remoção de usuários, incluindo perfil, cargo, pergunta
secreta e troca de senha. Senha sempre hasheada via `db.gerar_hash`.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import database as db

from core.auth_ui import _avatar_circular_html
from core.data import _invalidar_dados
from core.helpers import _empty_state, _equipe_atual, _pode_gestor, _ve_tudo
from core.ui_feedback import carregando


# Guard de perfil — Gestor-only
if not _pode_gestor():
    st.error(
        "⚠️ Acesso Restrito: Apenas Gestores podem gerenciar permissões "
        "da equipe."
    )
    st.stop()


usuario = st.session_state.usuario

# Escopo de equipe do gestor logado. GERAL = vê/edita tudo e escolhe a
# equipe ao cadastrar. Líder de equipe (SERVPEN/SERVPAR) só vê/edita a
# própria equipe e NÃO promove ninguém a Gestor nem muda equipe (regra
# em docs/PROMPT-controle-equipes.md §3.1).
_MINHA_EQUIPE = _equipe_atual()
_GERAL = _ve_tudo()
_EQUIPES = ["SERVPEN", "SERVPAR", "GERAL"]

st.header("👥 Gestão de Membros e Acessos")
if not _GERAL:
    st.caption(
        f"Você gerencia a equipe **{_MINHA_EQUIPE}**. Pessoas que você "
        f"cadastrar entram automaticamente nesta equipe."
    )

# 1. CADASTRO DE NOVO MEMBRO
with st.expander("➕ Cadastrar Novo Colaborador"):
    with st.form("novo_usuario_form"):
        c1, c2 = st.columns(2)
        n_nome = c1.text_input("Nome Completo")
        n_cargo = c2.text_input("Cargo (ex: Eng. Civil, Estagiário HVAC)")

        c3, c4 = st.columns(2)
        n_senha = c3.text_input("Senha de Acesso", type="password")
        # Perfis disponíveis dependem do escopo: só o Gestor Geral pode
        # criar outro Gestor (promover a líder). Líder de equipe cria só
        # Projetista/Visualizador.
        _perfis_novo = (
            ["Projetista", "Gestor", "Visualizador"] if _GERAL
            else ["Projetista", "Visualizador"]
        )
        n_perf = c4.selectbox(
            "Perfil de Sistema",
            _perfis_novo,
            help=(
                "Visualizador: acesso somente leitura. "
                + ("Gestor: líder de equipe."
                   if _GERAL else
                   "Só o Gestor Geral cria novos Gestores.")
            ),
        )

        # Equipe: Gestor Geral escolhe; líder de equipe grava a própria.
        if _GERAL:
            n_equipe = st.selectbox(
                "Equipe", _EQUIPES, index=0,
                help="A qual equipe de gestão esta pessoa pertence. "
                     "GERAL = vê tudo (use só para outro Gestor Geral).",
            )
        else:
            n_equipe = _MINHA_EQUIPE
            st.caption(f"Equipe: **{n_equipe}** (sua equipe)")

        # Pergunta secreta (usada na recuperação de senha)
        n_email = st.text_input(
            "E-mail (opcional)", placeholder="usado para contato futuro",
        )
        cp1, cp2 = st.columns(2)
        n_perg = cp1.text_input(
            "Pergunta secreta",
            placeholder="ex.: Nome do primeiro pet?",
            help="Usada para recuperar a senha caso o usuário esqueça.",
        )
        n_resp = cp2.text_input(
            "Resposta secreta",
            type="password",
            placeholder="a resposta da pergunta acima",
        )

        if st.form_submit_button("Finalizar Cadastro",
                                 use_container_width=True):
            if n_nome and n_senha:
                conn = db.conectar()
                c = conn.cursor()
                c.execute("SELECT * FROM usuarios WHERE nome = %s", (n_nome,))
                if c.fetchone():
                    st.error("Este nome já está cadastrado.")
                else:
                    _resp_hash = (
                        db.gerar_hash(n_resp.strip().lower())
                        if n_resp.strip() else None
                    )
                    # Defesa no servidor: nunca aceitar perfil/equipe fora
                    # do permitido pro escopo, mesmo se o front for burlado.
                    _perf_ok = n_perf if n_perf in _perfis_novo else "Projetista"
                    _equipe_ok = (
                        n_equipe if (_GERAL and n_equipe in _EQUIPES)
                        else _MINHA_EQUIPE
                    )
                    c.execute(
                        "INSERT INTO usuarios (nome, senha, perfil, cargo, "
                        "email, pergunta_secreta, resposta_secreta, equipe) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                        (n_nome, db.gerar_hash(n_senha), _perf_ok, n_cargo,
                         n_email.strip() or None,
                         n_perg.strip() or None, _resp_hash, _equipe_ok),
                    )
                    conn.commit()
                    if not n_perg.strip() or not n_resp.strip():
                        st.warning(
                            f"Membro {n_nome} criado, mas SEM pergunta "
                            f"secreta — ele não poderá recuperar a senha "
                            f"sozinho."
                        )
                    else:
                        st.success(f"Membro {n_nome} adicionado com sucesso!")
                conn.close()
                _invalidar_dados()
                st.rerun()
            else:
                st.warning("Nome e Senha são obrigatórios.")

st.divider()

# 2. LISTAGEM DE USUÁRIOS
# Líder de equipe só vê a própria equipe; Gestor Geral vê todos.
if _GERAL:
    df_membros = pd.read_sql_query(
        "SELECT * FROM usuarios ORDER BY "
        "CASE perfil WHEN 'Gestor' THEN 0 WHEN 'Projetista' THEN 1 "
        "ELSE 2 END, nome",
        db.get_engine(),
    )
else:
    df_membros = pd.read_sql_query(
        "SELECT * FROM usuarios WHERE COALESCE(equipe,'SERVPEN') = %s "
        "ORDER BY CASE perfil WHEN 'Gestor' THEN 0 "
        "WHEN 'Projetista' THEN 1 ELSE 2 END, nome",
        db.get_engine(),
        params=(_MINHA_EQUIPE,),
    )

# Métricas de composição da equipe
mc1, mc2, mc3, mc4 = st.columns(4)
mc1.metric("👥 Total", len(df_membros))
mc2.metric("🛡️ Gestores", int((df_membros["perfil"] == "Gestor").sum()))
mc3.metric("✏️ Projetistas", int((df_membros["perfil"] == "Projetista").sum()))
mc4.metric("👁️ Visualizadores",
           int((df_membros["perfil"] == "Visualizador").sum()))

st.subheader("Membros da Equipe")
_busca_membro = st.text_input(
    "🔍 Buscar por nome ou cargo", key="busca_membro",
    placeholder="ex.: rodrigo, eletricista...",
    label_visibility="collapsed",
)
if _busca_membro.strip():
    _t = _busca_membro.lower()
    df_membros = df_membros[
        df_membros["nome"].astype(str).str.lower().str.contains(_t, na=False)
        | df_membros["cargo"].astype(str).str.lower().str.contains(_t, na=False)
    ]

_cores_perfil = {
    "Gestor": "#b01a2c",
    "Projetista": "#0056b3",
    "Visualizador": "#6b7280",
}

if df_membros.empty:
    _empty_state(
        "🔎",
        "Nenhum membro encontrado",
        "Sua busca não retornou ninguém. Tente outro termo, ou apague "
        "o filtro pra ver todos.",
        cor_borda="#d97706",
    )

_cores_equipe = {
    "SERVPEN": "#0e7490",   # ciano-escuro
    "SERVPAR": "#7c3aed",   # roxo
    "GERAL":   "#374151",   # cinza-grafite
}

for _, u in df_membros.iterrows():
    cor_p = _cores_perfil.get(u["perfil"], "#0056b3")
    cargo_txt = u.get("cargo") or "Colaborador"
    email_txt = u.get("email") or ""
    eh_eu = (u["nome"] == usuario)
    tem_perg = bool(u.get("pergunta_secreta"))
    equipe_u = u.get("equipe") or "SERVPEN"

    with st.container(border=True):
        cav, cinfo, cbadge = st.columns([0.13, 0.67, 0.20])
        # Avatar circular
        cav.markdown(
            _avatar_circular_html(u.get("avatar_path"), size=58),
            unsafe_allow_html=True,
        )
        # Identificação
        with cinfo:
            _voce = (
                " <span style='opacity:.55;font-size:.78rem'>(você)</span>"
                if eh_eu else ""
            )
            _star = "⭐ " if eh_eu else ""
            _perg_html = (
                "<span style='color:#10b981'>🔑 recuperação ativa</span>"
                if tem_perg else
                "<span style='color:#f59e0b'>⚠️ sem pergunta secreta</span>"
            )
            st.markdown(
                f"<div style='font-size:1.08rem;font-weight:700'>"
                f"{_star}{u['nome']}{_voce}</div>"
                f"<div style='opacity:.78;font-style:italic;font-size:.88rem'>"
                f"💼 {cargo_txt}</div>"
                + (
                    f"<div style='opacity:.62;font-size:.8rem'>"
                    f"✉️ {email_txt}</div>" if email_txt else ""
                )
                + f"<div style='font-size:.72rem;margin-top:2px'>{_perg_html}</div>",
                unsafe_allow_html=True,
            )
        # Badge do perfil + badge da equipe (equipe só interessa pro
        # Gestor Geral, que vê gente de equipes diferentes na mesma lista)
        _cor_eq = _cores_equipe.get(equipe_u, "#374151")
        _badge_equipe = (
            f"<div style='margin-top:4px'>"
            f"<span style='background:{_cor_eq};color:#fff;"
            f"padding:2px 10px;border-radius:14px;font-size:.62rem;"
            f"font-weight:700;letter-spacing:.5px'>{equipe_u}</span></div>"
            if _GERAL else ""
        )
        cbadge.markdown(
            f"<div style='text-align:right'>"
            f"<span style='background:{cor_p};color:#fff;"
            f"padding:3px 12px;border-radius:14px;font-size:.7rem;"
            f"font-weight:700;text-transform:uppercase;letter-spacing:.5px'>"
            f"{u['perfil']}</span>{_badge_equipe}</div>",
            unsafe_allow_html=True,
        )

        # Permissão de gerência sobre ESTE alvo: líder de equipe não mexe
        # em Gestores (nem nos colegas de equipe, nem em si — pra isso há
        # "Meu Perfil"). Só o Gestor Geral gerencia Gestores.
        _pode_gerenciar_alvo = _GERAL or (u["perfil"] != "Gestor")

        # Ações
        ca1, ca2, _ca3 = st.columns([0.28, 0.30, 0.42])
        if ca1.button("✏️ Editar", key=f"ed_u_{u['id']}",
                      use_container_width=True,
                      disabled=not _pode_gerenciar_alvo,
                      help=(None if _pode_gerenciar_alvo else
                            "Só o Gestor Geral edita Gestores.")):
            st.session_state[f"editor_u_{u['id']}"] = not st.session_state.get(
                f"editor_u_{u['id']}", False
            )

        with ca2.popover("🗑️ Remover", use_container_width=True):
            if u["nome"] == usuario:
                st.error("Não é possível excluir o próprio usuário logado.")
            elif not _pode_gerenciar_alvo:
                st.error("Só o Gestor Geral pode remover Gestores.")
            else:
                st.markdown(f"**Remover `{u['nome']}` permanentemente?**")
                st.caption(
                    "Esta ação não pode ser desfeita. O usuário perderá "
                    "acesso imediatamente."
                )
                if st.button(
                    "✅ Sim, remover", key=f"yes_del_u_{u['id']}",
                    type="primary", use_container_width=True,
                ):
                    conn = db.conectar()
                    c = conn.cursor()
                    c.execute("DELETE FROM usuarios WHERE id = %s", (u["id"],))
                    conn.commit()
                    conn.close()
                    db.log_aud(usuario, "excluir", "usuario", u["id"],
                               f"nome='{u['nome']}'")
                    st.toast(f"Membro '{u['nome']}' removido.")
                    _invalidar_dados()
                    st.rerun()

        # PAINEL DE EDIÇÃO INTEGRADO
        # Defesa extra: se o editor foi aberto e o alvo não é gerenciável
        # (líder tentando editar Gestor), fecha sem renderizar.
        if st.session_state.get(f"editor_u_{u['id']}") and \
                not _pode_gerenciar_alvo:
            st.session_state[f"editor_u_{u['id']}"] = False
        if st.session_state.get(f"editor_u_{u['id']}"):
            st.divider()
            ce1, ce2 = st.columns(2)
            up_nome = ce1.text_input("Nome", value=u["nome"], key=f"n_{u['id']}")
            up_cargo = ce2.text_input("Cargo", value=cargo_txt,
                                      key=f"c_{u['id']}")

            ce3, ce4 = st.columns(2)
            # IMPORTANTE: campo de senha sempre VAZIO no edit (não dá pra "ler"
            # a senha atual porque está hasheada). Vazio = mantém; preenchido
            # = re-hasheia. Sem isso, salvaríamos texto puro e o login deixava
            # de funcionar pra esse usuário.
            up_senha = ce3.text_input(
                "Nova senha",
                value="",
                type="password",
                placeholder="Deixe vazio para manter a atual",
                key=f"s_{u['id']}",
                help=(
                    "Só preencha se quiser TROCAR a senha. Senha em branco "
                    "mantém a que já existe."
                ),
            )
            # Perfil: só o Gestor Geral pode promover a Gestor. Líder de
            # equipe edita só Projetista/Visualizador.
            _perfis = (
                ["Projetista", "Gestor", "Visualizador"] if _GERAL
                else ["Projetista", "Visualizador"]
            )
            _idx_perf = _perfis.index(u["perfil"]) if u["perfil"] in _perfis else 0
            up_perf = ce4.selectbox(
                "Perfil", _perfis, index=_idx_perf, key=f"p_{u['id']}",
            )

            # Equipe: só o Gestor Geral troca. Líder de equipe vê fixa.
            if _GERAL:
                _idx_eq = (
                    _EQUIPES.index(equipe_u) if equipe_u in _EQUIPES else 0
                )
                up_equipe = st.selectbox(
                    "Equipe", _EQUIPES, index=_idx_eq, key=f"eq_{u['id']}",
                    help="Mover a pessoa entre equipes de gestão.",
                )
            else:
                up_equipe = equipe_u
                st.caption(f"Equipe: **{equipe_u}** (só o Gestor Geral altera)")

            # Pergunta secreta (recuperação de senha). Carrega a pergunta
            # atual; resposta sempre vazia (é hash).
            _tem_pergunta = bool(u.get("pergunta_secreta"))
            cps1, cps2 = st.columns(2)
            up_perg = cps1.text_input(
                "Pergunta secreta",
                value=u.get("pergunta_secreta") or "",
                key=f"perg_{u['id']}",
                help="Usada na recuperação de senha.",
            )
            up_resp = cps2.text_input(
                "Nova resposta secreta",
                value="",
                type="password",
                placeholder=(
                    "Deixe vazio p/ manter" if _tem_pergunta
                    else "defina a resposta"
                ),
                key=f"resp_{u['id']}",
            )

            if st.button("💾 Salvar Alterações", key=f"sv_u_{u['id']}",
                         use_container_width=True):
                with carregando(f"Salvando dados de {u['nome']}..."):
                    # Senha: vazio mantém, preenchido hasheia
                    if up_senha.strip():
                        _senha_para_salvar = db.gerar_hash(up_senha)
                        _msg = "Dados atualizados (senha trocada)."
                    else:
                        _senha_para_salvar = u["senha"]
                        _msg = "Dados atualizados (senha mantida)."
                    # Resposta secreta: vazio mantém o hash atual,
                    # preenchido re-hasheia
                    if up_resp.strip():
                        _resp_para_salvar = db.gerar_hash(
                            up_resp.strip().lower()
                        )
                    else:
                        _resp_para_salvar = u.get("resposta_secreta")
                    # ── Validação de permissão NO SERVIDOR ──────────────
                    # Nunca confiar só no widget escondido. Líder de equipe
                    # não pode promover a Gestor nem trocar a equipe: força
                    # os valores de volta ao seguro.
                    if _GERAL:
                        _perf_final = up_perf
                        _equipe_final = (
                            up_equipe if up_equipe in _EQUIPES else equipe_u
                        )
                    else:
                        _perf_final = (
                            up_perf if up_perf in ("Projetista", "Visualizador")
                            else u["perfil"]
                        )
                        _equipe_final = equipe_u  # líder não muda equipe
                    conn = db.conectar()
                    c = conn.cursor()
                    c.execute(
                        "UPDATE usuarios SET nome=%s, cargo=%s, senha=%s, "
                        "perfil=%s, pergunta_secreta=%s, "
                        "resposta_secreta=%s, equipe=%s WHERE id=%s",
                        (up_nome, up_cargo, _senha_para_salvar, _perf_final,
                         up_perg.strip() or None, _resp_para_salvar,
                         _equipe_final, u["id"]),
                    )
                    conn.commit()
                    conn.close()
                    db.log_aud(
                        usuario, "editar", "usuario", u["id"],
                        f"nome='{up_nome}' perfil='{_perf_final}' "
                        f"equipe='{_equipe_final}'",
                    )
                    st.session_state[f"editor_u_{u['id']}"] = False
                    _invalidar_dados()
                st.toast(_msg, icon="✅")
                st.rerun()

st.markdown("<br>", unsafe_allow_html=True)
