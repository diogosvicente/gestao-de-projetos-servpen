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
