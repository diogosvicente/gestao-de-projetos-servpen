"""Aba Diário — relatos cronológicos por projeto, com menções @ e horas.

Inclui:
 - Painel persistente de menções pendentes (com "✕ Fechar" / "Limpar todos")
 - Resumo de horas registradas (hoje/semana/mês × minhas/equipe)
 - Formulário de novo relato com @mention
 - Listagem agrupada por projeto (expander que abre automaticamente em casos
   de não-lidos ou menção forçada do painel)
 - O helper `_render_relatos_proj` está em fragmento próprio pra evitar
   scroll-pro-topo quando o user clica em Excluir/Resolver/Responder.
"""

from __future__ import annotations

import os
import re
from datetime import datetime

import pandas as pd
import streamlit as st

import database as db
import relatorios

from core.data import _invalidar_dados, _load_df_d, _load_df_p, _load_df_u
from core.helpers import _pode_editar, _tempo_relativo
from core.mencoes import (
    _popover_mencionar,
    _processar_mencoes_diario,
    _render_mencoes_html,
)
from core.ui_feedback import carregando, confirmar_sucesso, erro_humano


usuario = st.session_state.usuario
perfil = st.session_state.get("perfil", "Projetista")
df_p = _load_df_p(usuario, perfil)
df_u = _load_df_u()
df_d = _load_df_d()


# Regex do cabeçalho de cada interação gravada em `resposta_gestor`:
#   "[DD/MM/AAAA HH:MM] Autor (Perfil): <texto>"
# Serve pra quebrar o histórico (um TEXT acumulado) em comentários separados.
_RE_INTERACAO = re.compile(
    r"\[(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2})\]\s+(.+?)\s+\(([^)]*)\)\s*:\s*"
)


def _interacoes_para_html(bruto, usuarios, eu):
    """Quebra o histórico de respostas em comentários e devolve (html, n).

    Cada comentário vira um "balão" com cabeçalho (autor · perfil · data) e
    corpo — separação visual clara de onde começa/termina cada um. Texto
    legado sem cabeçalho vira um balão único. A string HTML NÃO tem quebras
    de linha de propósito: 4+ espaços no início de linha viram bloco <pre>
    no markdown do Streamlit (e o HTML apareceria literal).
    """
    bruto = str(bruto or "").strip()
    if not bruto:
        return "", 0

    matches = list(_RE_INTERACAO.finditer(bruto))
    itens = []  # (data, autor, perfil, corpo)
    if not matches:
        itens.append(("", "", "", bruto))
    else:
        if matches[0].start() > 0:
            _pre = bruto[:matches[0].start()].strip()
            if _pre:
                itens.append(("", "", "", _pre))
        for i, m in enumerate(matches):
            ini = m.end()
            fim = matches[i + 1].start() if i + 1 < len(matches) else len(bruto)
            itens.append((m.group(1), m.group(2).strip(),
                          m.group(3).strip(), bruto[ini:fim].strip()))

    baloes = []
    for (data, autor, perfil_c, corpo) in itens:
        corpo_html = _render_mencoes_html(
            corpo.replace("\n", "<br>"), usuarios, eu_mesmo=eu,
        )
        _eh_gestor = perfil_c.lower().startswith("gestor")
        _accent = "#f5b301" if _eh_gestor else "#38bdf8"
        _icone = "👑" if _eh_gestor else "💬"
        _cab = (
            (f'<div style="display:flex;justify-content:space-between;'
             f'align-items:center;gap:8px;margin-bottom:5px;">'
             f'<span style="font-size:12px;font-weight:700;color:{_accent};">'
             f'{_icone} {autor}'
             f'<span style="opacity:.6;font-weight:400;"> · {perfil_c}</span>'
             f'</span>'
             f'<span style="opacity:.55;font-size:11px;white-space:nowrap;">'
             f'{data}</span></div>')
            if autor else ""
        )
        baloes.append(
            f'<div style="background:rgba(255,255,255,0.05);'
            f'border:1px solid rgba(255,255,255,0.08);'
            f'border-left:3px solid {_accent};border-radius:8px;'
            f'padding:9px 12px;margin-top:8px;">{_cab}'
            f'<div style="font-size:13px;line-height:1.55;color:#e9e9e9;">'
            f'{corpo_html}</div></div>'
        )
    return "".join(baloes), len(itens)


