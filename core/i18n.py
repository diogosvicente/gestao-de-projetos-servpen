"""Tradução pt-BR das mensagens nativas do Streamlit (versão segura).

Histórico:
 1ª versão usava `MutationObserver` com `characterData: true + subtree:
 true` sobre `document.body`. Em DOM grande do Streamlit (centenas de
 widgets), cada modificação de texto disparava nova mutação, criando uma
 cascata de callbacks que travava a main thread. Login → branco.

Versão atual:
 - `setInterval(500ms)` com `querySelectorAll` cirúrgico nos `data-testid`
   exatos onde as strings inglês aparecem (`InputInstructions`,
   `stFileUploaderDropzoneInstructions`, etc.). Sem walk recursivo do DOM.
 - Idempotente: flag em `window.parent` impede instalar de novo entre
   reruns. Se o setInterval ficar órfão (Streamlit recarrega o frame), o
   próximo `aplicar_traducoes_pt_br()` reinstala.
 - `try/catch` em volta — i18n é cosmético, nunca quebra o app.
"""

from __future__ import annotations

import streamlit.components.v1 as _components


# Mapa exato: string em inglês → pt-BR.
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
}

# Padrões com parte variável.
_REGEX_TRADUCOES = [
    (r"^Limit (\d+(?:\.\d+)?[KMG]?B) per file$",
     "Limite $1 por arquivo"),
    (r"^Limit (\d+(?:\.\d+)?[KMG]?B) per file • (.+)$",
     "Limite $1 por arquivo • $2"),
]

# Seletores onde as strings-alvo aparecem. Mais específico = menos custo
# por tick. Se uma nova string surgir num seletor não listado, adicionar
# aqui depois de inspecionar o DOM no DevTools.
_SELETORES_ALVO = [
    '[data-testid="InputInstructions"]',
    '[data-testid="stFileUploaderDropzoneInstructions"]',
    '[data-testid="stFileUploaderDropzone"] button',
    '[data-testid="stFileUploaderDropzone"] span',
    '[data-testid="stFileUploaderFileName"] + small',
    # Selectbox / multiselect placeholders
    '.stSelectbox div[role="combobox"]',
    '.stMultiSelect div[role="combobox"]',
]


def _build_js_payload() -> str:
    """Gera o conteúdo JS com as traduções (escapando aspas via JSON)."""
    import json as _json
    return (
        "var TRAD_EXATAS = " + _json.dumps(_TRADUCOES_EXATAS) + ";\n"
        "var TRAD_REGEX = " + _json.dumps(_REGEX_TRADUCOES) + ";\n"
        "var SELETORES = " + _json.dumps(_SELETORES_ALVO) + ";"
    )


def aplicar_traducoes_pt_br() -> None:
    """Injeta JS que substitui strings em inglês pelo equivalente pt-BR.

    Chame UMA VEZ no boot do `app.py`, depois do CSS global. O setInterval
    fica ativo na sessão do browser; reruns parciais não re-injetam graças
    à flag em `window.parent.__waI18nInstalled`.
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
                // Se o intervalo anterior ficou órfão (frame recarregou),
                // a flag mora em window.parent → sobrevive.
                if (TOP.__waI18nInstalled) return;
                TOP.__waI18nInstalled = true;

                {_payload}

                // Compila regex em pares prontos (1x)
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
                                // textContent direto (não recursão).
                                // Se o nodo tem filhos com sub-estrutura,
                                // o seletor já é específico o bastante
                                // pra apontar pro container do texto puro.
                                var atual = el.textContent;
                                var traduzido = traduzirTexto(atual);
                                if (traduzido !== null
                                    && traduzido !== atual) {{
                                    el.textContent = traduzido;
                                }}
                            }}
                        }}
                    }} catch (e) {{
                        // Erro num tick não derruba o intervalo.
                        // console.warn('i18n tick:', e);
                    }}
                }}

                // Primeiro tick imediato + intervalo curto.
                // 500ms é imperceptível pro user mas dá folga pro browser
                // entre execuções. Se ficar visível, posso baixar pra 250ms.
                tick();
                TOP.setInterval(tick, 500);
            }} catch (e) {{
                // I18n é cosmético — nunca quebra o app por causa disso.
                console.warn('i18n-pt-br:', e);
            }}
        }})();
        </script>
        """,
        height=0,
    )
