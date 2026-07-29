"""Aba Arquivos — central de anexos vinculados a projetos, com PASTAS.

Pedido de 29/07/2026: "criar uma pasta e poder ter subpastas".

Como funciona:
 - A hierarquia vive só no banco (tabela `pastas`, auto-referenciada por
   `pasta_pai_id`), e cada arquivo aponta pra uma pasta em `arquivos.pasta_id`
   (NULL = raiz do projeto). Em DISCO nada mudou: continua tudo plano em
   `anexos/<id_projeto>/`. Mover arquivo de pasta é só um UPDATE — sem risco
   de perder o binário no meio do caminho.
 - Navegação: escolhe o projeto, entra/sai das pastas pelo breadcrumb.
 - Criar/renomear/excluir pasta é **só do Gestor**; qualquer um sobe arquivo
   na pasta em que está.
 - Pasta com conteúdo dentro NÃO pode ser excluída (precisa esvaziar antes) —
   evita apagar arquivo sem querer.
"""

from __future__ import annotations

import os
from datetime import datetime

import pandas as pd
import streamlit as st

import database as db

from core.data import _load_df_p
from core.helpers import _pode_gestor
from core.ui_feedback import confirmar_sucesso, erro_humano


usuario = st.session_state.usuario
perfil = st.session_state.get("perfil", "Gestor")
df_p = _load_df_p(usuario, perfil)
_eh_gestor = _pode_gestor()


st.header("📁 Central de Arquivos Técnicos")
st.caption(
    "Anexe documentos a projetos específicos, organizados em **pastas e "
    "subpastas**. Os arquivos ficam salvos no servidor em "
    "`anexos/<id_projeto>/...` e a organização (pasta, descrição, autor, "
    "data) fica no banco."
)

# Mapeamento id → nome (usado em vários lugares abaixo)
_projetos_validos = (
    df_p[df_p["projeto"].notna() & (df_p["projeto"] != "")]
    if not df_p.empty else pd.DataFrame()
)
_id_para_nome = (
    dict(zip(_projetos_validos["id"], _projetos_validos["projeto"]))
    if not _projetos_validos.empty else {}
)

if not _id_para_nome:
    st.warning(
        "Cadastre ao menos um projeto na aba ➕ Novo Projeto antes de "
        "enviar arquivos."
    )
    st.stop()

# ── PROJETO ATUAL ────────────────────────────────────────────────────
_ids_proj = list(_id_para_nome.keys())
proj_id = st.selectbox(
    "📂 Projeto",
    options=_ids_proj,
    format_func=lambda x: _id_para_nome.get(x, "?"),
    key="arq_proj_sel",
)

# Trocar de projeto zera a navegação de pastas (uma pasta é sempre de um
# projeto só — manter o id antigo mostraria conteúdo de outro projeto).
if st.session_state.get("_arq_proj_atual") != proj_id:
    st.session_state["_arq_proj_atual"] = proj_id
    st.session_state["_arq_pasta_atual"] = None

pasta_atual = st.session_state.get("_arq_pasta_atual")
# Defesa: se a pasta guardada sumiu (excluída em outra aba) volta pra raiz.
if pasta_atual is not None and db.obter_pasta(pasta_atual) is None:
    pasta_atual = None
    st.session_state["_arq_pasta_atual"] = None

_trilha = db.caminho_pasta(pasta_atual) if pasta_atual else []


def _ir_para(pid):
    st.session_state["_arq_pasta_atual"] = pid
    st.rerun()


# ── BREADCRUMB ───────────────────────────────────────────────────────
_bc_cols = st.columns([0.18] + [0.18] * min(len(_trilha), 4) + [0.1])
if _bc_cols[0].button("🏠 Raiz", key="bc_raiz", width="stretch",
                      type=("primary" if not _trilha else "secondary"),
                      help="Voltar pra raiz do projeto"):
    _ir_para(None)
for _i, _p in enumerate(_trilha[-4:]):
    _ultimo = (_p["id"] == pasta_atual)
    if _bc_cols[_i + 1].button(
        f"📁 {_p['nome'][:14]}", key=f"bc_{_p['id']}", width="stretch",
        type=("primary" if _ultimo else "secondary"),
    ):
        _ir_para(_p["id"])

st.caption("📍 " + " / ".join(["Raiz"] + [p["nome"] for p in _trilha]))