# ══════════════════════════════════════════════════════════════════════
# FRAGMENT: renderiza lista de relatos de UM projeto.
#
# Decorada com @st.fragment para que `st.rerun(scope='fragment')` redesenhe
# APENAS este bloco quando o usuário clica Excluir/Resolver/Reabrir/Enviar
# — assim o scroll do navegador NÃO volta pro topo a cada ação.
#
# IMPORTANTE: re-consulta o banco a cada render. Sem isso, num
# `st.rerun(scope='fragment')` o fragmento mostraria dados antigos
# (resolver/excluir não refletiria).
# ══════════════════════════════════════════════════════════════════════
@st.fragment
def _render_relatos_proj(proj_id, busca, so_pendentes, usuarios_para_render,
                         autor_logado, perfil, destacar_relato_id):
    df_proj_d = pd.read_sql_query(
        "SELECT * FROM diario WHERE projeto_id = %s ORDER BY id DESC",
        db.get_engine(), params=(int(proj_id),),
    )

    if busca and busca.strip():
        t = busca.lower()
        df_proj_d = df_proj_d[
            df_proj_d["executado"].astype(str).str.lower().str.contains(t, na=False)
            | df_proj_d["autor"].astype(str).str.lower().str.contains(t, na=False)
            | df_proj_d["disciplina"].astype(str).str.lower().str.contains(t, na=False)
            | df_proj_d["resposta_gestor"].astype(str).str.lower().str.contains(t, na=False)
        ]
    if so_pendentes:
        df_proj_d = df_proj_d[df_proj_d["resolvido"] == 0]

    for _, d in df_proj_d.iterrows():
        texto_completo = str(d["executado"])
        texto_exibicao = texto_completo
        for tag_rem in (
            "[Relato de Atividade]", "[❓ Dúvida Técnica]", "[🛑 Impedimento]",
            "Relato de Atividade", "❓ Dúvida Técnica", "🛑 Impedimento"
        ):
            texto_exibicao = texto_exibicao.replace(tag_rem, "")
        texto_exibicao = texto_exibicao.strip()

        if d["resolvido"]:
            cor_topo, tag = "#1e7e34", "✅ RESOLVIDO"
        elif any(x in texto_completo for x in ["Impedimento", "Dúvida", "🛑", "❓"]):
            cor_topo, tag = "#b01a2c", "⚠️ PENDÊNCIA"
        else:
            cor_topo, tag = "#0056b3", "📝 RELATO"

        _destaque_relato = (destacar_relato_id == int(d["id"]))

        texto_exibicao = _render_mencoes_html(
            texto_exibicao, usuarios_para_render, eu_mesmo=autor_logado,
        )
        _interacoes_html, _n_interacoes = _interacoes_para_html(
            d.get("resposta_gestor"), usuarios_para_render, autor_logado,
        )
        _anexo = d.get("anexo")

        _wrap_pre = (
            '<div style="border:2px solid #f59e0b;border-radius:12px;'
            'padding:4px;box-shadow:0 0 18px rgba(245,158,11,0.45);'
            'margin-top:10px;">'
            if _destaque_relato else ""
        )
        _wrap_post = "</div>" if _destaque_relato else ""

        # Chip ⏱ Xh: só exibe quando horas > 0 (campo opcional)
        _horas_val = d.get("horas") or 0
        try:
            _horas_num = float(_horas_val)
        except (TypeError, ValueError):
            _horas_num = 0.0
        _horas_chip = (
            f'<span style="background:rgba(255,255,255,0.18);padding:2px 8px;'
            f'border-radius:4px;font-variant-numeric:tabular-nums;">'
            f'⏱ {_horas_num:.2f} h</span>'
            if _horas_num > 0 else ""
        )
        # Bloco "direito" (horas + tempo relativo) inline. NÃO pode ficar em
        # linhas indentadas dentro do f-string — a renderização markdown do
        # Streamlit interpreta 4+ espaços de indentação como bloco de código
        # `<pre>`, e o HTML aparece literal. Aprendido na carne em maio/2026.
        _right_chip = (
            f'<span style="display:flex;gap:8px;align-items:center;">'
            f'{_horas_chip}'
            f'<span title="{d["data"]}">{_tempo_relativo(d["data"])}</span>'
            f'</span>'
        )

        st.markdown(f"""
            {_wrap_pre}
            <div style="background-color:{cor_topo};color:white; padding:12px 15px;border-radius:10px 10px 0 0;margin-top:10px;">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;font-size:10px;text-transform:uppercase;letter-spacing:1px;">
                <span style="background:rgba(0,0,0,0.3);padding:2px 8px;border-radius:4px;">{tag}</span>{_right_chip}
            </div>
            <div style="font-size:16px;font-weight:700;margin-top:6px;">
                {d['disciplina'] if d['disciplina'] else 'Geral'}
            </div>
            <div style="font-size:11px;opacity:.85;">Por: {d['autor']}</div>
            </div>
            <div style="background:#1E1E1E;color:#EEE;padding:14px 15px;border:1px solid {cor_topo};border-top:none;border-radius:0 0 10px 10px;font-size:13px;line-height:1.6;margin-bottom:4px;">
            {texto_exibicao}
            {f'<div style="margin-top:12px;"><div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:{cor_topo};margin-bottom:4px;">💬 Interações · {_n_interacoes}</div>{_interacoes_html}</div>' if d.get('resposta_gestor') else ''}
            </div>
            {_wrap_post}
        """, unsafe_allow_html=True)

        # ── Barra de comandos dos cards ───────────────────────
        bc1, bc2, bc3, bc4 = st.columns([0.15, 0.15, 0.35, 0.35])

        if isinstance(_anexo, str) and _anexo.strip() and os.path.exists(_anexo):
            with open(_anexo, "rb") as _f:
                bc1.download_button(
                    "📎", _f,
                    file_name=os.path.basename(_anexo),
                    key=f"dl_{d['id']}",
                    width="stretch",
                )

        _pode_del = (perfil == "Gestor" or d.get("autor") == autor_logado)
        if _pode_del:
            if bc2.button("🗑️", key=f"del_{d['id']}",
                          width="stretch", help="Excluir registro"):
                db.excluir_registro_diario(d["id"])
                st.rerun(scope="fragment")

        if bc3.button("✍️ Responder / Interagir", key=f"btn_resp_{d['id']}",
                      width="stretch"):
            _k = f"editor_{d['id']}"
            st.session_state[_k] = not st.session_state.get(_k, False)
            st.rerun(scope="fragment")

        if perfil == "Gestor":
            if not d["resolvido"]:
                if bc4.button("✅ Resolver", key=f"btn_res_{d['id']}",
                              width="stretch"):
                    with db.conectar() as conn:
                        _c = conn.cursor()
                        _c.execute("UPDATE diario SET resolvido=1 WHERE id=%s",
                                   (d["id"],))
                        conn.commit()
                    st.rerun(scope="fragment")
            else:
                if bc4.button("🔓 Reabrir", key=f"btn_reap_{d['id']}",
                              width="stretch"):
                    with db.conectar() as conn:
                        _c = conn.cursor()
                        _c.execute("UPDATE diario SET resolvido=0 WHERE id=%s",
                                   (d["id"],))
                        conn.commit()
                    st.rerun(scope="fragment")

        if st.session_state.get(f"editor_{d['id']}"):
            try:
                lista_usuarios_int = db.listar_usuarios()
            except Exception:
                lista_usuarios_int = list(usuarios_para_render)
            if autor_logado in lista_usuarios_int:
                lista_usuarios_int.remove(autor_logado)

            # Item 5: removido o multiselect "Envolver outras pessoas na
            # interação" — era redundante e só escrevia "(Ref: @X)" no rodapé
            # sem disparar o fluxo real de menção. O "@ Mencionar inline"
            # abaixo é o mecanismo de verdade (acesso + notificação).
            nova_orient = st.text_area(
                "Adicionar resposta/comentário:",
                placeholder="Escreva aqui para continuar o assunto...",
                key=f"area_{d['id']}",
            )

            # @mention popover: insere `@"Nome"` no fim do texto (vai disparar
            # _processar_mencoes_diario quando enviar). É distinto do multiselect
            # acima — aquele só registra "Ref: @X" no rodapé sem disparar fluxo.
            _popover_mencionar(
                text_key=f"area_{d['id']}",
                nomes_disponiveis=lista_usuarios_int,
                label="@ Mencionar inline",
                pop_key=f"pop_men_resp_{d['id']}",
                selecionado_key=f"pop_men_sel_resp_{d['id']}",
                eu_mesmo=autor_logado,
            )

            if st.button("📤 Enviar", key=f"env_{d['id']}",
                         width="stretch"):
                if nova_orient.strip():
                    data_hora = datetime.now().strftime("%d/%m/%Y %H:%M")
                    linha_comentario = (
                        f"[{data_hora}] {autor_logado} "
                        f"({perfil}): {nova_orient.strip()}"
                    )
                    historico_banco = str(d.get("resposta_gestor") or "").strip()
                    texto_final = (
                        f"{historico_banco}\n{linha_comentario}"
                        if historico_banco else linha_comentario
                    )

                    with db.conectar() as conn:
                        _c = conn.cursor()
                        _c.execute(
                            "UPDATE diario SET resposta_gestor=%s WHERE id=%s",
                            (texto_final, d["id"]),
                        )
                        conn.commit()

                    _processar_mencoes_diario(
                        texto=nova_orient, projeto_id=int(d["projeto_id"]),
                        autor=autor_logado, relato_id=int(d["id"]),
                        contexto="resposta_gestor",
                        lista_usuarios=usuarios_para_render,
                    )
                    st.session_state[f"editor_{d['id']}"] = False
                    st.rerun(scope="fragment")
                else:
                    st.warning("Escreva algo antes de enviar.")

    # Limpa o destaque one-shot ao terminar de renderizar (vale pra UMA render)
    if destacar_relato_id is not None:
        st.session_state.pop("_diario_destacar_relato", None)


