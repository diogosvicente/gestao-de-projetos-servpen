"""Aba Agenda — calendário com 4 visões (Mensal, Semanal, Lista, Resumo).

Inclui métricas no topo, exportação .ics (RFC 5545), formulário de
cadastro/edição e tabela completa com filtros. Visibilidade respeita perfil
(Gestor vê tudo, outros só os seus).

`_gerar_ics` é helper local — só usado aqui.
"""

from __future__ import annotations

import calendar as _cal
import uuid
from datetime import datetime

import pandas as pd
import streamlit as st

import database as db

from core.data import _load_df_u
from core.helpers import _empty_state, _equipe_atual, _pill_select, _ve_tudo
from core.ui_feedback import carregando


usuario_atual = st.session_state.get("usuario", "")
perfil_atual = st.session_state.get("perfil", "Colaborador")
df_u = _load_df_u()


# ══════════════════════════════════════════════════════════════════════
# HELPER LOCAL: gerar .ics (RFC 5545) pra exportar agenda
# ══════════════════════════════════════════════════════════════════════
def _gerar_ics(df_eventos):
    """Gera conteúdo .ics a partir de DataFrame de eventos.

    Colunas esperadas: titulo, tipo, data_inicio, data_fim, responsaveis,
    descricao.
    """
    linhas = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//SERVPEN//Gestao de Projetos//PT-BR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Agenda SERVPEN",
    ]

    def _fmt(d):
        if pd.isna(d):
            return ""
        try:
            dt = pd.to_datetime(d)
            return dt.strftime("%Y%m%d")
        except Exception:
            return ""

    def _esc(s):
        return (str(s or "")
                .replace("\\", "\\\\").replace(";", "\\;")
                .replace(",", "\\,").replace("\n", "\\n"))

    for _, ev in df_eventos.iterrows():
        d_ini = _fmt(ev.get("data_inicio"))
        d_fim = _fmt(ev.get("data_fim"))
        if not d_ini:
            continue
        # All-day event (DTEND é exclusivo no .ics → soma 1 dia)
        if d_fim:
            try:
                d_fim_excl = (
                    pd.to_datetime(ev["data_fim"]) + pd.Timedelta(days=1)
                ).strftime("%Y%m%d")
            except Exception:
                d_fim_excl = d_ini
        else:
            d_fim_excl = d_ini
        linhas += [
            "BEGIN:VEVENT",
            f"UID:{uuid.uuid4()}@servpen",
            f"DTSTAMP:{datetime.now().strftime('%Y%m%dT%H%M%SZ')}",
            f"DTSTART;VALUE=DATE:{d_ini}",
            f"DTEND;VALUE=DATE:{d_fim_excl}",
            f"SUMMARY:{_esc(ev.get('tipo',''))} - {_esc(ev.get('titulo',''))}",
            f"DESCRIPTION:Envolvidos: {_esc(ev.get('responsaveis',''))}\\n"
            f"{_esc(ev.get('descricao',''))}",
            "END:VEVENT",
        ]
    linhas.append("END:VCALENDAR")
    return "\r\n".join(linhas).encode("utf-8")


# ══════════════════════════════════════════════════════════════════════
# UI principal
# ══════════════════════════════════════════════════════════════════════
st.header("📅 Agenda e Disponibilidade")

# ── recarrega agenda do banco único ──────────────────────────
try:
    df_agenda = pd.read_sql(
        "SELECT * FROM agenda ORDER BY data_inicio ASC",
        db.get_engine(),
    )
except Exception:
    df_agenda = pd.DataFrame(
        columns=["id", "titulo", "tipo", "data_inicio", "data_fim",
                 "responsaveis", "descricao", "local"]
    )

# ── VISIBILIDADE POR EQUIPE ───────────────────────────────────
# Quem o usuário pode ver na agenda (via `responsaveis`, CSV de nomes):
#   - Gestor Geral .......... TUDO (sem filtro).
#   - Líder SERVPEN/SERVPAR .. eventos de projetistas da sua equipe.
#   - Projetista/Visualizador  só os próprios eventos (regra antiga).
# `_nomes_agenda = None` significa "vê tudo".
if _ve_tudo():
    _nomes_agenda = None
elif perfil_atual == "Gestor":
    _nomes_agenda = db.nomes_por_equipe(_equipe_atual())
else:
    _nomes_agenda = {usuario_atual}


def _agenda_mask(df):
    """Máscara booleana: True nas linhas cujo `responsaveis` intersecta os
    nomes visíveis. Compara por CONJUNTO de nomes (split por vírgula +
    strip) — evita o falso-positivo de substring ('Ana' em 'Mariana').
    Se `_nomes_agenda is None`, tudo visível."""
    if _nomes_agenda is None or df.empty:
        return pd.Series(True, index=df.index)
    return df["responsaveis"].apply(
        lambda v: bool(
            {n.strip() for n in str(v).split(",") if n.strip()}
            & _nomes_agenda
        )
    )

