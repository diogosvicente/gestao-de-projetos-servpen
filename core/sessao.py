"""Persistência de sessão via COOKIE (sobrevive hard-refresh e nova aba).

POR QUE COOKIE (e não só `?t=TOKEN` na URL):
  - A navegação interna do Streamlit (`st.page_link`/`st.navigation`)
    APAGA a query string. Ao clicar em "Kanban", o `?t=` some da URL;
    um refresh nessa página deslogava (era a causa do "Ctrl+Shift+R
    desloga").
  - A query string NÃO passa pra uma aba nova (Ctrl+T) — por isso nova
    aba caía na tela de login.
  - O cookie vai AUTOMÁTICO em todo request HTTP da mesma origem:
    sobrevive refresh, navegação interna e nova aba. É o mecanismo
    correto pra "lembrar que estou logado".

LEITURA é nativa: `st.context.cookies` (Streamlit 1.42+; aqui usamos
1.58). ESCRITA precisa de JS (o servidor Streamlit não controla o
header Set-Cookie do response), então usamos um component mínimo que
seta `window.parent.document.cookie`. Esse component é injetado só no
login/renovação (1× por sessão, via flag) e no logout — NUNCA a cada
rerun (isso é o que deixava o app lento antes).

O token é `secrets.token_urlsafe(18)` → só A-Za-z0-9_- → seguro em
cookie sem escaping.
"""
from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as _components

_COOKIE_NOME = "servpen_sessao"
_COOKIE_DIAS = 7
_FLAG_GRAVADO = "_cookie_sessao_gravado"


def ler_token() -> str | None:
    """Token da sessão atual.

    Prioridade:
      1. `?t=` na URL — mais fresco (logo após login, ou link do toast).
      2. cookie `servpen_sessao` — robusto (refresh / nova aba).
    Retorna None se nenhum dos dois existir.
    """
    tok = st.query_params.get("t")
    if tok:
        return tok
    try:
        # st.context.cookies lê os cookies do request HTTP que abriu esta
        # conexão WebSocket — disponível em qualquer rerun.
        return st.context.cookies.get(_COOKIE_NOME)
    except Exception:
        return None


def gravar_cookie(token: str) -> None:
    """Grava/renova o cookie de sessão (7 dias).

    Idempotente por sessão: a flag em session_state garante que o
    component JS é injetado UMA vez por token (não a cada rerun). Sem
    isso, encheria o DOM de iframes e deixaria o app instável.
    """
    if st.session_state.get(_FLAG_GRAVADO) == token:
        return
    _max_age = _COOKIE_DIAS * 86400
    _components.html(
        f"""
        <script>
        try {{
            window.parent.document.cookie =
                "{_COOKIE_NOME}={token}; path=/; max-age={_max_age}; "
                + "SameSite=Lax";
        }} catch (e) {{ console.warn('sessao cookie set:', e); }}
        </script>
        """,
        height=0,
    )
    st.session_state[_FLAG_GRAVADO] = token


def limpar_cookie() -> None:
    """Apaga o cookie de sessão no browser (logout).

    Usado no logout. APENAS zera o cookie — NÃO tenta recarregar a página.

    Histórico do bug: a versão anterior fazia
    `window.parent.location.replace()` aqui, mas o iframe do
    `components.html` é sandboxed SEM `allow-top-navigation` — então o
    redirect era bloqueado (SecurityError, engolido pelo catch). O cookie
    limpava, mas a página não recarregava; com o `st.stop()` que vinha
    depois, a tela ficava só com a sidebar e o usuário precisava clicar
    "Sair" duas vezes.

    Fix: o logout agora é feito 100% no servidor (deletar_sessao +
    limpar session_state + st.rerun em app.py). Esta função só apaga o
    cookie no browser, sem redirect. Como `deletar_sessao` invalida a
    sessão no banco, mesmo que o cookie demore a sumir, o token fica
    inválido — o rerun já cai na tela de login.
    """
    _components.html(
        f"""
        <script>
        try {{
            window.parent.document.cookie =
                "{_COOKIE_NOME}=; path=/; max-age=0; SameSite=Lax";
        }} catch (e) {{ console.warn('sessao limpar cookie:', e); }}
        </script>
        """,
        height=0,
    )
    st.session_state.pop(_FLAG_GRAVADO, None)