# ── AÇÕES DA PASTA (só Gestor) ───────────────────────────────────────
if _eh_gestor:
    _ac1, _ac2 = st.columns(2)
    with _ac1.popover("➕ Nova pasta", width="stretch"):
        with st.form("form_nova_pasta", clear_on_submit=True):
            _nome_pasta = st.text_input(
                "Nome da pasta",
                placeholder="ex.: Projetos Executivos, ART, Fotos",
            )
            st.caption(
                "Criada dentro de **"
                + (_trilha[-1]["nome"] if _trilha else "Raiz") + "**."
            )
            if st.form_submit_button("Criar", width="stretch"):
                if not _nome_pasta.strip():
                    st.warning("Dê um nome à pasta.")
                elif db.criar_pasta(proj_id, _nome_pasta,
                                    pasta_pai_id=pasta_atual,
                                    criado_por=usuario):
                    db.log_aud(usuario, "criar", "pasta", proj_id,
                               f"pasta='{_nome_pasta.strip()}'")
                    confirmar_sucesso("Pasta criada", _nome_pasta.strip())
                    st.rerun()
                else:
                    st.warning(
                        f"Já existe uma pasta chamada "
                        f"**{_nome_pasta.strip()}** aqui."
                    )

    if pasta_atual:
        with _ac2.popover("⚙️ Esta pasta", width="stretch"):
            _p_cur = db.obter_pasta(pasta_atual) or {}
            with st.form("form_ren_pasta"):
                _novo_nome = st.text_input("Renomear para",
                                           value=_p_cur.get("nome", ""))
                if st.form_submit_button("💾 Renomear", width="stretch"):
                    if db.renomear_pasta(pasta_atual, _novo_nome):
                        confirmar_sucesso("Pasta renomeada",
                                          _novo_nome.strip())
                        st.rerun()
                    else:
                        st.warning("Nome inválido.")

            st.divider()
            _n_arq_p, _n_sub_p = db.pasta_tem_conteudo(pasta_atual)
            if _n_arq_p or _n_sub_p:
                st.info(
                    f"Esta pasta tem **{_n_arq_p}** arquivo(s) e "
                    f"**{_n_sub_p}** subpasta(s). Esvazie antes de excluir "
                    "(nada é apagado em cascata, de propósito)."
                )
            else:
                st.markdown("**Excluir esta pasta vazia?**")
                if st.button("🗑️ Sim, excluir", type="primary",
                             key="del_pasta_atual", width="stretch"):
                    _pai = _p_cur.get("pasta_pai_id")
                    if db.excluir_pasta(pasta_atual):
                        db.log_aud(usuario, "excluir", "pasta", proj_id,
                                   f"pasta='{_p_cur.get('nome','')}'")
                        confirmar_sucesso("Pasta excluída",
                                          _p_cur.get("nome", ""))
                        _ir_para(_pai)
                    else:
                        st.warning("A pasta deixou de estar vazia.")
else:
    st.caption("ℹ️ Criar e excluir pastas é função do Gestor. Você pode "
               "enviar e baixar arquivos normalmente.")