# ── MÉTRICAS NO TOPO (4 cards) ────────────────────────────────
_hoje_ag = datetime.now().date()
_limite_7d_ag = _hoje_ag + pd.Timedelta(days=7)
_ini_mes_ag = _hoje_ag.replace(day=1)
_fim_mes_ag = _hoje_ag.replace(
    day=_cal.monthrange(_hoje_ag.year, _hoje_ag.month)[1]
)

_df_ag_visivel = df_agenda.copy() if not df_agenda.empty else df_agenda
if not _df_ag_visivel.empty:
    _df_ag_visivel["_di"] = pd.to_datetime(
        _df_ag_visivel["data_inicio"], errors="coerce",
    ).dt.date
    _df_ag_visivel["_df"] = pd.to_datetime(
        _df_ag_visivel["data_fim"], errors="coerce",
    ).dt.date
    _df_ag_visivel = _df_ag_visivel[_agenda_mask(_df_ag_visivel)]


def _toca_janela(row, ini, fim):
    di, df_ = row.get("_di"), row.get("_df") or row.get("_di")
    return (di is not None and df_ is not None
            and df_ >= ini and di <= fim)


if _df_ag_visivel.empty:
    _qtd_7d = _qtd_visitas_mes = _qtd_ausentes_hoje = _qtd_total_mes = 0
else:
    _qtd_7d = int(_df_ag_visivel.apply(
        lambda r: _toca_janela(r, _hoje_ag, _limite_7d_ag), axis=1,
    ).sum())
    _qtd_visitas_mes = int(((_df_ag_visivel["tipo"] == "Visita Técnica")
        & _df_ag_visivel.apply(
            lambda r: _toca_janela(r, _ini_mes_ag, _fim_mes_ag), axis=1,
        )).sum())
    _qtd_ausentes_hoje = int((
        _df_ag_visivel["tipo"].isin(["Férias", "Licença", "Folga"])
        & _df_ag_visivel.apply(
            lambda r: _toca_janela(r, _hoje_ag, _hoje_ag), axis=1,
        )
    ).sum())
    _qtd_total_mes = int(_df_ag_visivel.apply(
        lambda r: _toca_janela(r, _ini_mes_ag, _fim_mes_ag), axis=1,
    ).sum())

m1, m2, m3, m4 = st.columns(4)
m1.metric("📌 Próximos 7 dias", _qtd_7d,
          help="Eventos que tocam a janela de hoje até hoje+7d.")
m2.metric("🏗️ Visitas no mês", _qtd_visitas_mes,
          help="Eventos do tipo Visita Técnica neste mês.")
m3.metric("🏖️ Ausentes hoje", _qtd_ausentes_hoje,
          delta="férias/licença/folga", delta_color="off",
          help=(
              "Membros em ausência registrada (Férias/Licença/Folga) hoje."
          ))
m4.metric("📅 Total no mês", _qtd_total_mes,
          help="Todos os compromissos que tocam o mês atual.")

st.divider()

# ── TOGGLE DE VISÃO ──────────────────────────────────────────
visao_ag = _pill_select(
    st, "Visão da Agenda",
    options=["Mensal", "Semanal", "Lista", "Resumo"],
    default="Mensal",
    key="agenda_visao",
    label_visibility="collapsed",
) or "Mensal"

# ── exportar .ics ─────────────────────────────────────────────
if not df_agenda.empty:
    df_exp = df_agenda[_agenda_mask(df_agenda)]
    leg = (
        "(todos os eventos)" if _nomes_agenda is None
        else "(da sua equipe)" if perfil_atual == "Gestor"
        else "(somente os seus)"
    )
    if not df_exp.empty:
        st.download_button(
            f"📥 Exportar agenda .ics {leg}",
            data=_gerar_ics(df_exp),
            file_name=(
                f"agenda_servpen_{datetime.now().strftime('%Y%m%d')}.ics"
            ),
            mime="text/calendar",
        )

st.divider()

# ════════════════════════════════════════════════════════════
#  LAYOUT PRINCIPAL: visão escolhida (esq) | cadastro (dir)
# ════════════════════════════════════════════════════════════
col_cal, col_form = st.columns([2, 1], gap="large")

# Paleta unificada
TIPO_COR = {
    "Visita Técnica": "#2563eb",
    "Reunião":        "#7c3aed",
    "Férias":         "#059669",
    "Licença":        "#d97706",
    "Folga":          "#6b7280",
}
TIPO_ICONE = {
    "Visita Técnica": "🏗️", "Reunião": "🤝",
    "Férias": "🏖️", "Licença": "🏥", "Folga": "😴",
}

