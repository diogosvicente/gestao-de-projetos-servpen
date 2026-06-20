"""UI feedback: spinners pra operações lentas + mensagens de erro humanas.

Por que existe:
 - `st.spinner` é ótimo mas a UI fica inconsistente — cada lugar escreve
   "Carregando...", "Processando...", "Aguarde...". `carregando(msg)` é
   um wrapper semântico que padroniza.
 - `st.error(f"Erro: {e}")` vazava stack trace pro usuário (ex.: "Erro Excel:
   relation 'projetos' does not exist"). Pior UX possível: assustador,
   inacionável, e dá pista pra atacante. `erro_humano(operacao, exc)` mostra
   mensagem amigável + loga stack trace nos logs do servidor + oferece
   expander "🔧 Detalhes técnicos" só pra Gestor (debug em produção).

Padrão de uso:

    from core.ui_feedback import carregando, erro_humano

    try:
        with carregando("Gerando PDF do projeto..."):
            pdf_bytes = relatorios.gerar_pdf_diario(proj, df_diario)
        st.download_button("⬇️ Baixar", pdf_bytes, ...)
    except Exception as exc:
        erro_humano("Geração do PDF do diário", exc,
                    sugestao="Tente novamente em alguns segundos.")
"""

from __future__ import annotations

import html as _html
import logging
from contextlib import contextmanager
from typing import Iterator

import streamlit as st

log = logging.getLogger(__name__)


# ─── SPINNER ─────────────────────────────────────────────────────────
@contextmanager
def carregando(mensagem: str = "Processando...") -> Iterator[None]:
    """Wrapper semântico de `st.spinner`. Use em operações > 0.5s.

    Args:
        mensagem: frase no gerúndio descrevendo a ação. Ex.:
            "Gerando PDF...", "Enviando arquivos...", "Aplicando ação em lote...".
    """
    with st.spinner(mensagem):
        yield


# ─── ERRO HUMANO ─────────────────────────────────────────────────────
def erro_humano(
    operacao: str,
    exc: Exception,
    *,
    sugestao: str | None = None,
) -> None:
    """Mostra erro com mensagem amigável + loga stack trace no servidor.

    Substitui `st.error(f"Erro: {e}")` que vazava o stack trace pro usuário.
    O Gestor vê um expander "🔧 Detalhes técnicos" pra debugar em produção;
    outros perfis só veem a mensagem amigável.

    Args:
        operacao: o que estava acontecendo. Ex.: "Geração do PDF",
            "Salvar projeto", "Upload do arquivo X".
        exc: a exception capturada.
        sugestao: frase de ação opcional. Ex.: "Tente novamente em alguns
            segundos.", "Avise o administrador se persistir."

    Esta função não relança a exceção — quem chamar pode continuar
    normalmente (ex.: voltar pro form em vez de tela em branco).
    """
    # Log COMPLETO no servidor (vai pro /var/log/gestao-de-projetos.log)
    log.exception("Falha em '%s'", operacao)

    msg_traduzida = _traduzir(exc)
    linhas = [f"❌ **{operacao}** falhou: {msg_traduzida}."]
    if sugestao:
        linhas.append(f"💡 {sugestao}")
    st.error("\n\n".join(linhas))

    # Detalhes técnicos só pra Gestor (debug em produção sem ssh).
    # Import deferido pra evitar ciclo (helpers.py não importa daqui).
    from core.helpers import _pode_gestor

    if _pode_gestor():
        with st.expander("🔧 Detalhes técnicos (somente Gestor)"):
            st.code(f"{type(exc).__name__}: {exc}", language="text")
            st.caption(
                "O stack trace completo foi gravado no log do servidor "
                "(`/var/log/gestao-de-projetos.log`). Pra ver, no servidor: "
                "`sudo journalctl -u gestao-de-projetos -n 100 --no-pager`"
            )