# ── UPLOAD (cai na pasta atual) ──────────────────────────────────────
_dest = _trilha[-1]["nome"] if _trilha else "Raiz"
with st.expander(f"⬆️ Anexar arquivo em: {_dest}", expanded=False):
    with st.form("form_upload_arquivo", clear_on_submit=True):
        desc_upload = st.text_input("Descrição (opcional)", key="upload_desc")
        arquivos_novos = st.file_uploader(
            "Selecione um ou mais arquivos",
            accept_multiple_files=True,
            key="upload_files",
            help="Limite de 100 MB por arquivo "
                 "(config em .streamlit/config.toml).",
        )
        submit_upload = st.form_submit_button(
            f"📤 Enviar para “{_dest}”", width="stretch",
        )

    if submit_upload:
        if not arquivos_novos:
            st.warning("Selecione ao menos um arquivo antes de enviar.")
        else:
            # Progress bar com feedback por arquivo. Mais útil que um
            # spinner único quando o user manda 5+ arquivos: ele vê
            # EXATAMENTE no que travou se travar.
            ok = 0
            falhas: list[tuple[str, Exception]] = []
            _total = len(arquivos_novos)
            _prog = st.progress(0.0, text="Iniciando upload...")
            for i, arq in enumerate(arquivos_novos):
                _prog.progress(
                    (i + 0.1) / _total,
                    text=f"Enviando **{arq.name}** ({i+1}/{_total})...",
                )
                try:
                    pasta, path_final = db.caminho_seguro_para_anexo(
                        proj_id, arq.name,
                    )
                    os.makedirs(pasta, exist_ok=True)
                    with open(path_final, "wb") as f:
                        f.write(arq.getbuffer())
                    db.salvar_arquivo(
                        projeto_id=proj_id,
                        nome_original=arq.name,
                        path_arquivo=path_final,
                        descricao=desc_upload,
                        autor=usuario,
                        tamanho_bytes=arq.size,
                        mime_type=arq.type or "",
                        pasta_id=pasta_atual,
                    )
                    db.log_aud(usuario, "upload", "arquivo", proj_id,
                               f"nome='{arq.name}', {arq.size}B, "
                               f"pasta='{_dest}'")
                    ok += 1
                except Exception as exc:
                    falhas.append((arq.name, exc))
                _prog.progress((i + 1) / _total,
                               text=f"Concluído {i+1}/{_total}")
            _prog.empty()

            if ok:
                st.success(
                    f"✅ {ok} arquivo(s) enviado(s) para "
                    f"**{_id_para_nome[proj_id]} / {_dest}**"
                )
            for nome_arq, exc in falhas:
                erro_humano(
                    f"Upload do arquivo '{nome_arq}'", exc,
                    sugestao=(
                        "Confira se o arquivo cabe em 100 MB e se você tem "
                        "permissão na pasta do projeto. Os outros arquivos "
                        "do lote foram enviados normalmente."
                    ),
                )
            if ok and not falhas:
                st.rerun()

st.divider()

# ── MÉTRICAS (do projeto inteiro, não só da pasta atual) ─────────────
_todos_proj = db.listar_arquivos(projeto_id=proj_id)
_tam_total = sum((r[7] or 0) for r in _todos_proj)
_m1, _m2, _m3 = st.columns(3)
_m1.metric("Arquivos no projeto", len(_todos_proj))
_m2.metric("Tamanho total", f"{_tam_total / (1024*1024):.1f} MB")
_m3.metric("Pastas (neste nível)",
           len(db.listar_pastas(proj_id, pasta_pai_id=pasta_atual)))

# ── CONTEÚDO DA PASTA ATUAL: subpastas + arquivos ────────────────────
_subpastas = db.listar_pastas(proj_id, pasta_pai_id=pasta_atual)
_arqs = db.listar_arquivos(projeto_id=proj_id, pasta_id=pasta_atual,
                           so_da_pasta=True)

# Destinos possíveis pra mover arquivo: raiz + todas as pastas do projeto.
# Monta a lista achatada com o caminho completo, pra não confundir pastas
# de mesmo nome em níveis diferentes.
def _todas_pastas_do_projeto(pid):
    _saida, _fila = [], [(None, "")]
    while _fila:
        _pai, _prefixo = _fila.pop(0)
        for _p in db.listar_pastas(pid, pasta_pai_id=_pai):
            _cam = f"{_prefixo}/{_p['nome']}" if _prefixo else _p["nome"]
            _saida.append((_p["id"], _cam))
            _fila.append((_p["id"], _cam))
    return _saida


_destinos = [(None, "🏠 Raiz")] + [
    (i, f"📁 {c}") for i, c in _todas_pastas_do_projeto(proj_id)
]
_dest_labels = {i: c for i, c in _destinos}

if _subpastas:
    st.markdown("##### 📁 Pastas")
    for _p in _subpastas:
        _na, _ns = db.pasta_tem_conteudo(_p["id"])
        with st.container(border=True):
            _pc1, _pc2 = st.columns([0.8, 0.2],
                                    vertical_alignment="center")
            if _pc1.button(
                f"📁  **{_p['nome']}**", key=f"abrir_pasta_{_p['id']}",
                width="stretch",
                help=f"{_na} arquivo(s) · {_ns} subpasta(s)",
            ):
                _ir_para(_p["id"])
            _pc2.caption(f"{_na} arq · {_ns} sub")

if not _arqs and not _subpastas:
    st.info("🗂️ Esta pasta está vazia. Envie um arquivo acima"
            + (" ou crie uma subpasta." if _eh_gestor else "."))