with col_cal:
    if visao_ag == "Mensal":
        st.subheader("🗓️ Calendário do Mês")

        if "agenda_ano" not in st.session_state:
            st.session_state.agenda_ano = datetime.now().year
        if "agenda_mes" not in st.session_state:
            st.session_state.agenda_mes = datetime.now().month

        nav1, nav2, nav3 = st.columns([1, 2, 1])
        if nav1.button("◀ Anterior", use_container_width=True,
                       key="cal_prev"):
            if st.session_state.agenda_mes == 1:
                st.session_state.agenda_mes = 12
                st.session_state.agenda_ano -= 1
            else:
                st.session_state.agenda_mes -= 1
        if nav3.button("Próximo ▶", use_container_width=True,
                       key="cal_next"):
            if st.session_state.agenda_mes == 12:
                st.session_state.agenda_mes = 1
                st.session_state.agenda_ano += 1
            else:
                st.session_state.agenda_mes += 1

        ano_atual = st.session_state.agenda_ano
        mes_atual = st.session_state.agenda_mes
        MESES_PT = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio",
                    "Junho", "Julho", "Agosto", "Setembro", "Outubro",
                    "Novembro", "Dezembro"]
        nav2.markdown(
            f"<h3 style='text-align:center;margin:0;padding:6px 0;'>"
            f"{MESES_PT[mes_atual]} {ano_atual}</h3>",
            unsafe_allow_html=True,
        )

        # Monta mapa: dia → lista de eventos
        eventos_mes: dict = {}
        if not df_agenda.empty:
            df_tmp = df_agenda.copy()
            df_tmp["di"] = pd.to_datetime(df_tmp["data_inicio"], errors="coerce")
            df_tmp["df"] = pd.to_datetime(df_tmp["data_fim"], errors="coerce")
            df_tmp = df_tmp[_agenda_mask(df_tmp)]   # isolamento por equipe
            for _, ev in df_tmp.iterrows():
                if pd.isna(ev["di"]):
                    continue
                d = ev["di"].date()
                fim = ev["df"].date() if not pd.isna(ev["df"]) else d
                cur = d
                while cur <= fim:
                    if cur.year == ano_atual and cur.month == mes_atual:
                        eventos_mes.setdefault(cur.day, []).append(ev)
                    cur += pd.Timedelta(days=1)

        primeiro_dia, total_dias = _cal.monthrange(ano_atual, mes_atual)
        hoje = datetime.now().date()

        # IMPORTANTE: `table-layout: fixed` força colunas de largura igual
        # (1/7 cada). Sem isso, a tabela usa auto-layout e pills com
        # `display:block; nowrap` esticam a coluna pra caber o texto —
        # resultado: pill "Visita Técnica - Sondagem" estourava a coluna
        # SÁB e invadia a coluna do formulário "Novo Compromisso" à direita.
        # `overflow:hidden` no td é defesa extra: clipa qualquer filho que
        # tente sair (ex: pill com max-width quebrado em browser antigo).
        html_cal = """
        <style>
        .srv-cal { width:100%; table-layout:fixed;
                   border-collapse:separate; border-spacing:3px;
                   font-family:'Segoe UI',sans-serif; }
        .srv-cal th { background:#1e3a5f; color:#93c5fd; font-size:.75rem;
                      font-weight:600; letter-spacing:1px;
                      padding:8px 4px; border-radius:4px; text-align:center;
                      width:14.28%; }
        .srv-cal td { vertical-align:top; background:rgba(255,255,255,0.03);
                      border:1px solid rgba(255,255,255,0.06);
                      border-radius:6px; padding:4px; min-height:72px;
                      width:14.28%; overflow:hidden; }
        .srv-cal td.hoje { border:2px solid #3b82f6 !important;
                           background:rgba(59,130,246,0.08); }
        .srv-cal td.vazio { background:transparent; border:none; }
        .dia-num { font-size:.8rem; font-weight:700; color:#94a3b8;
                   margin-bottom:3px; }
        .dia-num.hoje-num { color:#60a5fa; font-size:.9rem; }
        .ev-pill { font-size:.65rem; font-weight:600; color:#fff;
                   padding:1px 5px; border-radius:10px; margin-bottom:2px;
                   white-space:nowrap; overflow:hidden;
                   text-overflow:ellipsis; display:block;
                   max-width:100%; box-sizing:border-box; }
        </style>
        <table class="srv-cal"><thead><tr>
        <th>DOM</th><th>SEG</th><th>TER</th><th>QUA</th>
        <th>QUI</th><th>SEX</th><th>SÁB</th>
        </tr></thead><tbody><tr>
        """
        # dias em branco antes do dia 1 (semana começa domingo: offset+1)
        offset = (primeiro_dia + 1) % 7
        for _ in range(offset):
            html_cal += "<td class='vazio'></td>"

        dia_semana = offset
        for dia in range(1, total_dias + 1):
            data_dia = datetime(ano_atual, mes_atual, dia).date()
            is_hoje = (data_dia == hoje)
            cls_td = "hoje" if is_hoje else ""
            html_cal += f"<td class='{cls_td}'>"
            html_cal += (
                f"<div class='dia-num "
                f"{'hoje-num' if is_hoje else ''}'>{dia}</div>"
            )

            for ev in eventos_mes.get(dia, []):
                cor = TIPO_COR.get(str(ev.get("tipo", "")), "#475569")
                titulo_curto = str(ev.get("titulo", ""))[:18]
                html_cal += (
                    f"<span class='ev-pill' style='background:{cor}' "
                    f"title=\"{ev.get('tipo','')} — "
                    f"{ev.get('titulo','')} | "
                    f"{ev.get('responsaveis','')}\">⬤ {titulo_curto}</span>"
                )

            html_cal += "</td>"
            dia_semana += 1
            if dia_semana % 7 == 0 and dia < total_dias:
                html_cal += "</tr><tr>"

        restante = 6 - ((dia_semana - 1) % 7)
        if restante < 6:
            for _ in range(restante):
                html_cal += "<td class='vazio'></td>"

        html_cal += "</tr></tbody></table>"
        st.markdown(html_cal, unsafe_allow_html=True)

        # Legenda de cores
        st.markdown(
            "<div style='display:flex;gap:12px;flex-wrap:wrap;"
            "margin-top:8px;font-size:.75rem;'>"
            + "".join([
                f"<span style='display:flex;align-items:center;gap:4px;'>"
                f"<span style='width:10px;height:10px;background:{c};"
                f"border-radius:50%;display:inline-block'></span>"
                f"<span style='color:#94a3b8'>{t}</span></span>"
                for t, c in TIPO_COR.items()
            ])
            + "</div>",
            unsafe_allow_html=True,
        )

    # ─────────── VISÃO SEMANAL ───────────────────────────────
    elif visao_ag == "Semanal":
        st.subheader("📆 Semana")
        if "agenda_semana_offset" not in st.session_state:
            st.session_state.agenda_semana_offset = 0

        navs1, navs2, navs3 = st.columns([1, 2, 1])
        if navs1.button("◀ Anterior", key="sem_prev",
                        use_container_width=True):
            st.session_state.agenda_semana_offset -= 1
        if navs3.button("Próxima ▶", key="sem_next",
                        use_container_width=True):
            st.session_state.agenda_semana_offset += 1
        if navs2.button("Hoje", key="sem_hoje",
                        use_container_width=True):
            st.session_state.agenda_semana_offset = 0

        _hoje_sem = datetime.now().date()
        # semana começa no domingo (igual o calendário mensal)
        _dia_sem_hoje = (_hoje_sem.weekday() + 1) % 7
        _ini_sem = (
            _hoje_sem - pd.Timedelta(days=_dia_sem_hoje)
            + pd.Timedelta(weeks=st.session_state.agenda_semana_offset)
        )
        _fim_sem = _ini_sem + pd.Timedelta(days=6)

        st.markdown(
            f"<div style='text-align:center;color:#94a3b8;font-size:.9rem;"
            f"margin:6px 0 12px;'>"
            f"<b>{_ini_sem.strftime('%d/%m')}</b> a "
            f"<b>{_fim_sem.strftime('%d/%m/%Y')}</b></div>",
            unsafe_allow_html=True,
        )

        # Filtra eventos da semana visíveis
        if not _df_ag_visivel.empty:
            _df_sem = _df_ag_visivel[
                _df_ag_visivel.apply(
                    lambda r: _toca_janela(
                        r,
                        _ini_sem.date() if hasattr(_ini_sem, "date") else _ini_sem,
                        _fim_sem.date() if hasattr(_fim_sem, "date") else _fim_sem,
                    ),
                    axis=1,
                )
            ].copy()
        else:
            _df_sem = pd.DataFrame()

        NOMES_DIA = ["DOM", "SEG", "TER", "QUA", "QUI", "SEX", "SÁB"]
        _MAX_CHIPS_DIA = 3   # acima disso vira "+N"

        _ev_por_dia: dict = {}
        if not _df_sem.empty:
            for _i_d in range(7):
                _data_d = (
                    (_ini_sem + pd.Timedelta(days=_i_d)).date()
                    if hasattr(_ini_sem, "date")
                    else _ini_sem + pd.Timedelta(days=_i_d)
                )
                _ev_por_dia[_i_d] = [
                    r for _, r in _df_sem.iterrows()
                    if _toca_janela(r, _data_d, _data_d)
                ]

        html_sem = "<style>" \
            ".srv-sem { display:grid; grid-template-columns:repeat(7,1fr); " \
            "  gap:6px; }" \
            ".srv-sem .dia { background:rgba(255,255,255,0.03); border:1px solid " \
            "  rgba(255,255,255,0.06); border-radius:8px; padding:6px; " \
            "  min-height:80px; }" \
            ".srv-sem .dia.hoje { background:rgba(59,130,246,0.10); " \
            "  border:2px solid #3b82f6; }" \
            ".srv-sem .lbl { font-size:.65rem; letter-spacing:1px; color:#93c5fd; " \
            "  text-align:center; font-weight:700; }" \
            ".srv-sem .num { font-size:1rem; text-align:center; font-weight:700; " \
            "  color:#e5e7eb; margin-bottom:4px; }" \
            ".srv-sem .num.hoje { color:#60a5fa; }" \
            ".srv-sem .chip { color:#fff; padding:2px 6px; border-radius:5px; " \
            "  font-size:.65rem; margin-bottom:2px; line-height:1.25; " \
            "  overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }" \
            ".srv-sem .mais { font-size:.6rem; color:#94a3b8; text-align:center; " \
            "  margin-top:2px; }" \
            "</style><div class='srv-sem'>"

        for idx in range(7):
            _data_dia_s = (
                (_ini_sem + pd.Timedelta(days=idx)).date()
                if hasattr(_ini_sem, "date")
                else _ini_sem + pd.Timedelta(days=idx)
            )
            _eh_hoje_s = (_data_dia_s == _hoje_sem)
            _cls_dia = "dia hoje" if _eh_hoje_s else "dia"
            _cls_num = "num hoje" if _eh_hoje_s else "num"

            html_sem += f"<div class='{_cls_dia}'>"
            html_sem += f"<div class='lbl'>{NOMES_DIA[idx]}</div>"
            html_sem += f"<div class='{_cls_num}'>{_data_dia_s.day}</div>"

            _eventos_dia_d = _ev_por_dia.get(idx, [])
            for _ev in _eventos_dia_d[:_MAX_CHIPS_DIA]:
                _cor = TIPO_COR.get(str(_ev.get("tipo", "")), "#475569")
                _ico = TIPO_ICONE.get(str(_ev.get("tipo", "")), "📅")
                _titulo_curto = str(_ev["titulo"])[:18]
                html_sem += (
                    f"<div class='chip' style='background:{_cor}' "
                    f"title=\"{_ev['titulo']} "
                    f"({_ev.get('responsaveis','')})\""
                    f">{_ico} {_titulo_curto}</div>"
                )
            if len(_eventos_dia_d) > _MAX_CHIPS_DIA:
                _extras = len(_eventos_dia_d) - _MAX_CHIPS_DIA
                html_sem += f"<div class='mais'>+{_extras} mais</div>"
            html_sem += "</div>"

        html_sem += "</div>"
        st.markdown(html_sem, unsafe_allow_html=True)

        # Editor da semana: selectbox + botão Abrir, fora da grade
        _todos_ev_semana = []
        for _i_d in range(7):
            _todos_ev_semana.extend(_ev_por_dia.get(_i_d, []))
        # Dedup por id (eventos multi-dia aparecem em vários dias)
        _vistos_sem = set()
        _ev_unicos_sem = []
        for _e in _todos_ev_semana:
            _eid = int(_e["id"])
            if _eid not in _vistos_sem:
                _vistos_sem.add(_eid)
                _ev_unicos_sem.append(_e)

        if _ev_unicos_sem:
            st.markdown("---")
            _ed_c1, _ed_c2 = st.columns([4, 1])
            _opcoes_sem = {
                f"{TIPO_ICONE.get(str(e.get('tipo', '')), '📅')} "
                f"{e['titulo']} "
                f"({e['_di'].strftime('%d/%m') if e['_di'] else '?'})":
                int(e["id"])
                for e in _ev_unicos_sem
            }
            _esc_sem = _ed_c1.selectbox(
                "Editar evento desta semana",
                options=list(_opcoes_sem.keys()),
                key="sem_editar_sel",
                label_visibility="collapsed",
                placeholder="Selecione um evento pra editar...",
            )
            if _ed_c2.button("📝 Abrir", key="sem_editar_btn",
                             use_container_width=True):
                if _esc_sem:
                    st.session_state["agenda_edit_id"] = (
                        _opcoes_sem[_esc_sem]
                    )
                    st.rerun()

    # ─────────── VISÃO LISTA ─────────────────────────────────
    elif visao_ag == "Lista":
        st.subheader("📋 Lista completa")
        st.caption(
            "Use os filtros e a tabela detalhada abaixo (no rodapé desta "
            "aba) pra navegar, editar ou excluir cada compromisso."
        )
        if _df_ag_visivel.empty:
            _empty_state(
                "📅", "Nenhum compromisso cadastrado ainda",
                "Use o formulário ao lado pra agendar a primeira "
                "visita técnica, reunião ou ausência da equipe.",
                cor_borda="#7c3aed",
            )
        else:
            _qtd_futuros = int(_df_ag_visivel.apply(
                lambda r: (
                    r.get("_df", r.get("_di")) >= _hoje_ag
                    if r.get("_di") is not None else False
                ),
                axis=1,
            ).sum())
            st.markdown(
                f"- **{len(_df_ag_visivel)}** compromissos no total "
                f"(filtrados pela sua visibilidade)\n"
                f"- **{_qtd_futuros}** ainda futuros ou em andamento\n"
                f"- **{len(_df_ag_visivel) - _qtd_futuros}** já passaram"
            )

    # ─────────── VISÃO RESUMO (dashboard) ────────────────────
    else:  # Resumo
        st.subheader("📊 Resumo executivo")
        st.markdown(
            "**📌 Próximos compromissos "
            + ("(equipe)" if perfil_atual == "Gestor" else "(seus)")
            + "**"
        )
        if _df_ag_visivel.empty:
            st.info("Sem compromissos.")
        else:
            _df_prox = _df_ag_visivel[
                _df_ag_visivel.apply(
                    lambda r: (r.get("_df") or r.get("_di")) >= _hoje_ag,
                    axis=1,
                )
            ].sort_values("_di").head(5)
            if _df_prox.empty:
                st.info("Sem compromissos futuros.")
            else:
                for _, _ev in _df_prox.iterrows():
                    _di = _ev["_di"]
                    _df_ = _ev["_df"] or _di
                    _dias_ate = (_di - _hoje_ag).days
                    if _dias_ate < 0 and _df_ >= _hoje_ag:
                        _quando = (
                            f"<span style='color:#16a34a;font-weight:600;'>"
                            f"Em curso até {_df_.strftime('%d/%m')}</span>"
                        )
                    elif _dias_ate == 0:
                        _quando = (
                            "<span style='color:#3b82f6;font-weight:600;'>"
                            "Hoje</span>"
                        )
                    elif _dias_ate == 1:
                        _quando = (
                            "<span style='color:#0891b2;'>Amanhã</span>"
                        )
                    else:
                        _quando = f"em {_dias_ate} dias"

                    _cor = TIPO_COR.get(str(_ev.get("tipo", "")), "#475569")
                    _ico = TIPO_ICONE.get(str(_ev.get("tipo", "")), "📅")
                    _periodo = (
                        _di.strftime("%d/%m") if _di == _df_
                        else f"{_di.strftime('%d/%m')}–{_df_.strftime('%d/%m')}"
                    )
                    c_ev1, c_ev2 = st.columns([5, 1], gap="small")
                    # HTML montado em UMA LINHA pra evitar que o markdown do
                    # Streamlit interprete 4+ espaços de indentação como
                    # bloco de código <pre> (faria a tag <span> vazar como
                    # texto literal: "<span style='...'>... </span>" visível).
                    _ev_html = (
                        f"<div style=\"border-left:3px solid {_cor};padding:2px 0 2px 8px;margin:0;line-height:1.35;\">"
                        f"<b>{_ico} {_ev['titulo']}</b> "
                        f"<span style=\"color:#94a3b8;font-size:.78rem;\">· {_quando} "
                        f"<span style=\"opacity:.7;\">({_periodo})</span>"
                        f"</span></div>"
                    )
                    c_ev1.markdown(_ev_html, unsafe_allow_html=True)
                    if c_ev2.button("🔍", key=f"res_ab_{_ev['id']}",
                                    help="Abrir no formulário",
                                    use_container_width=True):
                        st.session_state["agenda_edit_id"] = int(_ev["id"])
                        st.rerun()

        st.divider()

        # Distribuição por tipo no mês atual
        st.markdown("**📊 Compromissos por tipo (este mês)**")
        if not _df_ag_visivel.empty:
            _df_mes_r = _df_ag_visivel[
                _df_ag_visivel.apply(
                    lambda r: _toca_janela(r, _ini_mes_ag, _fim_mes_ag),
                    axis=1,
                )
            ]
            _por_tipo = (
                _df_mes_r.groupby("tipo").size()
                .sort_values(ascending=False)
            )
            if _por_tipo.empty:
                st.caption("Sem dados no mês atual.")
            else:
                for _t, _q in _por_tipo.items():
                    _cor = TIPO_COR.get(str(_t), "#475569")
                    _ico = TIPO_ICONE.get(str(_t), "📅")
                    st.markdown(
                        f"- <span style='background:{_cor};color:#fff;"
                        f"padding:1px 8px;border-radius:8px;"
                        f"font-size:.78rem;'>"
                        f"{_ico} {_t}</span> &nbsp; **{_q}**",
                        unsafe_allow_html=True,
                    )

        st.divider()

        # Top membros mais ocupados (mês)
        if perfil_atual == "Gestor" and not _df_ag_visivel.empty:
            st.markdown("**👥 Membros mais ocupados (mês)**")
            _df_mes_r2 = _df_ag_visivel[
                _df_ag_visivel.apply(
                    lambda r: _toca_janela(r, _ini_mes_ag, _fim_mes_ag),
                    axis=1,
                )
            ]
            _contagem = {}
            for _, _r in _df_mes_r2.iterrows():
                for _nome in str(_r.get("responsaveis", "")).split(","):
                    _n = _nome.strip()
                    if _n:
                        _contagem[_n] = _contagem.get(_n, 0) + 1
            _top = sorted(_contagem.items(), key=lambda x: -x[1])[:5]
            if _top:
                for _n, _q in _top:
                    st.markdown(f"- **{_n}** — {_q} compromisso(s)")
            else:
                st.caption("Sem dados.")