# ══════════════════════════════════════════════════════════════════════
# UI da view (fora do fragmento)
# ══════════════════════════════════════════════════════════════════════
st.header("📝 Diário de Evolução")

# Ao abrir a aba, marca as menções pendentes como vistas (zera o flag de toast).
# Atenção: NÃO dispensa — dispensar é manual, só com o botão "✕ Fechar".
db.marcar_mencoes_vistas(usuario)

# ── PAINEL PERSISTENTE DE MENÇÕES ──────────────────────────
# Aparece sempre que houver menção pendente. Só some quando o usuário clicar
# em "✕ Fechar" (dispensa). Clicar no card abre o projeto correspondente.
_mencoes_lista = db.listar_mencoes_pendentes(usuario)
if _mencoes_lista:
    with st.container(border=True):
        _hd1, _hd2 = st.columns([4, 1])
        _hd1.markdown(
            f"### 🔔 Você foi mencionado em "
            f"**{len(_mencoes_lista)}** "
            f"{'aviso' if len(_mencoes_lista)==1 else 'avisos'}"
        )
        if _hd2.button(
            "Limpar todos", key="btn_disp_todas_men",
            help="Marca todas as menções como vistas e remove do painel.",
            width="stretch",
        ):
            db.dispensar_todas_mencoes(usuario)
            st.rerun()

        for (mn_id, _proj_id, _proj_nome, _relato_id, _por, _data,
             _ctx, _snippet) in _mencoes_lista:
            _cor_ctx = "#0056b3" if _ctx == "relato" else "#8e44ad"
            _label_ctx = (
                "no relato" if _ctx == "relato"
                else "na resposta do gestor"
            )
            _snip = (_snippet or "").replace("\n", " ").strip()
            if len(_snip) > 120:
                _snip = _snip[:120].rstrip() + "…"

            with st.container(border=True):
                _ca, _cb, _cc = st.columns([0.72, 0.16, 0.12])
                _ca.markdown(
                    f"<div style='line-height:1.45'>"
                    f"<span style='background:{_cor_ctx};color:#fff;"
                    f"padding:1px 8px;border-radius:6px;font-size:0.72rem;"
                    f"font-weight:600;text-transform:uppercase;"
                    f"letter-spacing:0.4px'>{_label_ctx}</span> &nbsp; "
                    f"<b>{_por}</b> em <b>📂 "
                    f"{_proj_nome or f'projeto #{_proj_id}'}</b>"
                    f"<br><span style='font-size:0.78rem;opacity:0.75'>"
                    f"{_tempo_relativo(_data)}</span>"
                    + (
                        f"<div style='margin-top:6px;font-size:0.88rem;"
                        f"opacity:0.85;font-style:italic'>"
                        f"“{_snip}”</div>" if _snip else ""
                    )
                    + "</div>",
                    unsafe_allow_html=True,
                )
                if _cb.button(
                    "Ver", key=f"men_ver_{mn_id}",
                    width="stretch",
                    help="Abre o projeto e o relato correspondente abaixo.",
                ):
                    st.session_state["_diario_abrir_proj"] = int(_proj_id)
                    st.session_state["_diario_destacar_relato"] = (
                        int(_relato_id) if _relato_id else None
                    )
                    st.rerun()
                if _cc.button(
                    "✕", key=f"men_disp_{mn_id}",
                    width="stretch",
                    help="Marca como visto e remove do painel.",
                ):
                    db.dispensar_mencao(mn_id)
                    st.rerun()
    st.divider()

