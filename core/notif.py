"""Notificações globais: toast custom de chat + fragmento que polla a cada 10s.

`_global_notif` é montado na sidebar do app.py — assim roda em TODAS as
páginas (a sidebar renderiza em qualquer view). Sem isso, com st.navigation
o toast de nova msg só apareceria quando você ESTIVESSE na aba Chat.
"""

from __future__ import annotations

import json as _json

import streamlit as st
import streamlit.components.v1 as _components

import database as db


# Slugs das páginas em `st.navigation` — deve refletir o `url_path` declarado
# em `app.py`. Usado pelo JS do toast pra detectar "estou em /diario ou /
# (dashboard default)?" e construir a URL alvo `<base>/chat?_goto_chat=NOME`
# corretamente, independente da página onde o user está.
#
# Dashboard NÃO entra aqui — é a página default, seu slug é "" (URL = base).
_PAGE_SLUGS = [
    "kanban", "novo_projeto", "diario", "arquivos",
    "equipe", "chat", "agenda", "auditoria", "acessos",
]
_CHAT_SLUG = "chat"


def _chat_toast_html(remetente: str, qtd: int, alvo: str | None = None):
    """Injeta um toast persistente (30s) no DOM pai via JS.

    O `st.toast` nativo dura ~4s e não aceita botões. Aqui injetamos um div
    fixo no DOM do top frame (fora do iframe do components.html) via
    `window.parent`, simulando um toast estilo WhatsApp/Telegram, com botões
    "✖ Fechar" e "📨 Ver mensagem".

    O link "Ver mensagem" usa `<a target="_top" href="...">` porque o iframe
    do components.html é sandboxed sem `allow-top-navigation` — JS via
    `window.parent.location` dispara SecurityError. Link com target=_top +
    clique do user passa pelo bloqueio (user-activated nav).

    A URL alvo é construída pra apontar pra `<base>/chat?_goto_chat=NOME`
    INDEPENDENTE da página onde o user está quando o toast aparece. Sem
    isso (versão antiga, pré-modularização), o clique adicionava
    `?_goto_chat=NOME` à URL atual — o que com `st.navigation` fazia o user
    cair em `/dashboard?_goto_chat=X` em vez de `/chat?_goto_chat=X`.
    """
    alvo = alvo or remetente
    _rem_js = _json.dumps(str(remetente))  # display (header do toast)
    _alvo_js = _json.dumps(str(alvo))      # alvo do clique (pessoa ou grupo)
    _qtd_js = int(qtd)
    _slugs_js = _json.dumps(_PAGE_SLUGS)
    _chat_slug_js = _json.dumps(_CHAT_SLUG)
    _components.html(
        f"""
        <script>
        (function () {{
            try {{
                var doc = window.parent.document;
                var REM = {_rem_js};
                var ALVO = {_alvo_js};
                var QTD = {_qtd_js};
                var KNOWN_SLUGS = {_slugs_js};
                var CHAT_SLUG = {_chat_slug_js};

                // CSS injetado uma vez só
                if (!doc.getElementById('wa-toast-styles')) {{
                    var styleTag = doc.createElement('style');
                    styleTag.id = 'wa-toast-styles';
                    styleTag.textContent = [
                        '#wa-toast-stack {{ position:fixed; right:16px; bottom:16px;',
                        '  display:flex; flex-direction:column; gap:8px;',
                        '  z-index:99999; max-width:360px; }}',
                        '.wa-toast {{ background:#1e3a5f; border:1px solid #3b82f6;',
                        '  border-radius:10px; padding:10px 14px; color:#e9edef;',
                        '  font-family:"Source Sans Pro",sans-serif; font-size:13.5px;',
                        '  box-shadow:0 4px 14px rgba(0,0,0,0.4);',
                        '  animation:wa-slide-in .25s ease-out; }}',
                        '.wa-toast-head {{ font-weight:600; margin-bottom:6px;',
                        '  display:flex; justify-content:space-between;',
                        '  align-items:center; gap:8px; }}',
                        '.wa-toast-actions {{ display:flex; gap:6px; margin-top:6px; }}',
                        // Aplica a `button` E `a` — o botão "Ver mensagem" é um
                        // <a target="_top">, mas precisa ter a mesma aparência
                        // dos botões (caso contrário herda azul padrão de link
                        // do browser, ficando azul-sobre-azul ilegível).
                        '.wa-toast-actions button, .wa-toast-actions a {{ flex:1; padding:5px 10px;',
                        '  border-radius:6px; border:1px solid rgba(255,255,255,.15);',
                        '  background:rgba(255,255,255,.07); color:#ffffff;',
                        '  font-size:12px; font-weight:600; cursor:pointer;',
                        '  text-decoration:none; transition:background .15s; }}',
                        '.wa-toast-actions button:hover, .wa-toast-actions a:hover {{ background:rgba(255,255,255,.15); color:#ffffff; }}',
                        '.wa-toast-actions button.primary, .wa-toast-actions a.primary {{ background:#2563eb;',
                        '  border-color:#2563eb; color:#ffffff; }}',
                        '.wa-toast-actions button.primary:hover, .wa-toast-actions a.primary:hover {{ background:#1d4ed8; color:#ffffff; }}',
                        '.wa-toast-close {{ background:transparent; border:0;',
                        '  color:#94a3b8; cursor:pointer; font-size:14px; padding:0 4px; }}',
                        '@keyframes wa-slide-in {{',
                        '  from {{ transform:translateX(110%); opacity:0; }}',
                        '  to   {{ transform:translateX(0); opacity:1; }} }}',
                    ].join('\\n');
                    doc.head.appendChild(styleTag);
                }}

                // Stack container (1 só, persistente)
                var stack = doc.getElementById('wa-toast-stack');
                if (!stack) {{
                    stack = doc.createElement('div');
                    stack.id = 'wa-toast-stack';
                    doc.body.appendChild(stack);
                }}

                // Função pra fechar.
                //
                // CRUCIAL: defina como FUNÇÃO GLOBAL NO TOP FRAME
                // (window.parent.waCloseToast), não como função local desta
                // IIFE. Razão: cada chamada de _chat_toast_html cria um
                // NOVO iframe (components.html); o iframe ANTERIOR é
                // destruído. Se o `onclick` do botão ✖ apontar pra função
                // do iframe antigo, depois que ele morrer o clique não
                // dispara nada (silenciosamente — "botão fechar não
                // funciona"). Definindo no top frame, sobrevive.
                //
                // Idempotente: só atribui uma vez. Funções pegam toast por
                // argumento + acessam DOM do parent (já estamos no parent).
                if (!doc.defaultView.waCloseToast) {{
                    var TOP = doc.defaultView;
                    doc.defaultView.waCloseToast = function (toast) {{
                        if (!toast || !toast.parentElement) return;
                        // setTimeout/clearTimeout explícitos no TOP FRAME
                        // (evita ambiguidade: dependendo de como o engine
                        // resolve identifier `setTimeout` dentro desta
                        // função, podia pegar o do iframe — que morre).
                        if (toast.__timer) {{ TOP.clearTimeout(toast.__timer); }}
                        toast.style.transition =
                            'transform .2s ease-in, opacity .2s ease-in';
                        toast.style.transform = 'translateX(120%)';
                        toast.style.opacity = '0';
                        TOP.setTimeout(function () {{
                            if (toast.parentElement) {{
                                toast.parentElement.removeChild(toast);
                            }}
                        }}, 230);
                    }};
                }}
                var closeToast = doc.defaultView.waCloseToast;

                // Se já tem toast desse remetente, atualiza qtd e renova timer
                var existing = stack.querySelector(
                    '[data-rem="' + ALVO.replace(/"/g, '&quot;') + '"]'
                );
                var toast = existing || doc.createElement('div');
                if (!existing) {{
                    toast.className = 'wa-toast';
                    toast.setAttribute('data-rem', ALVO);
                }}
                toast.innerHTML = ''
                    + '<div class="wa-toast-head">'
                    + '<span>🔔 💬 Nova(s) de <b></b> (<span class="qtd"></span>)</span>'
                    + '<button class="wa-toast-close" title="Fechar">✖</button>'
                    + '</div>'
                    + '<div class="wa-toast-actions">'
                    + '<a class="primary wa-btn-go" target="_top" '
                    + '   style="display:flex;align-items:center;'
                    + '          justify-content:center;text-decoration:none;">'
                    + '📨 Ver mensagem</a>'
                    + '</div>';
                // textContent pra evitar XSS no nome
                toast.querySelector('.wa-toast-head b').textContent = REM;
                toast.querySelector('.qtd').textContent = QTD;

                // URL final pro link "Ver mensagem".
                //
                // ALGORITMO:
                //   1. Pega o pathname atual (ex.: "/gestao-de-projetos/diario"
                //      ou "/gestao-de-projetos/" ou "/" em dev local).
                //   2. Tira a barra final.
                //   3. Olha o último segmento:
                //      - se for um slug de página conhecido (kanban, diario,
                //        agenda, etc.) → substitui por "chat"
                //      - se NÃO for (é a base do app, dashboard default
                //        renderiza em "/") → ANEXA "/chat" no fim
                //   4. Mantém todos os query params atuais (?t=token etc.)
                //      e adiciona ?_goto_chat=NOME.
                //
                // Resultado: clique no toast SEMPRE leva pra <base>/chat,
                // não importa em qual página o user esteja.
                try {{
                    var urlGo = new URL(window.parent.location.href);
                    var pathname = urlGo.pathname.replace(/\\/$/, '');
                    var parts = pathname.split('/');
                    var last = parts[parts.length - 1];
                    if (KNOWN_SLUGS.indexOf(last) !== -1) {{
                        parts[parts.length - 1] = CHAT_SLUG;
                    }} else {{
                        parts.push(CHAT_SLUG);
                    }}
                    urlGo.pathname = parts.join('/');
                    urlGo.searchParams.set('_goto_chat', ALVO);
                    toast.querySelector('.wa-btn-go')
                         .setAttribute('href', urlGo.toString());
                }} catch (e) {{
                    // Fallback minimalista. Perde token + base path, mas pelo
                    // menos tenta levar pra alguma URL de chat.
                    toast.querySelector('.wa-btn-go')
                         .setAttribute('href',
                             'chat?_goto_chat=' + encodeURIComponent(ALVO));
                }}

                // Botão ✖ fecha.
                //
                // Usa `.onclick = ...` em vez de `.addEventListener('click', ...)`
                // porque `onclick` SOBRESCREVE o handler anterior (uma só
                // função por elemento), enquanto `addEventListener` ACUMULA
                // — cada re-render do toast (a cada 10s ou após atualizar
                // qtd) penduraria mais um listener. Pior: como
                // re-escrevemos o innerHTML antes, o botão é um elemento
                // novo — mas o `addEventListener` apontaria pra função do
                // iframe ANTIGO (já destruído pelo Streamlit), virando
                // listener zumbi que não dispara. `onclick` sempre aponta
                // pra função do iframe ATUAL (na real, pra `closeToast` que
                // mora no top frame).
                toast.querySelector('.wa-toast-close').onclick = function () {{
                    closeToast(toast);
                }};
                // Click em "Ver mensagem" também fecha (não chama
                // preventDefault — deixa o <a> navegar normal).
                toast.querySelector('.wa-btn-go').onclick = function () {{
                    closeToast(toast);
                }};

                if (!existing) {{
                    stack.appendChild(toast);
                }} else if (toast.__timer) {{
                    clearTimeout(toast.__timer);
                }}

                // Auto-fecha em 30s.
                // Usa `doc.defaultView.setTimeout` (timer do top frame),
                // não `setTimeout` do iframe — pelo mesmo motivo do
                // `closeToast` global: garante que o timer sobreviva ao
                // iframe ser destruído pelo Streamlit no próximo tick.
                toast.__timer = doc.defaultView.setTimeout(function () {{
                    closeToast(toast);
                }}, 30000);
            }} catch (e) {{ console.warn('wa-toast:', e); }}
        }})();
        </script>
        """,
        height=0,
    )