# ── FORMULÁRIO DE CADASTRO / EDIÇÃO ───────────────────────────
with col_form:
    _ed_id = st.session_state.get("agenda_edit_id")
    _ed_row = None
    if _ed_id and not df_agenda.empty:
        _rows = df_agenda[df_agenda["id"] == _ed_id]
        if not _rows.empty:
            _ed_row = _rows.iloc[0]

    _titulo_form = (
        "✏️ Editar Compromisso" if _ed_row is not None
        else "➕ Novo Compromisso"
    )
    st.subheader(_titulo_form)

    # "Envolvidos" lista só gente da própria equipe (Geral vê todas) — pra
    # um líder não criar evento de projetista da outra equipe (que ele nem
    # conseguiria ver depois).
    if df_u.empty:
        equipe_lista = [usuario_atual]
    elif _ve_tudo():
        equipe_lista = df_u["nome"].tolist()
    else:
        equipe_lista = (
            df_u[df_u["equipe"] == _equipe_atual()]["nome"].tolist()
        )

    with st.form("form_agenda_nova", clear_on_submit=True):
        titulo_ev = st.text_input(
            "Título / Motivo",
            value=str(_ed_row["titulo"]) if _ed_row is not None else "",
        )
        _categorias = ["Visita Técnica", "Reunião", "Férias",
                       "Licença", "Folga"]
        tipo_ev = st.selectbox(
            "Categoria",
            _categorias,
            index=(
                _categorias.index(str(_ed_row["tipo"]))
                if _ed_row is not None and str(_ed_row["tipo"]) in _categorias
                else 0
            ),
        )
        local_ev = st.text_input(
            "Local (opcional)",
            value=(
                str(_ed_row.get("local", "")) if _ed_row is not None else ""
            ),
        )

        try:
            _d_ini_def = (
                pd.to_datetime(_ed_row["data_inicio"]).date()
                if _ed_row is not None else datetime.now().date()
            )
            _d_fim_def = (
                pd.to_datetime(_ed_row["data_fim"]).date()
                if _ed_row is not None else datetime.now().date()
            )
        except Exception:
            _d_ini_def = _d_fim_def = datetime.now().date()

        c_d1, c_d2 = st.columns(2)
        d_ini = c_d1.date_input("Início", value=_d_ini_def,
                                format="DD/MM/YYYY")
        d_fim = c_d2.date_input("Término", value=_d_fim_def,
                                format="DD/MM/YYYY")

        _def_resp = (
            [r.strip() for r in str(_ed_row["responsaveis"]).split(",")
             if r.strip() in equipe_lista]
            if _ed_row is not None else []
        )
        resp_ev = st.multiselect("Envolvidos", equipe_lista,
                                 default=_def_resp)

        obs_ev = st.text_area(
            "Observações",
            value=(
                str(_ed_row["descricao"]) if _ed_row is not None else ""
            ),
            height=90,
        )

        cols_btn = st.columns(2)
        submit_ok = cols_btn[0].form_submit_button(
            "💾 Salvar" if _ed_row is not None else "📌 Agendar",
            use_container_width=True,
        )
        submit_cancel = cols_btn[1].form_submit_button(
            "✖ Cancelar", use_container_width=True,
        )

    if submit_cancel and "agenda_edit_id" in st.session_state:
        del st.session_state.agenda_edit_id
        st.rerun()

    if submit_ok:
        if titulo_ev and resp_ev:
            if _ed_row is not None:
                with carregando("Atualizando compromisso..."):
                    db.atualizar_evento(
                        _ed_id, titulo_ev, tipo_ev, d_ini, d_fim,
                        resp_ev, obs_ev, local_ev,
                    )
                    db.log_aud(usuario_atual, "editar", "agenda",
                               _ed_id, titulo_ev)
                    if "agenda_edit_id" in st.session_state:
                        del st.session_state.agenda_edit_id
                st.toast("📅 Compromisso atualizado!", icon="✅")
            else:
                with carregando("Registrando compromisso..."):
                    db.salvar_evento(titulo_ev, tipo_ev, d_ini, d_fim,
                                     resp_ev, obs_ev, local_ev)
                    db.log_aud(usuario_atual, "criar", "agenda", None,
                               titulo_ev)
                st.toast("📅 Compromisso registrado!", icon="✅")
            st.rerun()
        else:
            st.warning("Título e Envolvidos são obrigatórios.")

