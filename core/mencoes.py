"""Menções @"Nome" no Diário: popover de inserção, extração, render e processamento.

Fluxo: o autor digita `@"Carlos"` num relato. Ao salvar, `_processar_mencoes_diario`
extrai os nomes, concede acesso ao projeto (idempotente), registra notificação
e loga auditoria. O Carlos vê toast + chip clicável no Diário dele.
"""

from __future__ import annotations

import re as _re

import streamlit as st

import database as db


def _inserir_mencao_cb(text_key, selecionado_key):
    """Callback do botão 'Inserir menção'. Appenda `@"Nome"` ao text_area.

    CRÍTICO que isto rode num `on_click` (callback), NÃO no corpo do script:
    o Streamlit proíbe escrever em `st.session_state[<key-de-widget>]` DEPOIS
    que o widget foi instanciado no mesmo run (era o
    `StreamlitAPIException: st.session_state.diario_texto cannot be modified
    after the widget ... is instantiated`). Callbacks executam ANTES da
    re-instanciação dos widgets, então a escrita é permitida.
    """
    sel = st.session_state.get(selecionado_key, "—")
    if not sel or sel == "—":
        return
    atual = st.session_state.get(text_key, "") or ""
    # Separador: nada se o texto está vazio ou já termina em espaço/linha;
    # senão um espaço. (O código antigo usava endswith((" ","\\n","")) — o
    # "" no fim torna o teste SEMPRE True, então a menção grudava no texto.)
    sep = "" if (atual == "" or atual.endswith((" ", "\n"))) else " "
    st.session_state[text_key] = f'{atual}{sep}@"{sel}" '
    st.session_state[selecionado_key] = "—"   # reseta o selectbox


def _popover_mencionar(text_key, nomes_disponiveis, *, label="@ Mencionar",
                       pop_key=None, selecionado_key=None, eu_mesmo=None):
    """Popover compacto que appenda `@"Nome"` ao text_area associado.

    Como Streamlit não permite injetar texto na posição do cursor em
    `st.text_area`, este helper faz append ao final — trade-off aceitável
    pra evitar gambiarra de JS dentro do widget.

    Args:
        text_key: a `key=` do st.text_area onde a menção será inserida.
        nomes_disponiveis: lista de strings (nomes dos membros).
        label: texto do botão do popover.
        pop_key, selecionado_key: chaves únicas se houver múltiplos popovers
            na mesma página (ex.: form de novo + form de resposta).
        eu_mesmo: se passado, remove esse nome da lista (não faz sentido
            mencionar a si próprio).
    """
    if pop_key is None:
        pop_key = f"pop_men_{text_key}"
    if selecionado_key is None:
        selecionado_key = f"pop_men_sel_{text_key}"

    opcoes = [n for n in (nomes_disponiveis or []) if n and n != eu_mesmo]
    if not opcoes:
        return

    with st.popover(label, width="content"):
        st.caption("Selecione um membro pra inserir `@\"Nome\"` no fim do texto.")
        st.selectbox(
            "Membro",
            options=["—"] + sorted(opcoes, key=str.lower),
            key=selecionado_key,
            label_visibility="collapsed",
        )
        # on_click roda ANTES dos widgets serem reinstanciados → pode
        # escrever na key do text_area sem o StreamlitAPIException. O
        # callback já dispara o rerun sozinho (sem st.rerun explícito).
        st.button(
            "➕ Inserir menção", key=f"{pop_key}_btn",
            width="stretch",
            on_click=_inserir_mencao_cb,
            args=(text_key, selecionado_key),
        )


def _extrair_mencoes(texto, lista_usuarios):
    """Extrai nomes mencionados como @"Nome Completo" no texto.

    Match case-insensitive contra `lista_usuarios` (nomes reais). Retorna
    lista de nomes CANÔNICOS (como estão no banco), únicos, na ordem que
    aparecem. Nomes que não casam com nenhum usuário são ignorados.
    """
    if not texto:
        return []
    nomes_lower = {str(u).strip().lower(): str(u) for u in (lista_usuarios or [])}
    encontrados = []
    for m in _re.findall(r'@"([^"]+)"', str(texto)):
        canonico = nomes_lower.get(m.strip().lower())
        if canonico and canonico not in encontrados:
            encontrados.append(canonico)
    return encontrados


def _render_mencoes_html(texto, lista_usuarios, eu_mesmo=None):
    """Substitui ocorrências de @"Nome" por <a> estilizado (chip clicável).

    Match case-insensitive contra lista_usuarios; nomes inválidos viram texto
    literal. Se `eu_mesmo == nome_mencionado`, o chip ganha highlight extra
    (verde) — visual de "te mencionaram". Texto fora das menções não é tocado
    (assume que já foi escapado se necessário).
    """
    if not texto:
        return ""
    nomes_lower = {str(u).strip().lower(): str(u) for u in (lista_usuarios or [])}

    def _replace(match):
        nome_match = match.group(1).strip()
        canonico = nomes_lower.get(nome_match.lower())
        if not canonico:
            return match.group(0)
        eh_eu = (eu_mesmo is not None and canonico == eu_mesmo)
        bg = "#1e7e34" if eh_eu else "#0056b3"
        return (
            f'<a href="#mencao-{canonico.replace(" ", "_")}" '
            f'style="background:{bg};color:#fff;padding:2px 8px;'
            f'border-radius:10px;font-size:0.85em;font-weight:600;'
            f'text-decoration:none;margin:0 1px;display:inline-block;'
            f'cursor:pointer;" '
            f'title="Usuario mencionado: {canonico}">@{canonico}</a>'
        )

    return _re.sub(r'@"([^"]+)"', _replace, str(texto))


def _processar_mencoes_diario(texto, projeto_id, autor, relato_id,
                              contexto, lista_usuarios):
    """Pipeline completo de uma menção:

    1. Extrai os nomes mencionados no texto.
    2. Para cada um (exceto auto-menção): concede acesso (idempotente)
       + grava notificação.
    3. Loga em auditoria apenas quando a concessão é NOVA (evita ruído).

    `contexto`: 'relato' ou 'resposta_gestor' (vai pra tabela de notificações).
    """
    if not texto or not projeto_id:
        return
    for nome in _extrair_mencoes(texto, lista_usuarios):
        if nome == autor:
            continue
        criou = db.conceder_acesso_por_mencao(
            usuario=nome, projeto_id=projeto_id,
            concedido_por=autor, relato_id=relato_id,
        )
        # Decisão #5 do módulo: notificação sempre é registrada (mesmo se já
        # tinha acesso). Só a auditoria é só na primeira vez.
        db.registrar_notificacao_mencao(
            usuario=nome, projeto_id=projeto_id, relato_id=relato_id,
            mencionado_por=autor, contexto=contexto,
        )
        if criou:
            db.log_aud(
                autor, "mencao_concedida", "projeto", projeto_id,
                f"mencionou '{nome}' no projeto id={projeto_id} (via {contexto})",
            )
