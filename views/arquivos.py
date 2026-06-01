"""Aba Arquivos — central de anexos vinculados a projetos."""

from __future__ import annotations

import os
from datetime import datetime

import pandas as pd
import streamlit as st

import database as db

from core.data import _load_df_p
from core.ui_feedback import erro_humano


usuario = st.session_state.usuario
perfil = st.session_state.get("perfil", "Gestor")
df_p = _load_df_p(usuario, perfil)


st.header("📁 Central de Arquivos Técnicos")
st.caption(
    "Anexe documentos a projetos específicos. Os arquivos ficam salvos no "
    "servidor em `anexos/<id_projeto>/...` e os metadados (descrição, autor, "
    "data) na tabela `arquivos`."
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

# === BLOCO DE UPLOAD ===
with st.expander("⬆️ Anexar Novo Arquivo", expanded=False):
    if _projetos_validos.empty:
        st.warning(
            "Cadastre ao menos um projeto na aba ➕ Novo Projeto antes "
            "de enviar arquivos."
        )
    else:
        with st.form("form_upload_arquivo", clear_on_submit=True):
            col_u1, col_u2 = st.columns([1, 1])
            proj_alvo_id = col_u1.selectbox(
                "Vincular ao Projeto*",
                options=list(_id_para_nome.keys()),
                format_func=lambda x: _id_para_nome.get(x, "?"),
                key="upload_proj_alvo",
            )
            desc_upload = col_u2.text_input(
                "Descrição (opcional)", key="upload_desc",
            )
            arquivos_novos = st.file_uploader(
                "Selecione um ou mais arquivos",
                accept_multiple_files=True,
                key="upload_files",
                help="Limite de 100 MB por arquivo "
                     "(config em .streamlit/config.toml).",
            )
            submit_upload = st.form_submit_button(
                "📤 Enviar arquivos", use_container_width=True,
            )

        if submit_upload:
            if not arquivos_novos:
                st.warning("Selecione ao menos um arquivo antes de enviar.")
            else:
                # Progress bar com feedback por arquivo. Mais útil que
                # um spinner único quando o user manda 5+ arquivos: ele
                # vê EXATAMENTE no que travou se travar.
                ok = 0
                falhas: list[tuple[str, Exception]] = []
                _total = len(arquivos_novos)
                _prog = st.progress(0.0, text="Iniciando upload...")
                for i, arq in enumerate(arquivos_novos):
                    _prog.progress(
                        (i + 0.1) / _total,
                        text=(
                            f"Enviando **{arq.name}** "
                            f"({i+1}/{_total})..."
                        ),
                    )
                    try:
                        pasta, path_final = db.caminho_seguro_para_anexo(
                            proj_alvo_id, arq.name,
                        )
                        os.makedirs(pasta, exist_ok=True)
                        with open(path_final, "wb") as f:
                            f.write(arq.getbuffer())
                        db.salvar_arquivo(
                            projeto_id=proj_alvo_id,
                            nome_original=arq.name,
                            path_arquivo=path_final,
                            descricao=desc_upload,
                            autor=usuario,
                            tamanho_bytes=arq.size,
                            mime_type=arq.type or "",
                        )
                        db.log_aud(usuario, "upload", "arquivo",
                                   proj_alvo_id,
                                   f"nome='{arq.name}', {arq.size}B")
                        ok += 1
                    except Exception as exc:
                        falhas.append((arq.name, exc))
                    _prog.progress(
                        (i + 1) / _total,
                        text=f"Concluído {i+1}/{_total}",
                    )
                _prog.empty()

                if ok:
                    st.success(
                        f"✅ {ok} arquivo(s) enviado(s) e vinculado(s) ao "
                        f"projeto **{_id_para_nome[proj_alvo_id]}**"
                    )
                for nome_arq, exc in falhas:
                    erro_humano(
                        f"Upload do arquivo '{nome_arq}'", exc,
                        sugestao=(
                            "Confira se o arquivo cabe em 100 MB e se "
                            "você tem permissão na pasta do projeto. Os "
                            "outros arquivos do lote foram enviados "
                            "normalmente."
                        ),
                    )
                if ok and not falhas:
                    st.rerun()

st.divider()

# === FILTRO + MÉTRICAS ===
col_f1, col_f2, col_f3 = st.columns([2, 1, 1])
opcoes_filtro = [None] + list(_id_para_nome.keys())
filtro_proj_id = col_f1.selectbox(
    "Filtrar por projeto",
    options=opcoes_filtro,
    format_func=lambda x: (
        "📂 Todos os projetos" if x is None
        else _id_para_nome.get(x, "?")
    ),
    key="filtro_arquivos",
)

arquivos_lista = db.listar_arquivos(projeto_id=filtro_proj_id)
tamanho_total = sum((r[7] or 0) for r in arquivos_lista)
col_f2.metric("Arquivos", len(arquivos_lista))
col_f3.metric("Tamanho total", f"{tamanho_total / (1024*1024):.1f} MB")

st.divider()

# === LISTAGEM ===
if not arquivos_lista:
    st.info("🗂️ Nenhum arquivo encontrado para esta seleção.")
else:
    _icones = {
        ".pdf": "📄", ".dwg": "📐", ".dxf": "📐",
        ".jpg": "🖼️", ".jpeg": "🖼️", ".png": "🖼️", ".gif": "🖼️",
        ".xls": "📊", ".xlsx": "📊", ".csv": "📊",
        ".doc": "📝", ".docx": "📝", ".txt": "📝",
        ".zip": "🗜️", ".rar": "🗜️", ".7z": "🗜️",
    }
    for row in arquivos_lista:
        (arq_id, proj_id, nome_original, path_arquivo, descricao,
         autor, data_upload, tamanho_bytes) = row
        ext = os.path.splitext(nome_original)[1].lower()
        icone = _icones.get(ext, "📎")
        proj_nome = _id_para_nome.get(proj_id, "(projeto removido)")

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
                data_upload.replace("T", " ")
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
                    f"📂 **{proj_nome}**  ·  👤 {autor or '—'}  ·  "
                    f"📅 {data_fmt}  ·  💾 {tamanho_str}"
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
                            use_container_width=True,
                        )
                else:
                    st.warning("Arquivo perdido", icon="⚠️")

                # Apenas Gestor ou autor pode excluir
                pode_excluir = (perfil == "Gestor" or autor == usuario)
                if pode_excluir:
                    with st.popover("🗑️ Excluir", use_container_width=True):
                        st.markdown(
                            f"**Excluir `{nome_original}` permanentemente?**"
                        )
                        st.caption(
                            "O arquivo será removido do disco e do "
                            "registro do projeto."
                        )
                        if st.button(
                            "✅ Sim, excluir", key=f"yes_del_arq_{arq_id}",
                            type="primary", use_container_width=True,
                        ):
                            db.excluir_arquivo(arq_id)
                            db.log_aud(usuario, "excluir", "arquivo", arq_id,
                                       f"nome='{nome_original}'")
                            st.toast(
                                f"Arquivo '{nome_original}' removido."
                            )
                            st.rerun()