if _arqs:
    st.markdown("##### 📄 Arquivos")
    _icones = {
        ".pdf": "📄", ".dwg": "📐", ".dxf": "📐",
        ".jpg": "🖼️", ".jpeg": "🖼️", ".png": "🖼️", ".gif": "🖼️",
        ".xls": "📊", ".xlsx": "📊", ".csv": "📊",
        ".doc": "📝", ".docx": "📝", ".txt": "📝",
        ".zip": "🗜️", ".rar": "🗜️", ".7z": "🗜️",
    }
    for row in _arqs:
        (arq_id, _pid_row, nome_original, path_arquivo, descricao,
         autor, data_upload, tamanho_bytes, _pasta_id_row) = row
        ext = os.path.splitext(nome_original)[1].lower()
        icone = _icones.get(ext, "📎")

        if tamanho_bytes is None:
            tamanho_str = "—"
        elif tamanho_bytes < 1024:
            tamanho_str = f"{tamanho_bytes} B"
        elif tamanho_bytes < 1024 * 1024:
            tamanho_str = f"{tamanho_bytes / 1024:.1f} KB"
        else:
            tamanho_str = f"{tamanho_bytes / (1024 * 1024):.1f} MB"

        try:
            data_fmt = datetime.fromisoformat(
                str(data_upload).replace("T", " ")
            ).strftime("%d/%m/%Y %H:%M")
        except Exception:
            data_fmt = str(data_upload)

        with st.container(border=True):
            c_ic, c_info, c_btns = st.columns([0.08, 0.62, 0.30])
            c_ic.markdown(
                f"<div style='font-size:38px; text-align:center; "
                f"padding-top:6px;'>{icone}</div>",
                unsafe_allow_html=True,
            )
            with c_info:
                st.markdown(f"**{nome_original}**")
                st.caption(
                    f"👤 {autor or '—'}  ·  📅 {data_fmt}  ·  "
                    f"💾 {tamanho_str}"
                )
                if descricao:
                    st.markdown(
                        f"<span style='font-size:0.85rem;opacity:0.9'>"
                        f"💬 {descricao}</span>",
                        unsafe_allow_html=True,
                    )
            with c_btns:
                if path_arquivo and os.path.exists(path_arquivo):
                    with open(path_arquivo, "rb") as f:
                        st.download_button(
                            "⬇️ Baixar",
                            data=f,
                            file_name=nome_original,
                            key=f"dl_arq_{arq_id}",
                            width="stretch",
                        )
                else:
                    st.warning("Arquivo perdido", icon="⚠️")

                # Mover de pasta: quem pode excluir também pode reorganizar.
                pode_mexer = (perfil == "Gestor" or autor == usuario)
                if pode_mexer and len(_destinos) > 1:
                    with st.popover("📦 Mover", width="stretch"):
                        _alvo = st.selectbox(
                            "Mover para",
                            options=[d[0] for d in _destinos],
                            format_func=lambda x: _dest_labels.get(x, "?"),
                            key=f"mv_sel_{arq_id}",
                        )
                        if st.button("Mover", key=f"mv_go_{arq_id}",
                                     width="stretch"):
                            db.mover_arquivo_para_pasta(arq_id, _alvo)
                            db.log_aud(usuario, "mover", "arquivo", arq_id,
                                       f"-> {_dest_labels.get(_alvo, '?')}")
                            confirmar_sucesso(
                                "Arquivo movido",
                                f"{nome_original} → "
                                f"{_dest_labels.get(_alvo, '')}",
                            )
                            st.rerun()

                # Apenas Gestor ou autor pode excluir
                if pode_mexer:
                    with st.popover("🗑️ Excluir", width="stretch"):
                        st.markdown(
                            f"**Excluir `{nome_original}` permanentemente?**"
                        )
                        st.caption(
                            "O arquivo será removido do disco e do "
                            "registro do projeto."
                        )
                        if st.button(
                            "✅ Sim, excluir", key=f"yes_del_arq_{arq_id}",
                            type="primary", width="stretch",
                        ):
                            db.excluir_arquivo(arq_id)
                            db.log_aud(usuario, "excluir", "arquivo", arq_id,
                                       f"nome='{nome_original}'")
                            confirmar_sucesso(
                                "Arquivo removido",
                                f"'{nome_original}' foi excluído.",
                            )
                            st.rerun()
