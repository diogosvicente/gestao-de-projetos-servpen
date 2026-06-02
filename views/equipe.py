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
from core.helpers import _empty_state, _pode_gestor
from core.ui_feedback import carregando


# Guard de perfil — Gestor-only
if not _pode_gestor():
    st.error(
        "⚠️ Acesso Restrito: Apenas Gestores podem gerenciar permissões "
        "da equipe."
    )
    st.stop()


usuario = st.session_state.usuario

st.header("👥 Gestão de Membros e Acessos")

# 1. CADASTRO DE NOVO MEMBRO
with st.expander("➕ Cadastrar Novo Colaborador"):
    with st.form("novo_usuario_form"):
        c1, c2 = st.columns(2)
        n_nome = c1.text_input("Nome Completo")
        n_cargo = c2.text_input("Cargo (ex: Eng. Civil, Estagiário HVAC)")

        c3, c4 = st.columns(2)
        n_senha = c3.text_input("Senha de Acesso", type="password")
        n_perf = c4.selectbox(
            "Perfil de Sistema",
            ["Projetista", "Gestor", "Visualizador"],
            help=(
                "Visualizador: acesso somente leitura (não pode criar, "
                "editar ou excluir nada)."
            ),
        )

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
                    c.execute(
                        "INSERT INTO usuarios (nome, senha, perfil, cargo, "
                        "email, pergunta_secreta, resposta_secreta) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (n_nome, db.gerar_hash(n_senha), n_perf, n_cargo,
                         n_email.strip() or None,
                         n_perg.strip() or None, _resp_hash),
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
df_membros = pd.read_sql_query(
    "SELECT * FROM usuarios ORDER BY "
    "CASE perfil WHEN 'Gestor' THEN 0 WHEN 'Projetista' THEN 1 ELSE 2 END, "
    "nome",
    db.get_engine(),
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

for _, u in df_membros.iterrows():
    cor_p = _cores_perfil.get(u["perfil"], "#0056b3")
    cargo_txt = u.get("cargo") or "Colaborador"
    email_txt = u.get("email") or ""
    eh_eu = (u["nome"] == usuario)
    tem_perg = bool(u.get("pergunta_secreta"))

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
        # Badge do perfil
        cbadge.markdown(
            f"<div style='text-align:right'>"
            f"<span style='background:{cor_p};color:#fff;"
            f"padding:3px 12px;border-radius:14px;font-size:.7rem;"
            f"font-weight:700;text-transform:uppercase;letter-spacing:.5px'>"
            f"{u['perfil']}</span></div>",
            unsafe_allow_html=True,
        )

        # Ações
        ca1, ca2, _ca3 = st.columns([0.28, 0.30, 0.42])
        if ca1.button("✏️ Editar", key=f"ed_u_{u['id']}",
                      use_container_width=True):
            st.session_state[f"editor_u_{u['id']}"] = not st.session_state.get(
                f"editor_u_{u['id']}", False
            )

        with ca2.popover("🗑️ Remover", use_container_width=True):
            if u["nome"] == usuario:
                st.error("Não é possível excluir o próprio usuário logado.")
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
            _perfis = ["Projetista", "Gestor", "Visualizador"]
            up_perf = ce4.selectbox(
                "Perfil", _perfis,
                index=_perfis.index(u["perfil"]) if u["perfil"] in _perfis else 0,
                key=f"p_{u['id']}",
            )

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
                    conn = db.conectar()
                    c = conn.cursor()
                    c.execute(
                        "UPDATE usuarios SET nome=%s, cargo=%s, senha=%s, "
                        "perfil=%s, pergunta_secreta=%s, "
                        "resposta_secreta=%s WHERE id=%s",
                        (up_nome, up_cargo, _senha_para_salvar, up_perf,
                         up_perg.strip() or None, _resp_para_salvar,
                         u["id"]),
                    )
                    conn.commit()
                    conn.close()
                    st.session_state[f"editor_u_{u['id']}"] = False
                    _invalidar_dados()
                st.toast(_msg, icon="✅")
                st.rerun()

st.markdown("<br>", unsafe_allow_html=True)
