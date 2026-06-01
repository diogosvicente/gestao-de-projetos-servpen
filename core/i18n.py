"""Tradução pt-BR das mensagens nativas do Streamlit (versão CSS-only).

Histórico das tentativas anteriores:

 1ª versão — MutationObserver (childList + subtree + characterData) sobre
              document.body. Em DOM grande, cada modificação de texto
              disparava nova mutação → cascata → main thread travava.
              Resultado: tela branca após o login.

 2ª versão — setInterval(500ms) + querySelectorAll + `el.textContent = pt`.
              Modificar textContent de um nó controlado pelo React faz o
              React perder o tracking. Na próxima reconciliação, ele tenta
              `removeChild` no nó "antigo" que já mudou → NotFoundError
              em loop, app trava.

 Versão atual (CSS-only):
   - JS NUNCA modifica conteúdo dos nós do React. Só seta `data-i18n-pt="..."`
     (atributo alheio, que o React ignora completamente).
   - CSS injetado uma vez torna o texto original transparente e usa o
     pseudo-elemento `::after` com `content: attr(data-i18n-pt)` pra
     renderizar a tradução por cima.
   - `position: relative` + `position: absolute` no ::after garantem que o
     texto traduzido sobreponha o original no mesmo lugar.
   - Idempotente via flag em `window.parent.__waI18nInstalled`.
   - `setInterval(500ms)` continua sendo o trigger (mais simples que
     MutationObserver, custo desprezível porque só faz querySelectorAll +
     setAttribute em <20 elementos típicos).
"""

from __future__ import annotations

import streamlit.components.v1 as _components


# Mapa exato: string em inglês → pt-BR.
_TRADUCOES_EXATAS = {
    # Forms (text_area / text_input dentro de st.form)
    "Press Ctrl+Enter to submit form": "Use Ctrl+Enter para enviar",
    "Press Enter to submit form":       "Pressione Enter para enviar",
    "Press Enter to apply":             "Pressione Enter para aplicar",
    # File uploader
    "Browse files":                     "Procurar arquivos",
    "Drag and drop file here":          "Arraste arquivos aqui",
    "Drag and drop files here":         "Arraste arquivos aqui",
    # Outros frequentes
    "No options to select.":            "Sem opções para selecionar.",
    "No results":                       "Sem resultados",
    "Loading...":                       "Carregando...",
    "Running...":                       "Executando...",
}

# Padrões com parte variável (ex.: "Limit 200MB per file").
_REGEX_TRADUCOES = [
    (r"^Limit (\d+(?:\.\d+)?[KMG]?B) per file$",
     "Limite $1 por arquivo"),
    (r"^Limit (\d+(?:\.\d+)?[KMG]?B) per file • (.+)$",
     "Limite $1 por arquivo • $2"),
]

# Seletores cirúrgicos onde as strings aparecem. Manter MÍNIMO — quanto
# mais específico, menor o custo por tick.
_SELETORES_ALVO = [
    '[data-testid="InputInstructions"]',
    '[data-testid="stFileUploaderDropzoneInstructions"]',
    '[data-testid="stFileUploaderDropzone"] button',
]


def _build_js_payload() -> str:
    import json as _json
    return (
        "var TRAD_EXATAS = " + _json.dumps(_TRADUCOES_EXATAS) + ";\n"
        "var TRAD_REGEX = " + _json.dumps(_REGEX_TRADUCOES) + ";\n"
        "var SELETORES = " + _json.dumps(_SELETORES_ALVO) + ";"
    )


# CSS que cuida da renderização visual:
#  - Texto original some via `color: transparent` (NÃO via display:none,
#    pra não colapsar layout do Streamlit que conta com o nó ocupando
#    espaço).
#  - ::after com `content: attr(data-i18n-pt)` mostra a tradução por cima
#    do original. `position: absolute` + `left/top:0` sobrepõe exatamente.
#  - Cor cinza claro (.6 opacity) é a aproximação visual das instruções
#    no tema escuro. No tema claro fica um pouco mais discreto que o
#    ideal mas legível.
_CSS_I18N = (
    "[data-i18n-pt] { "
    "  color: transparent !important; "
    "  position: relative !important; "
    "} "
    "[data-i18n-pt]::after { "
    "  content: attr(data-i18n-pt); "
    "  color: rgba(250, 250, 250, 0.6); "
    "  position: absolute; "
    "  left: 0; "
    "  top: 0; "
    "  white-space: nowrap; "
    "  font-size: inherit; "
    "  font-weight: inherit; "
    "  font-family: inherit; "
    "  line-height: inherit; "
    "  letter-spacing: inherit; "
    "} "
)


def aplicar_traducoes_pt_br() -> None:
    """Injeta JS que troca strings em inglês pelo equivalente pt-BR via CSS.

    Chame UMA VEZ no boot do `app.py`. Idempotente entre reruns graças à
    flag em `window.parent.__waI18nInstalled`.
    """
    _payload = _build_js_payload()
    import json as _json
    _css_js = _json.dumps(_CSS_I18N)

    _components.html(
        f"""
        <script>
        (function () {{
            try {{
                var TOP = window.parent;
                var doc = TOP.document;

                if (TOP.__waI18nInstalled) return;
                TOP.__waI18nInstalled = true;

                {_payload}

                // Injeta o CSS uma vez (idempotente via id).
                if (!doc.getElementById('wa-i18n-style')) {{
                    var styleTag = doc.createElement('style');
                    styleTag.id = 'wa-i18n-style';
                    styleTag.textContent = {_css_js};
                    doc.head.appendChild(styleTag);
                }}

                var regexPares = TRAD_REGEX.map(function (pair) {{
                    return {{ re: new RegExp(pair[0]), pt: pair[1] }};
                }});

                function traduzirTexto(s) {{
                    if (!s) return null;
                    var t = s.trim();
                    if (TRAD_EXATAS[t]) return TRAD_EXATAS[t];
                    for (var i = 0; i < regexPares.length; i++) {{
                        var p = regexPares[i];
                        var m = t.match(p.re);
                        if (m) {{
                            var out = p.pt;
                            for (var g = 1; g < m.length; g++) {{
                                out = out.replace('$' + g, m[g]);
                            }}
                            return out;
                        }}
                    }}
                    return null;
                }}

                function tick() {{
                    try {{
                        for (var si = 0; si < SELETORES.length; si++) {{
                            var els = doc.querySelectorAll(SELETORES[si]);
                            for (var ei = 0; ei < els.length; ei++) {{
                                var el = els[ei];
                                // textContent é só LEITURA aqui — não
                                // toca em nada que o React rastreia.
                                var atual = el.textContent.trim();
                                var traduzido = traduzirTexto(atual);
                                if (traduzido === null) continue;
                                // Se já estava com a tradução correta,
                                // pula. Senão atualiza (cobre o caso de
                                // strings dinâmicas como "Limit 200MB •").
                                if (el.getAttribute('data-i18n-pt')
                                    === traduzido) continue;
                                // CHAVE: só seta atributo custom. React
                                // ignora data-* alheios. CSS faz o resto.
                                el.setAttribute('data-i18n-pt', traduzido);
                            }}
                        }}
                    }} catch (e) {{
                        // Erro num tick não derruba o intervalo.
                    }}
                }}

                tick();
                TOP.setInterval(tick, 500);
            }} catch (e) {{
                console.warn('i18n-pt-br:', e);
            }}
        }})();
        </script>
        """,
        height=0,
    )
