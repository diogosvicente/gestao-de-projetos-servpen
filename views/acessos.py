"""Aba Acessos (somente Gestor) — revoga concessões de acesso por menção.

Quando alguém é mencionado (`@"Nome"`) num relato do Diário, ganha acesso
permanente ao projeto. Esta view lista todas as concessões ativas e permite
revogar individualmente.
"""

from __future__ import annotations

import streamlit as st

import database as db

from core.helpers import _pode_gestor, _tempo_relativo


# Guard de perfil — Gestor-only
if not _pode_gestor():
    st.error("🛑 Você não tem permissão para acessar Acessos.")
    st.stop()


st.header("🔑 Acessos por Menção")
st.caption(
    "Lista de usuários que ganharam acesso a projetos porque foram "
    "mencionados (`@\"Nome\"`) no Diário. Por decisão de produto, a "
    "concessão é permanente — só você (Gestor) pode revogar aqui."
)

_todas_mn = db.listar_todas_mencoes_acesso()
st.metric("Total de acessos por menção", len(_todas_mn))

if not _todas_mn:
    st.info(
        "Ninguém foi mencionado ainda. Quando alguém escrever "
        "`@\"Nome\"` no Diário, a concessão aparece aqui."
    )
else:
    # Filtros opcionais
    col_fa, col_fb = st.columns(2)
    _filtro_user = col_fa.text_input(
        "Filtrar por usuário mencionado", key="acessos_filtro_user",
        placeholder="ex.: maria",
    )
    _filtro_proj = col_fb.text_input(
        "Filtrar por nome do projeto", key="acessos_filtro_proj",
        placeholder="ex.: hupe",
    )
    st.divider()

    for (mn_id, usuario, proj_id, proj_nome, por, em) in _todas_mn:
        if _filtro_user and _filtro_user.lower() not in str(usuario).lower():
            continue
        if _filtro_proj and _filtro_proj.lower() not in str(proj_nome or "").lower():
            continue

        with st.container(border=True):
            col_a, col_b, col_c = st.columns([0.5, 0.35, 0.15])
            col_a.markdown(
                f"**👤 {usuario}** &nbsp;→&nbsp; "
                f"**📂 {proj_nome or f'(projeto #{proj_id} apagado)'}**"
            )
            col_b.caption(
                f"Concedido por **{por}** em {_tempo_relativo(em)}"
            )
            with col_c.popover("🗑️ Revogar", width="stretch"):
                st.warning(
                    f"Revogar acesso de **{usuario}** ao projeto "
                    f"**{proj_nome or proj_id}**?"
                )
                st.caption(
                    "O usuário perde acesso na próxima render dele. As "
                    "notificações já entregues continuam visíveis."
                )
                if st.button(
                    "✅ Sim, revogar", key=f"rev_mn_{mn_id}",
                    type="primary", width="stretch",
                ):
                    db.revogar_mencao(mn_id)
                    db.log_aud(
                        st.session_state.usuario, "mencao_revogada",
                        "projeto", proj_id,
                        f"revogou acesso de '{usuario}' "
                        f"(concedido por '{por}')",
                    )
                    st.toast(
                        f"Acesso de '{usuario}' ao projeto revogado."
                    )
                    st.rerun()