# ════════════════════════════════════════════════════════════
#  TABELA DE COMPROMISSOS
# ════════════════════════════════════════════════════════════
st.divider()
st.subheader("📋 Compromissos Cadastrados")

# Filtros rápidos
f1, f2, f3 = st.columns([2, 2, 1])
_tipos_disp = (
    ["Todos"] + sorted(df_agenda["tipo"].dropna().unique().tolist())
    if not df_agenda.empty else ["Todos"]
)
filtro_tipo = f1.selectbox("Filtrar por categoria", _tipos_disp,
                            key="ag_ftipo")
filtro_membro = f2.text_input("Filtrar por membro",
                               placeholder="nome...", key="ag_fmembro")
filtro_futuro = f3.checkbox("Só futuros", value=False, key="ag_ffut")

if not df_agenda.empty:
    df_show = df_agenda.copy()
    df_show["data_inicio"] = pd.to_datetime(df_show["data_inicio"],
                                             errors="coerce")
    df_show["data_fim"] = pd.to_datetime(df_show["data_fim"],
                                          errors="coerce")

    if perfil_atual != "Gestor":
        df_show = df_show[
            df_show["responsaveis"].str.contains(usuario_atual, na=False)
        ]
    if filtro_tipo != "Todos":
        df_show = df_show[df_show["tipo"] == filtro_tipo]
    if filtro_membro.strip():
        df_show = df_show[
            df_show["responsaveis"].str.contains(
                filtro_membro.strip(), case=False, na=False,
            )
        ]
    if filtro_futuro:
        df_show = df_show[
            df_show["data_fim"] >= pd.Timestamp(datetime.now().date())
        ]

    df_show = df_show.sort_values("data_inicio")

    if df_show.empty:
        _empty_state(
            "🔍", "Nenhum compromisso encontrado",
            "Tente afrouxar os filtros acima — pelo menos um critério "
            "(categoria / membro / só futuros) está muito restritivo.",
            cor_borda="#d97706",
        )
    else:
        for _, row in df_show.iterrows():
            icone = TIPO_ICONE.get(str(row["tipo"]), "📅")
            cor_tip = TIPO_COR.get(str(row["tipo"]), "#475569")
            ini_str = (
                row["data_inicio"].strftime("%d/%m/%Y")
                if not pd.isna(row["data_inicio"]) else "—"
            )
            fim_str = (
                row["data_fim"].strftime("%d/%m/%Y")
                if not pd.isna(row["data_fim"]) else "—"
            )

            try:
                dur = (
                    row["data_fim"].date() - row["data_inicio"].date()
                ).days + 1
                dur_txt = f"{dur} dia{'s' if dur > 1 else ''}"
            except Exception:
                dur_txt = "—"

            hoje_ts = pd.Timestamp(datetime.now().date())
            em_curso = (
                not pd.isna(row["data_inicio"])
                and not pd.isna(row["data_fim"])
                and row["data_inicio"] <= hoje_ts <= row["data_fim"]
            )
            badge_curso = (
                "<span style='background:#16a34a;color:#fff;font-size:.65rem;"
                "font-weight:700;padding:2px 8px;border-radius:10px;"
                "margin-left:8px;'>EM ANDAMENTO</span>"
                if em_curso else ""
            )

            st.markdown(f"""
            <div style="border:1px solid {cor_tip};border-left:5px solid {cor_tip};
                        border-radius:10px;padding:14px 16px;margin-bottom:8px;
                        background:rgba(255,255,255,0.02);">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:6px;">
                <div>
                <span style="font-size:1rem;font-weight:700;color:#e5e7eb;">
                    {icone} {row['titulo']}{badge_curso}
                </span><br>
                <span style="font-size:.75rem;background:{cor_tip};color:#fff;
                            padding:1px 8px;border-radius:8px;font-weight:600;">
                    {row['tipo']}
                </span>
                </div>
                <div style="text-align:right;font-size:.8rem;color:#94a3b8;">
                📅 {ini_str} → {fim_str}<br>⏱ {dur_txt}
                </div>
            </div>
            <div style="margin-top:10px;display:flex;flex-wrap:wrap;gap:16px;font-size:.82rem;color:#cbd5e1;">
                <span>👥 <b>Envolvidos:</b> {row['responsaveis'] or '—'}</span>
                {"<span>📍 <b>Local:</b> " + str(row.get('local','')) + "</span>" if row.get('local') else ""}
                {"<span>📝 " + str(row['descricao']) + "</span>" if row.get('descricao') else ""}
            </div>
            </div>
            """, unsafe_allow_html=True)

            # Botões de ação
            _pode_mexer = (
                perfil_atual == "Gestor"
                or usuario_atual in str(row.get("responsaveis", ""))
            )
            if _pode_mexer:
                b1, b2, _bspc = st.columns([1, 1, 5])
                if b1.button("✏️ Editar", key=f"ag_ed_{row['id']}",
                             use_container_width=True):
                    st.session_state.agenda_edit_id = int(row["id"])
                    st.rerun()
                with b2.popover("🗑️ Excluir", use_container_width=True):
                    st.markdown(f"**Excluir '{row['titulo']}'?**")
                    st.caption("Esta ação não pode ser desfeita.")
                    if st.button(
                        "✅ Sim, excluir",
                        key=f"ag_del_conf_{row['id']}",
                        type="primary", use_container_width=True,
                    ):
                        db.excluir_evento(int(row["id"]))
                        db.log_aud(usuario_atual, "excluir", "agenda",
                                   int(row["id"]), str(row["titulo"]))
                        st.toast(f"'{row['titulo']}' removido.")
                        st.rerun()
else:
    st.info(
        "📭 Agenda vazia — adicione o primeiro compromisso ao lado."
    )