# ── Mapa de não lidos por projeto ────────────────────────────
_mapa_nao_lidos = db.contar_nao_lidos_diario(usuario)

# ── HORAS REGISTRADAS (time tracking) ────────────────────────
# Agregação simples: hoje / semana / mês × minhas / equipe inteira +
# top 5 projetos do mês. Campo `horas` no diário é REAL; relatos sem
# horas (=0 ou NULL) ficam de fora.
with st.expander("⏱ Horas registradas", expanded=False):
    try:
        _df_h = pd.read_sql_query(
            """SELECT d.projeto_id, p.projeto, d.autor,
                      COALESCE(d.horas, 0) AS horas, d.data
               FROM diario d
               LEFT JOIN projetos p ON p.id = d.projeto_id
               WHERE COALESCE(d.horas, 0) > 0""",
            db.get_engine(),
        )
        # `data` é TEXT em "DD/MM/YYYY HH:MM" — parse aqui no pandas.
        _df_h["dt"] = pd.to_datetime(
            _df_h["data"], format="%d/%m/%Y %H:%M", errors="coerce",
        )
        _df_h = _df_h.dropna(subset=["dt"])
    except Exception as exc:
        erro_humano(
            "Carregar histórico de horas", exc,
            sugestao=(
                "Os totais de horas voltarão na próxima vez que você abrir "
                "o Diário. O resto da página continua funcionando normalmente."
            ),
        )
        _df_h = pd.DataFrame(
            columns=["projeto_id", "projeto", "autor", "horas", "dt"]
        )

    if _df_h.empty:
        st.info(
            "Nenhum relato com horas registradas ainda. Preencha o campo "
            "**⏱ Horas** ao criar um novo relato pra começar a acompanhar."
        )
    else:
        _agora = datetime.now()
        _ini_dia = _agora.replace(hour=0, minute=0, second=0, microsecond=0)
        _ini_sem = _ini_dia - pd.Timedelta(days=_agora.weekday())  # seg=0
        _ini_mes = _ini_dia.replace(day=1)

        def _soma(df, ini):
            return float(df[df["dt"] >= ini]["horas"].sum())

        _minha = _df_h[_df_h["autor"] == usuario]
        cA, cB, cC = st.columns(3)
        cA.metric("Hoje (minhas / equipe)",
                  f"{_soma(_minha, _ini_dia):.1f} h",
                  f"equipe: {_soma(_df_h, _ini_dia):.1f} h")
        cB.metric("Semana (minhas / equipe)",
                  f"{_soma(_minha, _ini_sem):.1f} h",
                  f"equipe: {_soma(_df_h, _ini_sem):.1f} h")
        cC.metric("Mês (minhas / equipe)",
                  f"{_soma(_minha, _ini_mes):.1f} h",
                  f"equipe: {_soma(_df_h, _ini_mes):.1f} h")

        # Top projetos do mês (equipe)
        _df_mes = _df_h[_df_h["dt"] >= _ini_mes]
        if not _df_mes.empty:
            _top_p = (
                _df_mes.groupby("projeto", dropna=False)["horas"]
                .sum().sort_values(ascending=False).head(5)
            )
            if not _top_p.empty:
                st.markdown(
                    "**🏆 Top projetos no mês** (horas totais da equipe)"
                )
                for _nome_p, _h in _top_p.items():
                    _nome_p = _nome_p if _nome_p else "(sem projeto)"
                    st.markdown(f"- **{_nome_p}** — {_h:.1f} h")

        # Breakdown por projetista no mês (só se há >1 autor)
        _aut_mes = (
            _df_mes.groupby("autor")["horas"]
            .sum().sort_values(ascending=False)
        )
        if len(_aut_mes) > 1:
            st.markdown("**👥 Horas por projetista no mês**")
            for _aut, _h in _aut_mes.items():
                st.markdown(f"- **{_aut}** — {_h:.1f} h")

