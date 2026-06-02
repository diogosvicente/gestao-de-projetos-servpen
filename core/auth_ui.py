"""UI de autenticação: tela de login (com recuperação) e modal Meu Perfil.

A validação em si está em `auth.py` (raiz do projeto) — este módulo é só
camada de apresentação. Helpers de avatar também ficam aqui porque são
usados pelo modal de perfil e pela sidebar logada.
"""

from __future__ import annotations

import base64
import os
import re as _re
from datetime import datetime

import streamlit as st

import auth
import database as db

from core.data import _invalidar_dados
from core.ui_feedback import carregando, erro_humano


# ─── AVATAR ──────────────────────────────────────────────────────────
def _avatar_b64(path):
    """Lê arquivo de imagem e devolve base64 pra embutir em <img src=data:...>."""
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")
    except Exception:
        return ""


def _avatar_circular_html(path, size=90):
    """<img> redondo a partir de arquivo local. Sem arquivo → círculo com 👤."""
    if path and os.path.exists(path):
        b64 = _avatar_b64(path)
        if b64:
            return (
                f"<div style='text-align:center'><img "
                f"src='data:image/jpeg;base64,{b64}' "
                f"style='width:{size}px;height:{size}px;border-radius:50%;"
                f"object-fit:cover;border:3px solid rgba(0,114,224,0.55);"
                f"box-shadow:0 4px 12px rgba(0,0,0,0.35);'></div>"
            )
    return (
        f"<div style='text-align:center'><div style='width:{size}px;"
        f"height:{size}px;border-radius:50%;"
        f"background:linear-gradient(135deg,#0056b3,#003d80);"
        f"display:inline-flex;align-items:center;justify-content:center;"
        f"font-size:{int(size*0.42)}px;box-shadow:0 4px 12px rgba(0,0,0,0.35);'>"
        f"👤</div></div>"
    )


def _processar_avatar(uploaded_file, nome):
    """Recorta no centro (quadrado), reduz pra 256x256, salva como JPEG leve.

    Retorna o caminho salvo. Mantém o arquivo pequeno → sidebar rápido.
    """
    from PIL import Image

    os.makedirs("anexos/avatars", exist_ok=True)
    img = Image.open(uploaded_file).convert("RGB")
    w, h = img.size
    lado = min(w, h)
    esq = (w - lado) // 2
    topo = (h - lado) // 2
    img = img.crop((esq, topo, esq + lado, topo + lado)).resize((256, 256))
    nome_seguro = _re.sub(r"[^A-Za-z0-9]", "_", nome)[:40]
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    caminho = f"anexos/avatars/{nome_seguro}_{ts}.jpg"
    img.save(caminho, "JPEG", quality=82, optimize=True)
    return caminho