# ─── TRADUÇÃO DE EXCEÇÕES COMUNS ─────────────────────────────────────
def _traduzir(exc: Exception) -> str:
    """Traduz exceção técnica em frase amigável.

    Catálogo deliberadamente curto: cobre os erros que VIMOS NA PRÁTICA
    neste app. Pra qualquer outra coisa, devolve mensagem genérica — o
    detalhe específico fica disponível no expander pro Gestor.
    """
    s = str(exc).lower()
    nome = type(exc).__name__

    # Banco de dados
    if "could not connect" in s or "connection refused" in s:
        return "não consegui conectar ao banco de dados"
    if "deadlock" in s or "could not serialize" in s:
        return (
            "houve um conflito de escrita simultânea — alguém da equipe "
            "estava mexendo no mesmo registro"
        )
    if "duplicate key" in s or "unique constraint" in s:
        return "esse registro já existe (algum campo único colide)"
    if "foreign key" in s:
        return (
            "esse registro está sendo usado por outro lugar do sistema "
            "e por isso não pôde ser apagado"
        )

    # Sistema de arquivos
    if "permission denied" in s:
        return "sem permissão pra acessar esse arquivo no servidor"
    if "no space left" in s or "disk full" in s:
        return "sem espaço em disco no servidor — avise o administrador"
    if "no such file" in s or nome == "FileNotFoundError":
        return "arquivo não encontrado no servidor"

    # Hardware (Athlon II X2 do 228.20 — sem AVX2)
    if "illegal instruction" in s:
        return (
            "esta operação não roda neste servidor (CPU sem AVX2). "
            "Tente do servidor moderno"
        )
    if "pyarrow" in s:
        return (
            "recurso indisponível neste servidor (depende de pyarrow, "
            "que não roda em CPU sem AVX2)"
        )

    # Rede / timeout
    if "timeout" in s or "timed out" in s:
        return "a operação demorou demais e foi cancelada"

    # PIL/imagem
    if "cannot identify image" in s or "cannot open image" in s:
        return "esse arquivo não parece ser uma imagem válida"

    # PDF / relatórios
    if "weasyprint" in s or "pango" in s or "cairo" in s:
        return "falha na geração do PDF (renderizador de PDF indisponível)"

    # Genérico
    return "ocorreu um erro inesperado"


# ─── CONFIRMAÇÃO DE SUCESSO (modal "enterprise") ─────────────────────
# Feedback de save/submit/update num modal verde centralizado (st.dialog).
#
# Fluxo:
#   1. No handler de save: confirmar_sucesso("Projeto salvo", "..."), st.rerun()
#   2. `_render_confirmacao_sucesso()` (no app.py, após pg.run()) detecta o
#      flag na sessão e abre o modal.
def confirmar_sucesso(titulo: str, detalhe: str = "") -> None:
    """Agenda um modal de sucesso pra próxima renderização.

    Use logo antes do `st.rerun()` após salvar/atualizar/enviar. Abre um modal
    centralizado com check verde, a mensagem e um botão "Continuar".
    """
    st.session_state["_confirmacao_sucesso"] = {
        "titulo": str(titulo or ""),
        "detalhe": str(detalhe or ""),
    }


def _render_confirmacao_sucesso() -> None:
    """Abre (1x) o MODAL de sucesso agendado por confirmar_sucesso(). Chamar
    em todo run num ponto global (app.py, após pg.run()). No-op se nada
    agendado. (Substitui o toast — preferência do usuário por modal.)"""
    if "_confirmacao_sucesso" not in st.session_state:
        return
    dados = st.session_state.pop("_confirmacao_sucesso")
    _titulo = dados.get("titulo") or "Tudo certo"
    _detalhe = dados.get("detalhe") or ""

    @st.dialog(_titulo)
    def _dlg():
        # `.ok-modal-mark` é só um marcador invisível: o CSS abaixo usa
        # `:has(.ok-modal-mark)` pra aplicar o estilo SÓ neste modal de
        # sucesso (não afeta o modal de excluir, que deve seguir vermelho).
        _corpo = (
            "<div class='ok-modal-mark'></div>"
            "<div style='text-align:center;padding:6px 4px 2px;'>"
            "<div style='width:68px;height:68px;border-radius:50%;"
            "background:rgba(34,197,94,.14);"
            "border:1px solid rgba(34,197,94,.45);color:#22c55e;display:flex;"
            "align-items:center;justify-content:center;margin:2px auto 16px;"
            "font-size:34px;font-weight:700;"
            "box-shadow:0 0 0 8px rgba(34,197,94,.06);"
            "animation:okpop .45s cubic-bezier(.2,.8,.2,1) both;'>✓</div>"
        )
        if _detalhe:
            _corpo += (
                "<p style='margin:0;color:#9aa6b2;font-size:14px;"
                f"line-height:1.5;'>{_html.escape(_detalhe)}</p>"
            )
        _corpo += (
            "</div>"
            "<style>"
            "@keyframes okpop{from{transform:scale(0);}"
            "70%{transform:scale(1.18);}to{transform:scale(1);}}"
            # Eleva o modal do fundo (sombra + borda verde sutil) — só este.
            "[role='dialog']:has(.ok-modal-mark){"
            "border:1px solid rgba(34,197,94,.30)!important;"
            "box-shadow:0 20px 60px rgba(0,0,0,.6)!important;}"
            # Botão "Continuar" VERDE (em vez do vermelho do tema primary).
            "[role='dialog']:has(.ok-modal-mark) .stButton button{"
            "background:#16a34a!important;border:1px solid #16a34a!important;"
            "color:#ffffff!important;font-weight:600!important;}"
            "[role='dialog']:has(.ok-modal-mark) .stButton button:hover{"
            "background:#15803d!important;border-color:#15803d!important;}"
            "</style>"
        )
        st.markdown(_corpo, unsafe_allow_html=True)
        if st.button("Continuar", width="stretch",
                     key="_btn_confirmar_sucesso"):
            st.rerun()

    _dlg()