# ── 1. FORMULÁRIO DE NOVO REGISTRO ───────────────────────────
if _pode_editar():
    with st.expander("➕ Novo Relato, Dúvida ou Impedimento", expanded=False):
        _proj_opts = df_p["projeto"].tolist() if not df_p.empty else ["-"]
        p_sel = st.selectbox("Projeto", _proj_opts, key="diario_proj_sel")

        c_d1, c_d2 = st.columns(2)
        tipo_relato = c_d1.selectbox(
            "Tipo",
            ["Relato de Atividade", "❓ Dúvida Técnica", "🛑 Impedimento"],
            key="diario_tipo",
        )
        lista_disc = st.session_state.get(
            "lista_checklist", ["Geral", "Elétrica", "HVAC", "Hidráulica"],
        )
        r_disc = c_d2.selectbox("Disciplina", lista_disc, key="diario_disc")

        r_rel = st.text_area("Descrição do Relato", key="diario_texto")

        # Popover @mention: appenda `@"Nome"` no fim do texto.
        _popover_mencionar(
            text_key="diario_texto",
            nomes_disponiveis=df_u["nome"].tolist() if not df_u.empty else [],
            label="@ Mencionar alguém da equipe",
            pop_key="pop_men_novo_relato",
            selecionado_key="pop_men_sel_novo_relato",
            eu_mesmo=usuario,
        )

        c_h, c_a = st.columns([1, 3])
        r_horas = c_h.number_input(
            "⏱ Horas",
            min_value=0.0, max_value=24.0, step=0.25, value=0.0,
            format="%.2f",
            key="diario_horas",
            help=(
                "Tempo dedicado a este relato (em horas, frações OK). "
                "0 = não preenchido."
            ),
        )
        r_arq = c_a.file_uploader(
            "Anexo (Opcional)",
            type=["pdf", "png", "jpg", "dwg", "zip"],
            key="diario_upload",
        )

        if st.button("💾 Salvar Registro", width="stretch",
                     key="diario_salvar"):
            if r_rel and p_sel != "-":
                try:
                    with carregando(
                        "Salvando anexo..." if r_arq else "Salvando relato..."
                    ):
                        path = ""
                        if r_arq:
                            if not os.path.exists("anexos"):
                                os.makedirs("anexos")
                            path = os.path.join(
                                "anexos",
                                f"{datetime.now().strftime('%Y%m%d%H%M')}_"
                                f"{r_arq.name}",
                            )
                            with open(path, "wb") as f:
                                f.write(r_arq.getbuffer())

                        info_p = df_p[df_p["projeto"] == p_sel].iloc[0]
                        pid = info_p["id"]

                        texto_final_banco = f"[{tipo_relato}] {r_rel}"

                        with db.conectar() as conn:
                            c = conn.cursor()
                            c.execute(
                                """INSERT INTO diario
                                (projeto_id, data, executado, autor,
                                 disciplina, horas, anexo, resolvido)
                                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                                RETURNING id""",
                                (int(pid),
                                 datetime.now().strftime("%d/%m/%Y %H:%M"),
                                 texto_final_banco,
                                 usuario, r_disc,
                                 float(r_horas or 0),
                                 path, 0),
                            )
                            _novo_relato_id = c.fetchone()[0]
                            conn.commit()

                        # Processa @"Nome" do texto: concede acesso +
                        # notifica + audita
                        _processar_mencoes_diario(
                            texto=r_rel, projeto_id=int(pid),
                            autor=usuario, relato_id=_novo_relato_id,
                            contexto="relato",
                            lista_usuarios=(
                                df_u["nome"].tolist() if not df_u.empty
                                else []
                            ),
                        )

                    _invalidar_dados()
                    confirmar_sucesso("Registro salvo",
                                      "Seu relato foi adicionado ao diário.")
                    st.rerun()
                except Exception as exc:
                    erro_humano(
                        "Salvar relato no diário", exc,
                        sugestao=(
                            "Tente novamente. Se você anexou arquivo, "
                            "confira se ele cabe em 100 MB e não está "
                            "corrompido."
                        ),
                    )
            else:
                st.warning("Selecione um projeto e escreva o relato.")

    st.divider()