# ─── DIALOG MEU PERFIL ───────────────────────────────────────────────
@st.dialog("👤 Meu Perfil")
def _dialog_meu_perfil():
    """Modal onde o PRÓPRIO usuário edita seus dados (menos nome de login).

    Tudo dentro de st.form: campos não disparam rerun a cada tecla (que antes
    podia zerar o cargo no momento do clique) — só o botão de envio processa.
    """
    nome = st.session_state.usuario
    me = db.obter_usuario(nome) or {}

    st.caption(f"Usuário (login): **{nome}** — não pode ser alterado.")

    # Avatar atual (visualização circular)
    st.markdown(_avatar_circular_html(me.get("avatar_path"), size=96),
                unsafe_allow_html=True)

    with st.form("form_meu_perfil", clear_on_submit=False):
        novo_avatar = st.file_uploader(
            "Trocar avatar (PNG/JPG)", type=["png", "jpg", "jpeg"],
            key="perfil_avatar",
        )
        st.text_input(
            "Cargo", value=me.get("cargo") or "", key="perfil_cargo",
            disabled=True,
            help="O cargo é definido pela gestão e não pode ser alterado por aqui.",
        )
        email = st.text_input("E-mail", value=me.get("email") or "",
                              key="perfil_email")

        st.markdown("**🔑 Recuperação de senha (pergunta secreta)**")
        perg = st.text_input("Pergunta secreta",
                             value=me.get("pergunta_secreta") or "",
                             key="perfil_perg",
                             placeholder="ex.: Nome do primeiro pet?")
        resp = st.text_input("Resposta secreta", type="password",
                             key="perfil_resp",
                             placeholder="vazio = manter a atual")

        st.markdown("**🔒 Trocar senha** (opcional)")
        senha_atual = st.text_input("Senha atual", type="password",
                                    key="perfil_sat")
        nova1 = st.text_input("Nova senha", type="password", key="perfil_n1")
        nova2 = st.text_input("Repetir nova senha", type="password",
                              key="perfil_n2")

        _enviado = st.form_submit_button("💾 Salvar alterações",
                                         type="primary",
                                         use_container_width=True)

    if not _enviado:
        return

    # 1) Avatar (processa: recorta quadrado + reduz)
    _avatar_path = None
    if novo_avatar is not None:
        try:
            with carregando("Processando avatar..."):
                _avatar_path = _processar_avatar(novo_avatar, nome)
        except Exception as exc:
            erro_humano(
                "Processar imagem do avatar", exc,
                sugestao=(
                    "Tente uma imagem PNG ou JPG menor que 5 MB. Imagens "
                    "muito grandes ou em formato exótico podem dar erro."
                ),
            )
            return

    # Envelopa toda a parte de gravação num spinner — bcrypt rehash
    # (resposta secreta e senha) pode levar 200-400ms, e em produção a
    # latência do Postgres soma. Sem isso, user clica "Salvar" e nada
    # aparece até o rerun ~1s depois — sensação de bug.
    with carregando("Salvando perfil..."):
        # 2) E-mail / avatar (cargo é read-only aqui — não atualizamos)
        db.atualizar_perfil(nome, email=email, avatar_path=_avatar_path)

        # 3) Pergunta secreta — só grava a resposta se digitou uma nova
        if perg.strip() and resp.strip():
            db.definir_pergunta_secreta(nome, perg.strip(), resp.strip())
        elif perg.strip() and me.get("pergunta_secreta") != perg.strip():
            st.warning(
                "Você mudou a pergunta — preencha também a resposta "
                "secreta. (Cargo e e-mail foram salvos.)"
            )
            _invalidar_dados()
            return

        # 4) Troca de senha (exige senha atual correta)
        if nova1 or nova2 or senha_atual:
            if not db.verificar_senha(nome, senha_atual):
                st.error("Senha atual incorreta — senha NÃO foi alterada. "
                         "(Resto salvo.)")
                _invalidar_dados()
                return
            if not nova1 or nova1 != nova2:
                st.error("A nova senha e a repetição precisam ser iguais "
                         "(e não vazias).")
                _invalidar_dados()
                return
            db.redefinir_senha(nome, nova1)
            db.log_aud(nome, "troca_senha", "usuario", None,
                       "pelo próprio perfil")

        db.log_aud(nome, "editar_perfil", "usuario", None,
                   "cargo/email/avatar/pergunta")
        _invalidar_dados()
    # Toast em vez de success: o st.rerun() abaixo fecha o dialog e zera o
    # script — st.success piscaria por <200ms. O toast vive no overlay.
    st.toast("✅ Perfil atualizado!", icon="👤")
    st.rerun()


