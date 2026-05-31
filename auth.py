import streamlit as st
import database as db

def validar_login(usuario, senha):
    conn = db.conectar()
    c = conn.cursor()
    
    # Converte a senha digitada para Hash para bater com o banco
    senha_hash = db.gerar_hash(senha)
    
    c.execute("SELECT nome, perfil FROM usuarios WHERE nome = ? AND senha = ?", (usuario, senha_hash))
    user = c.fetchone()
    conn.close()

    if user:
        # Trava o login no navegador (impede deslogar ao atualizar)
        st.session_state.autenticado = True
        st.session_state.usuario = user[0]
        st.session_state.perfil = user[1]
        return True
    return False

def logout():
    st.session_state.autenticado = False
    st.session_state.usuario = None
    st.session_state.perfil = None
    st.rerun()