# ── RELATÓRIO PDF ───────────────────────────────────────────
st.markdown("#### 📤 Gerar Relatório do Diário por Projeto")
_projs_diario = df_p["projeto"].tolist() if not df_p.empty else []
_col_rp1, _col_rp2 = st.columns([3, 1])
_proj_rel_sel = _col_rp1.selectbox(
    "Selecionar projeto para relatório:",
    options=["— Selecione —"] + _projs_diario,
    key="diario_rel_proj",
    label_visibility="collapsed",
)

if _col_rp2.button("📄 Gerar PDF", key="btn_gerar_rel_diario",
                   width="stretch"):
    if _proj_rel_sel != "— Selecione —":
        _proj_info = df_p[df_p["projeto"] == _proj_rel_sel]
        if not _proj_info.empty:
            _pid_rel = int(_proj_info.iloc[0]["id"])
            _d_diario = (
                df_d[df_d["projeto_id"] == _pid_rel] if not df_d.empty
                else pd.DataFrame()
            )
            try:
                with carregando(
                    f"Gerando PDF do diário de '{_proj_rel_sel}'..."
                ):
                    _pdf_diario = relatorios.gerar_pdf_diario(
                        _proj_info.iloc[0].to_dict(), _d_diario,
                    )
                st.session_state["_pdf_diario_bytes"] = _pdf_diario
                st.session_state["_pdf_diario_nome"] = _proj_rel_sel
                st.rerun()
            except Exception as exc:
                erro_humano(
                    f"Geração do PDF do diário de '{_proj_rel_sel}'", exc,
                    sugestao=(
                        "Tente de novo em alguns segundos. Se persistir, "
                        "confira se há relatos com caracteres incomuns."
                    ),
                )
    else:
        st.warning("Selecione um projeto antes de gerar.")