# ─── TELA DE LOGIN ───────────────────────────────────────────────────
# CSS dedicado da tela de login. Aplicado SÓ aqui (não vaza pro app
# logado) porque o app.py só chama `tela_login()` no ramo "não autenticado".
_CSS_LOGIN = """
<style>
/* Esconde elementos padrao do Streamlit so na tela de login */
[data-testid="stToolbar"], [data-testid="stHeader"] { display: none; }
section[data-testid="stSidebar"] { display: none; }

/* Centraliza o bloco e limita a largura. */
[data-testid="stMainBlockContainer"],
[data-testid="stAppViewBlockContainer"],
section[data-testid="stMain"] .block-container,
.main .block-container,
.main > div > div > div {
    max-width: 420px !important;
    width: 420px !important;
    margin-left: auto !important;
    margin-right: auto !important;
    padding-top: 3.5rem !important;
    padding-bottom: 3.5rem !important;
    padding-left: 1rem !important;
    padding-right: 1rem !important;
}

[data-testid="stForm"],
[data-testid="stForm"] > div,
.stTextInput,
.stTextInput > div,
.stTextInput > div > div {
    width: 100% !important;
    max-width: 100% !important;
    box-sizing: border-box !important;
}

@media (max-width: 420px) {
    [data-testid="stMainBlockContainer"],
    [data-testid="stAppViewBlockContainer"],
    section[data-testid="stMain"] .block-container,
    .main .block-container {
        max-width: calc(100% - 2rem) !important;
        width: auto !important;
    }
}

.login-header { text-align: center; margin-bottom: 24px; }
.login-header img {
    height: 78px;
    margin-bottom: 12px;
    filter: drop-shadow(0 6px 14px rgba(0, 0, 0, 0.55));
}
.login-header .brand {
    color: #ffffff;
    font-size: 1.6rem;
    font-weight: 700;
    letter-spacing: 3px;
    margin: 4px 0 2px;
}
.login-header .tagline {
    color: #8a8a8a;
    font-size: 0.78rem;
    letter-spacing: 0.4px;
}

.stTextInput > div > div > input {
    background-color: rgba(255, 255, 255, 0.04) !important;
    border: 1px solid rgba(255, 255, 255, 0.10) !important;
    border-radius: 8px !important;
    padding: 10px 12px !important;
    font-size: 0.92rem !important;
    color: #ffffff !important;
    transition: border-color 0.15s, box-shadow 0.15s;
}
.stTextInput > div > div > input:focus {
    border-color: #0072e0 !important;
    box-shadow: 0 0 0 3px rgba(0, 114, 224, 0.22) !important;
}
.stTextInput label {
    color: #bbbbbb !important;
    font-size: 0.82rem !important;
    font-weight: 500 !important;
    letter-spacing: 0.3px !important;
}

.stButton > button,
[data-testid="stFormSubmitButton"] > button {
    width: 100%;
    background: linear-gradient(135deg, #0056b3 0%, #003d80 100%);
    color: #ffffff;
    border: none;
    padding: 10px 0;
    border-radius: 8px;
    font-weight: 600;
    letter-spacing: 1.5px;
    font-size: 0.9rem;
    margin-top: 14px;
    transition: transform 0.12s, box-shadow 0.2s, background 0.2s;
}
.stButton > button:hover,
[data-testid="stFormSubmitButton"] > button:hover {
    background: linear-gradient(135deg, #006fd6 0%, #004a99 100%);
    box-shadow: 0 10px 24px rgba(0, 86, 179, 0.45);
    transform: translateY(-1px);
}
.stButton > button:active,
[data-testid="stFormSubmitButton"] > button:active { transform: translateY(0); }

[data-testid="stForm"] {
    border: none !important;
    padding: 0 !important;
    background: transparent !important;
}

/* Esconde o falso-positivo "Missing Submit Button" do Streamlit que pisca
 * brevemente em F5. O form de login TEM `st.form_submit_button("ACESSAR")`;
 * o warning é uma race condition do componente Form do Streamlit (AV no
 * bundle React): quando os elementos são streamados pro browser, há uma
 * janela onde o scriptRunState já virou NOT_RUNNING mas o submit_button
 * ainda não foi adicionado ao mapa `formsData.submitButtons`. Como nesta
 * tela só existe 1 form e ele é controlado, é seguro suprimir QUALQUER
 * alerta dentro do form — st.error de login falho é renderizado FORA
 * do `with st.form(...)`. Se um dia adicionar st.error/warning DENTRO
 * do form, isto esconderia também — basta restringir o seletor. */
[data-testid="stForm"] [data-testid="stAlert"] {
    display: none !important;
}

.login-footer {
    text-align: center;
    color: #4a4a4a;
    font-size: 0.7rem;
    margin-top: 34px;
    letter-spacing: 1.8px;
    font-weight: 500;
}
</style>
<div class="login-header">
    <img src="https://www.uerj.br/wp-content/uploads/2018/02/logomarca-uerj.png" alt="UERJ">
    <div class="brand">SERVPEN</div>
    <div class="tagline">Gestão de Projetos de Engenharia</div>
</div>
"""


