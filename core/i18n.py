"""Tradução pt-BR das mensagens nativas do Streamlit.

Por que existe:
 O Streamlit hardcoda várias mensagens em inglês na UI dos widgets (ex.:
 "Press Ctrl+Enter to submit form", "Browse files", "Drag and drop file
 here", "Limit 200MB per file"). Não dá pra controlar por parâmetro do
 widget — vêm direto do componente React empacotado. A única forma de
 traduzir sem fork-ar o Streamlit é injetar JS que observa mutações no
 DOM e substitui o texto na renderização.

Como funciona:
 `aplicar_traducoes_pt_br()` injeta um `<script>` via `components.html`
 que (1) aplica traduções no DOM inicial e (2) instala um MutationObserver
 que reaplica a cada mudança (rerun do Streamlit, widget criado/removido,
 etc.). O `closeToast` do toast de chat usou padrão parecido — função
 global no top frame que sobrevive aos iframes do `components.html`.

Custo:
 MutationObserver é barato quando filtra bem (`childList + subtree`).
 Como roda só nos containers que podem ter as strings-alvo, impacto é
 desprezível mesmo em pages com centenas de widgets.
"""

from __future__ import annotations

import streamlit.components.v1 as _components


# Mapa simples de tradução: string em inglês → pt-BR.
# Coberto:
#  - form: text_area / text_input com botão de submit
#  - file_uploader: rótulos e dicas
#  - st.dataframe / st.toast nativos: poucos hits, mantemos curto
#
# Pra adicionar nova tradução: inclua o par (en, pt) abaixo. Se a string
# tem parte variável (ex.: "Limit 200MB per file"), use a lista de regex
# `_REGEX_TRADUCOES` mais abaixo.
_TRADUCOES_EXATAS = {
    # Forms
    "Press Ctrl+Enter to submit form": "Use Ctrl+Enter para enviar",
    "Press Enter to submit form":       "Pressione Enter para enviar",
    "Press Enter to apply":             "Pressione Enter para aplicar",
    # File uploader
    "Browse files":                     "Procurar arquivos",
    "Drag and drop file here":          "Arraste arquivos aqui",
    "Drag and drop files here":         "Arraste arquivos aqui",
    # Outros frequentes
    "No options to select.":            "Sem opções para selecionar.",
    "Please select":                    "Selecione",
    "Choose an option":                 "Escolha uma opção",
    "No results":                       "Sem resultados",
    "Loading...":                       "Carregando...",
    "Running...":                       "Executando...",
    "Connecting":                       "Conectando",
    "Stop":                             "Parar",
    "Rerun":                            "Re-executar",
    "Deploy":                           "Publicar",
}

# Padrões com parte variável (limite de upload, contagens dinâmicas).
# Cada entrada: (regex_em_ingles, template_pt_br_com_$1, $2, ...)
_REGEX_TRADUCOES = [
    (r"^Limit (\d+(?:\.\d+)?[KMG]?B) per file$",  "Limite $1 por arquivo"),
    (r"^Limit (\d+(?:\.\d+)?[KMG]?B) per file • ",
     "Limite $1 por arquivo • "),
]


def _build_js_payload() -> str:
    """Gera o conteúdo JS com as traduções (string-safe pra escapar aspas)."""
    import json as _json
    return (
        "var TRAD_EXATAS = " + _json.dumps(_TRADUCOES_EXATAS) + ";\n"
        "var TRAD_REGEX = " + _json.dumps(_REGEX_TRADUCOES) + ";"
    )


def aplicar_traducoes_pt_br() -> None:
    """Injeta JS que substitui strings em inglês pelo equivalente pt-BR.

    Chame UMA VEZ no boot do `app.py`, depois do CSS global e antes de
    qualquer outro componente. O MutationObserver fica ativo pela sessão
    inteira; reruns parciais não precisam re-injetar.
    """
    _payload = _build_js_payload()
    _components.html(
        f"""
        <script>
        (function () {{
            try {{
                var TOP = window.parent;
                var doc = TOP.document;

                // Idempotente: se já instalamos pra esta sessão, sai.
                if (TOP.__waI18nInstalled) return;
                TOP.__waI18nInstalled = true;

                {_payload}

                // Compila regex em pares prontos
                var regexPares = TRAD_REGEX.map(function (pair) {{
                    return {{ re: new RegExp(pair[0]), pt: pair[1] }};
                }});

                function traduzirTexto(s) {{
                    if (!s) return s;
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
                    return null;  // sem tradução
                }}

                function aplicar(no) {{
                    // Percorre TextNodes do nó passado.
                    if (!no) return;
                    if (no.nodeType === 3) {{  // TEXT_NODE
                        var traduzido = traduzirTexto(no.nodeValue);
                        if (traduzido !== null) no.nodeValue = traduzido;
                        return;
                    }}
                    if (no.nodeType !== 1) return;  // só elementos depois
                    // Ignora <script>/<style> pra não destruir código
                    var tag = no.tagName;
                    if (tag === 'SCRIPT' || tag === 'STYLE') return;
                    // Filhos recursivamente
                    for (var i = 0; i < no.childNodes.length; i++) {{
                        aplicar(no.childNodes[i]);
                    }}
                }}

                // 1ª passada no DOM já renderizado
                aplicar(doc.body);

                // MutationObserver: reaplica em qualquer adição de nó.
                // Throttling implícito do browser cuida do custo.
                var obs = new TOP.MutationObserver(function (mutations) {{
                    for (var i = 0; i < mutations.length; i++) {{
                        var m = mutations[i];
                        for (var j = 0; j < m.addedNodes.length; j++) {{
                            aplicar(m.addedNodes[j]);
                        }}
                        // Também checa nó-alvo (caso só o textContent mude)
                        if (m.type === 'characterData') {{
                            aplicar(m.target);
                        }}
                    }}
                }});
                obs.observe(doc.body, {{
                    childList: true,
                    subtree: true,
                    characterData: true,
                }});
            }} catch (e) {{
                // I18n é cosmético — nunca quebra o app por causa disso.
                console.warn('i18n-pt-br:', e);
            }}
        }})();
        </script>
        """,
        height=0,
    )