if st.session_state.get("_pdf_diario_bytes"):
    _nome_arq = st.session_state.get("_pdf_diario_nome", "projeto")
    _nome_arq_safe = "".join(
        c if c.isalnum() or c in " _-" else "_" for c in _nome_arq
    )[:40]

    st.download_button(
        label=f"⬇️ Baixar PDF — {st.session_state['_pdf_diario_nome']}",
        data=st.session_state["_pdf_diario_bytes"],
        file_name=(
            f"diario_{_nome_arq_safe}_"
            f"{datetime.now().strftime('%d%m%Y')}.pdf"
        ),
        mime="application/pdf",
        width="stretch",
        key="dl_pdf_diario",
    )
    if st.button("✖ Limpar", key="limpar_pdf_diario"):
        st.session_state.pop("_pdf_diario_bytes", None)
        st.session_state.pop("_pdf_diario_nome", None)
        st.rerun()

st.divider()

# ── 2. AGRUPAMENTO POR PROJETO (CARDS) ───────────────────────
if df_d.empty or df_p.empty:
    st.info("📭 Nenhum registro no diário ainda.")
else:
    _proj_ids_com_diario = df_d["projeto_id"].unique().tolist()
    _projetos_diario = df_p[df_p["id"].isin(_proj_ids_com_diario)].copy()

    if _projetos_diario.empty:
        st.info("📭 Nenhum registro no diário ainda.")
    else:
        _f1, _f2 = st.columns([3, 1])
        _busca_diario = _f1.text_input(
            "🔍 Buscar em todos os registros",
            placeholder="palavra-chave, autor, disciplina, menções (@)...",
            key="diario_busca",
        )
        _so_pendentes = _f2.checkbox("Só pendências", key="diario_so_pend")

        for _, proj_row in _projetos_diario.iterrows():
            proj_id = int(proj_row["id"])
            proj_nome = str(proj_row["projeto"])

            df_proj_d = df_d[df_d["projeto_id"] == proj_id].copy()
            df_proj_d = df_proj_d.sort_values("id", ascending=False)

            # Busca também olha 'resposta_gestor' (onde ficam as interações)
            if _busca_diario.strip():
                t = _busca_diario.lower()
                df_proj_d = df_proj_d[
                    df_proj_d["executado"].astype(str).str.lower().str.contains(t, na=False)
                    | df_proj_d["autor"].astype(str).str.lower().str.contains(t, na=False)
                    | df_proj_d["disciplina"].astype(str).str.lower().str.contains(t, na=False)
                    | df_proj_d["resposta_gestor"].astype(str).str.lower().str.contains(t, na=False)
                ]
            if _so_pendentes:
                df_proj_d = df_proj_d[df_proj_d["resolvido"] == 0]

            if df_proj_d.empty:
                continue

            _nao_lidos_proj = _mapa_nao_lidos.get(proj_id, 0)
            _pendentes_proj = len(df_proj_d[df_proj_d["resolvido"] == 0])
            _total_proj = len(df_proj_d)

            _label_exp = (
                f"📁 {proj_nome}  "
                f"({_total_proj} registro{'s' if _total_proj != 1 else ''})"
            )
            if _nao_lidos_proj:
                _label_exp += (
                    f"  🔴 {_nao_lidos_proj} "
                    f"não lido{'s' if _nao_lidos_proj != 1 else ''}"
                )
            if _pendentes_proj:
                _label_exp += (
                    f"  ⚠️ {_pendentes_proj} "
                    f"pendente{'s' if _pendentes_proj != 1 else ''}"
                )

            # Inteligência visual: abre a pasta do projeto automaticamente se:
            #  1) tiver relato não lido, OU
            #  2) tiver menção @ pendente (sistema antigo, no resposta_gestor), OU
            #  3) user clicou "Ver" numa menção no painel persistente
            usuario_mencionado = f"@{usuario}".lower()
            tem_mencao_ativa = (
                df_proj_d["resposta_gestor"].astype(str).str.lower()
                .str.contains(usuario_mencionado, na=False).any()
            )
            _forcou_abrir = (
                st.session_state.get("_diario_abrir_proj") == proj_id
            )
            _abrir = bool(
                _nao_lidos_proj > 0 or tem_mencao_ativa or _forcou_abrir
            )
            # Consome os flags one-shot do painel de menções
            if _forcou_abrir:
                st.session_state.pop("_diario_abrir_proj", None)
                _consumir_destaque_depois = True
            else:
                _consumir_destaque_depois = False

            with st.expander(_label_exp, expanded=_abrir):
                if _nao_lidos_proj:
                    db.marcar_projeto_diario_lido(proj_id, usuario)
                    _mapa_nao_lidos[proj_id] = 0

                # Render dos relatos via fragmento (mantém scroll do usuário
                # ao excluir/resolver/responder, em vez de voltar pro topo).
                # Passa proj_id + filtros; o fragmento re-consulta o banco.
                _render_relatos_proj(
                    proj_id=proj_id,
                    busca=_busca_diario,
                    so_pendentes=_so_pendentes,
                    usuarios_para_render=(
                        df_u["nome"].tolist() if not df_u.empty else []
                    ),
                    autor_logado=usuario,
                    perfil=perfil,
                    destacar_relato_id=(
                        st.session_state.get("_diario_destacar_relato")
                        if _consumir_destaque_depois else None
                    ),
                )

                st.markdown("<br>", unsafe_allow_html=True)