def tela_login():
    """Renderiza a tela de login. Chamada pelo app.py quando não há sessão.

    Não retorna nada — usa `st.session_state.autenticado = True` + `st.rerun()`
    pra promover ao app logado. Inclui o expander "Esqueci minha senha"
    (recuperação via pergunta secreta).
    """
    st.markdown(_CSS_LOGIN, unsafe_allow_html=True)

    # Form: Enter em qualquer input submete o formulário
    with st.form("login_form", clear_on_submit=False, border=False):
        u = st.text_input("Usuário", placeholder="Nome completo, como cadastrado")
        s = st.text_input("Senha", type="password", placeholder="••••••••")
        submit = st.form_submit_button("ACESSAR", use_container_width=True)

    if submit:
        # Envolve em spinner — bcrypt verify é o gargalo (200-400ms em
        # CPU normal) e o user só vê a tela travada até o rerun
        # confirmar. Antes, "Entrar" parecia não fazer nada por 1s.
        with carregando("Validando credenciais..."):
            _login_ok = bool(u and s and auth.validar_login(u, s))
            if _login_ok:
                _token = db.criar_sessao(u, dias=7)
                st.query_params["t"] = _token
                db.log_aud(u, "login", "sessao", None, "sucesso")
        if _login_ok:
            st.toast("✅ Login realizado!", icon="🔓")
            st.rerun()
        else:
            # Distingue rate-limit de senha inválida (auth.py popula
            # `_login_bloqueado_ate` quando bloqueia).
            _bloq_ate = st.session_state.pop("_login_bloqueado_ate", None)
            if _bloq_ate:
                _mins = max(
                    1, int((_bloq_ate - datetime.now()).total_seconds() / 60)
                )
                db.log_aud(
                    u or "(vazio)", "login_bloqueado", "sessao", None,
                    f'rate limit ate {_bloq_ate.isoformat(timespec="seconds")}',
                )
                st.error(
                    f"🛑 Muitas tentativas falhas para **{u}**. "
                    f"Tente novamente em ~{_mins} min."
                )
            else:
                db.log_aud(u or "(vazio)", "login_falha", "sessao", None,
                           "usuario ou senha invalidos")
                st.error("Usuário ou senha incorretos.")

    # ── ESQUECI MINHA SENHA (pergunta secreta) ──────────────────────
    with st.expander("🔑 Esqueci minha senha"):
        rec_user = st.text_input("Seu usuário", key="rec_user",
                                 placeholder="Nome completo, como cadastrado")
        if rec_user:
            _pergunta = db.obter_pergunta_secreta(rec_user)
            if not _pergunta:
                st.info(
                    "Esse usuário não tem pergunta secreta cadastrada. "
                    "Peça a um Gestor para definir uma na aba Equipe "
                    "(ou redefinir sua senha)."
                )
            else:
                st.markdown(f"**Pergunta:** {_pergunta}")
                rec_resp = st.text_input("Sua resposta", key="rec_resp",
                                         type="password")
                rec_nova = st.text_input("Nova senha", key="rec_nova",
                                         type="password")
                rec_nova2 = st.text_input("Repita a nova senha",
                                          key="rec_nova2", type="password")
                if st.button("Redefinir senha", key="rec_btn",
                             use_container_width=True):
                    if not rec_resp.strip():
                        st.warning("Responda a pergunta secreta.")
                    elif not rec_nova or rec_nova != rec_nova2:
                        st.warning("As duas senhas novas precisam ser iguais "
                                   "(e não vazias).")
                    elif not db.validar_resposta_secreta(rec_user, rec_resp):
                        db.log_aud(rec_user, "reset_senha_falha", "usuario",
                                   None, "resposta secreta errada")
                        st.error("Resposta secreta incorreta.")
                    else:
                        db.redefinir_senha(rec_user, rec_nova)
                        db.log_aud(rec_user, "reset_senha", "usuario", None,
                                   "via pergunta secreta")
                        st.success(
                            "Senha redefinida! Pode fechar e entrar com a "
                            "nova senha."
                        )

    st.markdown(
        '<div class="login-footer">SERVPEN ENGENHARIA &nbsp;·&nbsp; UERJ</div>',
        unsafe_allow_html=True,
    )