@st.fragment(run_every="10s")
def _global_notif(usuario):
    """Polla notificações de chat e de menções no Diário a cada 10s.

    Montado na sidebar do app.py → roda em TODAS as views (a sidebar é
    renderizada em qualquer página do st.navigation). Sem isso, com
    st.navigation o toast de msg nova só apareceria quando você ESTIVESSE na
    aba Chat — porque os fragments só vivem na página onde foram registrados.
    """
    # 1) CHAT — toast custom 30s com botão "Ver mensagem"
    ultimas_chat = st.session_state.get("_chat_ultimas_contagens", {})
    atuais_chat = dict(db.listar_remetentes_com_nao_lidas(usuario))
    for rem, qtd in atuais_chat.items():
        anterior = ultimas_chat.get(rem, 0)
        if qtd > anterior:
            novas = qtd - anterior
            _chat_toast_html(rem, novas)
    st.session_state["_chat_ultimas_contagens"] = atuais_chat

    # 1b) CHAT GRUPOS (item 6) — mesmo toast custom; alvo = sentinela do grupo
    # pra o clique abrir o grupo certo. Display = label "👥 NOME".
    _equipe_notif = st.session_state.get("equipe", "SERVPEN")
    ultimas_grp = st.session_state.get("_chat_grp_ultimas", {})
    atuais_grp = db.nao_lidas_grupos(usuario, _equipe_notif)
    _grp_label = {s: l for s, l, _e in getattr(db, "GRUPOS_CHAT", [])}
    for grp, qtd in atuais_grp.items():
        anterior = ultimas_grp.get(grp, 0)
        if qtd > anterior:
            _chat_toast_html(_grp_label.get(grp, grp), qtd - anterior, alvo=grp)
    st.session_state["_chat_grp_ultimas"] = atuais_grp

    # NÃO setar `_chat_proximo_contato` aqui (intencional).
    #
    # Histórico do bug: o fragmento setava esse hint com base no "último
    # remetente do iterator de atuais_chat" — mas isso vinha de um
    # GROUP BY sem ORDER BY (ordem arbitrária no Postgres). Resultado:
    # clique no toast da Maria caía na conversa do Pedro.
    #
    # Único mecanismo de redirect: `_chat_force_target` (setado pelo boot
    # quando o user clica `?_goto_chat=NOME`). Sem clique, o selectbox da
    # view Chat já abre em quem tem mais não-lidas (sort por não-lidas DESC).

    # 2) MENÇÕES NO DIÁRIO — st.toast nativo basta (ação não é urgente)
    # Agrupa por remetente pra não spammar 1 toast por relato.
    ultimas_mn = st.session_state.get("_mencoes_ultimas_contagens", 0)
    atuais_mn = db.contar_mencoes_nao_vistas(usuario)
    if atuais_mn > ultimas_mn:
        pendentes = db.listar_mencoes_nao_vistas(usuario)
        novas = (
            pendentes[ultimas_mn:] if len(pendentes) >= ultimas_mn
            else pendentes
        )
        agrupado = {}
        for rem, _proj_id, _ctx in novas:
            agrupado[rem] = agrupado.get(rem, 0) + 1
        for rem, qtd in agrupado.items():
            st.toast(
                f"📝 **Você foi mencionado por {rem}** ({qtd}x no Diário)",
                icon="🔔",
            )
    st.session_state["_mencoes_ultimas_contagens"] = atuais_mn
