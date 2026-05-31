import logging

import streamlit as st
import database as db


log = logging.getLogger(__name__)


def validar_login(usuario, senha):
    """Valida o par (usuario, senha) e popula a session_state se OK.

    Mudou em maio/2026:
      - como bcrypt usa salt aleatório, NÃO dá pra comparar hash via SQL
        (`WHERE senha = ?`) — agora busca o hash do usuário e verifica com
        `db.verificar_hash`. Aceita SHA-256 legado e re-grava como bcrypt
        no primeiro login bem-sucedido (migração transparente).
      - **Rate limiting**: após `db.LIMITE_FALHAS_LOGIN` falhas em
        `db.JANELA_MIN_LOGIN` minutos, o usuário é bloqueado até a janela
        expirar. Quando bloqueado, populamos `st.session_state._login_bloqueado_ate`
        com o `datetime` em que libera, pra UI mostrar mensagem específica.
    """
    if not usuario or senha is None:
        return False

    # ── Rate limit (pré-check antes de tocar no hash) ──────────────────
    # Por segurança: contamos por nome de usuário (não IP). Isso evita
    # downside de atacante usar muitos IPs (botnet) burlando o limite.
    # Trade-off: um vândalo pode bloquear um usuário legítimo intencionalmente.
    # Pra base interna de 6 pessoas, é tradeoff aceitável.
    falhas = db.contar_falhas_login_recentes(usuario)
    if falhas >= db.LIMITE_FALHAS_LOGIN:
        prox = db.proxima_tentativa_login_em(usuario)
        log.warning("login bloqueado por rate limit: usuario=%r falhas=%d libera_em=%s",
                    usuario, falhas, prox)
        # Comunica pra UI mostrar mensagem específica (em vez de "senha inválida")
        st.session_state._login_bloqueado_ate = prox
        return False

    # ── Busca o usuário ─────────────────────────────────────────────────
    conn = db.conectar()
    c = conn.cursor()
    try:
        c.execute(
            "SELECT nome, perfil, senha FROM usuarios WHERE nome = %s",
            (usuario,),
        )
        row = c.fetchone()
    finally:
        conn.close()

    # ── Verifica hash ───────────────────────────────────────────────────
    if not row:
        # Usuário inexistente conta como falha (defesa contra enumeração).
        db.registrar_falha_login(usuario)
        return False
    nome_db, perfil_db, hash_db = row

    valido, precisa_rehash = db.verificar_hash(senha, hash_db)
    if not valido:
        db.registrar_falha_login(usuario)
        return False

    # ── Sucesso: limpa falhas + migra hash se preciso ───────────────────
    db.limpar_falhas_login(nome_db)
    if precisa_rehash:
        try:
            db.atualizar_hash_senha(nome_db, senha)
        except Exception as e:
            log.warning("rehash bcrypt falhou pra %s: %s", nome_db, e)

    # Trava o login no navegador (impede deslogar ao atualizar)
    st.session_state.autenticado = True
    st.session_state.usuario = nome_db
    st.session_state.perfil = perfil_db
    return True


def logout():
    st.session_state.autenticado = False
    st.session_state.usuario = None
    st.session_state.perfil = None
    st.rerun()