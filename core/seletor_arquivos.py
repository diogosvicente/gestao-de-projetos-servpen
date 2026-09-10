"""Seletor de arquivos que registra SÓ O NOME — o arquivo não é enviado.

Usado em "Documentações Geradas" (Kanban → edição do projeto). A pessoa
escolhe um ou vários arquivos, pelo botão ou arrastando, e o navegador devolve
pro Python apenas os nomes. O conteúdo nunca sai do computador. O
`st.file_uploader` não serve aqui: ele sempre envia o arquivo inteiro ao
servidor (lento pra planta/PDF grande), e o pedido foi justamente não anexar.

Feito com `st.components.v2` (HTML/CSS/JS inline, sem etapa de build).
"""

from __future__ import annotations

from streamlit.components.v2 import component as _componente_v2
from streamlit.components.v2.get_bidi_component_manager import (
    get_bidi_component_manager,
)

_NOME = "seletor_nomes_arquivos"

_HTML = """
<div class="sna">
  <button type="button" class="sna-botao">📎 <span class="sna-rotulo"></span></button>
  <span class="sna-dica"></span>
  <input type="file" multiple hidden>
</div>
"""

# Fica num shadow root (isolate_styles=True): o CSS do app não entra aqui e o
# daqui não vaza. Por isso as cores dos dois temas são definidas neste bloco.
_CSS = """
.sna {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  padding: 10px 12px; border-radius: 10px;
  border: 1px dashed rgba(255, 255, 255, .25);
  font-family: inherit; font-size: inherit; color: #cbd5e1;
}
.sna.sna-claro { color: #374151; border-color: rgba(0, 0, 0, .25); }
.sna.sna-arrastando { border-color: #0ea5e9; background: rgba(14, 165, 233, .10); }
.sna-botao {
  font-family: inherit; font-size: inherit; font-weight: 600;
  cursor: pointer; padding: 6px 14px; border-radius: 8px;
  border: 1px solid #0ea5e9; background: #0ea5e9; color: #fff;
}
.sna-botao:hover { background: #0284c7; border-color: #0284c7; }
.sna-dica { font-size: .82rem; opacity: .85; }
"""

_JS = """
export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const raiz = parentElement.querySelector(".sna");
  const botao = parentElement.querySelector(".sna-botao");
  const entrada = parentElement.querySelector("input[type=file]");
  if (!raiz || !botao || !entrada) return;

  const d = data || {};
  raiz.classList.toggle("sna-claro", !!d.claro);
  parentElement.querySelector(".sna-rotulo").textContent =
    d.rotulo || "Selecionar arquivos";
  parentElement.querySelector(".sna-dica").textContent = d.dica || "";

  const enviar = (lista) => {
    const nomes = Array.from(lista || []).map((f) => f.name).filter(Boolean);
    if (nomes.length) setTriggerValue("arquivos", nomes);
  };

  // Atribuição direta (onclick = ...) em vez de addEventListener: se esta
  // função rodar de novo no mesmo elemento, os ouvintes não se acumulam
  // (com ouvinte duplicado, cada seleção seria enviada várias vezes).
  botao.onclick = () => entrada.click();
  entrada.onchange = () => {
    enviar(entrada.files);
    entrada.value = "";  // permite escolher o mesmo arquivo de novo
  };
  raiz.ondragover = (e) => {
    e.preventDefault();
    raiz.classList.add("sna-arrastando");
  };
  raiz.ondragleave = () => raiz.classList.remove("sna-arrastando");
  raiz.ondrop = (e) => {
    e.preventDefault();
    raiz.classList.remove("sna-arrastando");
    enviar(e.dataTransfer && e.dataTransfer.files);
  };
}
"""

_montar = None


def _componente():
    """Callable de montagem, registrando o componente quando preciso.

    Só registra se o registro ATUAL não conhece o componente: no servidor isso
    acontece uma vez por processo. Registrar apenas no import do módulo não
    basta — no AppTest cada run tem um registro novo, e o módulo já importado
    não registraria de novo ("Component ... is not registered").
    """
    global _montar
    if _montar is None or get_bidi_component_manager().get(_NOME) is None:
        _montar = _componente_v2(_NOME, html=_HTML, css=_CSS, js=_JS)
    return _montar


def seletor_nomes_arquivos(key, *, claro=False, rotulo="Selecionar arquivos",
                           dica=""):
    """Mostra o seletor e devolve os nomes escolhidos NESTE run, ou None.

    É um valor de gatilho: existe só no run da seleção e volta a None no
    seguinte. Quem chama grava na hora, sem precisar de `st.rerun()`.
    """
    res = _componente()(
        key=key,
        data={"claro": bool(claro), "rotulo": rotulo, "dica": dica},
        # O Streamlit só expõe o evento se houver um callback
        # on_<evento>_change; o valor é lido no retorno, então ele é vazio.
        on_arquivos_change=lambda: None,
    )
    return res.get("arquivos") if res else None
