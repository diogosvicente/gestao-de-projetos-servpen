"""Funções cacheadas de leitura do banco (df_p, df_u, df_d).

Cada view chama `_load_df_*` no topo. Como são `@st.cache_data(ttl=8)`,
chamadas repetidas no mesmo rerun (ou em reruns consecutivos < 8s) não
voltam ao banco — o DataFrame fica em RAM. Após QUALQUER escrita, chame
`_invalidar_dados()` antes do `st.rerun()` pra o autor ver a mudança
imediatamente; o TTL é só rede de segurança.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import database as db


@st.cache_data(ttl=8, show_spinner=False)
def _load_df_u():
    # Inclui `equipe` e `perfil` pro controle por equipe (SERVPEN/SERVPAR/
    # GERAL). COALESCE garante 'SERVPEN' em linha antiga sem o default.
    # Callers que só usam `nome` continuam funcionando (colunas extras não
    # quebram nada).
    return pd.read_sql_query(
        "SELECT nome, perfil, cargo, email, avatar_path, "
        "COALESCE(equipe,'SERVPEN') AS equipe "
        "FROM usuarios",
        db.get_engine(),
    )


@st.cache_data(ttl=8, show_spinner=False)
def _load_df_d():
    return pd.read_sql_query("SELECT * FROM diario", db.get_engine())


@st.cache_data(ttl=8, show_spinner=False)
def _load_df_p(usuario, perfil):
    """Projetos visíveis pro usuário.

    Cacheado por (usuario, perfil) pra não vazar visibilidade entre usuários.

    Gestor vê tudo; Projetista/Visualizador vê os projetos onde seu nome
    consta em `projetista` (LIKE) + projetos que ganhou por menção
    (via `mencoes_acesso`).
    """
    if perfil in ("Projetista", "Visualizador"):
        projs = db.listar_projetos_por_mencao(usuario)
        params = [f"%{usuario}%"]
        sql = "SELECT * FROM projetos WHERE projetista LIKE %s"
        if projs:
            sql += " OR id IN (" + ",".join(["%s"] * len(projs)) + ")"
            params.extend(int(x) for x in projs)
        return pd.read_sql_query(sql, db.get_engine(), params=tuple(params))
    return pd.read_sql_query("SELECT * FROM projetos", db.get_engine())


def _invalidar_dados():
    """Chamar após escrever no banco (projeto/diário/usuário/arquivo/agenda)
    pra que a próxima leitura traga dados frescos em vez do cache."""
    try:
        st.cache_data.clear()
    except Exception:
        pass
