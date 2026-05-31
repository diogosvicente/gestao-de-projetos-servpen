import logging
import streamlit as st
import pandas as pd
import database as db
import auth
import os
from datetime import datetime
import plotly.express as px
import relatorios


# ─── LOGGING ─────────────────────────────────────────────────────
# Configura ANTES de qualquer st.* ou import pesado pra capturar tudo.
# Em produção (systemd com StandardOutput=append) o log vai pro arquivo;
# em dev (streamlit run local) vai pro stdout.
# Nível controlado por env LOG_LEVEL (default INFO; DEBUG pra investigar).
_LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    force=True,  # sobrescreve config default do Streamlit/Tornado
)
# Streamlit/Tornado/Plotly são MUITO verbosos em DEBUG — silencia-os
# a menos que o usuário explicitamente queira ver tudo.
if _LOG_LEVEL != "DEBUG":
    for noisy in ("tornado.access", "tornado.application", "watchdog",
                  "matplotlib", "PIL", "fontTools", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
log = logging.getLogger(__name__)
# (sem log.info no top-level: Streamlit re-executa o script a cada
#  interação do usuário, então logar aqui vira ruído. Use log.info/warning
#  dentro de handlers específicos quando algo relevante acontecer.)


# 1. CONFIGURAÇÃO DA PÁGINA (Sempre o PRIMEIRO comando Streamlit)
st.set_page_config(page_title="GESTÃO DE PROJETOS - SERVPEN", layout="wide", page_icon="🏢")

# 2. INICIALIZAÇÃO DE SESSION STATE
if 'autenticado' not in st.session_state:
    st.session_state.autenticado = False
if 'usuario' not in st.session_state:
    st.session_state.usuario = None
if 'perfil' not in st.session_state:
    st.session_state.perfil = "Gestor"
if 'lista_checklist' not in st.session_state:
    st.session_state.lista_checklist = ["Água Pluvial", "Arquitetura", "Ar condicionado", "Esgoto", "Especificação Técnica", "Estrutura",
        "Exaustão", "Gás", "HVAC", "Incêndio", "Laudo", "Levantamento", "Lógica",  "Memorial Descritivo", "Planilha", "Topografia"]
if 'tema' not in st.session_state:
    st.session_state.tema = 'dark'

# Helpers de tema (lidos pelo CSS e pelas chamadas do Plotly)
def _init_etapas():
    if 'etapas_form' not in st.session_state:
        st.session_state.etapas_form = [
            {'nome': 'Levantamento', 'duracao_dias': 5,  'dias_offset': 0},
            {'nome': 'Projeto',      'duracao_dias': 10, 'dias_offset': 5},
        ]

def _eh_tema_claro():
    return st.session_state.get('tema', 'dark') == 'light'

def _cor_fonte_grafico():
    return '#1f2937' if _eh_tema_claro() else '#ffffff'

def _cor_grade_grafico():
    return 'rgba(0,0,0,0.08)' if _eh_tema_claro() else 'rgba(255,255,255,0.08)'

def _pode_editar():
    """True se o perfil atual pode criar/editar/excluir. Visualizador eh read-only."""
    return st.session_state.get('perfil', '') in ('Gestor', 'Projetista')

def _pode_gestor():
    """True somente para perfil Gestor."""
    return st.session_state.get('perfil', '') == 'Gestor'

def _tempo_relativo(dt_input):
    """Converte data/hora absoluta em texto relativo: 'agora', 'há 5 min', 'há 2 h',
       'ontem', 'há 3 dias', ou data completa se for mais antigo que 7 dias.
       Aceita datetime, ISO string ou 'HH:MM' (assume hoje)."""
    if dt_input is None or dt_input == '':
        return '—'
    agora = datetime.now()
    try:
        if isinstance(dt_input, datetime):
            dt = dt_input
        else:
            s = str(dt_input).strip().replace('T', ' ')
            # 'HH:MM' -> hoje as HH:MM
            if len(s) <= 5 and ':' in s:
                hh, mm = s.split(':')
                dt = agora.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
            elif '/' in s:  # dd/mm/YYYY
                try:
                    dt = datetime.strptime(s, '%d/%m/%Y')
                except ValueError:
                    dt = datetime.strptime(s, '%d/%m/%Y %H:%M')
            else:
                dt = datetime.fromisoformat(s)
    except Exception:
        return str(dt_input)
    diff = agora - dt
    secs = diff.total_seconds()
    if secs < 0:
        # Futuro - mostra data fmt curto
        return dt.strftime('%d/%m')
    if secs < 60:
        return 'agora'
    if secs < 3600:
        return f"há {int(secs // 60)} min"
    if secs < 86400:
        return f"há {int(secs // 3600)} h"
    if secs < 172800:
        return 'ontem'
    if secs < 7 * 86400:
        return f"há {int(secs // 86400)} dias"
    return dt.strftime('%d/%m/%Y')

def _badge_status(status):
    """Devolve um <span> HTML estilizado para um status de projeto."""
    s = str(status or '').strip()
    cores = {
        'EM ESPERA':     ('#0056b3', '#ffffff'),
        '🛑 Parado': ('#d35400', '#ffffff'),
        'Parado':    ('#d35400', '#ffffff'),
        'Cancelado': ('#801a1a', '#ffffff'),
        'Concluído': ('#1a661a', '#ffffff'),
        'Concluido': ('#1a661a', '#ffffff'),
    }
    bg, fg = cores.get(s, ('#4a5568', '#ffffff'))
    return (f"<span style='display:inline-block; background:{bg}; color:{fg}; "
            f"padding:2px 10px; border-radius:12px; font-size:11px; font-weight:600; "
            f"letter-spacing:0.5px; text-transform:uppercase;'>{s}</span>")


def _cor_tag(tag):
    """Devolve par (bg, fg) determinístico pra uma tag — mesma tag = mesma cor.

    Usa hash da string lowercased como índice numa paleta curada. Assim a
    UI fica visualmente estável (não muda cor entre páginas) sem precisar
    catálogo persistente.
    """
    import hashlib as _hl
    paleta = [
        ('#2b6cb0', '#ffffff'),  # azul
        ('#2f855a', '#ffffff'),  # verde
        ('#b7791f', '#ffffff'),  # amarelo escuro
        ('#9c4221', '#ffffff'),  # laranja queimado
        ('#702459', '#ffffff'),  # roxo
        ('#2c5282', '#ffffff'),  # azul escuro
        ('#276749', '#ffffff'),  # verde escuro
        ('#b03a2e', '#ffffff'),  # vermelho
        ('#553c9a', '#ffffff'),  # violeta
        ('#0987a0', '#ffffff'),  # teal
    ]
    idx = int(_hl.md5(str(tag).strip().lower().encode()).hexdigest(), 16) % len(paleta)
    return paleta[idx]


def _render_tag_chips(tags_str, *, small=False):
    """Renderiza chips coloridos a partir de string CSV de tags.

    `small=True` reduz padding/fonte (pra chip no card do Kanban).
    Retorna string HTML pronta pra `unsafe_allow_html=True`. Vazio se sem tags.
    """
    if not tags_str:
        return ''
    chips = []
    pad = "1px 6px" if small else "2px 8px"
    fz  = "10px"    if small else "11px"
    mar = "2px 3px 0 0"
    for t in db.parse_tags(tags_str):
        bg, fg = _cor_tag(t)
        # Escape HTML básico no nome da tag
        safe = (t.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))
        chips.append(
            f"<span style='display:inline-block;background:{bg};color:{fg};"
            f"padding:{pad};border-radius:10px;font-size:{fz};font-weight:600;"
            f"margin:{mar};letter-spacing:0.3px;'>{safe}</span>"
        )
    return ''.join(chips)


def _popover_mencionar(text_key, nomes_disponiveis, *, label="@ Mencionar",
                       pop_key=None, selecionado_key=None, eu_mesmo=None):
    """Popover compacto que appenda `@"Nome"` ao text_area associado.

    Como Streamlit não permite injetar texto na posição do cursor em
    `st.text_area`, este helper faz append ao final — é o trade-off de UX
    aceitável pra evitar gambiarra de JS dentro do widget.

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
        return  # nada a fazer

    with st.popover(label, use_container_width=False):
        st.caption("Selecione um membro pra inserir `@\"Nome\"` no fim do texto.")
        sel = st.selectbox(
            "Membro",
            options=["—"] + sorted(opcoes, key=str.lower),
            key=selecionado_key,
            label_visibility="collapsed",
        )
        if st.button("➕ Inserir menção", key=f"{pop_key}_btn",
                     use_container_width=True):
            if sel and sel != "—":
                atual = st.session_state.get(text_key, "") or ""
                sep = "" if atual.endswith((" ", "\n", "")) else " "
                st.session_state[text_key] = f'{atual}{sep}@"{sel}" '
                # Reseta o select pra "—" pra próximo uso
                st.session_state[selecionado_key] = "—"
                st.rerun()


def _section_header(icone, titulo, subtitulo=None, cor="#3b82f6"):
    """Header de seção padronizado pra dashboard / abas com vários blocos.

    Visual: ícone + título grande + subtítulo opcional + linha colorida.
    Usado pra dar identidade visual a cada bloco de informação, sem
    depender de st.subheader (que vira H2 genérico).

    Args:
        icone: emoji ou char (📊, 📅, 📉, 👥…)
        titulo: frase curta
        subtitulo: opcional, em cinza, explica o que o bloco mostra
        cor: cor da linha de assinatura (default: azul Streamlit)
    """
    _sub = f"<div style='color:#94a3b8;font-size:.82rem;margin-top:2px;'>{subtitulo}</div>" \
           if subtitulo else ""
    st.markdown(
        f"""
        <div style="border-left:4px solid {cor}; padding:6px 12px;
                    margin:4px 0 12px;">
            <div style="font-size:1.05rem; font-weight:700; color:#e5e7eb;
                        display:flex; align-items:center; gap:8px;">
                <span style="font-size:1.25rem;">{icone}</span>{titulo}
            </div>
            {_sub}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _empty_state(icone, titulo, mensagem="", cta_label=None, cta_key=None,
                 cor_borda="#3b82f6"):
    """Empty state padrão: ícone grande, título, mensagem opcional e CTA.

    Substitui `st.info("Nenhum X cadastrado")` por algo visualmente
    mais convidativo — sem fazer o usuário se perguntar "e agora?".

    Args:
        icone: emoji ou char grande pra ilustrar (📂, 📅, 📊, 👥…)
        titulo: frase curta em destaque (ex.: "Nenhum projeto cadastrado")
        mensagem: subtítulo opcional explicando o que fazer
        cta_label: texto do botão "call to action" (ex.: "➕ Cadastrar primeiro")
        cta_key: key única do botão (obrigatório quando cta_label é passado)
        cor_borda: borda esquerda do card pra dar identidade visual

    Returns:
        True se o usuário clicou no CTA, False caso contrário.
    """
    st.markdown(
        f"""
        <div style="background:rgba(255,255,255,0.02);
                    border:1px dashed rgba(255,255,255,0.12);
                    border-left:4px solid {cor_borda};
                    border-radius:10px; padding:24px 18px; text-align:center;
                    margin:8px 0;">
            <div style="font-size:2.4rem; margin-bottom:6px;">{icone}</div>
            <div style="font-size:1rem; font-weight:600; color:#e5e7eb;
                        margin-bottom:6px;">{titulo}</div>
            {f'<div style="font-size:.82rem; color:#94a3b8; max-width:520px; margin:0 auto;">{mensagem}</div>' if mensagem else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )
    if cta_label and cta_key:
        c1, c2, c3 = st.columns([1, 2, 1])
        return bool(c2.button(cta_label, key=cta_key, use_container_width=True))
    return False


def _pill_select(container, label, options, *, default=None,
                 key=None, label_visibility="visible", help=None):
    """Pill-button select que escolhe o melhor widget disponível em runtime.

    - Streamlit ≥ 1.40 → `st.segmented_control` (UI agrupada, mais bonita)
    - Streamlit ≥ 1.25 → `st.radio(horizontal=True)` (fallback estável)

    Deixa o código portátil:
      - 228.20 (Athlon II X2, sem AVX2): Streamlit 1.39 → radio
      - 238.40 (Xeon Gold 5220, AVX-512): atualizar pra 1.40+ → segmented_control
        automaticamente, sem mudar este arquivo.

    Argumentos:
        container: alvo do widget (st, ou uma coluna como tb1, ou st.sidebar).
                   Permite usar dentro de st.columns sem precisar global.
        label: texto do label (escondido se label_visibility="collapsed").
        options: lista de strings.
        default: opção pré-selecionada. Se None, primeira opção.
        key, help, label_visibility: passados direto pro widget Streamlit.
    """
    if hasattr(st, 'segmented_control'):
        return container.segmented_control(
            label, options=options, default=default,
            key=key, label_visibility=label_visibility, help=help,
        )
    # Fallback radio horizontal — converte `default` em `index`
    try:
        idx = list(options).index(default) if default in options else 0
    except (ValueError, TypeError):
        idx = 0
    return container.radio(
        label, options=options, index=idx, horizontal=True,
        key=key, label_visibility=label_visibility, help=help,
    )


def _render_lista_kanban(df_kanban, df_d):
    """Visão 'Lista' do Kanban: tabela densa com sort + checkbox por linha
    + toolbar de bulk actions (mover status, adicionar tag em lote).

    Pensada pra triagem rápida quando há muitos projetos. Bulk actions
    aceleram operações típicas tipo "mover 5 finalizados pra Concluído"
    ou "marcar todos com tag Aguardando Cliente".
    """
    if df_kanban.empty:
        _empty_state(
            "📋",
            "Nenhum projeto pra mostrar",
            "Limpe a busca/filtros acima ou cadastre um projeto novo.",
            cor_borda="#7c3aed",
        )
        return

    # Ordenação
    _opcoes_sort = {
        "Prioridade ↓ → Status":      ['_ord_pri', 'status'],
        "Nome (A-Z)":                 ['projeto'],
        "Projetista (A-Z)":           ['projetista'],
        "Prazo (mais próximo)":       ['_prazo_dt'],
        "Status":                     ['status', 'projeto'],
    }
    _sort_label = st.selectbox(
        "Ordenar por", list(_opcoes_sort.keys()),
        key="kanban_lista_sort", label_visibility="collapsed",
    )
    df_l = df_kanban.copy()
    _ord_pri_map = {"Máxima": 0, "Média": 1, "Mínima": 2}
    df_l['_ord_pri'] = df_l.get('prioridade', '').map(
        lambda x: _ord_pri_map.get(str(x).strip(), 3)
    )
    df_l['_prazo_dt'] = pd.to_datetime(
        df_l.get('data_termino').fillna(df_l.get('data_fim', '')),
        errors='coerce',
    )
    df_l = df_l.sort_values(_opcoes_sort[_sort_label])

    # ── BULK SELECTION STATE ─────────────────────────────────────
    # Mantém set de IDs entre reruns. Limpa IDs que não estão mais no
    # filtro atual (defensivo, evita "fantasmas" após mudar busca).
    _ids_visiveis = set(int(x) for x in df_l['id'].tolist())
    sel_ids = st.session_state.setdefault("kanban_bulk_sel", set())
    sel_ids = sel_ids & _ids_visiveis
    st.session_state["kanban_bulk_sel"] = sel_ids

    # ── TOOLBAR DE BULK ACTIONS (só aparece se houver seleção) ──
    if sel_ids and _pode_editar():
        with st.container(border=True):
            st.markdown(
                f"<div style='color:#3b82f6;font-weight:600;font-size:.9rem;"
                f"margin-bottom:6px;'>"
                f"☑ {len(sel_ids)} projeto(s) selecionado(s)</div>",
                unsafe_allow_html=True,
            )
            with st.form("bulk_actions_form", clear_on_submit=False):
                bc1, bc2, bc3, bc4 = st.columns([2, 2, 1, 1])
                _novo_status = bc1.selectbox(
                    "Mover pra status",
                    options=["— (não mudar)", "Em Espera", "Ativo",
                             "🛑 Parado", "Cancelado", "Concluído"],
                    key="bulk_novo_status",
                )
                _tags_disp = db.listar_tags_existentes()
                _opcoes_tag = ["— (não mudar)"] + _tags_disp
                _tag_add = bc2.selectbox(
                    "Adicionar tag",
                    options=_opcoes_tag,
                    key="bulk_tag_add",
                    help="Adiciona a tag a TODOS os projetos selecionados. "
                         "Não remove tags existentes — só acrescenta.",
                )
                _aplicar = bc3.form_submit_button(
                    "✅ Aplicar", use_container_width=True,
                )
                _limpar = bc4.form_submit_button(
                    "✖ Limpar", use_container_width=True,
                )

            if _aplicar:
                _vai_status = (_novo_status and
                               not _novo_status.startswith("—"))
                _vai_tag = (_tag_add and not _tag_add.startswith("—"))
                if not _vai_status and not _vai_tag:
                    st.warning("Nada selecionado pra mudar.")
                else:
                    _n = 0
                    for _pid in sorted(sel_ids):
                        if _vai_status:
                            db.atualizar_campo_projeto(
                                _pid, "status", _novo_status
                            )
                        if _vai_tag:
                            # Adiciona tag sem perder as existentes
                            _conn_t = db.conectar(); _c_t = _conn_t.cursor()
                            try:
                                _c_t.execute(
                                    "SELECT tags FROM projetos WHERE id = %s",
                                    (int(_pid),),
                                )
                                _r_t = _c_t.fetchone()
                                _atuais = db.parse_tags(_r_t[0] if _r_t else None)
                                if _tag_add not in _atuais:
                                    _atuais.append(_tag_add)
                                _novo_csv = db.serializar_tags(_atuais) or None
                                _c_t.execute(
                                    "UPDATE projetos SET tags = %s WHERE id = %s",
                                    (_novo_csv, int(_pid)),
                                )
                                _conn_t.commit()
                            finally:
                                _conn_t.close()
                        _n += 1
                    db.log_aud(
                        st.session_state.usuario, 'bulk_acao', 'projeto',
                        None,
                        f"{_n} projetos · status={_novo_status if _vai_status else '—'}"
                        f" · tag={_tag_add if _vai_tag else '—'}",
                    )
                    st.session_state["kanban_bulk_sel"] = set()
                    _invalidar_dados()
                    st.success(f"✅ {_n} projeto(s) atualizado(s).")
                    st.rerun()

            if _limpar:
                st.session_state["kanban_bulk_sel"] = set()
                st.rerun()

    # ── CABEÇALHO DA TABELA ──────────────────────────────────────
    # +1 coluna inicial pra "selecionar todos" / espaço do checkbox
    _COLS_ET = [0.35, 1.4, 3, 2, 1.5, 1.2, 2, 0.6]
    hdr = st.columns(_COLS_ET)
    # "Selecionar todos" no header se for Gestor/edit
    if _pode_editar():
        _todos_marcados = (len(sel_ids) > 0
                           and sel_ids >= _ids_visiveis)
        _toggle_all = hdr[0].checkbox(
            "", value=_todos_marcados, key="bulk_sel_all",
            help="Selecionar/desmarcar todos os visíveis",
            label_visibility="collapsed",
        )
        # Reage só se mudou de estado vs. derivado
        if _toggle_all and not _todos_marcados:
            st.session_state["kanban_bulk_sel"] = _ids_visiveis.copy()
            st.rerun()
        elif (not _toggle_all) and _todos_marcados:
            st.session_state["kanban_bulk_sel"] = set()
            st.rerun()
    else:
        hdr[0].markdown(" ")
    for col_obj, txt in zip(
        hdr[1:],
        ["Status", "Projeto", "Projetista", "Prazo", "Prioridade", "Tags", ""],
    ):
        col_obj.markdown(
            f"<small style='color:#94a3b8;text-transform:uppercase;"
            f"letter-spacing:.5px;font-weight:600;'>{txt}</small>",
            unsafe_allow_html=True,
        )

    # ── LINHAS DA TABELA ─────────────────────────────────────────
    with st.container(height=720, border=False):
        for _, row in df_l.iterrows():
            cols = st.columns(_COLS_ET)
            pid = int(row['id'])

            # Checkbox de seleção (col 0) — só se pode editar
            if _pode_editar():
                _checked = cols[0].checkbox(
                    "", value=(pid in sel_ids),
                    key=f"lista_chk_{pid}",
                    label_visibility="collapsed",
                )
                if _checked:
                    sel_ids.add(pid)
                else:
                    sel_ids.discard(pid)
            else:
                cols[0].markdown(" ")

            cols[1].markdown(
                f"<div style='padding-top:6px;'>{_badge_status(row.get('status'))}</div>",
                unsafe_allow_html=True,
            )
            cols[2].markdown(
                f"<div style='padding-top:6px;font-weight:600;'>"
                f"{row.get('projeto', '—')} "
                f"<span style='color:#64748b;font-weight:400;font-size:11px;'>"
                f"#{pid}</span></div>",
                unsafe_allow_html=True,
            )
            cols[3].markdown(
                f"<div style='padding-top:8px;font-size:12px;opacity:.85;'>"
                f"👤 {row.get('projetista', '—')}</div>",
                unsafe_allow_html=True,
            )
            _prazo = row.get('data_termino') or row.get('data_fim') or '—'
            cols[4].markdown(
                f"<div style='padding-top:8px;font-size:12px;'>📅 {_prazo}</div>",
                unsafe_allow_html=True,
            )
            _pri = str(row.get('prioridade', '')).strip()
            _pri_html = {
                "Máxima": "<span class='kc-pri-max'>▲ MÁX</span>",
                "Média":  "<span class='kc-pri-med'>◆ MÉD</span>",
                "Mínima": "<span class='kc-pri-min'>▼ MÍN</span>",
            }.get(_pri, "")
            cols[5].markdown(
                f"<div style='padding-top:8px;'>{_pri_html}</div>",
                unsafe_allow_html=True,
            )
            cols[6].markdown(
                f"<div style='padding-top:6px;'>{_render_tag_chips(row.get('tags'), small=True)}</div>",
                unsafe_allow_html=True,
            )
            if cols[7].button("🔍", key=f"lista_ver_{pid}",
                              help="Abrir detalhes / editar"):
                st.session_state.projeto_em_edicao = pid
                st.rerun()

    # Persiste estado final (depois de processar todos os checkboxes)
    st.session_state["kanban_bulk_sel"] = sel_ids


def _render_resumo_kanban(df_kanban, df_d):
    """Visão 'Resumo' do Kanban: visão executiva com top urgentes + atrasados +
    distribuição. Pensada como 'dashboard de cima' pra reuniões/decisão."""
    if df_kanban.empty:
        _empty_state(
            "📊",
            "Nada pra resumir",
            "Limpe a busca/filtros acima — sem projetos visíveis não há resumo.",
            cor_borda="#0891b2",
        )
        return

    hoje = datetime.now().date()
    df_r = df_kanban.copy()
    df_r['_prazo_dt'] = pd.to_datetime(
        df_r.get('data_termino').fillna(df_r.get('data_fim', '')),
        errors='coerce',
    )

    # ── Coluna esquerda: TOP URGENTES (Máxima Em Espera + Atrasados Ativos)
    # ── Coluna direita: distribuição por status (chart bar)
    col_esq, col_dir = st.columns([3, 2])

    with col_esq:
        st.markdown("### 🔥 Atenção imediata")

        _maxima = df_r[(df_r['status'] == 'Em Espera')
                       & (df_r['prioridade'].astype(str).str.strip() == 'Máxima')]
        _atrasados = df_r[(df_r['status'] == 'Ativo')
                          & (df_r['_prazo_dt'].notna())
                          & (df_r['_prazo_dt'].dt.date < hoje)]

        if _maxima.empty and _atrasados.empty:
            st.success("✅ Nenhum projeto urgente no momento — tudo sob controle.")
        else:
            if not _maxima.empty:
                st.markdown(f"**▲ Máxima na fila ({len(_maxima)}):**")
                for _, r in _maxima.head(10).iterrows():
                    pid = int(r['id'])
                    c1, c2 = st.columns([5, 1])
                    c1.markdown(
                        f"• **{r['projeto']}** — 👤 {r['projetista']} "
                        f"· 📅 {r.get('data_termino') or r.get('data_fim') or '—'}"
                    )
                    if c2.button("🔍", key=f"resumo_max_{pid}",
                                 help="Abrir projeto"):
                        st.session_state.projeto_em_edicao = pid
                        st.rerun()

            if not _atrasados.empty:
                st.markdown(f"**🔴 Atrasados ({len(_atrasados)}):**")
                for _, r in _atrasados.head(10).iterrows():
                    pid = int(r['id'])
                    _dt = r['_prazo_dt'].date() if pd.notna(r['_prazo_dt']) else None
                    _dias_atraso = (hoje - _dt).days if _dt else 0
                    c1, c2 = st.columns([5, 1])
                    c1.markdown(
                        f"• **{r['projeto']}** — 👤 {r['projetista']} "
                        f"· 📅 {_dt.strftime('%d/%m/%Y') if _dt else '—'} "
                        f"<span style='color:#ef4444;font-weight:600;'>"
                        f"(−{_dias_atraso}d)</span>",
                        unsafe_allow_html=True,
                    )
                    if c2.button("🔍", key=f"resumo_atr_{pid}",
                                 help="Abrir projeto"):
                        st.session_state.projeto_em_edicao = pid
                        st.rerun()

    with col_dir:
        st.markdown("### 📊 Distribuição")
        _dist = (df_r.groupby('status').size()
                     .reset_index(name='qtd')
                     .sort_values('qtd', ascending=True))
        if not _dist.empty:
            try:
                fig = px.bar(_dist, x='qtd', y='status', orientation='h',
                             text='qtd', color='status',
                             color_discrete_map={
                                 'Em Espera':  '#7c3aed',
                                 'Ativo':      '#00d4ff',
                                 '🛑 Parado':  '#ff9f43',
                                 'Cancelado':  '#ff4d4d',
                                 'Concluído':  '#4dff4d',
                             })
                fig.update_traces(textposition='outside')
                fig.update_layout(
                    showlegend=False, height=280,
                    margin=dict(l=0, r=30, t=10, b=10),
                    xaxis_title=None, yaxis_title=None,
                )
                _estiliza_plotly(fig) if '_estiliza_plotly' in globals() else None
                st.plotly_chart(fig, use_container_width=True)
            except Exception as e:
                st.info(f"Distribuição: {dict(zip(_dist['status'], _dist['qtd']))}")

        # Distribuição por tag (top 5)
        _tag_count = {}
        for _, row in df_r.iterrows():
            for t in db.parse_tags(row.get('tags')):
                _tag_count[t] = _tag_count.get(t, 0) + 1
        if _tag_count:
            st.markdown("**🏷 Top tags em uso:**")
            _top_tags = sorted(_tag_count.items(), key=lambda x: -x[1])[:5]
            for tag, qtd in _top_tags:
                st.markdown(
                    f"• {_render_tag_chips(tag, small=True)} — "
                    f"<small>{qtd} projeto(s)</small>",
                    unsafe_allow_html=True,
                )


def _gerar_ics(df_eventos):
    """Gera conteudo .ics (RFC 5545) a partir de um DataFrame de eventos da agenda.
       Colunas esperadas: titulo, tipo, data_inicio, data_fim, responsaveis, descricao."""
    import uuid
    linhas = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//SERVPEN//Gestao de Projetos//PT-BR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Agenda SERVPEN",
    ]
    def _fmt(d):
        if pd.isna(d): return ''
        try:
            dt = pd.to_datetime(d)
            return dt.strftime('%Y%m%d')
        except Exception:
            return ''
    def _esc(s):
        return (str(s or '')
                .replace('\\', '\\\\').replace(';', '\\;')
                .replace(',', '\\,').replace('\n', '\\n'))
    for _, ev in df_eventos.iterrows():
        d_ini = _fmt(ev.get('data_inicio'))
        d_fim = _fmt(ev.get('data_fim'))
        if not d_ini: continue
        # All-day event (DTEND eh exclusivo no .ics, entao somamos 1 dia)
        if d_fim:
            try:
                d_fim_excl = (pd.to_datetime(ev['data_fim']) + pd.Timedelta(days=1)).strftime('%Y%m%d')
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
            f"DESCRIPTION:Envolvidos: {_esc(ev.get('responsaveis',''))}\\n{_esc(ev.get('descricao',''))}",
            "END:VEVENT",
        ]
    linhas.append("END:VCALENDAR")
    return "\r\n".join(linhas).encode('utf-8')

def _extrair_mencoes(texto, lista_usuarios):
    """Extrai nomes mencionados como @"Nome Completo" no texto.
       Match case-insensitive contra `lista_usuarios` (nomes reais).
       Devolve lista de nomes CANONICOS (como estao no banco), unicos, na ordem
       que aparecem. Nomes que nao casam com nenhum usuario sao ignorados."""
    import re as _re
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
    """Substitui ocorrencias de @"Nome" no texto por um <a> estilizado (chip clicavel).
       Casa case-insensitive contra lista_usuarios; nomes invalidos ficam como texto.
       Se `eu_mesmo` for igual ao nome mencionado, o chip ganha highlight extra (verde).
       Retorna HTML seguro (texto fora das mencoes nao eh tocado - assume que ja foi
       escapado se necessario)."""
    import re as _re
    if not texto:
        return ''
    nomes_lower = {str(u).strip().lower(): str(u) for u in (lista_usuarios or [])}
    def _replace(match):
        nome_match = match.group(1).strip()
        canonico = nomes_lower.get(nome_match.lower())
        if not canonico:
            # nao casa com nenhum usuario - deixa o texto literal
            return match.group(0)
        eh_eu = (eu_mesmo is not None and canonico == eu_mesmo)
        bg = '#1e7e34' if eh_eu else '#0056b3'
        return (f'<a href="#mencao-{canonico.replace(" ", "_")}" '
                f'style="background:{bg};color:#fff;padding:2px 8px;'
                f'border-radius:10px;font-size:0.85em;font-weight:600;'
                f'text-decoration:none;margin:0 1px;display:inline-block;'
                f'cursor:pointer;" '
                f'title="Usuario mencionado: {canonico}">@{canonico}</a>')
    return _re.sub(r'@"([^"]+)"', _replace, str(texto))


def _processar_mencoes_diario(texto, projeto_id, autor, relato_id, contexto, lista_usuarios):
    """Pipeline completo de uma menção:
       1. Extrai os nomes mencionados no texto
       2. Para cada um (exceto auto-menção): concede acesso (idempotente) + grava notificação
       3. Loga em auditoria apenas quando a concessão é NOVA (evita ruído)
       contexto = 'relato' ou 'resposta_gestor' (vai pra tabela de notificações)
    """
    if not texto or not projeto_id:
        return
    for nome in _extrair_mencoes(texto, lista_usuarios):
        if nome == autor:
            continue  # auto-mencao: ignora
        criou = db.conceder_acesso_por_mencao(
            usuario=nome, projeto_id=projeto_id,
            concedido_por=autor, relato_id=relato_id,
        )
        # Notificação sempre é registrada (mesmo se já tinha acesso) - decisão 5
        db.registrar_notificacao_mencao(
            usuario=nome, projeto_id=projeto_id, relato_id=relato_id,
            mencionado_por=autor, contexto=contexto,
        )
        if criou:
            db.log_aud(
                autor, 'mencao_concedida', 'projeto', projeto_id,
                f"mencionou '{nome}' no projeto id={projeto_id} (via {contexto})",
            )


@st.fragment
def _render_relatos_proj(proj_id, busca, so_pendentes, usuarios_para_render,
                         autor_logado, perfil, destacar_relato_id):
    """Renderiza a LISTA de relatos de UM projeto no Diário.

    Decorada com @st.fragment para que st.rerun(scope='fragment') redesenhe APENAS
    este bloco quando o usuário clica em Excluir/Resolver/Reabrir/Enviar — assim o
    scroll do navegador NÃO volta pro topo a cada ação.

    IMPORTANTE: re-consulta o banco a cada render (em vez de receber os registros
    fixos). Sem isso, num st.rerun(scope='fragment') o fragmento mostraria dados
    antigos (resolver/excluir não refletiria). Aplica os mesmos filtros de busca e
    'só pendências' que a aba usa."""
    df_proj_d = pd.read_sql_query(
        "SELECT * FROM diario WHERE projeto_id = %s ORDER BY id DESC",
        db.get_engine(), params=(int(proj_id),),
    )

    if busca and busca.strip():
        t = busca.lower()
        df_proj_d = df_proj_d[
            df_proj_d['executado'].astype(str).str.lower().str.contains(t, na=False) |
            df_proj_d['autor'].astype(str).str.lower().str.contains(t, na=False) |
            df_proj_d['disciplina'].astype(str).str.lower().str.contains(t, na=False) |
            df_proj_d['resposta_gestor'].astype(str).str.lower().str.contains(t, na=False)
        ]
    if so_pendentes:
        df_proj_d = df_proj_d[df_proj_d['resolvido'] == 0]

    for _, d in df_proj_d.iterrows():
        texto_completo = str(d['executado'])
        texto_exibicao = texto_completo
        for tag_rem in (
            "[Relato de Atividade]", "[❓ Dúvida Técnica]", "[🛑 Impedimento]",
            "Relato de Atividade", "❓ Dúvida Técnica", "🛑 Impedimento"
        ):
            texto_exibicao = texto_exibicao.replace(tag_rem, "")
        texto_exibicao = texto_exibicao.strip()

        if d['resolvido']:
            cor_topo, tag = "#1e7e34", "✅ RESOLVIDO"
        elif any(x in texto_completo for x in ["Impedimento", "Dúvida", "🛑", "❓"]):
            cor_topo, tag = "#b01a2c", "⚠️ PENDÊNCIA"
        else:
            cor_topo, tag = "#0056b3", "📝 RELATO"

        _destaque_relato = (destacar_relato_id == int(d['id']))

        texto_exibicao = _render_mencoes_html(
            texto_exibicao, usuarios_para_render, eu_mesmo=autor_logado,
        )
        resposta_limpa_html = _render_mencoes_html(
            str(d.get('resposta_gestor') or '').replace('\n', '<br>'),
            usuarios_para_render, eu_mesmo=autor_logado,
        )
        _anexo = d.get('anexo')

        _wrap_pre = (
            '<div style="border:2px solid #f59e0b;border-radius:12px;'
            'padding:4px;box-shadow:0 0 18px rgba(245,158,11,0.45);'
            'margin-top:10px;">'
            if _destaque_relato else ''
        )
        _wrap_post = '</div>' if _destaque_relato else ''

        # Chip ⏱ Xh: só exibe quando horas > 0 (campo opcional)
        _horas_val = d.get('horas') or 0
        try:
            _horas_num = float(_horas_val)
        except (TypeError, ValueError):
            _horas_num = 0.0
        _horas_chip = (
            f'<span style="background:rgba(255,255,255,0.18);padding:2px 8px;'
            f'border-radius:4px;font-variant-numeric:tabular-nums;">'
            f'⏱ {_horas_num:.2f} h</span>'
            if _horas_num > 0 else ''
        )
        # Bloco "direito" (horas + tempo relativo) inline. NÃO pode ficar em
        # linhas indentadas dentro do f-string — a renderização markdown do
        # Streamlit interpreta 4+ espaços de indentação como bloco de código
        # `<pre>`, e o HTML aparece literal com o text-transform:uppercase do
        # pai virando "<SPAN TITLE=...>". Aprendido na carne em maio/2026.
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
            {f'''<div style="background:rgba(255,255,255,0.05);padding:10px;margin-top:10px;border-left:3px solid {cor_topo};border-radius:4px;">
                <b style="color:{cor_topo}">💡 ORIENTAÇÃO / INTERAÇÕES:</b><br>{resposta_limpa_html}
                </div>''' if d.get('resposta_gestor') else ''}
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
                    use_container_width=True,
                )

        _pode_del = (perfil == 'Gestor' or d.get('autor') == autor_logado)
        if _pode_del:
            if bc2.button("🗑️", key=f"del_{d['id']}", use_container_width=True, help="Excluir registro"):
                db.excluir_registro_diario(d['id'])
                st.rerun(scope="fragment")  # NÃO volta pro topo

        if bc3.button("✍️ Responder / Interagir", key=f"btn_resp_{d['id']}", use_container_width=True):
            _k = f"editor_{d['id']}"
            st.session_state[_k] = not st.session_state.get(_k, False)
            st.rerun(scope="fragment")

        if perfil == "Gestor":
            if not d['resolvido']:
                if bc4.button("✅ Resolver", key=f"btn_res_{d['id']}", use_container_width=True):
                    with db.conectar() as conn:
                        _c = conn.cursor()
                        _c.execute("UPDATE diario SET resolvido=1 WHERE id=%s", (d['id'],))
                        conn.commit()
                    st.rerun(scope="fragment")
            else:
                if bc4.button("🔓 Reabrir", key=f"btn_reap_{d['id']}", use_container_width=True):
                    with db.conectar() as conn:
                        _c = conn.cursor()
                        _c.execute("UPDATE diario SET resolvido=0 WHERE id=%s", (d['id'],))
                        conn.commit()
                    st.rerun(scope="fragment")

        if st.session_state.get(f"editor_{d['id']}"):
            try:
                lista_usuarios_int = db.listar_usuarios()
            except Exception:
                lista_usuarios_int = list(usuarios_para_render)
            if autor_logado in lista_usuarios_int:
                lista_usuarios_int.remove(autor_logado)

            pessoas_selecionadas = st.multiselect(
                "Envolver outras pessoas na interação (Opcional):",
                options=lista_usuarios_int,
                key=f"Mencionar_{d['id']}",
                placeholder="Selecione os projetistas ou gestores..."
            )
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

            if st.button("📤 Enviar", key=f"env_{d['id']}", use_container_width=True):
                if nova_orient.strip():
                    data_hora = datetime.now().strftime("%d/%m/%Y %H:%M")
                    marcacao = ""
                    if pessoas_selecionadas:
                        marcacao = " (Ref: " + ", ".join([f"@{p}" for p in pessoas_selecionadas]) + ")"
                    linha_comentario = f"[{data_hora}] {autor_logado}{marcacao} ({perfil}): {nova_orient.strip()}"
                    historico_banco = str(d.get('resposta_gestor') or '').strip()
                    texto_final = f"{historico_banco}\n{linha_comentario}" if historico_banco else linha_comentario

                    with db.conectar() as conn:
                        _c = conn.cursor()
                        _c.execute("UPDATE diario SET resposta_gestor=%s WHERE id=%s", (texto_final, d['id']))
                        conn.commit()

                    _processar_mencoes_diario(
                        texto=nova_orient, projeto_id=int(d['projeto_id']),
                        autor=autor_logado, relato_id=int(d['id']),
                        contexto='resposta_gestor',
                        lista_usuarios=usuarios_para_render,
                    )
                    st.session_state[f"editor_{d['id']}"] = False
                    st.rerun(scope="fragment")
                else:
                    st.warning("Escreva algo antes de enviar.")

    # Limpa o destaque one-shot ao terminar de renderizar (so vale pra UMA render)
    if destacar_relato_id is not None:
        st.session_state.pop('_diario_destacar_relato', None)


def _safe_chat_html(texto):
    """Escapa HTML do usuario e aplica markdown leve (**bold**, _italic_, `code`, links, \\n).
       Previne XSS no chat enquanto permite formatacao basica."""
    import html as _html
    import re as _re
    t = _html.escape(str(texto or ''))
    # `code`
    t = _re.sub(r'`([^`\n]+)`',
                r"<code style='background:rgba(255,255,255,0.18);padding:1px 5px;border-radius:4px;font-size:0.9em'>\1</code>",
                t)
    # **bold**
    t = _re.sub(r'\*\*([^*\n]+)\*\*', r'<b>\1</b>', t)
    # _italic_ (cuidado p/ nao casar com underline no meio de palavra)
    t = _re.sub(r'(?<!\w)_([^_\n]+)_(?!\w)', r'<i>\1</i>', t)
    # links http(s)://...
    t = _re.sub(
        r'(https?://[^\s<]+)',
        r"<a href='\1' target='_blank' rel='noopener noreferrer' style='color:#7dd3fc'>\1</a>",
        t,
    )
    # quebra de linha
    t = t.replace('\n', '<br>')
    return t

def _estiliza_plotly(fig):
    """Aplica fundo transparente + cor de fonte/grade/eixos/legenda/annotations
       segundo o tema atual (claro/escuro). Chamar como ULTIMO passo de cada fig
       para garantir que sobrescreve qualquer cor branca herdada do template."""
    cor = _cor_fonte_grafico()
    grade = _cor_grade_grafico()
    fig.update_layout(
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        font=dict(color=cor),
        legend=dict(font=dict(color=cor), title=dict(font=dict(color=cor))),
    )
    fig.update_xaxes(tickfont=dict(color=cor), title_font=dict(color=cor), gridcolor=grade, linecolor=grade, zerolinecolor=grade)
    fig.update_yaxes(tickfont=dict(color=cor), title_font=dict(color=cor), gridcolor=grade, linecolor=grade, zerolinecolor=grade)
    fig.update_annotations(font_color=cor)
    return fig

# 2.1 PERSISTENCIA DE LOGIN VIA TOKEN NA URL
# A tabela 'sessoes' armazena tokens opacos (24 chars) associados a cada usuario logado.
# O token vai no query param ?t=... -> sobrevive F5 e fechar/abrir o navegador.
# Logout deleta a linha do banco, invalidando o token de verdade (nao basta apagar a URL).
db.criar_tabela_sessoes()
db.limpar_sessoes_expiradas()

if not st.session_state.get('autenticado', False):
    _tok = st.query_params.get('t')
    _sess = db.validar_sessao(_tok)
    if _sess:
        st.session_state.autenticado = True
        st.session_state.usuario = _sess[0]
        st.session_state.perfil = _sess[1]

# 3. INICIALIZAÇÃO DO BANCO E PASTAS
db.criar_tabelas()
db.criar_tabela_agenda() # Cria a tabela de férias/reuniões
db.criar_tabela_progresso()
db.criar_tabela_arquivos()
db.criar_tabela_auditoria()
db.criar_tabela_mencoes()
db.criar_tabela_diario_leituras()   # nova tabela de leituras do diário
db.migrar_status_em_espera()


if not os.path.exists("anexos"):
    os.makedirs("anexos")

# 4. CARREGAMENTO DA AGENDA E ALERTAS
# IMPORTANTE: lê de gestao_equipe.db (onde salvar_evento grava), não do servpen.db
# antigo. Antes isso lia de um arquivo e escrevia em outro (split-brain) -> a agenda
# do boot mostrava dados desatualizados.
try:
    df_agenda = pd.read_sql("SELECT * FROM agenda", db.get_engine())

    # SINAL DE ALERTA (Toast)
    hoje = datetime.now().date()
    if not df_agenda.empty:
        # Garantimos que a data_inicio seja lida como data para comparar
        df_agenda['data_inicio_dt'] = pd.to_datetime(df_agenda['data_inicio']).dt.date
        alertas_hoje = df_agenda[df_agenda['data_inicio_dt'] == hoje]
        
        for _, alerta in alertas_hoje.iterrows():
            st.toast(f"🔔 **HOJE:** {alerta['titulo']} ({alerta['tipo']})", icon="📅")
except Exception as e:
    # Se der erro, criamos um DataFrame vazio para não travar o resto do app
    df_agenda = pd.DataFrame(columns=['id', 'titulo', 'tipo', 'data_inicio', 'data_fim', 'responsaveis', 'descricao'])

# ── CACHE DE LEITURA (reduz queries repetidas a cada rerun) ──────────────────
# TTL curto (8s): se ninguém escrever, o mesmo DataFrame é reaproveitado entre
# reruns em vez de reconsultar o banco toda hora. Após QUALQUER escrita, chamamos
# _invalidar_dados() (= st.cache_data.clear()) antes do st.rerun() pra o autor ver
# a mudança na hora. O TTL é só rede de segurança caso algum write não invalide.
@st.cache_data(ttl=8, show_spinner=False)
def _load_df_u():
    return pd.read_sql_query("SELECT nome FROM usuarios", db.get_engine())

@st.cache_data(ttl=8, show_spinner=False)
def _load_df_d():
    return pd.read_sql_query("SELECT * FROM diario", db.get_engine())

@st.cache_data(ttl=8, show_spinner=False)
def _load_df_p(usuario, perfil):
    """Projetos visíveis. Cacheado por (usuario, perfil) pra não vazar visibilidade
    entre usuários diferentes."""
    if perfil in ("Projetista", "Visualizador"):
        projs = db.listar_projetos_por_mencao(usuario)
        params = [f"%{usuario}%"]
        sql = "SELECT * FROM projetos WHERE projetista LIKE %s"
        if projs:
            sql += " OR id IN (" + ",".join(["%s"] * len(projs)) + ")"
            params.extend(int(x) for x in projs)
        return pd.read_sql_query(sql, db.get_engine(), params=tuple(params))
    return pd.read_sql_query("SELECT * FROM projetos", db.get_engine())

def _invalidar_dados():
    """Chamar após escrever no banco (projeto/diário/usuário/arquivo/agenda) para
    que a próxima leitura traga dados frescos em vez do cache."""
    try:
        st.cache_data.clear()
    except Exception:
        pass


def _avatar_b64(path):
    """Lê um arquivo de imagem e devolve base64 (pra embutir em <img src=data:...>).
    Permite renderizar avatar redondo via HTML sem depender de URL servida."""
    import base64
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")
    except Exception:
        return ""

def _avatar_circular_html(path, size=90):
    """<img> redondo a partir de um arquivo local. Se não houver, círculo com 👤."""
    if path and os.path.exists(path):
        b64 = _avatar_b64(path)
        if b64:
            return (f"<div style='text-align:center'><img src='data:image/jpeg;base64,{b64}' "
                    f"style='width:{size}px;height:{size}px;border-radius:50%;object-fit:cover;"
                    f"border:3px solid rgba(0,114,224,0.55);box-shadow:0 4px 12px rgba(0,0,0,0.35);'></div>")
    return (f"<div style='text-align:center'><div style='width:{size}px;height:{size}px;"
            f"border-radius:50%;background:linear-gradient(135deg,#0056b3,#003d80);display:inline-flex;"
            f"align-items:center;justify-content:center;font-size:{int(size*0.42)}px;"
            f"box-shadow:0 4px 12px rgba(0,0,0,0.35);'>👤</div></div>")


def _processar_avatar(uploaded_file, nome):
    """Recorta a imagem no centro (quadrado), reduz pra 256x256 e salva como JPEG
    leve. Retorna o caminho salvo. Mantém o arquivo pequeno -> sidebar rápido."""
    import re as _re
    from PIL import Image
    os.makedirs("anexos/avatars", exist_ok=True)
    img = Image.open(uploaded_file).convert("RGB")
    w, h = img.size
    lado = min(w, h)
    esq = (w - lado) // 2
    topo = (h - lado) // 2
    img = img.crop((esq, topo, esq + lado, topo + lado)).resize((256, 256))
    nome_seguro = _re.sub(r'[^A-Za-z0-9]', '_', nome)[:40]
    ts = datetime.now().strftime('%Y%m%d%H%M%S')
    caminho = f"anexos/avatars/{nome_seguro}_{ts}.jpg"
    img.save(caminho, "JPEG", quality=82, optimize=True)
    return caminho


@st.dialog("👤 Meu Perfil")
def _dialog_meu_perfil():
    """Modal onde o PRÓPRIO usuário edita seus dados (menos o nome de login).
    Tudo dentro de st.form: os campos NÃO disparam rerun a cada tecla (o que antes
    podia zerar o cargo no momento do clique) — só o botão de envio processa."""
    nome = st.session_state.usuario
    me = db.obter_usuario(nome) or {}

    st.caption(f"Usuário (login): **{nome}** — não pode ser alterado.")

    # Avatar atual (visualização circular)
    st.markdown(_avatar_circular_html(me.get('avatar_path'), size=96), unsafe_allow_html=True)

    with st.form("form_meu_perfil", clear_on_submit=False):
        novo_avatar = st.file_uploader(
            "Trocar avatar (PNG/JPG)", type=['png', 'jpg', 'jpeg'], key="perfil_avatar",
        )
        st.text_input(
            "Cargo", value=me.get('cargo') or "", key="perfil_cargo",
            disabled=True,
            help="O cargo é definido pela gestão e não pode ser alterado por aqui.",
        )
        email = st.text_input("E-mail", value=me.get('email') or "", key="perfil_email")

        st.markdown("**🔑 Recuperação de senha (pergunta secreta)**")
        perg = st.text_input("Pergunta secreta", value=me.get('pergunta_secreta') or "",
                             key="perfil_perg", placeholder="ex.: Nome do primeiro pet?")
        resp = st.text_input("Resposta secreta", type="password", key="perfil_resp",
                             placeholder="vazio = manter a atual")

        st.markdown("**🔒 Trocar senha** (opcional)")
        senha_atual = st.text_input("Senha atual", type="password", key="perfil_sat")
        nova1 = st.text_input("Nova senha", type="password", key="perfil_n1")
        nova2 = st.text_input("Repetir nova senha", type="password", key="perfil_n2")

        _enviado = st.form_submit_button("💾 Salvar alterações", type="primary",
                                         use_container_width=True)

    if _enviado:
        # 1) Avatar (processa: recorta quadrado + reduz)
        _avatar_path = None
        if novo_avatar is not None:
            try:
                _avatar_path = _processar_avatar(novo_avatar, nome)
            except Exception as _e:
                st.error(f"Falha ao processar a imagem: {_e}")
                return

        # 2) E-mail / avatar (cargo é read-only aqui — não atualizamos)
        db.atualizar_perfil(nome, email=email, avatar_path=_avatar_path)

        # 3) Pergunta secreta — só grava a resposta se ele digitou uma nova
        if perg.strip() and resp.strip():
            db.definir_pergunta_secreta(nome, perg.strip(), resp.strip())
        elif perg.strip() and me.get('pergunta_secreta') != perg.strip():
            st.warning("Você mudou a pergunta — preencha também a resposta secreta. "
                       "(Cargo e e-mail foram salvos.)")
            _invalidar_dados()
            return

        # 4) Troca de senha (exige senha atual correta)
        if nova1 or nova2 or senha_atual:
            if not db.verificar_senha(nome, senha_atual):
                st.error("Senha atual incorreta — senha NÃO foi alterada. (Resto salvo.)")
                _invalidar_dados()
                return
            if not nova1 or nova1 != nova2:
                st.error("A nova senha e a repetição precisam ser iguais (e não vazias).")
                _invalidar_dados()
                return
            db.redefinir_senha(nome, nova1)
            db.log_aud(nome, 'troca_senha', 'usuario', None, 'pelo próprio perfil')

        db.log_aud(nome, 'editar_perfil', 'usuario', None, 'cargo/email/avatar/pergunta')
        _invalidar_dados()
        st.success("Perfil atualizado!")
        st.rerun()


# --- CSS INTEGRAL (base escuro + media queries responsivas) ---
st.markdown("""
    <style>
    /* Esconde o menu padrao do Streamlit (3 pontinhos no canto superior direito) e
       o rodape "Made with Streamlit" - visual de aplicacao em producao, sem ruido
       de dev. O nosso toggle de tema no sidebar substitui o "Settings" desse menu. */
    [data-testid="stMainMenu"], #MainMenu,
    [data-testid="stDecoration"],
    footer, [data-testid="stStatusWidget"] { display: none !important; }
    [data-testid="stHeader"] { background: transparent !important; }

    /* === RESPIRO VISUAL: espacamento mais generoso entre secoes === */
    .main .block-container {
        padding-top: 1.5rem !important;
        padding-bottom: 4rem !important;
        max-width: 1400px;
    }

    /* Headers de secao com underline sutil */
    .main h1 {
        font-size: 1.85rem !important;
        margin-bottom: 0.6rem !important;
        padding-bottom: 0.5rem;
        border-bottom: 2px solid rgba(0, 86, 179, 0.35);
    }
    .main h2 {
        margin-top: 1.8rem !important;
        margin-bottom: 0.7rem !important;
        font-size: 1.4rem !important;
    }
    .main h3 {
        margin-top: 1.3rem !important;
        margin-bottom: 0.5rem !important;
        font-size: 1.15rem !important;
        opacity: 0.92;
    }

    /* Divider mais visivel */
    [data-testid="stDivider"], hr {
        margin: 1.5rem 0 !important;
        opacity: 0.5;
    }

    /* Containers de st.container(border=True) com mais respiro */
    [data-testid="stVerticalBlockBorderWrapper"] {
        padding: 14px 16px !important;
        margin-bottom: 12px !important;
        border-radius: 10px !important;
    }

    /* Espaco entre widgets dentro de uma coluna */
    [data-testid="stVerticalBlock"] > [data-testid="stVerticalBlock"] > div {
        margin-bottom: 4px;
    }

    /* Forms com fundo sutil pra destacar do resto */
    [data-testid="stForm"] {
        padding: 18px !important;
        border-radius: 12px !important;
    }

    /* Expanders mais elegantes */
    [data-testid="stExpander"] {
        border-radius: 10px !important;
        margin-bottom: 12px;
    }
    [data-testid="stExpander"] summary {
        padding: 10px 14px !important;
        font-weight: 500;
    }

    /* Botoes (no main, fora do login) com cantos arredondados */
    .main .stButton > button,
    .main [data-testid="stFormSubmitButton"] > button {
        border-radius: 8px;
        transition: transform 0.1s, box-shadow 0.2s;
    }
    .main .stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 10px rgba(0,0,0,0.15);
    }

    /* Sidebar mais aconchegante */
    section[data-testid="stSidebar"] {
        padding-top: 0.5rem;
    }
    section[data-testid="stSidebar"] .stButton > button {
        border-radius: 8px;
    }

    [data-testid="stMetric"] {
        background-color: transparent !important;
        border-radius: 15px;
        padding: 20px !important;
        box-shadow: 4px 4px 10px rgba(0,0,0,0.4) !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
    }
    div[data-testid="stMetric"]:nth-of-type(1) { background-color: #003366 !important; border-left: 8px solid #00d4ff !important; }
    div[data-testid="stMetric"]:nth-of-type(2) { background-color: #8c4a00 !important; border-left: 8px solid #ff9f43 !important; }
    div[data-testid="stMetric"]:nth-of-type(3) { background-color: #660000 !important; border-left: 8px solid #ff4d4d !important; }
    div[data-testid="stMetric"]:nth-of-type(4) { background-color: #1a4314 !important; border-left: 8px solid #2ecc71 !important; }
    [data-testid="stMetricLabel"] > div, [data-testid="stMetricValue"] > div { color: #ffffff !important; }

    /* === ABAS: pills que QUEBRAM em linhas (sem barra de rolagem) === */
    /* As abas viram "pills" que se reorganizam em quantas linhas forem necessárias.
       Em tela larga ficam em 1 linha; em tela estreita quebram pra 2-3 linhas.
       Zero scroll horizontal. */
    .stTabs [data-baseweb="tab-list"] {
        flex-wrap: wrap !important;
        gap: 6px;
        overflow: visible !important;
        border-bottom: none !important;
        padding-bottom: 4px;
    }
    .stTabs [data-baseweb="tab"] {
        white-space: nowrap;
        border-radius: 9px;
        padding: 6px 14px !important;
        background: rgba(255,255,255,0.05);
        border: 1px solid rgba(255,255,255,0.10);
        transition: background 0.15s, transform 0.1s;
        min-height: 0 !important;
    }
    .stTabs [data-baseweb="tab"]:hover {
        background: rgba(0,114,224,0.20);
        transform: translateY(-1px);
    }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #0056b3 0%, #003d80 100%) !important;
        color: #ffffff !important;
        border-color: transparent !important;
    }
    /* Esconde o "sublinhado" deslizante padrão do Streamlit (não combina com pills) */
    .stTabs [data-baseweb="tab-highlight"],
    .stTabs [data-baseweb="tab-border"] { display: none !important; }

    
    .card-espera {
        background-color: #3b1f6e;
        color: white;
        padding: 18px;
        border-radius: 12px;
        border-left: 10px solid #7c3aed;
        margin-bottom: 15px;
    }
    @media (max-width: 992px) {
        .card-espera { padding: 12px; font-size: .9rem; }
    }
    @media (max-width: 640px) {
        .card-espera { padding: 10px; }
    }
    
    .card-ativo { background-color: #0056b3; color: white; padding: 18px; border-radius: 12px; border-left: 10px solid #00d4ff; margin-bottom: 15px; }
    .card-parado { background-color: #d35400; color: white; padding: 18px; border-radius: 12px; border-left: 10px solid #ff9f43; margin-bottom: 15px; }
    .card-cancelado { background-color: #801a1a; color: white; padding: 18px; border-radius: 12px; border-left: 10px solid #ff4d4d; margin-bottom: 15px; }
    .card-concluido { background-color: #1a661a; color: white; padding: 18px; border-radius: 12px; border-left: 10px solid #4dff4d; margin-bottom: 15px; }

    .card-projetista {
        background: linear-gradient(145deg, #1e1e1e, #252525);
        border-radius: 15px; padding: 20px; margin-bottom: 20px;
        border: 1px solid rgba(255, 255, 255, 0.05);
        box-shadow: 5px 5px 15px rgba(0, 0, 0, 0.3);
        transition: transform 0.3s;
    }
    .card-projetista:hover { transform: translateY(-5px); }
    .nome-projetista {
        font-size: 1.25rem; font-weight: bold; margin-bottom: 12px;
        display: flex; align-items: center; gap: 10px;
    }
    .demanda-texto { font-size: 0.9rem; color: #cccccc; line-height: 1.5; }
    .badge-projeto {
        background-color: rgba(255, 255, 255, 0.03);
        padding: 4px 10px; border-radius: 8px; font-size: 0.8rem;
        margin-top: 6px; display: inline-block;
        border: 1px solid rgba(255, 255, 255, 0.08);
    }

    /* === RESPONSIVIDADE (tablet) === */
    @media (max-width: 992px) {
        .main .block-container { padding: 1.4rem 1rem !important; }
        [data-testid="stMetric"] { padding: 14px !important; }
        .card-ativo, .card-parado, .card-cancelado, .card-concluido {
            padding: 12px; font-size: 0.9rem;
        }
        .card-projetista { padding: 14px; }
        .nome-projetista { font-size: 1.05rem; }
        h1 { font-size: 1.7rem !important; }
        h2 { font-size: 1.35rem !important; }
    }

    /* === RESPONSIVIDADE (celular) === */
    @media (max-width: 640px) {
        .main .block-container { padding: 0.9rem 0.55rem !important; }
        [data-testid="stMetric"] { padding: 10px !important; box-shadow: 2px 2px 6px rgba(0,0,0,0.3) !important; }
        [data-testid="stMetricLabel"] > div { font-size: 0.7rem !important; }
        [data-testid="stMetricValue"] > div { font-size: 1.45rem !important; }
        h1 { font-size: 1.35rem !important; }
        h2 { font-size: 1.15rem !important; }
        h3 { font-size: 1rem !important; }
        .stTabs [data-baseweb="tab-list"] { gap: 4px; }
        .stTabs [data-baseweb="tab"] { padding: 5px 10px !important; font-size: 0.78rem; }
        .card-projetista { padding: 12px; margin-bottom: 12px; }
        .card-projetista .nome-projetista { font-size: 0.95rem; }
        .demanda-texto { font-size: 0.82rem; }
        .badge-projeto { font-size: 0.72rem; padding: 3px 8px; }
    }
    </style>
""", unsafe_allow_html=True)

# --- TEMA CLARO: override aplicado sob demanda ---
if _eh_tema_claro():
    st.markdown("""
        <style>
        .stApp { background-color: #f4f6f9 !important; color: #1f2937 !important; }
        .stApp > header { background-color: transparent !important; }
        section[data-testid="stSidebar"] { background-color: #ffffff !important; border-right: 1px solid #e5e7eb; }
        section[data-testid="stSidebar"] * { color: #1f2937 !important; }

        .stMarkdown, .stMarkdown p, .stMarkdown li, .stMarkdown span,
        [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] * {
            color: #1f2937 !important;
        }
        h1, h2, h3, h4, h5, h6 { color: #111827 !important; }

        /* Metricas: tons mais suaves no claro (fundo colorido, texto branco) */
        div[data-testid="stMetric"]:nth-of-type(1) { background-color: #1e88e5 !important; }
        div[data-testid="stMetric"]:nth-of-type(2) { background-color: #f57c00 !important; }
        div[data-testid="stMetric"]:nth-of-type(3) { background-color: #e53935 !important; }
        div[data-testid="stMetric"]:nth-of-type(4) { background-color: #43a047 !important; }

        /* Inputs claros */
        .stTextInput input, .stTextArea textarea,
        .stSelectbox > div > div, .stMultiSelect > div > div,
        .stDateInput input, .stNumberInput input {
            background-color: #ffffff !important;
            color: #1f2937 !important;
            border-color: #d1d5db !important;
        }

        /* Cards de projetista no tema claro */
        .card-projetista {
            background: #ffffff !important;
            border: 1px solid #e5e7eb !important;
            box-shadow: 0 2px 8px rgba(0,0,0,0.06) !important;
            color: #1f2937;
        }
        .demanda-texto { color: #4b5563 !important; }
        .badge-projeto {
            background-color: rgba(0,0,0,0.04) !important;
            border-color: rgba(0,0,0,0.08) !important;
            color: #1f2937;
        }

        /* Containers diversos */
        [data-testid="stExpander"] { background-color: #ffffff !important; border: 1px solid #e5e7eb !important; }
        [data-testid="stForm"] { background-color: #fafbfc; border-radius: 12px; padding: 14px; border: 1px solid #e5e7eb; }

        /* Abas */
        .stTabs [data-baseweb="tab"] { color: #4b5563 !important; }
        .stTabs [aria-selected="true"] { color: #0056b3 !important; }

        /* === BOTOES (sidebar + main): tema claro com fundo claro e texto escuro ===
           O Streamlit, por estar configurado com base="dark", renderiza botoes com
           fundo escuro + texto claro. Em modo claro precisamos inverter. */
        .stButton > button,
        [data-testid="stFormSubmitButton"] > button,
        [data-testid="baseButton-secondary"],
        [data-testid="baseButton-primary"] {
            background-color: #f3f4f6 !important;
            color: #1f2937 !important;
            border: 1px solid #d1d5db !important;
            box-shadow: 0 1px 2px rgba(0,0,0,0.04) !important;
        }
        .stButton > button:hover,
        [data-testid="stFormSubmitButton"] > button:hover {
            background-color: #e5e7eb !important;
            border-color: #9ca3af !important;
            color: #111827 !important;
        }
        /* Botoes especificamente no sidebar - mesma coisa, garantia */
        section[data-testid="stSidebar"] .stButton > button,
        section[data-testid="stSidebar"] [data-testid="stFormSubmitButton"] > button {
            background-color: #f3f4f6 !important;
            color: #1f2937 !important;
            border: 1px solid #d1d5db !important;
        }

        /* === ALERTS (st.info / st.success / st.warning / st.error) ===
           Streamlit renderiza com fundo tintado-escuro + texto claro no base=dark.
           Re-pintamos com fundo claro tintado e texto escuro. */
        [data-testid="stAlert"] {
            background-color: #eff6ff !important;
            border-left: 4px solid #3b82f6 !important;
            color: #1f2937 !important;
        }
        [data-testid="stAlert"][kind="success"],
        [data-testid="stNotification"][kind="success"] {
            background-color: #ecfdf5 !important;
            border-left-color: #10b981 !important;
        }
        [data-testid="stAlert"][kind="warning"],
        [data-testid="stNotification"][kind="warning"] {
            background-color: #fffbeb !important;
            border-left-color: #f59e0b !important;
        }
        [data-testid="stAlert"][kind="error"],
        [data-testid="stNotification"][kind="error"] {
            background-color: #fef2f2 !important;
            border-left-color: #ef4444 !important;
        }
        [data-testid="stAlert"] *,
        [data-testid="stAlert"] [data-testid="stMarkdownContainer"] *,
        [data-testid="stNotification"] *,
        [data-testid="stNotificationContent"] * {
            color: #1f2937 !important;
        }

        /* === FUNDOS ESCUROS HARDCODED -> CLAROS === */
        /* Cards de membros da Equipe + bloco inferior do Diario usam background-color: #1E1E1E.
           No tema claro fica feio (caixinhas pretas no fundo branco) e ainda por cima
           o texto interno eh branco/cinza-claro (invisivel). Convertemos via atributo. */
        div[style*="background-color: #1E1E1E"],
        div[style*="background-color:#1E1E1E"] {
            background-color: #ffffff !important;
            border: 1px solid #e5e7eb !important;
            box-shadow: 0 2px 6px rgba(0,0,0,0.05) !important;
        }
        /* Texto interno: branco -> grafite, cinza-claro (#EEE/#AAA) -> cinza-medio */
        div[style*="background-color: #1E1E1E"] [style*="color: white"],
        div[style*="background-color:#1E1E1E"] [style*="color: white"],
        div[style*="background-color: #1E1E1E"] [style*="color:#fff"],
        div[style*="background-color:#1E1E1E"] [style*="color:#fff"] {
            color: #111827 !important;
        }
        div[style*="background-color: #1E1E1E"] [style*="color: #EEE"],
        div[style*="background-color: #1E1E1E"] [style*="color: #AAA"],
        div[style*="background-color:#1E1E1E"] [style*="color: #EEE"],
        div[style*="background-color:#1E1E1E"] [style*="color: #AAA"] {
            color: #6b7280 !important;
        }

        /* Bolha de chat recebido (background:#333) -> cinza claro */
        div[style*="background: #333"], div[style*="background:#333"] {
            background: #e5e7eb !important;
            border-color: #d1d5db !important;
        }
        div[style*="background: #333"] [style*="color: white"],
        div[style*="background:#333"] [style*="color: white"] {
            color: #1f2937 !important;
        }

        /* Os cards-coloridos (kanban / chat enviado / badges de perfil) MANTEM texto branco
           porque o fundo deles eh colorido. Isto cancela qualquer override acidental. */
        .card-ativo, .card-parado, .card-cancelado, .card-concluido,
        .card-ativo *, .card-parado *, .card-cancelado *, .card-concluido * {
            color: white !important;
        }
        [data-testid="stMetric"] *, [data-testid="stMetric"] [data-testid="stMetricLabel"] > div,
        [data-testid="stMetric"] [data-testid="stMetricValue"] > div {
            color: white !important;
        }
        </style>
    """, unsafe_allow_html=True)

# --- LÓGICA DE LOGIN ---
if not st.session_state.autenticado:
    st.markdown("""
        <style>
        /* Esconde elementos padrao do Streamlit so na tela de login */
        [data-testid="stToolbar"], [data-testid="stHeader"] { display: none; }
        section[data-testid="stSidebar"] { display: none; }

        /* Centraliza o bloco e limita a largura.
           Usamos data-testid (mais estavel entre versoes do Streamlit) + .main + classe
           pra garantir que o seletor casa independente da versao. layout="wide" no
           set_page_config joga max-width pra 100% sem !important, entao precisamos
           do !important em TUDO pra ganhar a especificidade. */
        [data-testid="stMainBlockContainer"],
        [data-testid="stAppViewBlockContainer"],
        section[data-testid="stMain"] .block-container,
        .main .block-container,
        .main > div > div > div {
            max-width: 420px !important;
            width: 420px !important;
            margin-left: auto !important;
            margin-right: auto !important;
            padding-top: 3.5rem !important;
            padding-bottom: 3.5rem !important;
            padding-left: 1rem !important;
            padding-right: 1rem !important;
        }

        /* Garante que o form e seus inputs nao estouram a largura do container */
        [data-testid="stForm"],
        [data-testid="stForm"] > div,
        .stTextInput,
        .stTextInput > div,
        .stTextInput > div > div {
            width: 100% !important;
            max-width: 100% !important;
            box-sizing: border-box !important;
        }

        /* Em telas pequenas (celular), volta a usar largura cheia menos margem */
        @media (max-width: 420px) {
            [data-testid="stMainBlockContainer"],
            [data-testid="stAppViewBlockContainer"],
            section[data-testid="stMain"] .block-container,
            .main .block-container {
                max-width: calc(100% - 2rem) !important;
                width: auto !important;
            }
        }

        /* Cabecalho com logo + titulo */
        .login-header { text-align: center; margin-bottom: 24px; }
        .login-header img {
            height: 78px;
            margin-bottom: 12px;
            filter: drop-shadow(0 6px 14px rgba(0, 0, 0, 0.55));
        }
        .login-header .brand {
            color: #ffffff;
            font-size: 1.6rem;
            font-weight: 700;
            letter-spacing: 3px;
            margin: 4px 0 2px;
        }
        .login-header .tagline {
            color: #8a8a8a;
            font-size: 0.78rem;
            letter-spacing: 0.4px;
        }

        /* Inputs estilizados - mais compactos */
        .stTextInput > div > div > input {
            background-color: rgba(255, 255, 255, 0.04) !important;
            border: 1px solid rgba(255, 255, 255, 0.10) !important;
            border-radius: 8px !important;
            padding: 10px 12px !important;
            font-size: 0.92rem !important;
            color: #ffffff !important;
            transition: border-color 0.15s, box-shadow 0.15s;
        }
        .stTextInput > div > div > input:focus {
            border-color: #0072e0 !important;
            box-shadow: 0 0 0 3px rgba(0, 114, 224, 0.22) !important;
        }
        .stTextInput label {
            color: #bbbbbb !important;
            font-size: 0.82rem !important;
            font-weight: 500 !important;
            letter-spacing: 0.3px !important;
        }

        /* Botao Acessar - gradiente azul SERVPEN (cobre st.button e form_submit_button) */
        .stButton > button,
        [data-testid="stFormSubmitButton"] > button {
            width: 100%;
            background: linear-gradient(135deg, #0056b3 0%, #003d80 100%);
            color: #ffffff;
            border: none;
            padding: 10px 0;
            border-radius: 8px;
            font-weight: 600;
            letter-spacing: 1.5px;
            font-size: 0.9rem;
            margin-top: 14px;
            transition: transform 0.12s, box-shadow 0.2s, background 0.2s;
        }
        .stButton > button:hover,
        [data-testid="stFormSubmitButton"] > button:hover {
            background: linear-gradient(135deg, #006fd6 0%, #004a99 100%);
            box-shadow: 0 10px 24px rgba(0, 86, 179, 0.45);
            transform: translateY(-1px);
        }
        .stButton > button:active,
        [data-testid="stFormSubmitButton"] > button:active { transform: translateY(0); }

        /* Esconde a borda do form na tela de login (visual mais limpo) */
        [data-testid="stForm"] { border: none !important; padding: 0 !important; background: transparent !important; }

        /* Rodape discreto */
        .login-footer {
            text-align: center;
            color: #4a4a4a;
            font-size: 0.7rem;
            margin-top: 34px;
            letter-spacing: 1.8px;
            font-weight: 500;
        }
        </style>
        <div class="login-header">
            <img src="https://www.uerj.br/wp-content/uploads/2018/02/logomarca-uerj.png" alt="UERJ">
            <div class="brand">SERVPEN</div>
            <div class="tagline">Gestão de Projetos de Engenharia</div>
        </div>
    """, unsafe_allow_html=True)

    # Envolve em st.form: Enter em qualquer input submete o formulario
    with st.form("login_form", clear_on_submit=False, border=False):
        u = st.text_input("Usuário", placeholder="Nome completo, como cadastrado")
        s = st.text_input("Senha", type="password", placeholder="••••••••")
        submit = st.form_submit_button("ACESSAR", use_container_width=True)

    if submit:
        if u and s and auth.validar_login(u, s):
            # Cria sessao no banco (valida 7 dias) e poe token na URL
            _token = db.criar_sessao(u, dias=7)
            st.query_params['t'] = _token
            db.log_aud(u, 'login', 'sessao', None, 'sucesso')
            st.success("Login realizado!")
            st.rerun()
        else:
            # Distingue bloqueio por rate-limit de senha inválida (auth.py
            # popula `_login_bloqueado_ate` quando bloqueia).
            _bloq_ate = st.session_state.pop('_login_bloqueado_ate', None)
            if _bloq_ate:
                _mins = max(1, int((_bloq_ate - datetime.now()).total_seconds() / 60))
                db.log_aud(u or '(vazio)', 'login_bloqueado', 'sessao', None,
                           f'rate limit ate {_bloq_ate.isoformat(timespec="seconds")}')
                st.error(
                    f"🛑 Muitas tentativas falhas para **{u}**. "
                    f"Tente novamente em ~{_mins} min."
                )
            else:
                db.log_aud(u or '(vazio)', 'login_falha', 'sessao', None,
                           'usuario ou senha invalidos')
                st.error("Usuário ou senha incorretos.")

    # ── ESQUECI MINHA SENHA (pergunta secreta) ──────────────────────
    with st.expander("🔑 Esqueci minha senha"):
        rec_user = st.text_input("Seu usuário", key="rec_user",
                                 placeholder="Nome completo, como cadastrado")
        if rec_user:
            _pergunta = db.obter_pergunta_secreta(rec_user)
            if not _pergunta:
                st.info(
                    "Esse usuário não tem pergunta secreta cadastrada. "
                    "Peça a um Gestor para definir uma na aba Equipe (ou redefinir sua senha)."
                )
            else:
                st.markdown(f"**Pergunta:** {_pergunta}")
                rec_resp = st.text_input("Sua resposta", key="rec_resp", type="password")
                rec_nova = st.text_input("Nova senha", key="rec_nova", type="password")
                rec_nova2 = st.text_input("Repita a nova senha", key="rec_nova2", type="password")
                if st.button("Redefinir senha", key="rec_btn", use_container_width=True):
                    if not rec_resp.strip():
                        st.warning("Responda a pergunta secreta.")
                    elif not rec_nova or rec_nova != rec_nova2:
                        st.warning("As duas senhas novas precisam ser iguais (e não vazias).")
                    elif not db.validar_resposta_secreta(rec_user, rec_resp):
                        db.log_aud(rec_user, 'reset_senha_falha', 'usuario', None, 'resposta secreta errada')
                        st.error("Resposta secreta incorreta.")
                    else:
                        db.redefinir_senha(rec_user, rec_nova)
                        db.log_aud(rec_user, 'reset_senha', 'usuario', None, 'via pergunta secreta')
                        st.success("Senha redefinida! Pode fechar e entrar com a nova senha.")

    st.markdown(
        '<div class="login-footer">SERVPEN ENGENHARIA &nbsp;·&nbsp; UERJ</div>',
        unsafe_allow_html=True,
    )
    st.stop()

else:
    # --- SISTEMA LOGADO ---
    # Avatar circular + identificação no topo do sidebar
    _me_side = db.obter_usuario(st.session_state.usuario) or {}
    st.sidebar.markdown(
        _avatar_circular_html(_me_side.get('avatar_path'), size=88),
        unsafe_allow_html=True,
    )
    st.sidebar.markdown(
        f"<div style='text-align:center;font-weight:700;font-size:1.05rem;margin-top:8px'>"
        f"{st.session_state.usuario}</div>"
        f"<div style='text-align:center;opacity:0.7;font-size:0.8rem;margin-bottom:8px'>"
        f"{st.session_state.get('perfil', 'Gestor')}</div>",
        unsafe_allow_html=True,
    )

    # Botão Meu Perfil (abre o modal de edição própria)
    if st.sidebar.button("👤 Meu Perfil", use_container_width=True, key="btn_meu_perfil"):
        _dialog_meu_perfil()

    if st.sidebar.button("🔴 Sair do Sistema"):
        # Invalida sessao no banco + limpa estado + tira ?t= da URL
        db.log_aud(st.session_state.usuario, 'logout', 'sessao', None, '')
        db.deletar_sessao(st.query_params.get('t'))
        st.query_params.clear()
        st.session_state.autenticado = False
        st.session_state.usuario = None
        st.session_state.perfil = None
        st.rerun()

    # --- TOGGLE DE TEMA (Claro / Escuro) ---
    st.sidebar.divider()
    _label_botao_tema = "☀️ Mudar para Tema Claro" if not _eh_tema_claro() else "🌙 Mudar para Tema Escuro"
    if st.sidebar.button(_label_botao_tema, use_container_width=True, key="btn_tema"):
        st.session_state.tema = 'light' if st.session_state.tema == 'dark' else 'dark'
        st.rerun()
    st.sidebar.caption(f"Tema atual: **{'Claro' if _eh_tema_claro() else 'Escuro'}**")

    # --- CARREGAMENTO ÚNICO DE DADOS (cacheado, ver _load_* no topo) ---
    # Visibilidade: Gestor vê tudo; Projetista/Visualizador vê projetos onde seu
    # nome consta + projetos ganhos por menção. _load_df_p cacheia por (usuario, perfil).
    try:
        df_p = _load_df_p(st.session_state.usuario, st.session_state.get('perfil'))
        df_u = _load_df_u()
        df_d = _load_df_d()
    except Exception as e:
        st.error(f"Erro ao carregar banco: {e}")
        df_p = pd.DataFrame()
        df_u = pd.DataFrame()
        df_d = pd.DataFrame()

    # Aviso visivel pra Visualizador (read-only) - rodapesinho no sidebar
    if not _pode_editar():
        st.sidebar.warning("👁️ **Modo Visualização**: você não pode criar, editar ou excluir registros.", icon="🔒")

    # Contador de não lidos no diário (relatos novos + menções @ não dispensadas).
    # IMPORTANTE: respeita a visibilidade do usuario (df_p ja eh filtrado para o
    # perfil dele acima na linha ~874). Sem isso, Projetista veria contagem inflada
    # com relatos de projetos que ele nao tem acesso.
    _projs_visiveis = (
        None if _pode_gestor() else
        (df_p['id'].tolist() if not df_p.empty else [])
    )
    _nao_lidos_diario = db.total_nao_lidos_diario_visivel(
        st.session_state.usuario, _projs_visiveis,
    )
    _mencoes_pendentes_total = db.contar_mencoes_pendentes(st.session_state.usuario)
    _total_diario_badge = _nao_lidos_diario + _mencoes_pendentes_total
    _label_diario = f"📝 Diário 🔴 {_total_diario_badge}" if _total_diario_badge else "📝 Diário"

    # Contador de não lidas no chat
    _qtd_nao_lidas = db.contar_nao_lidas(st.session_state.usuario)
    _label_chat = f"💬 Chat 🔴 {_qtd_nao_lidas}" if _qtd_nao_lidas else "💬 Chat"

    _labels_abas = [
        "📊 Dashboard",
        "📋 Kanban",
        "➕ Novo Projeto",
        _label_diario,        # ← substituído
        "📁 Arquivos",
        "👥 Equipe",
        _label_chat,
        "📅 Agenda",
    ]
    if _pode_gestor():
        _labels_abas.append("🛡️ Auditoria")
        _labels_abas.append("🔑 Acessos")

    tabs = st.tabs(_labels_abas)
    if _pode_gestor():
        t_bi, t_kanban, t_novo, t_diario, t_arquivos, t_equipe, t_chat, t_agenda, t_auditoria, t_acessos = tabs
    else:
        t_bi, t_kanban, t_novo, t_diario, t_arquivos, t_equipe, t_chat, t_agenda = tabs
        t_auditoria = None
        t_acessos = None

    # --- ABA 1: DASHBOARD BI (COMPLETA E CORRIGIDA) ---
    with t_bi:
        st.markdown(
            """
            <div style="display:flex;justify-content:space-between;align-items:flex-end;
                        padding-bottom:6px;border-bottom:1px solid rgba(255,255,255,0.06);
                        margin-bottom:14px;">
                <div>
                    <div style="font-size:1.6rem;font-weight:800;color:#e5e7eb;
                                letter-spacing:.3px;line-height:1.1;">
                        📊 Painel Gerencial
                    </div>
                    <div style="font-size:.85rem;color:#94a3b8;margin-top:2px;">
                        Visão executiva da carteira de projetos, equipe e progresso técnico.
                    </div>
                </div>
                <div style="font-size:.75rem;color:#94a3b8;text-align:right;">
                    Atualizado em<br>
                    <b style="color:#cbd5e1;">""" + datetime.now().strftime('%d/%m/%Y %H:%M') + """</b>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # 1. SEGURANÇA E LIMPEZA DE DADOS
        df_p_limpo = df_p[df_p['projeto'].notna() & (df_p['projeto'] != '')].copy() if not df_p.empty else pd.DataFrame()

        # ── SEÇÃO 1: KPIs ──────────────────────────────────────────
        _section_header(
            "📌",
            "Indicadores Principais",
            "Métricas do estado atual respeitando seu perfil de acesso.",
            cor="#0891b2",
        )

        # 2. MÉTRICAS DINÂMICAS
        c1, c2, c3, c4 = st.columns(4)
        
        if st.session_state.perfil == "Projetista":
            c1.metric("Meus Projetos Ativos", len(df_p_limpo[df_p_limpo['status'] == 'Ativo']) if not df_p_limpo.empty else 0)
            c2.metric("Meus Projetos Parados", len(df_p_limpo[df_p_limpo['status'] == '🛑 Parado']) if not df_p_limpo.empty else 0)
            
            meus_ids = df_p_limpo['id'].tolist() if not df_p_limpo.empty else []
            minhas_duvidas = df_d[df_d['projeto_id'].isin(meus_ids) & (df_d['resolvido'] == 0)] if not df_d.empty else pd.DataFrame()
            c3.metric("Minhas Dúvidas", len(minhas_duvidas))
            c4.metric("Equipe Online", len(df_u))
        else:
            c1.metric("Em Execução",
                  len(df_p_limpo[df_p_limpo['status'] == 'Ativo'])
                  if not df_p_limpo.empty else 0)

            c2.metric("Em Espera",
                    len(df_p_limpo[df_p_limpo['status'] == 'Em Espera'])
                    if not df_p_limpo.empty else 0)

            c3.metric("Dúvidas Pendentes",
                    len(df_d[df_d['resolvido'] == 0]) if not df_d.empty else 0)

            c4.metric("Membros na Equipe", len(df_u))

        st.divider()
        
        
        # 3. GRÁFICO DE GANTT
        _section_header(
            "📅",
            "Cronograma Integrado (Gantt)",
            "Linha do tempo dos projetos no recorte selecionado. Toggle abaixo "
            "alterna entre projeto inteiro e detalhamento por etapas.",
            cor="#3b82f6",
        )

        _toggle_etapas = st.toggle(
            "Detalhar por etapas",
            value=False,
            key="gantt_toggle_etapas",
            help="Ativado: mostra cada etapa como barra separada. Desativado: mostra o projeto inteiro.",
        )

        if not df_p_limpo.empty:
            # Obter a lista de todos os projetos para o filtro
            todos_projetos_gantt = df_p_limpo['projeto'].unique().tolist()

            # Persistencia da selecao do Gantt entre reruns.
            #
            # Por que NAO usamos `key="gantt_projetos_selecionados"` direto no multiselect:
            # se o codigo escreve em st.session_state[key] (pra limpar opcoes que sumiram,
            # por exemplo), o Streamlit considera isso "value set via Session State API"
            # e conflita com o default implicito do widget -> warning amarelo.
            #
            # Solucao: guardamos a selecao em uma chave SEPARADA (com underline) que nao
            # eh a key de nenhum widget. Alimentamos o multiselect via `default=` e
            # capturamos o retorno pra salvar na chave separada. Sem warning, mesmo
            # comportamento.
            _key_gantt_user = "_gantt_projetos_selecionados_user"
            _gantt_atual = st.session_state.get(_key_gantt_user, todos_projetos_gantt[:])
            # Limpa itens que nao existem mais (projeto excluido entre reruns)
            _gantt_atual = [item for item in _gantt_atual if item in todos_projetos_gantt]
            if not _gantt_atual:
                _gantt_atual = todos_projetos_gantt[:]

            projetos_selecionados_gantt = st.multiselect(
                "Selecione os projetos para o Gantt:",
                options=todos_projetos_gantt,
                default=_gantt_atual,
                help="Selecione os projetos que deseja visualizar no cronograma.",
            )

            # Salva pra proxima render preservar a escolha do usuario
            st.session_state[_key_gantt_user] = projetos_selecionados_gantt

            if not projetos_selecionados_gantt:
                _empty_state(
                    "📊",
                    "Nenhum projeto selecionado pro Gantt",
                    "Use o multiselect acima pra escolher os projetos "
                    "que você quer ver no cronograma.",
                    cor_borda="#3b82f6",
                )
            else:
                # Filtrar df_p_limpo pelos projetos selecionados
                df_p_filtrado_gantt = df_p_limpo[df_p_limpo['projeto'].isin(projetos_selecionados_gantt)].copy()

                if _toggle_etapas:
                    # Busca etapas de todos os projetos
                    _etapas_todas = db.listar_etapas_todos_projetos()

                    if _etapas_todas:
                        # Constrói DataFrame com datas reais de cada etapa
                        _rows_g = []
                        for et in _etapas_todas:
                            # Filtra apenas etapas de projetos selecionados no multiselect
                            if et['projeto'] not in projetos_selecionados_gantt:
                                continue

                            try:
                                _d_ini = pd.to_datetime(et['data_inicio'])
                                if pd.isna(_d_ini): continue
                                _et_ini = _d_ini + pd.Timedelta(days=int(et['dias_offset']))
                                _et_fim = _et_ini + pd.Timedelta(days=max(1, int(et['duracao_dias'])) - 1)
                                _rows_g.append({
                                    'projeto': et['projeto'],
                                    'etapa': f"  ↳ {et['nome']}",
                                    'data_inicio': _et_ini,
                                    'data_fim': _et_fim,
                                    'tipo': 'Etapa',
                                })
                            except Exception:
                                continue

                        df_gantt_et = pd.DataFrame(_rows_g)
                        if not df_gantt_et.empty:
                            fig_gantt = px.timeline(
                                df_gantt_et,
                                x_start="data_inicio", x_end="data_fim", y="etapa",
                                color="projeto",
                                hover_data=["projeto"],
                                labels={"etapa": "Etapa", "projeto": "Projeto",
                                        "data_inicio": "Início", "data_fim": "Fim"},
                            )
                            fig_gantt.update_yaxes(autorange="reversed", title_text="")
                            fig_gantt.update_xaxes(title_text="Período")
                            fig_gantt.update_layout(
                                height=max(350, len(df_gantt_et) * 28 + 80),
                                legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                            xanchor="right", x=1),
                                margin=dict(l=10, r=10, t=60, b=40),
                            )
                            _estiliza_plotly(fig_gantt)
                            st.plotly_chart(fig_gantt, use_container_width=True)
                        else:
                            _empty_state(
                                "🏁",
                                "Sem etapas nos projetos escolhidos",
                                "Os projetos selecionados ainda não têm etapas. "
                                "Abra cada um pelo Kanban → ⚙️ Detalhes → "
                                "🏁 Etapas pra cadastrar.",
                                cor_borda="#3b82f6",
                            )
                    else:
                        _empty_state(
                            "🏁",
                            "Nenhuma etapa cadastrada",
                            "Pra cadastrar etapas de um projeto: Kanban → "
                            "**⚙️ Detalhes** no card → seção **🏁 Etapas do Projeto**.",
                            cor_borda="#3b82f6",
                        )
                else:
                    # Gantt padrão por projeto
                    # Usar df_p_filtrado_gantt aqui
                    df_plot = df_p_filtrado_gantt.copy()
                    df_plot['data_inicio'] = pd.to_datetime(df_plot['data_inicio'])
                    df_plot['data_fim']    = pd.to_datetime(df_plot['data_fim'])
                    df_plot = df_plot.dropna(subset=['data_inicio','data_fim'])

                    if not df_plot.empty:
                        fig_gantt = px.timeline(
                            df_plot, x_start="data_inicio", x_end="data_fim", y="projeto",
                            color="prioridade", hover_data=["projetista","status"],
                            labels={"projeto":"Projeto","data_inicio":"Início","data_fim":"Entrega prevista",
                                    "prioridade":"Prioridade","projetista":"Projetista","status":"Status"},
                            color_discrete_map={"Máxima":"#ff4d4d","Média":"#ff9f43","Mínima":"#2ecc71"},
                        )
                        fig_gantt.update_yaxes(autorange="reversed", title_text="")
                        fig_gantt.update_xaxes(title_text="Período")
                        fig_gantt.update_layout(
                            height=420,
                            legend=dict(title=dict(text="<b>Prioridade</b>"),
                                        orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                            margin=dict(l=10, r=10, t=60, b=40),
                        )
                        _estiliza_plotly(fig_gantt)
                        st.plotly_chart(fig_gantt, use_container_width=True)
                    else:
                        st.info("Nenhum projeto com datas válidas para exibir no Gantt.")
        else:
            _empty_state(
                "🛠️",
                "Nenhum projeto ativo no momento",
                "Cadastre projetos novos pela aba **➕ Novo Projeto** e "
                "mova pra status **Ativo** no Kanban quando começar.",
                cor_borda="#3b82f6",
            )

        st.divider() # Adicionado para garantir que o divider original seja mantidopara exibir no cronograma.")

        # ── 4. GRÁFICO DE PIZZA: VOLUME POR PESSOA ───────────────────
        _section_header(
            "🥧",
            "Volume de Trabalho por Pessoa",
            "Quantos projetos cada projetista carrega no momento. Útil pra "
            "balancear a carga e identificar sobrecarga.",
            cor="#7c3aed",
        )

        if not df_p_limpo.empty and not df_u.empty:
            lista_oficial = df_u['nome'].tolist()

            contagem_bruta = (
                df_p_limpo['projetista']
                .str.split(', ')
                .explode()
                .pipe(lambda s: s[s.isin(lista_oficial)])
                .value_counts()
                .reset_index()
            )
            contagem_bruta.columns = ['Projetista', 'Qtd']

            if not contagem_bruta.empty:
                todos_projetistas_pizza = contagem_bruta['Projetista'].unique().tolist()

                # Inicializa o session_state para a seleção de projetistas da pizza se não existir
                _key_pizza_sel = "pizza_projetistas_selecionados"
                if _key_pizza_sel not in st.session_state:
                    st.session_state[_key_pizza_sel] = todos_projetistas_pizza[:] # Seleciona todos por padrão

                # Garante que a seleção atual não contém opções que não existem mais
                st.session_state[_key_pizza_sel] = [item for item in st.session_state[_key_pizza_sel] if item in todos_projetistas_pizza]

                # Caixa de seleção (st.multiselect) para projetistas
                projetistas_selecionados_pizza = st.multiselect(
                    "Selecione os projetistas para o gráfico de pizza:",
                    options=todos_projetistas_pizza,
                    default=st.session_state[_key_pizza_sel],
                    key=_key_pizza_sel, # Usa a chave para persistência
                    help="Selecione os projetistas que deseja incluir no gráfico de volume de trabalho.",
                )

                if not projetistas_selecionados_pizza:
                    st.info("Nenhum projetista selecionado para o gráfico de pizza.")
                else:
                    # Filtrar a contagem bruta pelos projetistas selecionados
                    contagem = contagem_bruta[contagem_bruta['Projetista'].isin(projetistas_selecionados_pizza)].copy()

                    if not contagem.empty:
                        # Paleta corporativa com contraste adequado
                        PALETA_PIZZA = [
                            "#0056b3", "#00a8cc", "#f59e0b", "#10b981",
                            "#8b5cf6", "#ef4444", "#ec4899", "#14b8a6",
                            "#f97316", "#6366f1",
                        ]

                        fig_pizza = px.pie(
                            contagem,
                            names='Projetista',
                            values='Qtd',
                            color='Projetista',
                            color_discrete_sequence=PALETA_PIZZA,
                            hole=0.42,           # rosca — mais elegante e corporativo
                            custom_data=['Qtd'],
                        )
                        fig_pizza.update_traces(
                            textposition='outside',
                            textinfo='label+percent',
                            textfont_size=13,
                            hovertemplate="<b>%{label}</b><br>%{value} projeto(s) — %{percent}<extra></extra>",
                            pull=[0.04] * len(contagem),   # leve destaque em todas as fatias
                            marker=dict(line=dict(color='rgba(0,0,0,0.15)', width=1.5)),
                        )
                        # Texto central da rosca
                        total_proj = int(contagem['Qtd'].sum())
                        fig_pizza.add_annotation(
                            text=f"<b>{total_proj}</b><br><span style='font-size:10px'>projetos</span>",
                            x=0.5, y=0.5,
                            font_size=18,
                            showarrow=False,
                            xref="paper", yref="paper",
                        )
                        fig_pizza.update_layout(
                            height=420,
                            legend=dict(
                                title=dict(text="<b>Projetista</b>"),
                                orientation="v",
                                yanchor="middle", y=0.5,
                                xanchor="left",  x=1.02,
                                font=dict(size=12),
                                bgcolor="rgba(0,0,0,0)",
                            ),
                            margin=dict(l=20, r=160, t=30, b=30),
                        )
                        _estiliza_plotly(fig_pizza)
                        st.plotly_chart(fig_pizza, use_container_width=True)

                        # Cards resumo abaixo da pizza
                        cols_resumo = st.columns(min(len(contagem), 5))
                        for i, (_, row) in enumerate(contagem.iterrows()):
                            cor = PALETA_PIZZA[i % len(PALETA_PIZZA)]
                            with cols_resumo[i % len(cols_resumo)]:
                                st.markdown(
                                    f"<div style='border-left:4px solid {cor};padding:8px 12px;"
                                    f"border-radius:6px;background:rgba(255,255,255,0.03);"
                                    f"margin-bottom:6px;'>"
                                    f"<div style='font-size:.75rem;color:#94a3b8;'>{row['Projetista']}</div>"
                                    f"<div style='font-size:1.4rem;font-weight:700;color:{cor};'>"
                                    f"{row['Qtd']}</div>"
                                    f"<div style='font-size:.7rem;color:#6b7280;'>projeto(s)</div>"
                                    f"</div>",
                                    unsafe_allow_html=True,
                                )
                    else:
                        st.info("Nenhum dado de projetista para exibir com a seleção atual.")
            else:
                st.info("Nenhum dado de projetista para exibir.")
        else:
            st.info("Cadastre projetos e membros para ver a distribuição de carga.")

        st.divider()

        # ── 5. EVOLUÇÃO TÉCNICA COM SELEÇÃO DE PROJETOS ──────────────
        _section_header(
            "📉",
            "Evolução Técnica por Projeto",
            "Progresso de cada disciplina dentro de cada projeto. Use o toggle "
            "abaixo pra escolher entre **Barras**, **Heatmap** ou **Tabela**.",
            cor="#16a34a",
        )

        try:
            df_evolucao = pd.read_sql("""
                SELECT p.id as projeto_id, p.projeto, p.projetista,
                    pd.disciplina, pd.percentual
                FROM progresso_disciplinas pd
                JOIN projetos p ON pd.projeto_id = p.id
                ORDER BY p.projeto, pd.disciplina
            """, db.get_engine())

            if not df_evolucao.empty:
                projetos_com_dados = df_evolucao['projeto'].unique().tolist()

                # Default: todos os projetos com dados (heatmap escala bem)
                _default_sel = st.session_state.get(
                    "evolucao_sel_projetos", projetos_com_dados
                )
                _default_sel = [p for p in _default_sel if p in projetos_com_dados]
                if not _default_sel:
                    _default_sel = projetos_com_dados

                projetos_sel = st.multiselect(
                    "Projetos exibidos no heatmap",
                    options=projetos_com_dados,
                    default=_default_sel,
                    key="evolucao_sel_projetos",  # persistência entre runs
                    help="O heatmap aceita N projetos; ordena os mais avançados "
                         "no topo. Mais avançado = verde · Mais atrasado = vermelho.",
                )

                if not projetos_sel:
                    _empty_state(
                        "📊",
                        "Nenhum projeto selecionado",
                        "Use o multiselect acima pra escolher os projetos que "
                        "quer comparar.",
                        cor_borda="#3b82f6",
                    )
                else:
                    # ════════════════════════════════════════════════════════
                    #  3 VISUALIZAÇÕES SELECIONÁVEIS
                    #  - Heatmap: matriz Projeto × Disciplina (denso, visão única)
                    #  - Barras agrupadas: 1 gráfico só, barras lado a lado por
                    #    disciplina, eixo X = projeto. NÃO usa facet (que embolava).
                    #  - Tabela: pivot HTML compacta pra triagem
                    # ════════════════════════════════════════════════════════
                    df_graf = df_evolucao[
                        df_evolucao['projeto'].isin(projetos_sel)
                    ].copy()

                    # Pivot reutilizado por Heatmap e Tabela
                    _pivot = df_graf.pivot_table(
                        index='projeto', columns='disciplina',
                        values='percentual', aggfunc='mean',
                    )
                    # Ordena projetos por progresso médio (mais completos no topo)
                    _ordem_proj = _pivot.mean(axis=1).sort_values(ascending=True).index
                    _pivot = _pivot.loc[_ordem_proj]
                    _pivot = _pivot.reindex(sorted(_pivot.columns), axis=1)

                    _modo_viz = _pill_select(
                        st, "Visualização",
                        options=["Heatmap", "Barras", "Tabela"],
                        default="Barras",
                        key="evolucao_modo_viz",
                        label_visibility="collapsed",
                    ) or "Barras"

                    # ── HEATMAP ────────────────────────────────────────
                    if _modo_viz == "Heatmap":
                        _z = _pivot.values
                        _text = [
                            [f"{v:.0f}%" if pd.notna(v) else "—" for v in row]
                            for row in _z
                        ]
                        import plotly.graph_objects as go
                        fig_disc = go.Figure(data=go.Heatmap(
                            z=_z,
                            x=_pivot.columns.tolist(),
                            y=_pivot.index.tolist(),
                            text=_text,
                            texttemplate="%{text}",
                            textfont={"size": 11, "color": "#fff"},
                            colorscale=[
                                [0.00, "#7f1d1d"],
                                [0.25, "#b91c1c"],
                                [0.50, "#d97706"],
                                [0.75, "#65a30d"],
                                [1.00, "#16a34a"],
                            ],
                            zmin=0, zmax=100,
                            colorbar=dict(
                                title=dict(text="Progresso (%)", side="right"),
                                tickvals=[0, 25, 50, 75, 100],
                                ticktext=["0%", "25%", "50%", "75%", "100%"],
                                thickness=14, len=0.85,
                            ),
                            hovertemplate=("<b>%{y}</b><br>"
                                           "Disciplina: %{x}<br>"
                                           "Progresso: %{z:.0f}%<extra></extra>"),
                            xgap=2, ygap=2,
                        ))
                        fig_disc.update_layout(
                            height=max(280, 36 * len(_pivot.index) + 120),
                            margin=dict(t=20, b=60, l=10, r=10),
                            xaxis=dict(side="bottom", tickangle=-30,
                                       title=None, fixedrange=True),
                            yaxis=dict(title=None, fixedrange=True,
                                       autorange="reversed"),
                        )
                        _estiliza_plotly(fig_disc)
                        st.plotly_chart(fig_disc, use_container_width=True)

                    # ── BARRAS POR PROJETO (subplots arrumados) ───────
                    elif _modo_viz == "Barras":
                        # Filtra projetos sem dados (todos zeros ou NaN) pra
                        # não desperdiçar subplots vazios.
                        _proj_com_dados = (
                            df_graf.groupby('projeto')['percentual']
                            .sum().pipe(lambda s: s[s > 0]).index.tolist()
                        )
                        if not _proj_com_dados:
                            _empty_state(
                                "📉",
                                "Sem progresso registrado",
                                "Os projetos selecionados ainda não têm "
                                "percentual de progresso lançado em nenhuma "
                                "disciplina.",
                                cor_borda="#d97706",
                            )
                        else:
                            df_graf_v = df_graf[
                                df_graf['projeto'].isin(_proj_com_dados)
                            ].copy()

                            # Layout: 2 cols se até 4 projetos, senão 3 cols.
                            # Menos subplots por linha = mais respiro,
                            # menos chance de label do projeto colidir com
                            # eixo X do próximo.
                            n_cols_f = 2 if len(_proj_com_dados) <= 4 else 3
                            n_linhas_f = -(-len(_proj_com_dados) // n_cols_f)

                            fig_disc = px.bar(
                                df_graf_v,
                                x="disciplina",
                                y="percentual",
                                color="disciplina",
                                facet_col="projeto",
                                facet_col_wrap=n_cols_f,
                                facet_row_spacing=0.18,
                                facet_col_spacing=0.05,
                                text_auto=".0f",
                                range_y=[0, 110],
                                labels={
                                    "disciplina": "",
                                    "percentual": "Progresso (%)",
                                },
                                hover_data={"projetista": True,
                                            "projeto": False},
                                category_orders={
                                    "projeto": _proj_com_dados,
                                    "disciplina": sorted(
                                        df_graf_v['disciplina'].unique()
                                    ),
                                },
                            )
                            fig_disc.update_traces(
                                textposition="outside",
                                textfont_size=10,
                                cliponaxis=False,
                            )
                            # Eixos X: tick angle, sem matches pra cada
                            # subplot mostrar suas disciplinas.
                            fig_disc.update_xaxes(
                                matches=None,
                                showticklabels=True,
                                tickangle=-30,
                                title_text="",
                                tickfont_size=10,
                            )
                            # Eixos Y: só primeira coluna mostra label
                            # "Progresso (%)". As outras herdam range mas
                            # sem ticks/label duplicados.
                            fig_disc.update_yaxes(
                                matches=None,
                                range=[0, 115],
                                showticklabels=False,
                                title_text="",
                            )
                            # Re-mostra ticks só nos eixos Y da coluna esquerda
                            for facet_i in range(len(_proj_com_dados)):
                                _coluna_atual = facet_i % n_cols_f
                                if _coluna_atual == 0:
                                    _ax_key = ('yaxis' if facet_i == 0
                                               else f'yaxis{facet_i+1}')
                                    fig_disc.update_layout(
                                        **{_ax_key: dict(
                                            showticklabels=True,
                                            title_text="Progresso (%)",
                                            title_font_size=10,
                                        )}
                                    )

                            # Título de cada subplot = só o nome do projeto
                            # (sem "projeto=" e em bold, em fonte menor).
                            fig_disc.for_each_annotation(
                                lambda a: a.update(
                                    text=f"<b>{a.text.split('=')[-1]}</b>",
                                    font=dict(size=11, color="#cbd5e1"),
                                )
                            )
                            fig_disc.update_layout(
                                height=max(360, n_linhas_f * 330 + 100),
                                margin=dict(t=40, b=110, l=50, r=10),
                                legend=dict(
                                    title=dict(text="<b>Disciplina</b>"),
                                    orientation="h",
                                    yanchor="top", y=-0.12 / n_linhas_f,
                                    xanchor="center", x=0.5,
                                    font=dict(size=10),
                                ),
                                bargap=0.25,
                            )
                            _estiliza_plotly(fig_disc)
                            st.plotly_chart(fig_disc, use_container_width=True)

                    # ── TABELA (pivot HTML compacto) ──────────────────
                    else:  # Tabela
                        def _cor_cel(v):
                            if pd.isna(v): return "#1f2937"
                            v = float(v)
                            if v >= 75: return "#16a34a"
                            if v >= 50: return "#65a30d"
                            if v >= 25: return "#d97706"
                            return "#b91c1c"

                        _ths = "".join(
                            f"<th style='padding:6px 10px;font-size:11px;"
                            f"color:#94a3b8;text-align:center;border-bottom:"
                            f"1px solid #1f2937;'>{c}</th>"
                            for c in _pivot.columns
                        )
                        _media_row = _pivot.mean(axis=1)
                        _rows_html = ""
                        for proj, row in _pivot.iterrows():
                            _cells = "".join(
                                f"<td style='padding:6px;text-align:center;"
                                f"background:{_cor_cel(v)};color:#fff;"
                                f"font-weight:600;font-size:12px;'>"
                                f"{'—' if pd.isna(v) else f'{v:.0f}%'}</td>"
                                for v in row
                            )
                            _med = _media_row[proj]
                            _rows_html += (
                                f"<tr>"
                                f"<td style='padding:6px 10px;font-weight:600;"
                                f"color:#e5e7eb;border-bottom:1px solid #1f2937;'>"
                                f"{proj}</td>{_cells}"
                                f"<td style='padding:6px;text-align:center;"
                                f"background:{_cor_cel(_med)};color:#fff;"
                                f"font-weight:700;font-size:12px;'>"
                                f"{_med:.0f}%</td>"
                                f"</tr>"
                            )
                        st.markdown(
                            f"<div style='overflow-x:auto;'>"
                            f"<table style='width:100%;border-collapse:separate;"
                            f"border-spacing:2px;'>"
                            f"<thead><tr>"
                            f"<th style='padding:6px 10px;font-size:11px;"
                            f"color:#94a3b8;text-align:left;border-bottom:"
                            f"1px solid #1f2937;'>Projeto</th>{_ths}"
                            f"<th style='padding:6px 10px;font-size:11px;"
                            f"color:#fbbf24;text-align:center;border-bottom:"
                            f"1px solid #1f2937;'>MÉDIA</th>"
                            f"</tr></thead>"
                            f"<tbody>{_rows_html}</tbody>"
                            f"</table></div>",
                            unsafe_allow_html=True,
                        )

                    # Sumário de leitura — sempre embaixo (qualquer visualização)
                    _media_geral = float(_pivot.stack().mean()) \
                                   if not _pivot.stack().empty else 0.0
                    _top_proj = _pivot.mean(axis=1).idxmax() \
                                if not _pivot.empty else "—"
                    _top_pct  = float(_pivot.mean(axis=1).max()) \
                                if not _pivot.empty else 0
                    _gap_proj = _pivot.mean(axis=1).idxmin() \
                                if not _pivot.empty else "—"
                    _gap_pct  = float(_pivot.mean(axis=1).min()) \
                                if not _pivot.empty else 0

                    cR1, cR2, cR3 = st.columns(3)
                    cR1.metric("📈 Progresso médio (todos)",
                               f"{_media_geral:.0f}%")
                    cR2.metric(f"🏆 Mais avançado", _top_proj,
                               delta=f"{_top_pct:.0f}%", delta_color="off")
                    cR3.metric(f"🐢 Mais atrasado", _gap_proj,
                               delta=f"{_gap_pct:.0f}%", delta_color="off")

                    # Cards de resumo
                    st.markdown("**Progresso médio por projeto:**")
                    res_cols = st.columns(len(projetos_sel))
                    for i, proj in enumerate(projetos_sel):
                        _media = df_graf[df_graf['projeto'] == proj]['percentual'].mean()
                        _cor   = ("#10b981" if _media >= 80
                                else "#f59e0b" if _media >= 40
                                else "#ef4444")
                        with res_cols[i]:
                            st.markdown(
                                f"<div style='border:1px solid {_cor};"
                                f"border-top:4px solid {_cor};border-radius:8px;"
                                f"padding:10px;text-align:center;"
                                f"background:rgba(255,255,255,.02);'>"
                                f"<div style='font-size:.72rem;color:#94a3b8;"
                                f"margin-bottom:4px;overflow:hidden;"
                                f"text-overflow:ellipsis;white-space:nowrap;'"
                                f" title='{proj}'>"
                                f"{proj[:22]}{'…' if len(proj)>22 else ''}</div>"
                                f"<div style='font-size:1.6rem;font-weight:700;"
                                f"color:{_cor};'>{_media:.0f}%</div>"
                                f"</div>",
                                unsafe_allow_html=True,
                            )
                            st.progress(float(_media) / 100.0)
                
        except Exception as e:
            st.error(f"Erro ao carregar evolução técnica: {e}")

        # 5. CARDS COLORIDOS
        if st.session_state.perfil == "Gestor":
            _section_header(
                "👥",
                "Detalhamento da Equipe",
                "Distribuição dos projetos por projetista e visão da carga atual.",
                cor="#7c3aed",
            )
            lista_exibicao = df_u['nome'].tolist() if not df_u.empty else []
        else:
            _section_header(
                "👤",
                "Minha Carga de Trabalho",
                "Seus projetos, pendências e ações imediatas.",
                cor="#7c3aed",
            )
            lista_exibicao = [st.session_state.usuario]

        cols_eq = st.columns(3)
        cores_equipe = ["#00d4ff", "#ff9f43", "#ff4d4d", "#2ecc71", "#a29bfe", "#fd79a8"]

        for i, user in enumerate(lista_exibicao):
            cor_atual = cores_equipe[i % len(cores_equipe)]
            with cols_eq[i % 3]:
                projs_user = df_p_limpo[df_p_limpo['projetista'].str.contains(user, na=False)] if not df_p_limpo.empty else pd.DataFrame()
                demandas = projs_user['projeto'].tolist() if not projs_user.empty else []
                
                demandas_html = "".join([f'<div class="badge-projeto" style="border-left: 3px solid {cor_atual};">📌 {d}</div><br>' for d in demandas]) if demandas else "Sem projetos"
                
                st.markdown(f"""
                    <div class="card-projetista" style="border-top: 5px solid {cor_atual};">
                        <div class="nome-projetista" style="color: {cor_atual}; margin-bottom: 10px; font-weight: bold;">👤 {user}</div>
                        <div class="demanda-texto"><b>Demandas Atuais:</b><br><div style="margin-top: 10px;">{demandas_html}</div></div>
                    </div>
                """, unsafe_allow_html=True)

        st.markdown("---")
        _section_header(
            "📥",
            "Exportar Relatórios",
            "Baixa snapshots do estado atual em Excel, PDF e CSV.",
            cor="#d97706",
        )

        # Carrega dados auxiliares para os relatórios
        try:
            _eng_rel = db.get_engine()
            _df_etapas_rel = pd.read_sql("""
                SELECT e.*, p.projeto, p.data_inicio
                FROM etapas_projeto e
                JOIN projetos p ON e.projeto_id = p.id
                ORDER BY e.projeto_id, e.ordem
            """, _eng_rel)
            _df_prog_rel = pd.read_sql("""
                SELECT pd.*, p.projeto, p.id as projeto_id
                FROM progresso_disciplinas pd
                JOIN projetos p ON pd.projeto_id = p.id
            """, _eng_rel)
        except Exception:
            _df_etapas_rel = pd.DataFrame()
            _df_prog_rel   = pd.DataFrame()

        c_r1, c_r2, c_r3 = st.columns(3)

        # Excel
        with c_r1:
            try:
                dados_ex = relatorios.gerar_excel(
                    df_p_limpo,
                    df_etapas=_df_etapas_rel if not _df_etapas_rel.empty else None,
                    df_progresso=_df_prog_rel if not _df_prog_rel.empty else None,
                )
                st.download_button(
                    label="📊 Baixar Excel Completo",
                    data=dados_ex,
                    file_name=f"projetos_servpen_{datetime.now().strftime('%d_%m_%Y')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    help="Abas: Projetos · Etapas · Progresso Técnico",
                )
            except Exception as e:
                st.error(f"Erro Excel: {e}")

        # PDF completo
        with c_r2:
            try:
                dados_pdf = relatorios.gerar_pdf(
                    df_p_limpo,
                    df_etapas=_df_etapas_rel if not _df_etapas_rel.empty else None,
                    df_progresso=_df_prog_rel if not _df_prog_rel.empty else None,
                )
                if dados_pdf:
                    st.download_button(
                        label="📄 Baixar PDF Completo",
                        data=dados_pdf,
                        file_name=f"relatorio_servpen_{datetime.now().strftime('%d_%m_%Y')}.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                        help="Ficha detalhada de cada projeto + etapas + progresso",
                    )
                else:
                    st.warning("Dados insuficientes para PDF.")
            except Exception as e:
                st.error(f"Erro PDF: {e}")

        # PDF Gantt
        with c_r3:
            try:
                if not _df_etapas_rel.empty:
                    dados_gantt = relatorios.gerar_pdf_gantt(
                        df_p_limpo, _df_etapas_rel
                    )
                    st.download_button(
                        label="📅 Baixar Gantt PDF",
                        data=dados_gantt,
                        file_name=f"gantt_servpen_{datetime.now().strftime('%d_%m_%Y')}.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                        help="Cronograma visual de todas as etapas em paisagem A4",
                    )
                else:
                    st.info("Cadastre etapas nos projetos para gerar o Gantt PDF.")
            except Exception as e:
                st.error(f"Erro Gantt: {e}")
                                
    # --- ABA 2: QUADRO KANBAN (VERSÃO COMPLETA E ESTÁVEL) ---
    with t_kanban:
        st.header("📋 Controle de Fluxo")

        # ── BUSCA + FILTRO DE TAGS ───────────────────────────────────
        col_busca, col_tags = st.columns([3, 2])
        busca_kanban = col_busca.text_input(
            "🔍 Buscar por nome, projetista ou cliente",
            placeholder="ex.: residencial silva, joão, prefeitura...",
            key="kanban_search",
        )
        _todas_tags_kanban = db.listar_tags_existentes()
        tags_filtro = col_tags.multiselect(
            "🏷 Filtrar por tags",
            options=_todas_tags_kanban,
            default=[],
            key="kanban_tags_filter",
            help="Mostra apenas projetos que contêm TODAS as tags selecionadas. Vazio = não filtra.",
            placeholder="(qualquer tag)" if _todas_tags_kanban else "Nenhuma tag cadastrada ainda",
            disabled=not _todas_tags_kanban,
        )

        if busca_kanban:
            termo = busca_kanban.lower().strip()
            mask = (
                df_p['projeto'].astype(str).str.lower().str.contains(termo, na=False)
                | df_p['projetista'].astype(str).str.lower().str.contains(termo, na=False)
                | df_p['solicitante'].astype(str).str.lower().str.contains(termo, na=False)
            )
            df_kanban = df_p[mask].copy()
        else:
            df_kanban = df_p.copy() if not df_p.empty else pd.DataFrame()

        # Filtro de tags: projeto deve conter TODAS as tags selecionadas (AND).
        if tags_filtro and not df_kanban.empty:
            sel_lower = {t.lower() for t in tags_filtro}
            def _tem_todas(s):
                proj_tags = {t.lower() for t in db.parse_tags(s)}
                return sel_lower.issubset(proj_tags)
            # Defensivo: se a coluna ainda não existir (migration não rodou),
            # apply em Series vazia retorna False pra tudo → df vazio.
            _col_tags = df_kanban['tags'] if 'tags' in df_kanban.columns \
                        else pd.Series([''] * len(df_kanban), index=df_kanban.index)
            df_kanban = df_kanban[_col_tags.apply(_tem_todas)].copy()

        # ── 4 CARDS DE MÉTRICAS (visão executiva sobre o filtro atual) ──
        # As métricas refletem o que está filtrado (busca + tags), não o
        # banco inteiro. Atrasados = status Ativo + data_termino/data_fim < hoje.
        _df_metricas = df_kanban if not df_kanban.empty else \
                       pd.DataFrame(columns=df_p.columns)
        _hoje_metricas = datetime.now().date()

        def _eh_atrasado(row):
            if row.get('status') != 'Ativo':
                return False
            dt_str = row.get('data_termino') or row.get('data_fim')
            if not dt_str:
                return False
            try:
                return pd.to_datetime(str(dt_str)).date() < _hoje_metricas
            except Exception:
                return False

        _qtd_andamento = int((_df_metricas['status'] == 'Ativo').sum()) \
                         if not _df_metricas.empty else 0
        _qtd_espera = int((_df_metricas['status'] == 'Em Espera').sum()) \
                      if not _df_metricas.empty else 0
        _qtd_atrasados = int(_df_metricas.apply(_eh_atrasado, axis=1).sum()) \
                         if not _df_metricas.empty else 0
        _qtd_prio_max_espera = int(
            ((_df_metricas['status'] == 'Em Espera')
             & (_df_metricas['prioridade'].astype(str).str.strip() == 'Máxima')
            ).sum()
        ) if not _df_metricas.empty else 0

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("🚀 Em Andamento", _qtd_andamento,
                  help="Projetos com status Ativo no filtro atual.")
        m2.metric("⏳ Em Espera", _qtd_espera,
                  help="Projetos aguardando triagem no filtro atual.")
        m3.metric("🔴 Atrasados", _qtd_atrasados,
                  delta=f"de {_qtd_andamento}" if _qtd_andamento else None,
                  delta_color="off",
                  help="Ativos cuja data de término já passou.")
        m4.metric("▲ Máxima na fila", _qtd_prio_max_espera,
                  help="Em Espera com prioridade Máxima (precisa de triagem).")

        st.divider()

        # ── TOGGLE DE VISÃO: Kanban / Lista / Resumo ─────────────────
        # 3 modos, cada um pra um cenário diferente:
        #   - Kanban: fluxo visual por status (atual). Bom pra movimentação.
        #   - Lista:  tabela densa com sort. Bom pra triagem rápida em volume.
        #   - Resumo: dashboard de cima (urgentes + atrasados + distribuição).
        # Helper escolhe segmented_control (Streamlit 1.40+) ou radio (≤1.39).
        # Portável entre 228.20 (Athlon II → radio) e 238.40 (Xeon → segmented).
        visao = _pill_select(
            st, "Visão",
            options=["Kanban", "Lista", "Resumo"],
            default="Kanban",
            key="kanban_visao",
            label_visibility="collapsed",
        ) or "Kanban"

        if visao == "Lista":
            _render_lista_kanban(df_kanban, df_d)
        elif visao == "Resumo":
            _render_resumo_kanban(df_kanban, df_d)
        else:
            # ════════════════════════════════════════════════════════════
            #  KANBAN TRADICIONAL (default)
            #  MAPA DE CONFIGURAÇÃO DAS COLUNAS
            #  status_db  = valor real no banco de dados
            #  label_ui   = nome exibido na interface
            # ════════════════════════════════════════════════════════════
            ORDEM_PRIORIDADE = {"Máxima": 0, "Média": 1, "Mínima": 2, "": 3}

            CONFIG_COLUNAS = [
                {"status_db": "Em Espera",  "label_ui": "⏳ Em Espera",
                 "card_cls": "kc-espera",   "ordenar_por_prioridade": True},
                {"status_db": "Ativo",      "label_ui": "🚀 Em Execução",
                 "card_cls": "kc-ativo",    "ordenar_por_prioridade": False},
                {"status_db": "🛑 Parado",  "label_ui": "🛑 Parados",
                 "card_cls": "kc-parado",   "ordenar_por_prioridade": False},
                {"status_db": "Cancelado",  "label_ui": "❌ Cancelados",
                 "card_cls": "kc-cancel",   "ordenar_por_prioridade": False},
                {"status_db": "Concluído",  "label_ui": "✅ Concluídos",
                 "card_cls": "kc-conc",     "ordenar_por_prioridade": False},
            ]

            # CSS uniforme para os cards do Kanban — compactos, mesma estrutura
            # pras 5 colunas, só varia background/border (via classe específica).
            # Densidade controlada por classe `.kc-d-{c|n|e}` (compacto/normal/expandido).
            st.markdown("""
            <style>
            .kc {
                border-radius: 8px;
                border-left: 4px solid var(--kc-border, #888);
                color: #fff;
                background: var(--kc-bg, #444);
                overflow: hidden;
            }
            /* DENSIDADES — controlam padding/font conforme escolha do usuário */
            .kc.kc-d-c { padding: 6px 8px; font-size: 11px;   line-height: 1.3;
                         margin-bottom: 5px; }
            .kc.kc-d-n { padding: 9px 11px; font-size: 12.5px; line-height: 1.4;
                         margin-bottom: 7px; }
            .kc.kc-d-e { padding: 12px 14px; font-size: 13.5px; line-height: 1.5;
                         margin-bottom: 10px; }
            .kc.kc-d-c .nome { font-size:11.5px; }
            .kc.kc-d-n .nome { font-size:13px; }
            .kc.kc-d-e .nome { font-size:14.5px; }
            .kc.kc-d-c .meta { font-size:10px; }
            .kc.kc-d-n .meta { font-size:11.5px; }
            .kc.kc-d-e .meta { font-size:12.5px; }

            .kc-espera { --kc-bg:#3b1f6e; --kc-border:#7c3aed; }
            .kc-ativo  { --kc-bg:#0d3d75; --kc-border:#00d4ff; }
            .kc-parado { --kc-bg:#7c3a0a; --kc-border:#ff9f43; }
            .kc-cancel { --kc-bg:#5c1414; --kc-border:#ff4d4d; }
            .kc-conc   { --kc-bg:#143d14; --kc-border:#4dff4d; }
            .kc .row1 { display:flex; gap:4px; flex-wrap:wrap; align-items:center;
                        margin-bottom: 3px; min-height: 14px; }
            .kc .nome { font-weight:700; margin:2px 0; word-break: break-word; }
            .kc .meta { opacity:.85; margin-top:2px; word-break: break-word; }
            .kc .tags { margin-top:4px; line-height:1.6; }
            .kc-pri-max  { background:#ef4444; color:#fff; font-size:9px;
                           font-weight:700; padding:1px 6px; border-radius:5px;
                           letter-spacing:.3px; }
            .kc-pri-med  { background:#f59e0b; color:#fff; font-size:9px;
                           font-weight:700; padding:1px 6px; border-radius:5px;
                           letter-spacing:.3px; }
            .kc-pri-min  { background:#10b981; color:#fff; font-size:9px;
                           font-weight:700; padding:1px 6px; border-radius:5px;
                           letter-spacing:.3px; }
            .kc-alerta   { background:#ff4d4d; color:#fff; font-size:9px;
                           font-weight:700; padding:1px 6px; border-radius:5px;
                           letter-spacing:.3px; }
            /* Header da coluna: STICKY no topo da coluna, sempre visível ao rolar */
            .kc-col-header {
                position: sticky; top: 0;
                background: var(--background-color, #0e1117);
                z-index: 5;
                font-size: 13px; font-weight:700; margin: 0 0 6px;
                padding: 6px 4px;
                border-bottom: 1px solid rgba(255,255,255,.08);
            }
            </style>
            """, unsafe_allow_html=True)

            # ── TOOLBAR: densidade + collapse finalizados ────────────────
            tb1, tb2, _tb3 = st.columns([1.2, 1.2, 2])
            # Helper portátil — segmented_control no Xeon, radio no Athlon.
            densidade = _pill_select(
                tb1, "Densidade",
                options=["Compacto", "Normal", "Expandido"],
                default="Normal",
                key="kanban_densidade",
                label_visibility="collapsed",
                help="Espaçamento dos cards. Compacto = mais cards visíveis.",
            )
            _density_cls_map = {"Compacto": "kc-d-c", "Normal": "kc-d-n",
                                "Expandido": "kc-d-e"}
            _density_cls = _density_cls_map.get(densidade or "Normal", "kc-d-n")

            mostrar_finalizados = tb2.toggle(
                "Mostrar finalizados",
                value=False,
                key="kanban_show_done",
                help="Inclui colunas 🚫 Cancelados e ✅ Concluídos no quadro.",
            )

            # ── COLUNAS DO KANBAN (3 ou 5, dependendo do toggle) ─────────
            COLUNAS_FINAIS = {"Cancelado", "Concluído"}
            configs_visiveis = [
                c for c in CONFIG_COLUNAS
                if mostrar_finalizados or c["status_db"] not in COLUNAS_FINAIS
            ]
            colunas_ui = st.columns(len(configs_visiveis))

            # Altura do container scrollable. 75vh = não exige rolar a página
            # principal, cada coluna rola sozinha.
            ALTURA_COL = 700

            for cfg, coluna in zip(configs_visiveis, colunas_ui):
                with coluna:
                    if not df_kanban.empty:
                        items = df_kanban[df_kanban['status'] == cfg['status_db']].copy()
                    else:
                        items = pd.DataFrame()

                    # Ordenação por prioridade na coluna Em Espera
                    if cfg['ordenar_por_prioridade'] and not items.empty:
                        items['_ord_pri'] = items['prioridade'].map(
                            lambda x: ORDEM_PRIORIDADE.get(str(x).strip(), 3)
                        )
                        items = items.sort_values('_ord_pri')

                    # Header da coluna FORA do container scrollable: sempre visível
                    # mesmo quando os cards da coluna estão rolados pra baixo.
                    st.markdown(
                        f"<div class='kc-col-header'>{cfg['label_ui']} "
                        f"<span style='opacity:.6;font-weight:500;'>({len(items)})</span></div>",
                        unsafe_allow_html=True,
                    )

                    # Container com altura limitada → cada coluna rola sozinha,
                    # a página principal não sobe nem desce.
                    with st.container(height=ALTURA_COL, border=False):
                        if items.empty:
                            st.markdown(
                                "<div style='color:#6b7280;font-size:11px;"
                                "border:1px dashed rgba(255,255,255,0.1);"
                                "border-radius:6px;padding:8px;text-align:center;'>"
                                "Nenhum projeto</div>",
                                unsafe_allow_html=True,
                            )

                        for _, p in items.iterrows():
                            # Alerta de pendências abertas (só badge compacto na row1)
                            pend_abertas  = df_d[(df_d['projeto_id'] == p['id']) & (df_d['resolvido'] == 0)] \
                                            if not df_d.empty else pd.DataFrame()
                            texto_diario  = " ".join(pend_abertas['executado'].astype(str)) \
                                            if not pend_abertas.empty else ""
                            tem_trava     = any(x in texto_diario for x in ["Impedimento","Dúvida","🛑","❓"])
                            badge_alerta  = "<span class='kc-alerta'>⚠ TRAVA</span>" if tem_trava else ""

                            # Prioridade compacta
                            pri = str(p.get('prioridade', '')).strip()
                            if pri == 'Máxima':
                                badge_pri = "<span class='kc-pri-max'>▲ MÁX</span>"
                            elif pri == 'Média':
                                badge_pri = "<span class='kc-pri-med'>◆ MÉD</span>"
                            elif pri == 'Mínima':
                                badge_pri = "<span class='kc-pri-min'>▼ MÍN</span>"
                            else:
                                badge_pri = ""

                            prazo_str = str(p.get('data_fim', '') or p.get('data_termino', '') or '—')

                            # Chips de tags (small=True pra caber no card compacto)
                            _tags_html = _render_tag_chips(p.get('tags'), small=True)
                            _tags_wrap = f'<div class="tags">{_tags_html}</div>' if _tags_html else ''

                            card_html = (
                                f'<div class="kc {cfg["card_cls"]} {_density_cls}">'
                                f'<div class="row1">{badge_alerta}{badge_pri}</div>'
                                f'<div class="nome">{p["projeto"]}</div>'
                                f'<div class="meta">👤 {p["projetista"]} · 📅 {prazo_str}</div>'
                                f'{_tags_wrap}'
                                f'</div>'
                            )
                            st.markdown(card_html, unsafe_allow_html=True)

                            # ── Ações em popover único (3 botões grandes viravam ruído) ──
                            status_db = cfg['status_db']
                            with st.popover("⚙️", use_container_width=True,
                                            help="Ações e detalhes"):
                                if st.button("🔍 Abrir detalhes / editar",
                                             key=f"ver_{p['id']}",
                                             use_container_width=True):
                                    st.session_state.projeto_em_edicao = p['id']
                                    st.rerun()

                                if _pode_editar():
                                    st.divider()
                                    if status_db == "Em Espera":
                                        if st.button("▶️ Mover para Em Execução",
                                                     key=f"ativ_{p['id']}",
                                                     use_container_width=True):
                                            db.atualizar_campo_projeto(p['id'], "status", "Ativo")
                                            db.log_aud(st.session_state.usuario, 'status',
                                                       'projeto', p['id'], "Em Espera → Ativo")
                                            _invalidar_dados(); st.rerun()
                                        if st.button("❌ Cancelar projeto",
                                                     key=f"canc_esp_{p['id']}",
                                                     use_container_width=True):
                                            db.atualizar_campo_projeto(p['id'], "status", "Cancelado")
                                            _invalidar_dados(); st.rerun()
                                    elif status_db == "Ativo":
                                        if st.button("⏸️ Pausar projeto",
                                                     key=f"p_{p['id']}",
                                                     use_container_width=True):
                                            db.atualizar_campo_projeto(p['id'], "status", "🛑 Parado")
                                            _invalidar_dados(); st.rerun()
                                        if st.button("✅ Concluir projeto",
                                                     key=f"f_{p['id']}",
                                                     use_container_width=True):
                                            db.atualizar_campo_projeto(p['id'], "status", "Concluído")
                                            _invalidar_dados(); st.rerun()
                                    elif status_db == "🛑 Parado":
                                        if st.button("▶️ Retomar → Em Execução",
                                                     key=f"r_{p['id']}",
                                                     use_container_width=True):
                                            db.atualizar_campo_projeto(p['id'], "status", "Ativo")
                                            _invalidar_dados(); st.rerun()
                                        if st.button("❌ Cancelar",
                                                     key=f"c_{p['id']}",
                                                     use_container_width=True):
                                            db.atualizar_campo_projeto(p['id'], "status", "Cancelado")
                                            _invalidar_dados(); st.rerun()
                                    elif status_db == "Cancelado":
                                        if st.button("🔓 Reativar → Em Espera",
                                                     key=f"re_{p['id']}",
                                                     use_container_width=True):
                                            db.atualizar_campo_projeto(p['id'], "status", "Em Espera")
                                            _invalidar_dados(); st.rerun()
                                    elif status_db == "Concluído":
                                        if st.button("🔓 Reabrir → Em Execução",
                                                     key=f"reabrir_{p['id']}",
                                                     use_container_width=True):
                                            db.atualizar_campo_projeto(p['id'], "status", "Ativo")
                                            _invalidar_dados(); st.rerun()

        # --- CENTRAL DE EDIÇÃO (COM TODO O DETALHAMENTO VOLTADO) ---
        if 'projeto_em_edicao' in st.session_state:
            st.divider()
            id_ed = st.session_state.projeto_em_edicao
 
            # Recarrega sempre do banco para ter dados frescos
            _df_ed = pd.read_sql_query(
                "SELECT * FROM projetos WHERE id = %s",
                db.get_engine(), params=(int(id_ed),),
            )
 
            if _df_ed.empty:
                st.warning("Projeto não encontrado.")
                del st.session_state.projeto_em_edicao
                st.rerun()
 
            dados = _df_ed.fillna('').iloc[0]
 
            st.subheader(f"📝 Detalhamento e Edição: {dados['projeto']}")
            st.markdown(_badge_status(dados.get('status', '')), unsafe_allow_html=True)
 
            # ── helper de parse de data ──────────────────────────────
            def _parse_d(val):
                for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%Y-%m-%d %H:%M:%S'):
                    try:
                        return datetime.strptime(str(val).strip(), fmt).date()
                    except Exception:
                        pass
                return datetime.now().date()
 
            # ════════════════════════════════════════════════════════
            #  FORMULÁRIO ESPELHANDO O CADASTRO DE NOVO PROJETO
            # ════════════════════════════════════════════════════════
            with st.form("form_edicao_v6"):
 
                st.markdown("#### 📌 Identificação")
                r1c1, r1c2 = st.columns(2)
                ed_nm  = r1c1.text_input("Nome do Projeto / Cliente *",
                                         value=str(dados['projeto']))
                ed_sei = r1c2.text_input("Nº SEI / Documento",
                                         value=str(dados.get('numero_sei', '')),
                                         placeholder="ex.: 2024/12345-6")
 
                r2c1, r2c2 = st.columns(2)
                ed_so = r2c1.text_input("Solicitante / Cliente",
                                        value=str(dados['solicitante']))
                ed_co = r2c2.text_input("Contato (Tel/Email)",
                                        value=str(dados['contato']))
 
                r3c1, r3c2 = st.columns(2)
                ed_ed = r3c1.text_input("Endereço da Obra",
                                        value=str(dados['endereco']))
                ed_li = r3c2.text_input("Link da Pasta (Drive/Nuvem)",
                                        value=str(dados['link_projeto']))
 
                list_u = df_u['nome'].tolist()
                def_u  = [x.strip() for x in str(dados['projetista']).split(',')
                          if x.strip() in list_u]
                ed_eq = st.multiselect("Equipe Responsável *", list_u, default=def_u)
 
                lista_pri = ["Máxima", "Média", "Mínima"]
                pri_atual  = str(dados.get('prioridade', 'Média')).strip()

                ed_r4c1, ed_r4c2 = st.columns([1, 2])
                ed_pr = ed_r4c1.selectbox("Prioridade", lista_pri,
                                     index=lista_pri.index(pri_atual)
                                     if pri_atual in lista_pri else 1)

                _tags_existentes_e = db.listar_tags_existentes()
                _tags_atuais_csv = str(dados.get('tags') or '')
                ed_tags = ed_r4c2.text_input(
                    "🏷 Tags (separadas por vírgula)",
                    value=_tags_atuais_csv,
                    placeholder=", ".join(_tags_existentes_e[:3]) if _tags_existentes_e else "Crítico, Aprovado",
                    help=(
                        "Etiquetas livres pra agrupar projetos. "
                        + (f"Já em uso: {', '.join(_tags_existentes_e)}."
                           if _tags_existentes_e else "")
                    ),
                )

                st.markdown("#### 📅 Datas")
                dc1, dc2, dc3, dc4 = st.columns(4)
                ed_drec = dc1.date_input("Data de Recebimento",
                                         value=_parse_d(dados.get('data_recebimento')))
                ed_prev = dc2.date_input("Previsão de Execução",
                                         value=_parse_d(dados.get('previsao_execucao')))
                ed_di   = dc3.date_input("Data de Início",
                                         value=_parse_d(dados.get('data_inicio')))
                ed_dt   = dc4.date_input("Data de Término",
                                         value=_parse_d(dados.get('data_termino')
                                                        or dados.get('data_fim')))
 
                st.markdown("#### 📋 Escopo e Disciplinas")
                # Disciplinas: reconstruídas da lista padrão + o que está salvo
                _discs_salvas = [d.strip() for d in
                                 str(dados.get('demandas', '')).split('|')[0].split(',')
                                 if d.strip()]
                _lista_chk = list(dict.fromkeys(
                    st.session_state.get('lista_checklist', []) + _discs_salvas
                ))
                ed_chk = st.multiselect("Disciplinas do Projeto",
                                        options=_lista_chk,
                                        default=[d for d in _discs_salvas
                                                 if d in _lista_chk])
 
                ed_esc = st.text_area("Descrição do Escopo",
                                      value=str(dados['solicitacao']), height=90)
                # Demandas adicionais (parte após o "|")
                _dem_extra = str(dados.get('demandas', '')).split('|')[-1].strip() \
                             if '|' in str(dados.get('demandas', '')) else ''
                ed_dem = st.text_area("Checklist Adicional / Demandas",
                                      value=_dem_extra, height=70)
 
                # ── BOTÕES ──────────────────────────────────────────
                f_c1, f_c2, f_c3, f_c4 = st.columns(4)

                _salvar = f_c1.form_submit_button("💾 Salvar e Sair",
                                                   use_container_width=True)
                _clonar = f_c2.form_submit_button(
                    "📋 Clonar projeto",
                    use_container_width=True,
                    help="Cria um novo projeto copiando dados básicos + estrutura de etapas. "
                         "Não copia diário, arquivos nem progresso de disciplinas.",
                )
                _excluir = f_c3.form_submit_button("🗑️ Excluir Projeto",
                                                    use_container_width=True)
                _fechar  = f_c4.form_submit_button("❌ Fechar",
                                                    use_container_width=True)

                confirmar_del = st.checkbox(
                    f"⚠️ Confirmo EXCLUIR permanentemente '{dados['projeto']}'",
                    key=f"conf_del_{id_ed}",
                )
 
            # ── Ações dos botões ─────────────────────────────────────
            if _salvar:
                equipe_str      = ", ".join(ed_eq)
                checklist_final = ", ".join(ed_chk) + \
                                  (" | " + ed_dem if ed_dem.strip() else "")
                dados_finais = (
                    equipe_str, ed_nm, ed_ed, ed_so, ed_co,
                    ed_sei, ed_drec, ed_di, ed_dt, ed_dt,
                    ed_li, checklist_final, ed_esc, ed_pr,
                )
                db.atualizar_projeto_completo(id_ed, dados_finais)
                # `atualizar_projeto_completo` tem assinatura fixa de 14 valores
                # (compat). Tags vão num UPDATE separado pra não quebrar.
                _tags_csv_save = db.serializar_tags(db.parse_tags(ed_tags)) or None
                db.atualizar_campo_projeto(id_ed, "tags", _tags_csv_save)
                db.log_aud(st.session_state.usuario, 'editar', 'projeto',
                           id_ed, f"nome='{ed_nm}' tags='{_tags_csv_save or ''}'")
                del st.session_state.projeto_em_edicao
                _invalidar_dados(); st.rerun()

            if _excluir:
                if not confirmar_del:
                    st.warning("Marque a caixa de confirmação antes de excluir.")
                else:
                    db.excluir_projeto(id_ed)
                    db.log_aud(st.session_state.usuario, 'excluir', 'projeto',
                               id_ed, f"nome='{dados['projeto']}'")
                    del st.session_state.projeto_em_edicao
                    _invalidar_dados(); st.rerun()

            if _clonar:
                # Cria projeto novo no banco baseado neste, redireciona pra
                # edição dele pra Sara ajustar nome/datas/equipe antes de salvar.
                novo_id = db.clonar_projeto(id_ed)
                if novo_id:
                    db.log_aud(st.session_state.usuario, 'clonar', 'projeto',
                               id_ed,
                               f"origem='{dados['projeto']}' -> novo_id={novo_id}")
                    _invalidar_dados()
                    st.success(
                        f"📋 Projeto clonado! Novo id={novo_id} criado em **Em Espera**. "
                        f"Abrindo edição pra você ajustar nome/datas/equipe."
                    )
                    # Abre direto o painel de edição do novo clone
                    st.session_state.projeto_em_edicao = int(novo_id)
                    st.rerun()
                else:
                    st.error(
                        "Não foi possível clonar o projeto. "
                        "Veja o log do servidor pra detalhes."
                    )

            if _fechar:
                del st.session_state.projeto_em_edicao
                st.rerun()
 
            # ════════════════════════════════════════════════════════
            #  ETAPAS DO PROJETO (edição inline)
            # ════════════════════════════════════════════════════════
            st.markdown("### 🏁 Etapas do Projeto")
 
            _key_et   = f"etapas_edit_{id_ed}"
            if _key_et not in st.session_state:
                st.session_state[_key_et] = db.listar_etapas(id_ed)
 
            _et_list = st.session_state[_key_et]
 
            # Proporções das colunas: ord (0.5 pra caber "Ord."), nome (2.5),
            # duração (1.2), offset (1.5), ação (0.7 pra "🗑 Remover")
            _COLS_ET = [0.5, 2.5, 1.2, 1.5, 0.7]

            with st.form(f"form_etapas_{id_ed}"):
                novas_etapas = []
                _del_et = None

                if not _et_list:
                    # Empty state — sem header solto e sem linhas vazias
                    st.markdown(
                        "<div style='border:1px dashed rgba(255,255,255,0.12);"
                        "border-radius:8px;padding:18px;text-align:center;"
                        "color:#6b7280;font-size:13px;'>"
                        "Nenhuma etapa cadastrada ainda.<br>"
                        "<small>Clique em <b>+ Adicionar Etapa</b> abaixo pra começar.</small>"
                        "</div>",
                        unsafe_allow_html=True,
                    )
                else:
                    # Header só aparece quando há etapas
                    h0, h1, h2, h3, h4 = st.columns(_COLS_ET)
                    h0.markdown("<small style='color:#94a3b8'>Ord.</small>",
                                unsafe_allow_html=True)
                    h1.markdown("<small style='color:#94a3b8'>Nome da Etapa</small>",
                                unsafe_allow_html=True)
                    h2.markdown("<small style='color:#94a3b8'>Duração (dias)</small>",
                                unsafe_allow_html=True)
                    h3.markdown("<small style='color:#94a3b8'>Início (dias após início do projeto)</small>",
                                unsafe_allow_html=True)
                    h4.markdown("<small style='color:#94a3b8'>Ação</small>",
                                unsafe_allow_html=True)

                    for i, et in enumerate(_et_list):
                        c0, c1, c2, c3, c4 = st.columns(_COLS_ET)
                        c0.markdown(
                            f"<div style='padding-top:28px;text-align:center;"
                            f"color:#64748b;font-weight:700;'>{i+1}</div>",
                            unsafe_allow_html=True,
                        )
                        n = c1.text_input("Nome", value=str(et.get('nome', '')),
                                          label_visibility="collapsed",
                                          key=f"etn_{id_ed}_{i}")
                        d = c2.number_input("Dur", value=int(et.get('duracao_dias', 1)),
                                             min_value=1, label_visibility="collapsed",
                                             key=f"etd_{id_ed}_{i}")
                        o = c3.number_input("Off", value=int(et.get('dias_offset', 0)),
                                             min_value=0, label_visibility="collapsed",
                                             key=f"eto_{id_ed}_{i}")
                        if c4.form_submit_button(f"🗑 #{i+1}",
                                                 use_container_width=True):
                            _del_et = i
                        novas_etapas.append({
                            'nome': n, 'duracao_dias': d,
                            'dias_offset': o, 'ordem': i,
                        })

                btn_add, btn_salvar_et = st.columns(2)
                _add_et = btn_add.form_submit_button("➕ Adicionar Etapa",
                                                      use_container_width=True)
                _salv_et = btn_salvar_et.form_submit_button("💾 Salvar Etapas",
                                                             use_container_width=True,
                                                             disabled=not _et_list,
                                                             help="Disponível quando há etapas pra salvar"
                                                                  if not _et_list else None)
 
            if _del_et is not None:
                st.session_state[_key_et].pop(_del_et)
                acum = 0
                for et in st.session_state[_key_et]:
                    et['dias_offset'] = acum
                    acum += et['duracao_dias']
                st.rerun()
 
            if _add_et:
                _ult = st.session_state[_key_et][-1] \
                       if st.session_state[_key_et] \
                       else {'dias_offset': 0, 'duracao_dias': 0}
                st.session_state[_key_et].append({
                    'nome': f'Etapa {len(st.session_state[_key_et])+1}',
                    'duracao_dias': 5,
                    'dias_offset': _ult['dias_offset'] + _ult['duracao_dias'],
                    'ordem': len(st.session_state[_key_et]),
                })
                st.rerun()
 
            if _salv_et:
                db.salvar_etapas(id_ed,
                                 [e for e in novas_etapas if str(e['nome']).strip()])
                st.session_state[_key_et] = db.listar_etapas(id_ed)
                st.success("Etapas salvas!"); st.rerun()
 
            # Mini-Gantt das etapas
            _et_salvas = db.listar_etapas(id_ed)
            _di_proj   = dados.get('data_inicio') or dados.get('data_fim')
            if _et_salvas and _di_proj:
                try:
                    _base = pd.to_datetime(str(_di_proj))
                    _rows_g2 = []
                    for et in _et_salvas:
                        _ini = _base + pd.Timedelta(days=int(et['dias_offset']))
                        _fim = _ini  + pd.Timedelta(days=max(1, int(et['duracao_dias'])) - 1)
                        _rows_g2.append({'Etapa': et['nome'],
                                         'Início': _ini, 'Fim': _fim})
                    _df_g2  = pd.DataFrame(_rows_g2)
                    _fig_g2 = px.timeline(_df_g2, x_start="Início",
                                          x_end="Fim", y="Etapa", color="Etapa")
                    _fig_g2.update_yaxes(autorange="reversed", title_text="")
                    _fig_g2.update_layout(
                        height=max(200, len(_rows_g2) * 32 + 60),
                        showlegend=False,
                        margin=dict(l=5, r=5, t=15, b=10),
                    )
                    _estiliza_plotly(_fig_g2)
                    st.plotly_chart(_fig_g2, use_container_width=True)
                except Exception:
                    pass
 
            # ════════════════════════════════════════════════════════
            #  EVOLUÇÃO TÉCNICA POR DISCIPLINA  ← CORREÇÃO 3
            #  Checklist: slider 100% → checkbox marcado automaticamente
            # ════════════════════════════════════════════════════════
            st.markdown("### 📊 Evolução Técnica por Disciplina")

            # Disciplinas vêm do campo demandas (parte antes do "|")
            _dem_raw = str(dados.get('demandas', '')).split('|')[0]
            disciplinas_projeto = [d.strip() for d in _dem_raw.split(',') if d.strip()]

            if not disciplinas_projeto:
                st.info(
                    "Nenhuma disciplina vinculada. "
                    "Adicione-as no campo **Disciplinas do Projeto** acima e salve."
                )
            else:
                df_prog = pd.read_sql(
                    "SELECT * FROM progresso_disciplinas WHERE projeto_id = %s",
                    db.get_engine(), params=(int(id_ed),),
                )

                disciplinas_no_banco = df_prog['disciplina'].tolist()

                # Sincroniza disciplinas (adiciona novas, remove obsoletas)
                _sync_needed = False
                for _d in disciplinas_projeto:
                    if _d not in disciplinas_no_banco:
                        _c = db.conectar(); _cu = _c.cursor()
                        _cu.execute(
                            "INSERT INTO progresso_disciplinas "
                            "(projeto_id, disciplina, concluido, percentual) VALUES (%s,%s,%s,%s)",
                            (int(id_ed), _d, 0, 0),
                        )
                        _c.commit(); _c.close()
                        _sync_needed = True
                        
                for _d in disciplinas_no_banco:
                    if _d not in disciplinas_projeto:
                        _c = db.conectar(); _cu = _c.cursor()
                        _cu.execute(
                            "DELETE FROM progresso_disciplinas "
                            "WHERE projeto_id=%s AND disciplina=%s",
                            (int(id_ed), _d),
                        )
                        _c.commit(); _c.close()
                        _sync_needed = True
                        
                if _sync_needed:
                    st.rerun()

                # CORREÇÃO DA INDENTAÇÃO: O formulário agora roda sempre, fora do bloco de sync!
                with st.form(key=f"check_evolucao_{id_ed}"):
                    c_check, c_prog = st.columns([1.3, 1])
                    novos_vals = []

                    with c_check:
                        st.markdown(
                            "<div style='margin-bottom:6px;font-size:.78rem;"
                            "color:#94a3b8;display:flex;gap:32px;padding-left:4px;'>"
                            "<span>✔ Concluído</span>"
                            "<span style='margin-left:8px'>Progresso (%)</span>"
                            "</div>",
                            unsafe_allow_html=True,
                        )
                        for _, row in df_prog.iterrows():
                            if row['disciplina'] not in disciplinas_projeto:
                                continue

                            _st_banco  = bool(row['concluido'])
                            _per_banco = int(row['percentual'])

                            col_cb, col_sl = st.columns([0.38, 0.62])

                            _n_st = col_cb.checkbox(
                                f"**{row['disciplina']}**",
                                value=_st_banco,
                                key=f"ch_{row['id']}",
                            )
                            _n_per = col_sl.slider(
                                "Prog", 0, 100, _per_banco,
                                key=f"sl_{row['id']}",
                                label_visibility="collapsed",
                            )

                            # ── Lógica de sincronização corrigida ──────────
                            _cb_mudou  = (_n_st  != _st_banco)
                            _sl_mudou  = (_n_per != _per_banco)

                            if _cb_mudou:
                                _n_per = 100 if _n_st else 0
                            elif _sl_mudou:
                                _n_st = (_n_per == 100)

                            novos_vals.append((
                                1 if _n_st else 0,
                                _n_per,
                                int(row['id']),
                            ))

                    with c_prog:
                        _media = df_prog['percentual'].mean() if not df_prog.empty else 0
                        _cor_prog = (
                            "#10b981" if _media >= 70
                            else "#f59e0b" if _media >= 40
                            else "#ef4444"
                        )
                        
                        # Substituído a div HTML por um st.container com borda nativo
                        with st.container(border=True):
                            st.markdown(
                                f"<div style='text-align:center; padding:10px 0;'>"
                                f"<div style='font-size:2rem;font-weight:700;color:{_cor_prog};line-height:1'>{_media:.0f}%</div>"
                                f"<div style='font-size:.72rem;color:#94a3b8;margin-top:5px;'>progresso geral</div>"
                                f"</div>",
                                unsafe_allow_html=True,
                            )
                            
                            # A barra de progresso agora renderiza de forma segura e visível aqui
                            st.progress(min(_media / 100, 1.0))

                        if _media >= 100:
                            st.success("🎉 CONCLUÍDO!")

                    if st.form_submit_button("🔄 Atualizar Progresso", use_container_width=True):
                        _c = db.conectar(); _cu = _c.cursor()
                        for _s, _p, _i in novos_vals:
                            _cu.execute(
                                "UPDATE progresso_disciplinas "
                                "SET concluido=%s, percentual=%s WHERE id=%s",
                                (_s, _p, _i),
                            )
                        _c.commit(); _c.close()
                        st.success("Evolução salva!")
                        st.rerun()
    

    # --- ABA 3: NOVO PROJETO ---
    with t_novo:
        st.header("➕ Cadastrar Novo Projeto")

        _init_etapas()

        # ── Gerenciar checklist ────────────────────────────────────
        with st.expander("⚙️ Gerenciar Disciplinas do Checklist"):
            nova_disc = st.text_input("Nova Disciplina (ex: Gás, Acústica)", key="add_disc")
            if st.button("Adicionar Disciplina", key="btn_add_disc"):
                if nova_disc and nova_disc not in st.session_state.lista_checklist:
                    st.session_state.lista_checklist.append(nova_disc)
                    st.success(f"'{nova_disc}' adicionada!"); st.rerun()

        # ── Formulário principal ──────────────────────────────────
        with st.form("form_novo_projeto_v2", clear_on_submit=False):

            st.markdown("#### 📌 Identificação")
            r1c1, r1c2 = st.columns(2)
            f_nm  = r1c1.text_input("Nome do Projeto / Cliente *")
            f_sei = r1c2.text_input("Nº SEI / Documento", placeholder="ex.: 2024/12345-6")

            r2c1, r2c2 = st.columns(2)
            f_so  = r2c1.text_input("Solicitante / Cliente")
            f_co  = r2c2.text_input("Contato (Tel/Email)")

            r3c1, r3c2 = st.columns(2)
            f_ed  = r3c1.text_input("Endereço da Obra")
            f_li  = r3c2.text_input("Link da Pasta (Drive/Nuvem)")

            f_eq  = st.multiselect("Equipe Responsável *", df_u['nome'].tolist() if not df_u.empty else [])

            r4c1, r4c2 = st.columns([1, 2])
            f_pr  = r4c1.selectbox("Prioridade", ["Máxima", "Média", "Mínima"], index=1)
            # Tags livres separadas por vírgula. Mostra as já existentes como hint.
            _tags_existentes = db.listar_tags_existentes()
            _placeholder_tags = (
                ", ".join(_tags_existentes[:3]) if _tags_existentes
                else "Crítico, Aguardando Cliente, Aprovado"
            )
            f_tags = r4c2.text_input(
                "🏷 Tags (separadas por vírgula)",
                value="",
                placeholder=_placeholder_tags,
                help=(
                    "Etiquetas livres pra agrupar projetos além do status. "
                    "Ex.: setor, fase, urgência, cliente. "
                    + (f"Já em uso: {', '.join(_tags_existentes)}." if _tags_existentes else "")
                ),
            )

            st.markdown("#### 📅 Datas")
            dc1, dc2, dc3, dc4 = st.columns(4)
            f_drec  = dc1.date_input("Data de Recebimento do Pedido", value=datetime.now())
            f_prev  = dc2.date_input("Previsão de Início da Execução", value=datetime.now())
            f_di    = dc3.date_input("Data de Início", value=datetime.now())
            f_dt    = dc4.date_input("Data de Término", value=datetime.now())

            st.markdown("#### 📋 Escopo e Disciplinas")
            f_chk = st.multiselect("Disciplinas do Projeto", st.session_state.lista_checklist)
            f_esc = st.text_area("Descrição do Escopo", height=90)
            f_dem = st.text_area("Checklist Adicional / Demandas", height=70)

            # ── ETAPAS (dentro do form, mas gerenciadas via session_state) ──
            st.markdown("#### 🏁 Etapas do Projeto")
            st.caption(
                "As etapas são em sequência. O *Início (dias após início do projeto)* indica "
                "quantos dias após a Data de Início a etapa começa. As barras aparecerão no Gantt."
            )

            # Cabeçalho
            h0, h1, h2, h3, h4 = st.columns([0.35, 2.5, 1.2, 1.2, 0.5])
            h0.markdown("<small style='color:#94a3b8'>Ord.</small>", unsafe_allow_html=True)
            h1.markdown("<small style='color:#94a3b8'>Nome da Etapa</small>", unsafe_allow_html=True)
            h2.markdown("<small style='color:#94a3b8'>Duração (dias)</small>", unsafe_allow_html=True)
            h3.markdown("<small style='color:#94a3b8'>Início (dias offset)</small>", unsafe_allow_html=True)
            h4.markdown("<small style='color:#94a3b8'>—</small>", unsafe_allow_html=True)

            etapas_validas = []
            _to_delete = None

            for i, et in enumerate(st.session_state.etapas_form):
                c0, c1, c2, c3, c4 = st.columns([0.35, 2.5, 1.2, 1.2, 0.5])
                c0.markdown(
                    f"<div style='padding-top:30px;text-align:center;color:#64748b;font-weight:700'>"
                    f"{i+1}</div>", unsafe_allow_html=True,
                )
                nome_et  = c1.text_input("Etapa", value=et['nome'],
                                        label_visibility="collapsed", key=f"et_nome_{i}")
                dur_et   = c2.number_input("Dias", value=int(et['duracao_dias']),
                                            min_value=1, max_value=3650,
                                            label_visibility="collapsed", key=f"et_dur_{i}")
                off_et   = c3.number_input("Offset", value=int(et['dias_offset']),
                                            min_value=0, max_value=3650,
                                            label_visibility="collapsed", key=f"et_off_{i}")
                if c4.form_submit_button(f"🗑 #{i+1}",
                                        help=f"Remover etapa '{et['nome']}'"):
                    _to_delete = i

                etapas_validas.append({
                    'nome': nome_et,
                    'duracao_dias': dur_et,
                    'dias_offset': off_et,
                    'ordem': i,
                })

            # Botão de adicionar etapa (dentro do form usando form_submit_button)
            c_add, c_sub = st.columns([1, 3])
            _add_etapa   = c_add.form_submit_button("➕ Adicionar Etapa", use_container_width=True)
            submit_novo  = c_sub.form_submit_button("🔨 Registrar Projeto", use_container_width=True)

        # ── Ações dos botões FORA do form ─────────────────────────
        if _to_delete is not None:
            st.session_state.etapas_form.pop(_to_delete)
            # Recalcula offsets automaticamente em sequência
            acum = 0
            for et in st.session_state.etapas_form:
                et['dias_offset'] = acum
                acum += et['duracao_dias']
            st.rerun()

        if _add_etapa:
            # Próxima etapa começa após a última
            if st.session_state.etapas_form:
                ultimo = st.session_state.etapas_form[-1]
                novo_offset = ultimo['dias_offset'] + ultimo['duracao_dias']
            else:
                novo_offset = 0
            st.session_state.etapas_form.append({
                'nome': f'Etapa {len(st.session_state.etapas_form)+1}',
                'duracao_dias': 5,
                'dias_offset': novo_offset,
                'ordem': len(st.session_state.etapas_form),
            })
            st.rerun()

        if submit_novo:
        # Sincroniza valores digitados de volta ao session_state
            for i, et in enumerate(etapas_validas):
                if i < len(st.session_state.etapas_form):
                    st.session_state.etapas_form[i].update(et)
    
            if f_nm and f_eq:
                checklist_final = ", ".join(f_chk) + (" | " + f_dem if f_dem.strip() else "")
                _tags_csv = db.serializar_tags(db.parse_tags(f_tags)) or None
                dados_sql = (
                    ", ".join(f_eq),   # projetista
                    f_nm,              # projeto
                    f_ed,              # endereco
                    f_so,              # solicitante
                    f_co,              # contato
                    f_sei,             # numero_sei
                    f_drec,            # data_recebimento
                    f_prev,            # previsao_execucao
                    f_di,              # data_inicio
                    f_dt,              # data_termino
                    f_dt,              # data_fim  (compatibilidade Gantt)
                    "Em Espera",       # ← STATUS CORRETO: entra na fila de triagem
                    f_li,              # link_projeto
                    checklist_final,   # demandas
                    f_esc,             # solicitacao
                    f_pr,              # prioridade
                    _tags_csv,         # tags (string CSV ou None)
                )
                novo_id = db.salvar_projeto(dados_sql)
                if novo_id:
                    etapas_para_salvar = [
                        {'nome': et['nome'],
                        'duracao_dias': et['duracao_dias'],
                        'dias_offset': et['dias_offset'],
                        'ordem': i}
                        for i, et in enumerate(etapas_validas)
                        if str(et.get('nome', '')).strip()
                    ]
                    if etapas_para_salvar:
                        db.salvar_etapas(novo_id, etapas_para_salvar)
    
                    db.log_aud(st.session_state.usuario, 'criar', 'projeto', novo_id, f_nm)
                    st.session_state.etapas_form = [
                        {'nome': 'Levantamento', 'duracao_dias': 5,  'dias_offset': 0},
                        {'nome': 'Projeto',      'duracao_dias': 10, 'dias_offset': 5},
                    ]
                    st.success(f"✅ Projeto **{f_nm}** criado! Ele está na coluna **Em Espera** do Kanban.")
                    _invalidar_dados(); st.rerun()
                else:
                    st.error("Erro técnico ao salvar no banco de dados.")
            else:
                st.warning("⚠️ Campos **Nome** e **Equipe** são obrigatórios.")

        # ── Mini-preview do Gantt de etapas enquanto preenche ────
        if st.session_state.get('etapas_form') and len(st.session_state.etapas_form) > 0:
            with st.expander("👁️ Pré-visualização do Gantt das Etapas", expanded=False):
                _di_prev = datetime.now()
                _rows_prev = []
                for et in st.session_state.etapas_form:
                    if not str(et.get('nome','')).strip():
                        continue
                    _ini = _di_prev + pd.Timedelta(days=int(et.get('dias_offset', 0)))
                    _fim = _ini    + pd.Timedelta(days=max(1, int(et.get('duracao_dias', 1))) - 1)
                    _rows_prev.append({'Etapa': et['nome'], 'Início': _ini, 'Fim': _fim})

                if _rows_prev:
                    _df_prev = pd.DataFrame(_rows_prev)
                    _fig_prev = px.timeline(
                        _df_prev, x_start="Início", x_end="Fim", y="Etapa",
                        color="Etapa",
                    )
                    _fig_prev.update_yaxes(autorange="reversed", title_text="")
                    _fig_prev.update_layout(height=250, showlegend=False,
                                            margin=dict(l=5, r=5, t=20, b=10))
                    _estiliza_plotly(_fig_prev)
                    st.plotly_chart(_fig_prev, use_container_width=True)
                    st.caption("ℹ️ Datas calculadas a partir de hoje como referência.")

    # --- ABA 4: DIÁRIO DE EVOLUÇÃO (VERSÃO INTEGRADA) ---
   
    with t_diario:
        st.header("📝 Diário de Evolução")

        # Ao abrir a aba, marca as menções pendentes como vistas (zera o flag de toast).
        # Atenção: NÃO dispensa — dispensar é manual, só com o botão "✕ Fechar".
        db.marcar_mencoes_vistas(st.session_state.usuario)

        # ── PAINEL PERSISTENTE DE MENÇÕES ──────────────────────────
        # Aparece sempre que houver menção pendente. Só some quando o usuário
        # clicar em "✕ Fechar" (dispensa). Clicar no card abre o projeto correspondente.
        _mencoes_lista = db.listar_mencoes_pendentes(st.session_state.usuario)
        if _mencoes_lista:
            with st.container(border=True):
                _hd1, _hd2 = st.columns([4, 1])
                _hd1.markdown(
                    f"### 🔔 Você foi mencionado em "
                    f"**{len(_mencoes_lista)}** {'aviso' if len(_mencoes_lista)==1 else 'avisos'}"
                )
                if _hd2.button("Limpar todos", key="btn_disp_todas_men",
                              help="Marca todas as menções como vistas e remove do painel.",
                              use_container_width=True):
                    db.dispensar_todas_mencoes(st.session_state.usuario)
                    st.rerun()

                for (mn_id, _proj_id, _proj_nome, _relato_id, _por, _data,
                     _ctx, _snippet) in _mencoes_lista:
                    _cor_ctx = '#0056b3' if _ctx == 'relato' else '#8e44ad'
                    _label_ctx = 'no relato' if _ctx == 'relato' else 'na resposta do gestor'
                    _snip = (_snippet or '').replace('\n', ' ').strip()
                    if len(_snip) > 120:
                        _snip = _snip[:120].rstrip() + '…'

                    with st.container(border=True):
                        _ca, _cb, _cc = st.columns([0.72, 0.16, 0.12])
                        _ca.markdown(
                            f"<div style='line-height:1.45'>"
                            f"<span style='background:{_cor_ctx};color:#fff;"
                            f"padding:1px 8px;border-radius:6px;font-size:0.72rem;"
                            f"font-weight:600;text-transform:uppercase;letter-spacing:0.4px'>"
                            f"{_label_ctx}</span> &nbsp; "
                            f"<b>{_por}</b> em <b>📂 {_proj_nome or f'projeto #{_proj_id}'}</b>"
                            f"<br><span style='font-size:0.78rem;opacity:0.75'>"
                            f"{_tempo_relativo(_data)}</span>"
                            + (f"<div style='margin-top:6px;font-size:0.88rem;"
                               f"opacity:0.85;font-style:italic'>"
                               f"“{_snip}”</div>" if _snip else "")
                            + "</div>",
                            unsafe_allow_html=True,
                        )
                        if _cb.button("Ver", key=f"men_ver_{mn_id}",
                                     use_container_width=True,
                                     help="Abre o projeto e o relato correspondente abaixo."):
                            # Pede pra abrir o expander do projeto E destacar o relato
                            st.session_state['_diario_abrir_proj'] = int(_proj_id)
                            st.session_state['_diario_destacar_relato'] = (
                                int(_relato_id) if _relato_id else None
                            )
                            st.rerun()
                        if _cc.button("✕", key=f"men_disp_{mn_id}",
                                     use_container_width=True,
                                     help="Marca como visto e remove do painel."):
                            db.dispensar_mencao(mn_id)
                            st.rerun()
            st.divider()

        # ── Mapa de não lidos por projeto ────────────────────────────
        _mapa_nao_lidos = db.contar_nao_lidos_diario(st.session_state.usuario)

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
                _df_h['dt'] = pd.to_datetime(
                    _df_h['data'], format='%d/%m/%Y %H:%M', errors='coerce'
                )
                _df_h = _df_h.dropna(subset=['dt'])
            except Exception as e:
                st.warning(f"Não foi possível carregar horas: {e}")
                _df_h = pd.DataFrame(columns=['projeto_id','projeto','autor','horas','dt'])

            if _df_h.empty:
                st.info(
                    "Nenhum relato com horas registradas ainda. Preencha o campo "
                    "**⏱ Horas** ao criar um novo relato pra começar a acompanhar."
                )
            else:
                _agora    = datetime.now()
                _ini_dia  = _agora.replace(hour=0, minute=0, second=0, microsecond=0)
                _ini_sem  = _ini_dia - pd.Timedelta(days=_agora.weekday())  # seg=0
                _ini_mes  = _ini_dia.replace(day=1)

                _eu = st.session_state.usuario

                def _soma(df, ini):
                    return float(df[df['dt'] >= ini]['horas'].sum())

                _minha = _df_h[_df_h['autor'] == _eu]
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
                _df_mes = _df_h[_df_h['dt'] >= _ini_mes]
                if not _df_mes.empty:
                    _top_p = (
                        _df_mes.groupby('projeto', dropna=False)['horas']
                        .sum().sort_values(ascending=False).head(5)
                    )
                    if not _top_p.empty:
                        st.markdown("**🏆 Top projetos no mês** (horas totais da equipe)")
                        for _nome_p, _h in _top_p.items():
                            _nome_p = _nome_p if _nome_p else "(sem projeto)"
                            st.markdown(f"- **{_nome_p}** — {_h:.1f} h")

                # Breakdown por projetista no mês (só se há >1 autor)
                _aut_mes = (
                    _df_mes.groupby('autor')['horas']
                    .sum().sort_values(ascending=False)
                )
                if len(_aut_mes) > 1:
                    st.markdown("**👥 Horas por projetista no mês**")
                    for _aut, _h in _aut_mes.items():
                        st.markdown(f"- **{_aut}** — {_h:.1f} h")

        # ── 1. FORMULÁRIO DE NOVO REGISTRO ───────────────────────────
        with st.expander("➕ Novo Relato, Dúvida ou Impedimento", expanded=False):
            _proj_opts = df_p['projeto'].tolist() if not df_p.empty else ["-"]
            p_sel = st.selectbox("Projeto", _proj_opts, key="diario_proj_sel")

            c_d1, c_d2 = st.columns(2)
            tipo_relato = c_d1.selectbox(
                "Tipo",
                ["Relato de Atividade", "❓ Dúvida Técnica", "🛑 Impedimento"],
                key="diario_tipo",
            )
            lista_disc = st.session_state.get(
                'lista_checklist', ["Geral", "Elétrica", "HVAC", "Hidráulica"]
            )
            r_disc = c_d2.selectbox("Disciplina", lista_disc, key="diario_disc")

            r_rel = st.text_area("Descrição do Relato", key="diario_texto")

            # Popover @mention: dropdown com nomes da equipe → appenda `@"Nome"`
            # no fim do texto. Substitui a digitação manual de `@"Nome Completo"`.
            _popover_mencionar(
                text_key="diario_texto",
                nomes_disponiveis=df_u['nome'].tolist() if not df_u.empty else [],
                label="@ Mencionar alguém da equipe",
                pop_key="pop_men_novo_relato",
                selecionado_key="pop_men_sel_novo_relato",
                eu_mesmo=st.session_state.get('usuario'),
            )

            c_h, c_a = st.columns([1, 3])
            r_horas = c_h.number_input(
                "⏱ Horas",
                min_value=0.0, max_value=24.0, step=0.25, value=0.0,
                format="%.2f",
                key="diario_horas",
                help="Tempo dedicado a este relato (em horas, frações OK). 0 = não preenchido.",
            )
            r_arq = c_a.file_uploader(
                "Anexo (Opcional)", type=['pdf', 'png', 'jpg', 'dwg', 'zip'],
                key="diario_upload",
            )

            if st.button("💾 Salvar Registro", use_container_width=True, key="diario_salvar"):
                if r_rel and p_sel != "-":
                    path = ""
                    if r_arq:
                        if not os.path.exists("anexos"):
                            os.makedirs("anexos")
                        path = os.path.join(
                            "anexos",
                            f"{datetime.now().strftime('%Y%m%d%H%M')}_{r_arq.name}",
                        )
                        with open(path, "wb") as f:
                            f.write(r_arq.getbuffer())

                    info_p = df_p[df_p['projeto'] == p_sel].iloc[0]
                    pid = info_p['id']

                    texto_final_banco = f"[{tipo_relato}] {r_rel}"

                    with db.conectar() as conn:
                        c = conn.cursor()
                        c.execute(
                            """INSERT INTO diario
                            (projeto_id, data, executado, autor, disciplina,
                             horas, anexo, resolvido)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                            RETURNING id""",
                            (int(pid),
                            datetime.now().strftime("%d/%m/%Y %H:%M"),
                            texto_final_banco,
                            st.session_state.usuario,
                            r_disc,
                            float(r_horas or 0),
                            path, 0),
                        )
                        _novo_relato_id = c.fetchone()[0]
                        conn.commit()

                    # Processa mencoes @"Nome" do texto: concede acesso + notifica + audita
                    _processar_mencoes_diario(
                        texto=r_rel, projeto_id=int(pid),
                        autor=st.session_state.usuario, relato_id=_novo_relato_id,
                        contexto='relato', lista_usuarios=df_u['nome'].tolist() if not df_u.empty else [],
                    )

                    st.success("Registro salvo!")
                    _invalidar_dados(); st.rerun()
                else:
                    st.warning("Selecione um projeto e escreva o relato.")

        st.divider()

        # ── RELATÓRIO PDF ───────────────────────────────────────────
        st.markdown("#### 📤 Gerar Relatório do Diário por Projeto")
        _projs_diario = df_p['projeto'].tolist() if not df_p.empty else []
        _col_rp1, _col_rp2 = st.columns([3, 1])
        _proj_rel_sel = _col_rp1.selectbox(
            "Selecionar projeto para relatório:",
            options=["— Selecione —"] + _projs_diario,
            key="diario_rel_proj",
            label_visibility="collapsed",
        )
        
        if _col_rp2.button("📄 Gerar PDF", key="btn_gerar_rel_diario", use_container_width=True):
            if _proj_rel_sel != "— Selecione —":
                _proj_info = df_p[df_p['projeto'] == _proj_rel_sel]
                if not _proj_info.empty:
                    _pid_rel = int(_proj_info.iloc[0]['id'])
                    _d_diario = df_d[df_d['projeto_id'] == _pid_rel] if not df_d.empty else pd.DataFrame()
                    try:
                        _pdf_diario = relatorios.gerar_pdf_diario(
                            _proj_info.iloc[0].to_dict(),
                            _d_diario,
                        )
                        st.session_state['_pdf_diario_bytes'] = _pdf_diario
                        st.session_state['_pdf_diario_nome'] = _proj_rel_sel
                        st.rerun()
                    except Exception as _e:
                        st.error(f"Erro ao gerar PDF: {_e}")
            else:
                st.warning("Selecione um projeto antes de gerar.")

        if st.session_state.get('_pdf_diario_bytes'):
            _nome_arq = st.session_state.get('_pdf_diario_nome', 'projeto')
            _nome_arq_safe = ''.join(c if c.isalnum() or c in ' _-' else '_' for c in _nome_arq)[:40]
            
            st.download_button(
                label=f"⬇️ Baixar PDF — {st.session_state['_pdf_diario_nome']}",
                data=st.session_state['_pdf_diario_bytes'],
                file_name=f"diario_{_nome_arq_safe}_{datetime.now().strftime('%d%m%Y')}.pdf",
                mime="application/pdf",
                use_container_width=True,
                key="dl_pdf_diario",
            )
            if st.button("✖ Limpar", key="limpar_pdf_diario"):
                st.session_state.pop('_pdf_diario_bytes', None)
                st.session_state.pop('_pdf_diario_nome', None)
                st.rerun()

        st.divider()

        # ── 2. AGRUPAMENTO POR PROJETO (CARDS) ───────────────────────
        if df_d.empty or df_p.empty:
            st.info("📭 Nenhum registro no diário ainda.")
        else:
            _proj_ids_com_diario = df_d['projeto_id'].unique().tolist()
            _projetos_diario = df_p[df_p['id'].isin(_proj_ids_com_diario)].copy()

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
                    proj_id = int(proj_row['id'])
                    proj_nome = str(proj_row['projeto'])

                    df_proj_d = df_d[df_d['projeto_id'] == proj_id].copy()
                    df_proj_d = df_proj_d.sort_values('id', ascending=False)

                    # CORREÇÃO: A busca agora também olha para o campo 'resposta_gestor' (onde ficam as interações)
                    if _busca_diario.strip():
                        t = _busca_diario.lower()
                        df_proj_d = df_proj_d[
                            df_proj_d['executado'].astype(str).str.lower().str.contains(t, na=False) |
                            df_proj_d['autor'].astype(str).str.lower().str.contains(t, na=False) |
                            df_proj_d['disciplina'].astype(str).str.lower().str.contains(t, na=False) |
                            df_proj_d['resposta_gestor'].astype(str).str.lower().str.contains(t, na=False)
                        ]
                    if _so_pendentes:
                        df_proj_d = df_proj_d[df_proj_d['resolvido'] == 0]

                    if df_proj_d.empty:
                        continue

                    _nao_lidos_proj = _mapa_nao_lidos.get(proj_id, 0)
                    _pendentes_proj = len(df_proj_d[df_proj_d['resolvido'] == 0])
                    _total_proj = len(df_proj_d)

                    _label_exp = f"📁 {proj_nome}  ({_total_proj} registro{'s' if _total_proj != 1 else ''})"
                    if _nao_lidos_proj:
                        _label_exp += f"  🔴 {_nao_lidos_proj} não lido{'s' if _nao_lidos_proj != 1 else ''}"
                    if _pendentes_proj:
                        _label_exp += f"  ⚠️ {_pendentes_proj} pendente{'s' if _pendentes_proj != 1 else ''}"

                    # Inteligência visual: Abre a pasta do projeto automaticamente se:
                    #  1) Tiver relato não lido, OU
                    #  2) Tiver menção @ pendente (sistema antigo, no resposta_gestor), OU
                    #  3) Usuário clicou "Ver" numa menção no painel persistente (forçou esse projeto)
                    usuario_mencionado = f"@{st.session_state.usuario}".lower()
                    tem_mencao_ativa = df_proj_d['resposta_gestor'].astype(str).str.lower().str.contains(usuario_mencionado, na=False).any()
                    _forcou_abrir = (st.session_state.get('_diario_abrir_proj') == proj_id)
                    _abrir = bool(_nao_lidos_proj > 0 or tem_mencao_ativa or _forcou_abrir)
                    # Consome os flags one-shot do painel de menções
                    # (abrir + destacar valem só pra UMA render; depois volta ao normal)
                    if _forcou_abrir:
                        st.session_state.pop('_diario_abrir_proj', None)
                        # Marca pra limpar o destaque no fim da iteração
                        _consumir_destaque_depois = True
                    else:
                        _consumir_destaque_depois = False

                    with st.expander(_label_exp, expanded=_abrir):
                        if _nao_lidos_proj:
                            db.marcar_projeto_diario_lido(proj_id, st.session_state.usuario)
                            _mapa_nao_lidos[proj_id] = 0

                        # Render dos relatos via fragmento (mantém o scroll do usuário
                        # ao excluir/resolver/responder, em vez de voltar pro topo).
                        # Passa proj_id + filtros; o fragmento re-consulta o banco sozinho.
                        _render_relatos_proj(
                            proj_id=proj_id,
                            busca=_busca_diario,
                            so_pendentes=_so_pendentes,
                            usuarios_para_render=df_u['nome'].tolist() if not df_u.empty else [],
                            autor_logado=st.session_state.usuario,
                            perfil=st.session_state.get('perfil', 'Projetista'),
                            destacar_relato_id=(
                                st.session_state.get('_diario_destacar_relato')
                                if _consumir_destaque_depois else None
                            ),
                        )

                        st.markdown("<br>", unsafe_allow_html=True)

    # --- ABA 7: CHAT (TEMPO REAL via @st.fragment) ---
    # O fragmento abaixo re-roda apenas a si mesmo a cada 5s, sem rerodar a pagina inteira.
    # (Era 2s — afrouxado p/ 5s pra cortar carga de fundo com muitos usuarios online.)
    # CSS injetado uma vez por sessão (no boot do fragmento dá pra cachear,
    # mas pra simplicidade re-injeta — Streamlit deduplica HTML idêntico).
    _CHAT_CSS = """
    <style>
    /* Bubbles estilo WhatsApp */
    .wa-row { display:flex; margin: 2px 0; align-items:flex-end; }
    .wa-row.mine { justify-content:flex-end; }
    .wa-row.theirs { justify-content:flex-start; }
    .wa-bub {
        max-width: 72%;
        padding: 6px 10px 4px;
        border-radius: 10px;
        font-size: 13.5px; line-height: 1.35;
        word-wrap: break-word; overflow-wrap: anywhere;
        box-shadow: 0 1px 2px rgba(0,0,0,0.25);
    }
    .wa-bub.mine   { background: #005c4b; color: #e9edef;
                     border-bottom-right-radius: 2px; }
    .wa-bub.theirs { background: #202c33; color: #e9edef;
                     border-bottom-left-radius: 2px; }
    .wa-meta { font-size: 10px; opacity: .6; margin-top: 2px;
               text-align: right; }
    .wa-who  { font-size: 11px; font-weight: 600; color: #6ab1ff;
               margin-bottom: 1px; }
    .wa-date-sep { text-align: center; margin: 12px 0 6px; }
    .wa-date-sep span { background: rgba(255,255,255,0.06);
                        color: #94a3b8; font-size: 11px; padding: 2px 10px;
                        border-radius: 10px; }
    .wa-empty { color: #6b7280; text-align: center;
                font-size: 13px; padding: 24px; }
    </style>
    """

    @st.fragment(run_every="2s")
    def _render_chat_messages(usuario, contato_nome):
        try:
            df_m = pd.read_sql_query(
                "SELECT * FROM chat WHERE (remetente = %s AND destinatario = %s) "
                "OR (remetente = %s AND destinatario = %s) ORDER BY id ASC",
                db.get_engine(),
                params=(usuario, contato_nome, contato_nome, usuario),
            )
        except Exception as e:
            st.error(f"Erro ao carregar mensagens: {e}")
            df_m = pd.DataFrame()

        st.markdown(_CHAT_CSS, unsafe_allow_html=True)

        chat_box = st.container(border=True, height=520)
        with chat_box:
            if df_m.empty:
                st.markdown(
                    "<div class='wa-empty'>"
                    "Nenhuma mensagem por aqui ainda — manda um oi 👋"
                    "</div>",
                    unsafe_allow_html=True,
                )
                return

            # Render: agrupa por dia com separador "hoje / ontem / DD/MM"
            _hoje_chat = datetime.now().date()
            _ultimo_dia = None

            # `enumerate` pra ter um índice único como salvaguarda nos keys
            # (defensivo: se algum dia df_m tiver linha duplicada por bug
            # de query/migração, keys colidem; índice torna unique).
            for _idx_m, (_, m) in enumerate(df_m.iterrows()):
                sou_eu = m['remetente'] == usuario
                _msg_id = int(m['id'])
                _kfx = f"{_msg_id}_{_idx_m}"   # sufixo de key

                # Separador de dia
                try:
                    _dt_msg = pd.to_datetime(str(m['data']), errors='coerce')
                    _dia = _dt_msg.date() if pd.notna(_dt_msg) else None
                except Exception:
                    _dia = None
                if _dia and _dia != _ultimo_dia:
                    if _dia == _hoje_chat:
                        _lbl_dia = "Hoje"
                    elif _dia == _hoje_chat - pd.Timedelta(days=1):
                        _lbl_dia = "Ontem"
                    else:
                        _lbl_dia = _dia.strftime("%d/%m/%Y")
                    st.markdown(
                        f"<div class='wa-date-sep'>"
                        f"<span>{_lbl_dia}</span></div>",
                        unsafe_allow_html=True,
                    )
                    _ultimo_dia = _dia

                # Está em modo edição?
                _em_edit = st.session_state.get(f"edit_mode_{_msg_id}", False)

                # Bolha + horário compactos
                _horario = (_dt_msg.strftime("%H:%M")
                            if _dia is not None and pd.notna(_dt_msg)
                            else _tempo_relativo(m['data']))
                _who_html = (f"<div class='wa-who'>{m['remetente']}</div>"
                             if not sou_eu else "")
                _classe = "mine" if sou_eu else "theirs"

                # Marca "(editado)" se a mensagem foi modificada — estilo
                # WhatsApp. Coluna editado_em populada por editar_mensagem_chat.
                _edit_marker = ""
                _ed_raw = m.get('editado_em') if 'editado_em' in m else None
                if _ed_raw is not None and not (
                    isinstance(_ed_raw, float) and pd.isna(_ed_raw)
                ):
                    try:
                        _ed_dt = pd.to_datetime(_ed_raw, errors='coerce')
                        if pd.notna(_ed_dt):
                            _edit_marker = (
                                " <span style='opacity:.55;font-style:italic;"
                                "font-size:9.5px;' "
                                f"title='Editado em {_ed_dt.strftime('%d/%m/%Y %H:%M')}'>"
                                "(editado)</span>"
                            )
                    except Exception:
                        pass

                _bolha_html = (
                    f"<div class='wa-row {_classe}'>"
                    f"<div class='wa-bub {_classe}'>"
                    f"{_who_html}"
                    f"{_safe_chat_html(m['mensagem'])}"
                    f"<div class='wa-meta'>{_edit_marker}{_horario}</div>"
                    f"</div></div>"
                )

                if sou_eu:
                    # Layout: bolha (92%) + popover ⋯ (8%) alinhados à direita
                    cm_main, cm_act = st.columns([0.92, 0.08])
                    cm_main.markdown(_bolha_html, unsafe_allow_html=True)
                    with cm_act:
                        with st.popover("⋯", use_container_width=True,
                                        help="Ações da mensagem"):
                            if st.button("✏️ Editar", key=f"ed_{_kfx}",
                                         use_container_width=True):
                                st.session_state[f"edit_mode_{_msg_id}"] = True
                                st.rerun(scope="fragment")
                            if st.button("🗑️ Apagar", key=f"del_{_kfx}",
                                         use_container_width=True):
                                db.excluir_mensagem_chat(_msg_id)
                                st.rerun(scope="fragment")
                else:
                    st.markdown(_bolha_html, unsafe_allow_html=True)

                # Editor inline (logo abaixo da mensagem)
                if sou_eu and _em_edit:
                    with st.container(border=True):
                        _novo_txt = st.text_input(
                            "Corrigir mensagem",
                            value=str(m['mensagem']),
                            key=f"inp_{_kfx}",
                            label_visibility="collapsed",
                        )
                        ec1, ec2 = st.columns(2)
                        if ec1.button("✅ Salvar", key=f"sv_{_kfx}",
                                      use_container_width=True):
                            db.editar_mensagem_chat(_msg_id, _novo_txt)
                            st.session_state[f"edit_mode_{_msg_id}"] = False
                            st.rerun(scope="fragment")
                        if ec2.button("✖ Cancelar", key=f"cn_{_kfx}",
                                      use_container_width=True):
                            st.session_state[f"edit_mode_{_msg_id}"] = False
                            st.rerun(scope="fragment")

            # ── ÂNCORA + AUTO-SCROLL INTELIGENTE ─────────────────
            # Só rola pra baixo se o usuário JÁ está perto do fim (≤ 200px).
            # Se estiver lendo histórico no meio, não bagunça a leitura.
            st.markdown(
                "<div id='wa-bot-anchor'></div>",
                unsafe_allow_html=True,
            )

        # Script vai DEPOIS de fechar o container, pra rodar quando o
        # DOM da lista já está montado. Roda dentro de iframe, então
        # acessa o DOM principal via window.parent.document.
        import streamlit.components.v1 as _components
        _components.html(
            """
            <script>
            (function () {
                try {
                    var doc = window.parent.document;
                    var anchor = doc.getElementById('wa-bot-anchor');
                    if (!anchor) return;

                    // Acha o ancestor scrollable (st.container(height=N) põe
                    // overflow-y:auto num div interno).
                    var node = anchor.parentElement;
                    var scrollable = null;
                    while (node && node !== doc.body) {
                        var cs = window.parent.getComputedStyle(node);
                        if (cs.overflowY === 'auto' || cs.overflowY === 'scroll') {
                            scrollable = node;
                            break;
                        }
                        node = node.parentElement;
                    }
                    if (!scrollable) return;

                    // "Perto do fim" = últimos 200px
                    var diff = scrollable.scrollHeight
                             - scrollable.scrollTop
                             - scrollable.clientHeight;
                    if (diff < 200) {
                        scrollable.scrollTop = scrollable.scrollHeight;
                    }
                } catch (e) { /* silencia erro de JS */ }
            })();
            </script>
            """,
            height=0,
        )

    # === FRAGMENTO GLOBAL: TOAST DE NOVA MENSAGEM / MENÇÃO NO DIÁRIO ===
    # Re-roda a cada 10s em QUALQUER aba. (Foi 30s; trazendo de volta pra 10s
    # pra toast de nova mensagem aparecer rápido conforme pedido do usuário,
    # mantendo carga modesta — 1 SELECT a cada 10s/usuario online.)
    @st.fragment(run_every="10s")
    def _global_notif(usuario):
        # 1) Chat
        ultimas_chat = st.session_state.get('_chat_ultimas_contagens', {})
        atuais_chat = dict(db.listar_remetentes_com_nao_lidas(usuario))
        _ultimo_remetente_novo = None  # quem foi o autor da última msg nova
        for rem, qtd in atuais_chat.items():
            anterior = ultimas_chat.get(rem, 0)
            if qtd > anterior:
                novas = qtd - anterior
                # Toast com instrução pra ir à aba Chat (st.toast não é
                # clicável nativamente — quando o usuário FINALMENTE entrar
                # na aba Chat, o selectbox abre direto no `rem` graças ao
                # `_chat_proximo_contato` setado abaixo).
                st.toast(
                    f"💬 **{novas} nova(s) de {rem}** — abra a aba 💬 Chat",
                    icon="🔔",
                )
                _ultimo_remetente_novo = rem
        st.session_state['_chat_ultimas_contagens'] = atuais_chat
        # Memoriza o último remetente com msg nova → o selectbox da aba Chat
        # vai abrir nele automaticamente, sem o usuário precisar caçar.
        if _ultimo_remetente_novo:
            st.session_state['_chat_proximo_contato'] = _ultimo_remetente_novo

        # 2) Menções no Diário (decisão 5: toast mesmo se ja tinha acesso)
        # Agrupa as pendentes por (remetente, projeto_id) p/ nao spammar 1 toast por relato
        ultimas_mn = st.session_state.get('_mencoes_ultimas_contagens', 0)
        atuais_mn = db.contar_mencoes_nao_vistas(usuario)
        if atuais_mn > ultimas_mn:
            pendentes = db.listar_mencoes_nao_vistas(usuario)
            # Pega so as novas (alem das que ja existiam)
            novas = pendentes[ultimas_mn:] if len(pendentes) >= ultimas_mn else pendentes
            agrupado = {}
            for rem, _proj_id, _ctx in novas:
                agrupado[rem] = agrupado.get(rem, 0) + 1
            for rem, qtd in agrupado.items():
                st.toast(f"📝 **Você foi mencionado por {rem}** ({qtd}x no Diário)", icon="🔔")
        st.session_state['_mencoes_ultimas_contagens'] = atuais_mn

    _global_notif(st.session_state.usuario)

    with t_chat:
        st.header("💬 Chat Interno")
        st.caption("🟢 Tempo real — mensagens novas aparecem em até 2 segundos sem precisar atualizar.")

        # 1. Seleção de Contato com badge de não-lidas por usuário
        lista_usuarios = df_u['nome'].tolist() if not df_u.empty else []
        if st.session_state.usuario in lista_usuarios:
            lista_usuarios.remove(st.session_state.usuario)

        # Mapa "remetente → qtd não lidas" pra mostrar (N) ao lado do nome.
        # Sara Borges (3) · Leticia · Rodrigo (1)
        _nao_lidas_por_user = dict(
            db.listar_remetentes_com_nao_lidas(st.session_state.usuario)
        )
        # Ordena: quem tem não-lidas vai pro topo, depois alfabético
        lista_usuarios.sort(
            key=lambda n: (-int(_nao_lidas_por_user.get(n, 0)), n.lower())
        )

        def _fmt_contato(nome):
            _q = int(_nao_lidas_por_user.get(nome, 0))
            return f"🔴 {nome} ({_q})" if _q > 0 else nome

        # Pré-seleção: se o toast global setou alguém com msg nova, sobrescreve
        # a key do widget ANTES dele renderizar (Streamlit usa o session_state
        # como valor inicial). Equivale a "clicar no toast" → entrar direto na
        # conversa certa, sem o usuário ter que caçar na lista.
        _prox = st.session_state.pop('_chat_proximo_contato', None)
        if _prox and _prox in lista_usuarios:
            st.session_state["sel_contato_final_v2"] = _prox

        contato = st.selectbox(
            "Conversar com:",
            lista_usuarios,
            format_func=_fmt_contato,
            key="sel_contato_final_v2",
        )

        if contato:
            # Marca como lidas todas as mensagens recebidas desse contato
            db.marcar_lidas(st.session_state.usuario, contato)
            # 2. Render do paineil de mensagens (auto-refresh 2s via fragmento)
            _render_chat_messages(st.session_state.usuario, contato)

            # 3. Campo de Envio compacto (fora do fragmento; submete a pagina)
            # Layout: text_area largo + botão "➤" único caractere na lateral.
            # Em tela estreita (~280px de coluna), botão com label longo virava
            # "▶ E n v i a r" empilhado vertical letra-a-letra. Solução: usar
            # 1 char (➤) com tooltip + CSS pra esticar verticalmente.
            st.markdown(
                """
                <style>
                /* Botão envia: 1 char grande e centralizado em qualquer tela */
                div[data-testid="stFormSubmitButton"] button {
                    font-size: 1.6rem !important;
                    font-weight: 600 !important;
                    min-height: 86px;
                    line-height: 1 !important;
                    padding: 4px !important;
                }
                </style>
                """,
                unsafe_allow_html=True,
            )
            with st.form("f_chat_v3_final", clear_on_submit=True):
                in_c1, in_c2 = st.columns([6, 1], gap="small")
                msg_input = in_c1.text_area(
                    "Digite uma mensagem...",
                    height=86,
                    label_visibility="collapsed",
                    placeholder="Digite uma mensagem...",
                )
                _enviar = in_c2.form_submit_button(
                    "➤",
                    use_container_width=True,
                    help="Enviar mensagem",
                )
                if _enviar and msg_input.strip():
                    # Grava timestamp completo "DD/MM/YYYY HH:MM" pra suporte
                    # ao separador de dias no histórico.
                    conn = db.conectar(); c = conn.cursor()
                    _agora_iso = datetime.now().strftime("%d/%m/%Y %H:%M")
                    c.execute(
                        "INSERT INTO chat (remetente, destinatario, mensagem, data) "
                        "VALUES (%s,%s,%s,%s)",
                        (st.session_state.usuario, contato, msg_input.strip(),
                         _agora_iso),
                    )
                    conn.commit(); conn.close()
                    st.rerun()
        else:
            st.info("Selecione um contato pra iniciar a conversa.")

    # --- ABA 6: EQUIPE (GESTÃO DE ACESSOS, PERFIS E CARGOS) ---
    with t_equipe:
        # 1. Trava de Segurança: Apenas quem é Gestor no banco pode mexer aqui
        if st.session_state.get('perfil') != "Gestor":
            st.error("⚠️ Acesso Restrito: Apenas Gestores podem gerenciar permissões da equipe.")
        else:
            st.header("👥 Gestão de Membros e Acessos")
            
            # 2. CADASTRO DE NOVO MEMBRO
            with st.expander("➕ Cadastrar Novo Colaborador"):
                with st.form("novo_usuario_form"):
                    c1, c2 = st.columns(2)
                    n_nome = c1.text_input("Nome Completo")
                    n_cargo = c2.text_input("Cargo (ex: Eng. Civil, Estagiário HVAC)")
                    
                    c3, c4 = st.columns(2)
                    n_senha = c3.text_input("Senha de Acesso", type="password")
                    n_perf = c4.selectbox(
                        "Perfil de Sistema",
                        ["Projetista", "Gestor", "Visualizador"],
                        help="Visualizador: acesso somente leitura (não pode criar, editar ou excluir nada).",
                    )

                    # Pergunta secreta (usada na recuperação de senha)
                    n_email = st.text_input("E-mail (opcional)", placeholder="usado para contato futuro")
                    cp1, cp2 = st.columns(2)
                    n_perg = cp1.text_input(
                        "Pergunta secreta",
                        placeholder="ex.: Nome do primeiro pet?",
                        help="Usada para recuperar a senha caso o usuário esqueça.",
                    )
                    n_resp = cp2.text_input(
                        "Resposta secreta",
                        type="password",
                        placeholder="a resposta da pergunta acima",
                    )

                    if st.form_submit_button("Finalizar Cadastro", use_container_width=True):
                        if n_nome and n_senha:
                            conn = db.conectar(); c = conn.cursor()
                            c.execute("SELECT * FROM usuarios WHERE nome = %s", (n_nome,))
                            if c.fetchone():
                                st.error("Este nome já está cadastrado.")
                            else:
                                _resp_hash = db.gerar_hash(n_resp.strip().lower()) if n_resp.strip() else None
                                c.execute(
                                    "INSERT INTO usuarios (nome, senha, perfil, cargo, email, pergunta_secreta, resposta_secreta) "
                                    "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                                    (n_nome, db.gerar_hash(n_senha), n_perf, n_cargo,
                                     n_email.strip() or None,
                                     n_perg.strip() or None, _resp_hash),
                                )
                                conn.commit()
                                if not n_perg.strip() or not n_resp.strip():
                                    st.warning(f"Membro {n_nome} criado, mas SEM pergunta secreta — ele não poderá recuperar a senha sozinho.")
                                else:
                                    st.success(f"Membro {n_nome} adicionado com sucesso!")
                            conn.close(); _invalidar_dados(); st.rerun()
                        else:
                            st.warning("Nome e Senha são obrigatórios.")

            st.divider()

            # 3. LISTAGEM DE USUÁRIOS
            df_membros = pd.read_sql_query(
                "SELECT * FROM usuarios ORDER BY "
                "CASE perfil WHEN 'Gestor' THEN 0 WHEN 'Projetista' THEN 1 ELSE 2 END, nome",
                db.get_engine(),
            )

            # Métricas de composição da equipe
            mc1, mc2, mc3, mc4 = st.columns(4)
            mc1.metric("👥 Total", len(df_membros))
            mc2.metric("🛡️ Gestores", int((df_membros['perfil'] == 'Gestor').sum()))
            mc3.metric("✏️ Projetistas", int((df_membros['perfil'] == 'Projetista').sum()))
            mc4.metric("👁️ Visualizadores", int((df_membros['perfil'] == 'Visualizador').sum()))

            st.subheader("Membros da Equipe")
            _busca_membro = st.text_input(
                "🔍 Buscar por nome ou cargo", key="busca_membro",
                placeholder="ex.: rodrigo, eletricista...", label_visibility="collapsed",
            )
            if _busca_membro.strip():
                _t = _busca_membro.lower()
                df_membros = df_membros[
                    df_membros['nome'].astype(str).str.lower().str.contains(_t, na=False) |
                    df_membros['cargo'].astype(str).str.lower().str.contains(_t, na=False)
                ]

            _cores_perfil = {'Gestor': '#b01a2c', 'Projetista': '#0056b3', 'Visualizador': '#6b7280'}

            if df_membros.empty:
                _empty_state(
                    "🔎",
                    "Nenhum membro encontrado",
                    "Sua busca não retornou ninguém. Tente outro termo, "
                    "ou apague o filtro pra ver todos.",
                    cor_borda="#d97706",
                )

            for _, u in df_membros.iterrows():
                cor_p = _cores_perfil.get(u['perfil'], '#0056b3')
                cargo_txt = u.get('cargo') or 'Colaborador'
                email_txt = u.get('email') or ''
                eh_eu = (u['nome'] == st.session_state.usuario)
                tem_perg = bool(u.get('pergunta_secreta'))

                with st.container(border=True):
                    cav, cinfo, cbadge = st.columns([0.13, 0.67, 0.20])
                    # Avatar circular
                    cav.markdown(_avatar_circular_html(u.get('avatar_path'), size=58), unsafe_allow_html=True)
                    # Identificação
                    with cinfo:
                        _voce = " <span style='opacity:.55;font-size:.78rem'>(você)</span>" if eh_eu else ""
                        _star = "⭐ " if eh_eu else ""
                        _perg_html = (
                            "<span style='color:#10b981'>🔑 recuperação ativa</span>" if tem_perg
                            else "<span style='color:#f59e0b'>⚠️ sem pergunta secreta</span>"
                        )
                        st.markdown(
                            f"<div style='font-size:1.08rem;font-weight:700'>{_star}{u['nome']}{_voce}</div>"
                            f"<div style='opacity:.78;font-style:italic;font-size:.88rem'>💼 {cargo_txt}</div>"
                            + (f"<div style='opacity:.62;font-size:.8rem'>✉️ {email_txt}</div>" if email_txt else "")
                            + f"<div style='font-size:.72rem;margin-top:2px'>{_perg_html}</div>",
                            unsafe_allow_html=True,
                        )
                    # Badge do perfil
                    cbadge.markdown(
                        f"<div style='text-align:right'><span style='background:{cor_p};color:#fff;"
                        f"padding:3px 12px;border-radius:14px;font-size:.7rem;font-weight:700;"
                        f"text-transform:uppercase;letter-spacing:.5px'>{u['perfil']}</span></div>",
                        unsafe_allow_html=True,
                    )

                    # Ações
                    ca1, ca2, _ca3 = st.columns([0.28, 0.30, 0.42])
                    if ca1.button("✏️ Editar", key=f"ed_u_{u['id']}", use_container_width=True):
                        st.session_state[f"editor_u_{u['id']}"] = not st.session_state.get(f"editor_u_{u['id']}", False)

                    with ca2.popover("🗑️ Remover", use_container_width=True):
                        if u['nome'] == st.session_state.usuario:
                            st.error("Não é possível excluir o próprio usuário logado.")
                        else:
                            st.markdown(f"**Remover `{u['nome']}` permanentemente?**")
                            st.caption("Esta ação não pode ser desfeita. O usuário perderá acesso imediatamente.")
                            if st.button("✅ Sim, remover", key=f"yes_del_u_{u['id']}", type="primary", use_container_width=True):
                                conn = db.conectar(); c = conn.cursor()
                                c.execute("DELETE FROM usuarios WHERE id = %s", (u['id'],))
                                conn.commit(); conn.close()
                                db.log_aud(st.session_state.usuario, 'excluir', 'usuario', u['id'], f"nome='{u['nome']}'")
                                st.toast(f"Membro '{u['nome']}' removido.")
                                _invalidar_dados(); st.rerun()

                    # PAINEL DE EDIÇÃO INTEGRADO
                    if st.session_state.get(f"editor_u_{u['id']}"):
                        st.divider()
                        ce1, ce2 = st.columns(2)
                        up_nome = ce1.text_input("Nome", value=u['nome'], key=f"n_{u['id']}")
                        up_cargo = ce2.text_input("Cargo", value=cargo_txt, key=f"c_{u['id']}")

                        ce3, ce4 = st.columns(2)
                        # IMPORTANTE: campo de senha sempre VAZIO no edit (nao da pra
                        # "ler" a senha atual porque ela esta hasheada). Se o admin
                        # deixar vazio, mantemos a senha existente; se digitar algo,
                        # hasheamos antes de salvar. Sem isso, salvariamos texto puro
                        # no banco e o login deixava de funcionar pra esse usuario.
                        up_senha = ce3.text_input(
                            "Nova senha",
                            value="",
                            type="password",
                            placeholder="Deixe vazio para manter a atual",
                            key=f"s_{u['id']}",
                            help="Só preencha se quiser TROCAR a senha. Senha em branco mantém a que ja existe.",
                        )
                        _perfis = ["Projetista", "Gestor", "Visualizador"]
                        up_perf = ce4.selectbox(
                            "Perfil", _perfis,
                            index=_perfis.index(u['perfil']) if u['perfil'] in _perfis else 0,
                            key=f"p_{u['id']}",
                        )

                        # Pergunta secreta (recuperação de senha). Carrega a pergunta atual;
                        # resposta sempre vazia (é hash, não dá pra exibir).
                        _tem_pergunta = bool(u.get('pergunta_secreta'))
                        cps1, cps2 = st.columns(2)
                        up_perg = cps1.text_input(
                            "Pergunta secreta",
                            value=u.get('pergunta_secreta') or "",
                            key=f"perg_{u['id']}",
                            help="Usada na recuperação de senha.",
                        )
                        up_resp = cps2.text_input(
                            "Nova resposta secreta",
                            value="",
                            type="password",
                            placeholder=("Deixe vazio p/ manter" if _tem_pergunta else "defina a resposta"),
                            key=f"resp_{u['id']}",
                        )

                        if st.button("💾 Salvar Alterações", key=f"sv_u_{u['id']}", use_container_width=True):
                            # Senha: vazio mantém, preenchido hasheia
                            if up_senha.strip():
                                _senha_para_salvar = db.gerar_hash(up_senha)
                                _msg = "Dados atualizados (senha trocada)."
                            else:
                                _senha_para_salvar = u['senha']
                                _msg = "Dados atualizados (senha mantida)."
                            # Resposta secreta: vazio mantém o hash atual, preenchido re-hasheia
                            if up_resp.strip():
                                _resp_para_salvar = db.gerar_hash(up_resp.strip().lower())
                            else:
                                _resp_para_salvar = u.get('resposta_secreta')
                            conn = db.conectar(); c = conn.cursor()
                            c.execute(
                                "UPDATE usuarios SET nome=%s, cargo=%s, senha=%s, perfil=%s, "
                                "pergunta_secreta=%s, resposta_secreta=%s WHERE id=%s",
                                (up_nome, up_cargo, _senha_para_salvar, up_perf,
                                 up_perg.strip() or None, _resp_para_salvar, u['id']),
                            )
                            conn.commit(); conn.close()
                            st.session_state[f"editor_u_{u['id']}"] = False
                            _invalidar_dados(); st.success(_msg); st.rerun()

            st.markdown("<br>", unsafe_allow_html=True)

    # --- ABA 5: ARQUIVOS (CENTRAL DE DOCUMENTAÇÃO) ---
    with t_arquivos:
        st.header("📁 Central de Arquivos Técnicos")
        st.caption(
            "Anexe documentos a projetos específicos. Os arquivos ficam salvos no servidor "
            "em `anexos/<id_projeto>/...` e os metadados (descrição, autor, data) na tabela `arquivos`."
        )

        # Mapeamento id->nome (usado em varios lugares abaixo)
        _projetos_validos = df_p[df_p['projeto'].notna() & (df_p['projeto'] != '')] if not df_p.empty else pd.DataFrame()
        _id_para_nome = dict(zip(_projetos_validos['id'], _projetos_validos['projeto'])) if not _projetos_validos.empty else {}

        # === BLOCO DE UPLOAD ===
        with st.expander("⬆️ Anexar Novo Arquivo", expanded=False):
            if _projetos_validos.empty:
                st.warning("Cadastre ao menos um projeto na aba ➕ Novo Projeto antes de enviar arquivos.")
            else:
                with st.form("form_upload_arquivo", clear_on_submit=True):
                    col_u1, col_u2 = st.columns([1, 1])
                    proj_alvo_id = col_u1.selectbox(
                        "Vincular ao Projeto*",
                        options=list(_id_para_nome.keys()),
                        format_func=lambda x: _id_para_nome.get(x, '?'),
                        key="upload_proj_alvo",
                    )
                    desc_upload = col_u2.text_input("Descrição (opcional)", key="upload_desc")
                    arquivos_novos = st.file_uploader(
                        "Selecione um ou mais arquivos",
                        accept_multiple_files=True,
                        key="upload_files",
                        help="Limite de 100 MB por arquivo (config em .streamlit/config.toml).",
                    )
                    submit_upload = st.form_submit_button(
                        "📤 Enviar arquivos", use_container_width=True
                    )

                if submit_upload:
                    if not arquivos_novos:
                        st.warning("Selecione ao menos um arquivo antes de enviar.")
                    else:
                        ok = 0
                        for arq in arquivos_novos:
                            pasta, path_final = db.caminho_seguro_para_anexo(proj_alvo_id, arq.name)
                            os.makedirs(pasta, exist_ok=True)
                            with open(path_final, "wb") as f:
                                f.write(arq.getbuffer())
                            db.salvar_arquivo(
                                projeto_id=proj_alvo_id,
                                nome_original=arq.name,
                                path_arquivo=path_final,
                                descricao=desc_upload,
                                autor=st.session_state.usuario,
                                tamanho_bytes=arq.size,
                                mime_type=arq.type or "",
                            )
                            db.log_aud(st.session_state.usuario, 'upload', 'arquivo', proj_alvo_id, f"nome='{arq.name}', {arq.size}B")
                            ok += 1
                        st.success(f"✅ {ok} arquivo(s) enviado(s) e vinculado(s) ao projeto **{_id_para_nome[proj_alvo_id]}**")
                        st.rerun()

        st.divider()

        # === FILTRO + MÉTRICAS ===
        col_f1, col_f2, col_f3 = st.columns([2, 1, 1])
        opcoes_filtro = [None] + list(_id_para_nome.keys())
        filtro_proj_id = col_f1.selectbox(
            "Filtrar por projeto",
            options=opcoes_filtro,
            format_func=lambda x: "📂 Todos os projetos" if x is None else _id_para_nome.get(x, '?'),
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
                '.pdf': '📄', '.dwg': '📐', '.dxf': '📐',
                '.jpg': '🖼️', '.jpeg': '🖼️', '.png': '🖼️', '.gif': '🖼️',
                '.xls': '📊', '.xlsx': '📊', '.csv': '📊',
                '.doc': '📝', '.docx': '📝', '.txt': '📝',
                '.zip': '🗜️', '.rar': '🗜️', '.7z': '🗜️',
            }
            for row in arquivos_lista:
                arq_id, proj_id, nome_original, path_arquivo, descricao, autor, data_upload, tamanho_bytes = row
                ext = os.path.splitext(nome_original)[1].lower()
                icone = _icones.get(ext, '📎')
                proj_nome = _id_para_nome.get(proj_id, '(projeto removido)')

                if tamanho_bytes is None:
                    tamanho_str = "—"
                elif tamanho_bytes < 1024:
                    tamanho_str = f"{tamanho_bytes} B"
                elif tamanho_bytes < 1024 * 1024:
                    tamanho_str = f"{tamanho_bytes / 1024:.1f} KB"
                else:
                    tamanho_str = f"{tamanho_bytes / (1024 * 1024):.1f} MB"

                # Formata data como dd/mm/YYYY HH:MM
                try:
                    data_fmt = datetime.fromisoformat(data_upload.replace('T', ' ')).strftime('%d/%m/%Y %H:%M')
                except Exception:
                    data_fmt = str(data_upload)

                with st.container(border=True):
                    c_ic, c_info, c_btns = st.columns([0.08, 0.62, 0.30])
                    c_ic.markdown(
                        f"<div style='font-size:38px; text-align:center; padding-top:6px;'>{icone}</div>",
                        unsafe_allow_html=True,
                    )
                    with c_info:
                        st.markdown(f"**{nome_original}**")
                        st.caption(
                            f"📂 **{proj_nome}**  ·  👤 {autor or '—'}  ·  "
                            f"📅 {data_fmt}  ·  💾 {tamanho_str}"
                        )
                        if descricao:
                            st.markdown(f"<span style='font-size:0.85rem;opacity:0.9'>💬 {descricao}</span>",
                                        unsafe_allow_html=True)
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
                        pode_excluir = (st.session_state.get('perfil') == 'Gestor'
                                        or autor == st.session_state.get('usuario'))
                        if pode_excluir:
                            with st.popover("🗑️ Excluir", use_container_width=True):
                                st.markdown(f"**Excluir `{nome_original}` permanentemente?**")
                                st.caption("O arquivo será removido do disco e do registro do projeto.")
                                if st.button("✅ Sim, excluir", key=f"yes_del_arq_{arq_id}", type="primary", use_container_width=True):
                                    db.excluir_arquivo(arq_id)
                                    db.log_aud(st.session_state.usuario, 'excluir', 'arquivo', arq_id, f"nome='{nome_original}'")
                                    st.toast(f"Arquivo '{nome_original}' removido.")
                                    st.rerun()

    # ═══════════════════════════════════════════════════════════════
    #  ABA AGENDA  —  cole este bloco substituindo o "with t_agenda:"
    #  Dependências extras já presentes no projeto: pandas, plotly
    # ═══════════════════════════════════════════════════════════════

    with t_agenda:
        st.header("📅 Agenda e Disponibilidade")

        usuario_atual = st.session_state.get('usuario', '')
        perfil_atual  = st.session_state.get('perfil', 'Colaborador')

        # ── recarrega agenda do banco único ──────────────────────────
        try:
            df_agenda = pd.read_sql(
                "SELECT * FROM agenda ORDER BY data_inicio ASC",
                db.get_engine(),
            )
        except Exception:
            df_agenda = pd.DataFrame(columns=['id','titulo','tipo','data_inicio',
                                            'data_fim','responsaveis','descricao','local'])

        # ── MÉTRICAS NO TOPO (4 cards) ────────────────────────────────
        # Cálculo sobre o df_agenda inteiro, mas respeitando visibilidade
        # por perfil (Gestor vê tudo, outros só os seus).
        _hoje_ag      = datetime.now().date()
        _limite_7d_ag = _hoje_ag + pd.Timedelta(days=7)
        _ini_mes_ag   = _hoje_ag.replace(day=1)
        import calendar as _cal_ag
        _fim_mes_ag   = _hoje_ag.replace(
            day=_cal_ag.monthrange(_hoje_ag.year, _hoje_ag.month)[1]
        )

        _df_ag_visivel = df_agenda.copy() if not df_agenda.empty else df_agenda
        if not _df_ag_visivel.empty:
            _df_ag_visivel['_di'] = pd.to_datetime(
                _df_ag_visivel['data_inicio'], errors='coerce'
            ).dt.date
            _df_ag_visivel['_df'] = pd.to_datetime(
                _df_ag_visivel['data_fim'], errors='coerce'
            ).dt.date
            if perfil_atual != "Gestor":
                _df_ag_visivel = _df_ag_visivel[
                    _df_ag_visivel['responsaveis'].astype(str)
                    .str.contains(usuario_atual, na=False)
                ]

        def _toca_janela(row, ini, fim):
            di, df_ = row.get('_di'), row.get('_df') or row.get('_di')
            return (di is not None and df_ is not None
                    and df_ >= ini and di <= fim)

        if _df_ag_visivel.empty:
            _qtd_7d = _qtd_visitas_mes = _qtd_ausentes_hoje = _qtd_total_mes = 0
        else:
            _qtd_7d = int(_df_ag_visivel.apply(
                lambda r: _toca_janela(r, _hoje_ag, _limite_7d_ag), axis=1
            ).sum())
            _qtd_visitas_mes = int(((_df_ag_visivel['tipo'] == 'Visita Técnica')
                & _df_ag_visivel.apply(
                    lambda r: _toca_janela(r, _ini_mes_ag, _fim_mes_ag), axis=1
                )).sum())
            _qtd_ausentes_hoje = int((
                _df_ag_visivel['tipo'].isin(['Férias','Licença','Folga'])
                & _df_ag_visivel.apply(
                    lambda r: _toca_janela(r, _hoje_ag, _hoje_ag), axis=1
                )
            ).sum())
            _qtd_total_mes = int(_df_ag_visivel.apply(
                lambda r: _toca_janela(r, _ini_mes_ag, _fim_mes_ag), axis=1
            ).sum())

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("📌 Próximos 7 dias", _qtd_7d,
                  help="Eventos que tocam a janela de hoje até hoje+7d.")
        m2.metric("🏗️ Visitas no mês", _qtd_visitas_mes,
                  help="Eventos do tipo Visita Técnica neste mês.")
        m3.metric("🏖️ Ausentes hoje", _qtd_ausentes_hoje,
                  delta="férias/licença/folga", delta_color="off",
                  help="Membros em ausência registrada (Férias/Licença/Folga) hoje.")
        m4.metric("📅 Total no mês", _qtd_total_mes,
                  help="Todos os compromissos que tocam o mês atual.")

        st.divider()

        # ── TOGGLE DE VISÃO ──────────────────────────────────────────
        # Mensal: calendário HTML grid 7 colunas (visualização espacial)
        # Semanal: 7 cards horizontais com eventos por dia (detalhe semanal)
        # Lista: tabela vertical filtrada (operacional, edit/delete)
        # Resumo: dashboard executivo (próximos 7d, stats, top membros)
        visao_ag = _pill_select(
            st, "Visão da Agenda",
            options=["Mensal", "Semanal", "Lista", "Resumo"],
            default="Mensal",
            key="agenda_visao",
            label_visibility="collapsed",
        ) or "Mensal"

        # ── exportar .ics ─────────────────────────────────────────────
        if not df_agenda.empty:
            df_exp = df_agenda if perfil_atual == "Gestor" else \
                    df_agenda[df_agenda['responsaveis'].str.contains(usuario_atual, na=False)]
            leg = "(todos os eventos)" if perfil_atual == "Gestor" else "(somente os seus)"
            if not df_exp.empty:
                st.download_button(
                    f"📥 Exportar agenda .ics {leg}",
                    data=_gerar_ics(df_exp),
                    file_name=f"agenda_servpen_{datetime.now().strftime('%Y%m%d')}.ics",
                    mime="text/calendar",
                )

        st.divider()

        # ════════════════════════════════════════════════════════════
        #  LAYOUT PRINCIPAL: visão escolhida (esq) | cadastro (dir)
        # ════════════════════════════════════════════════════════════
        col_cal, col_form = st.columns([2, 1], gap="large")

        # Paleta unificada (usada em todas as visões)
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

        # ── RAMIFICA POR VISÃO ───────────────────────────────────────
        with col_cal:
            if visao_ag == "Mensal":
                st.subheader("🗓️ Calendário do Mês")

                # Controle de mês/ano via session_state
                if 'agenda_ano'  not in st.session_state: st.session_state.agenda_ano  = datetime.now().year
                if 'agenda_mes'  not in st.session_state: st.session_state.agenda_mes  = datetime.now().month

                nav1, nav2, nav3 = st.columns([1, 2, 1])
                if nav1.button("◀ Anterior", use_container_width=True, key="cal_prev"):
                    if st.session_state.agenda_mes == 1:
                        st.session_state.agenda_mes = 12; st.session_state.agenda_ano -= 1
                    else:
                        st.session_state.agenda_mes -= 1
                if nav3.button("Próximo ▶", use_container_width=True, key="cal_next"):
                    if st.session_state.agenda_mes == 12:
                        st.session_state.agenda_mes = 1; st.session_state.agenda_ano += 1
                    else:
                        st.session_state.agenda_mes += 1

                import calendar as _cal
                ano_atual = st.session_state.agenda_ano
                mes_atual = st.session_state.agenda_mes
                MESES_PT = ['', 'Janeiro','Fevereiro','Março','Abril','Maio','Junho',
                            'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']
                nav2.markdown(
                    f"<h3 style='text-align:center;margin:0;padding:6px 0;'>"
                    f"{MESES_PT[mes_atual]} {ano_atual}</h3>",
                    unsafe_allow_html=True,
                )

                # Monta mapa: dia → lista de eventos
                eventos_mes: dict = {}
                if not df_agenda.empty:
                    df_tmp = df_agenda.copy()
                    df_tmp['di'] = pd.to_datetime(df_tmp['data_inicio'], errors='coerce')
                    df_tmp['df'] = pd.to_datetime(df_tmp['data_fim'],    errors='coerce')
                    # filtro por visibilidade
                    if perfil_atual != "Gestor":
                        df_tmp = df_tmp[df_tmp['responsaveis'].str.contains(usuario_atual, na=False)]
                    for _, ev in df_tmp.iterrows():
                        if pd.isna(ev['di']): continue
                        d = ev['di'].date()
                        fim = ev['df'].date() if not pd.isna(ev['df']) else d
                        cur = d
                        while cur <= fim:
                            if cur.year == ano_atual and cur.month == mes_atual:
                                eventos_mes.setdefault(cur.day, []).append(ev)
                            cur += pd.Timedelta(days=1)

                # Paleta por tipo
                TIPO_COR = {
                    "Visita Técnica": "#2563eb",
                    "Reunião":        "#7c3aed",
                    "Férias":         "#059669",
                    "Licença":        "#d97706",
                    "Folga":          "#6b7280",
                }

                # Gera HTML do calendário
                primeiro_dia, total_dias = _cal.monthrange(ano_atual, mes_atual)
                hoje = datetime.now().date()

                html_cal = """
                <style>
                .srv-cal { width:100%; border-collapse:separate; border-spacing:3px; font-family:'Segoe UI',sans-serif; }
                .srv-cal th { background:#1e3a5f; color:#93c5fd; font-size:.75rem; font-weight:600;
                            letter-spacing:1px; padding:8px 4px; border-radius:4px; text-align:center; }
                .srv-cal td { vertical-align:top; background:rgba(255,255,255,0.03);
                            border:1px solid rgba(255,255,255,0.06); border-radius:6px;
                            padding:4px; min-height:72px; width:14.28%; }
                .srv-cal td.hoje { border:2px solid #3b82f6 !important; background:rgba(59,130,246,0.08); }
                .srv-cal td.vazio { background:transparent; border:none; }
                .dia-num { font-size:.8rem; font-weight:700; color:#94a3b8; margin-bottom:3px; }
                .dia-num.hoje-num { color:#60a5fa; font-size:.9rem; }
                .ev-pill { font-size:.65rem; font-weight:600; color:#fff; padding:1px 5px;
                        border-radius:10px; margin-bottom:2px; white-space:nowrap;
                        overflow:hidden; text-overflow:ellipsis; display:block; }
                </style>
                <table class="srv-cal"><thead><tr>
                <th>DOM</th><th>SEG</th><th>TER</th><th>QUA</th><th>QUI</th><th>SEX</th><th>SÁB</th>
                </tr></thead><tbody><tr>
                """
                # dias em branco antes do dia 1  (semana começa domingo: offset+1)
                offset = (primeiro_dia + 1) % 7
                for _ in range(offset):
                    html_cal += "<td class='vazio'></td>"

                dia_semana = offset
                for dia in range(1, total_dias + 1):
                    data_dia = datetime(ano_atual, mes_atual, dia).date()
                    is_hoje  = (data_dia == hoje)
                    cls_td   = "hoje" if is_hoje else ""
                    html_cal += f"<td class='{cls_td}'>"
                    html_cal += f"<div class='dia-num {'hoje-num' if is_hoje else ''}'>{dia}</div>"

                    for ev in eventos_mes.get(dia, []):
                        cor = TIPO_COR.get(str(ev.get('tipo','')), '#475569')
                        titulo_curto = str(ev.get('titulo',''))[:18]
                        html_cal += (f"<span class='ev-pill' style='background:{cor}' "
                                    f"title=\"{ev.get('tipo','')} — {ev.get('titulo','')}"
                                    f" | {ev.get('responsaveis','')}\">⬤ {titulo_curto}</span>")

                    html_cal += "</td>"
                    dia_semana += 1
                    if dia_semana % 7 == 0 and dia < total_dias:
                        html_cal += "</tr><tr>"

                # preenche final da semana
                restante = 6 - ((dia_semana - 1) % 7)
                if restante < 6:
                    for _ in range(restante):
                        html_cal += "<td class='vazio'></td>"

                html_cal += "</tr></tbody></table>"
                st.markdown(html_cal, unsafe_allow_html=True)

                # Legenda de cores
                st.markdown(
                    "<div style='display:flex;gap:12px;flex-wrap:wrap;margin-top:8px;font-size:.75rem;'>" +
                    "".join([f"<span style='display:flex;align-items:center;gap:4px;'>"
                            f"<span style='width:10px;height:10px;background:{c};border-radius:50%;display:inline-block'></span>"
                            f"<span style='color:#94a3b8'>{t}</span></span>"
                            for t, c in TIPO_COR.items()]) +
                    "</div>",
                    unsafe_allow_html=True,
                )

            # ─────────── VISÃO SEMANAL ───────────────────────────────
            elif visao_ag == "Semanal":
                st.subheader("📆 Semana")
                if 'agenda_semana_offset' not in st.session_state:
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
                _ini_sem = _hoje_sem - pd.Timedelta(days=_dia_sem_hoje) \
                           + pd.Timedelta(weeks=st.session_state.agenda_semana_offset)
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
                            lambda r: _toca_janela(r, _ini_sem.date()
                                                   if hasattr(_ini_sem, 'date')
                                                   else _ini_sem,
                                                   _fim_sem.date()
                                                   if hasattr(_fim_sem, 'date')
                                                   else _fim_sem),
                            axis=1,
                        )
                    ].copy()
                else:
                    _df_sem = pd.DataFrame()

                # Render dos 7 dias como HTML único — Streamlit não envelopa
                # st.button dentro de markdown custom, então construímos a
                # grade inteira em HTML estático (cards + chips) sem botões
                # individuais. A edição vai pelo selectbox embaixo da grade.
                NOMES_DIA = ["DOM","SEG","TER","QUA","QUI","SEX","SÁB"]
                _MAX_CHIPS_DIA = 3   # acima disso vira "+N"

                # Mapa dia → eventos
                _ev_por_dia: dict = {}
                if not _df_sem.empty:
                    for _i_d in range(7):
                        _data_d = (_ini_sem + pd.Timedelta(days=_i_d)).date() \
                                  if hasattr(_ini_sem, 'date') \
                                  else _ini_sem + pd.Timedelta(days=_i_d)
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
                    _data_dia_s = (_ini_sem + pd.Timedelta(days=idx)).date() \
                                  if hasattr(_ini_sem, 'date') \
                                  else _ini_sem + pd.Timedelta(days=idx)
                    _eh_hoje_s = (_data_dia_s == _hoje_sem)
                    _cls_dia = "dia hoje" if _eh_hoje_s else "dia"
                    _cls_num = "num hoje" if _eh_hoje_s else "num"

                    html_sem += f"<div class='{_cls_dia}'>"
                    html_sem += f"<div class='lbl'>{NOMES_DIA[idx]}</div>"
                    html_sem += f"<div class='{_cls_num}'>{_data_dia_s.day}</div>"

                    _eventos_dia_d = _ev_por_dia.get(idx, [])
                    for _ev in _eventos_dia_d[:_MAX_CHIPS_DIA]:
                        _cor = TIPO_COR.get(str(_ev.get('tipo','')), '#475569')
                        _ico = TIPO_ICONE.get(str(_ev.get('tipo','')), '📅')
                        _titulo_curto = str(_ev['titulo'])[:18]
                        html_sem += (f"<div class='chip' style='background:{_cor}' "
                                     f"title=\"{_ev['titulo']} ({_ev.get('responsaveis','')})\""
                                     f">{_ico} {_titulo_curto}</div>")
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
                    _eid = int(_e['id'])
                    if _eid not in _vistos_sem:
                        _vistos_sem.add(_eid)
                        _ev_unicos_sem.append(_e)

                if _ev_unicos_sem:
                    st.markdown("---")
                    _ed_c1, _ed_c2 = st.columns([4, 1])
                    _opcoes_sem = {
                        f"{TIPO_ICONE.get(str(e.get('tipo','')), '📅')} "
                        f"{e['titulo']} "
                        f"({e['_di'].strftime('%d/%m') if e['_di'] else '?'})":
                        int(e['id'])
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
                            st.session_state['agenda_edit_id'] = _opcoes_sem[_esc_sem]
                            st.rerun()

            # ─────────── VISÃO LISTA ─────────────────────────────────
            elif visao_ag == "Lista":
                st.subheader("📋 Lista completa")
                st.caption(
                    "Use os filtros e a tabela detalhada abaixo (no rodapé desta "
                    "aba) pra navegar, editar ou excluir cada compromisso."
                )
                # A tabela com filtros já existe mais embaixo na aba; só
                # damos um atalho visual aqui em cima.
                if _df_ag_visivel.empty:
                    _empty_state(
                        "📅",
                        "Nenhum compromisso cadastrado ainda",
                        "Use o formulário ao lado pra agendar a primeira "
                        "visita técnica, reunião ou ausência da equipe.",
                        cor_borda="#7c3aed",
                    )
                else:
                    _qtd_futuros = int(_df_ag_visivel.apply(
                        lambda r: r.get('_df', r.get('_di')) >= _hoje_ag
                        if r.get('_di') is not None else False,
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
                # Próximos 5 eventos do usuário (inclui em-curso, exclui passados)
                st.markdown(
                    "**📌 Próximos compromissos "
                    + ("(equipe)" if perfil_atual == "Gestor" else "(seus)") + "**"
                )
                if _df_ag_visivel.empty:
                    st.info("Sem compromissos.")
                else:
                    _df_prox = _df_ag_visivel[
                        _df_ag_visivel.apply(
                            lambda r: (r.get('_df') or r.get('_di')) >= _hoje_ag,
                            axis=1,
                        )
                    ].sort_values('_di').head(5)
                    if _df_prox.empty:
                        st.info("Sem compromissos futuros.")
                    else:
                        for _, _ev in _df_prox.iterrows():
                            _di = _ev['_di']
                            _df_ = _ev['_df'] or _di
                            _dias_ate = (_di - _hoje_ag).days
                            # Status temporal contextual (sem "em -N dias" estranho)
                            if _dias_ate < 0 and _df_ >= _hoje_ag:
                                _quando = f"<span style='color:#16a34a;font-weight:600;'>" \
                                          f"Em curso até {_df_.strftime('%d/%m')}</span>"
                            elif _dias_ate == 0:
                                _quando = "<span style='color:#3b82f6;font-weight:600;'>Hoje</span>"
                            elif _dias_ate == 1:
                                _quando = "<span style='color:#0891b2;'>Amanhã</span>"
                            else:
                                _quando = f"em {_dias_ate} dias"

                            _cor = TIPO_COR.get(str(_ev.get('tipo','')), '#475569')
                            _ico = TIPO_ICONE.get(str(_ev.get('tipo','')), '📅')
                            _periodo = (
                                _di.strftime('%d/%m')
                                if _di == _df_
                                else f"{_di.strftime('%d/%m')}–{_df_.strftime('%d/%m')}"
                            )
                            # Layout compacto: largura maior pro botão (~25%)
                            # pra "Abrir" não quebrar em coluna estreita.
                            c_ev1, c_ev2 = st.columns([5, 1], gap="small")
                            c_ev1.markdown(
                                f"<div style='border-left:3px solid {_cor};"
                                f"padding:2px 0 2px 8px;margin:0;line-height:1.35;'>"
                                f"<b>{_ico} {_ev['titulo']}</b> "
                                f"<span style='color:#94a3b8;font-size:.78rem;'>"
                                f"· {_quando} <span style='opacity:.7;'>({_periodo})</span>"
                                f"</span></div>",
                                unsafe_allow_html=True,
                            )
                            if c_ev2.button("🔍", key=f"res_ab_{_ev['id']}",
                                            help="Abrir no formulário",
                                            use_container_width=True):
                                st.session_state['agenda_edit_id'] = int(_ev['id'])
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
                    _por_tipo = _df_mes_r.groupby('tipo').size() \
                                .sort_values(ascending=False)
                    if _por_tipo.empty:
                        st.caption("Sem dados no mês atual.")
                    else:
                        for _t, _q in _por_tipo.items():
                            _cor = TIPO_COR.get(str(_t), '#475569')
                            _ico = TIPO_ICONE.get(str(_t), '📅')
                            st.markdown(
                                f"- <span style='background:{_cor};color:#fff;"
                                f"padding:1px 8px;border-radius:8px;font-size:.78rem;'>"
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
                        for _nome in str(_r.get('responsaveis','')).split(','):
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
            # Verifica se está em modo edição
            _ed_id  = st.session_state.get('agenda_edit_id')
            _ed_row = None
            if _ed_id and not df_agenda.empty:
                _rows = df_agenda[df_agenda['id'] == _ed_id]
                if not _rows.empty:
                    _ed_row = _rows.iloc[0]

            _titulo_form = "✏️ Editar Compromisso" if _ed_row is not None else "➕ Novo Compromisso"
            st.subheader(_titulo_form)

            equipe_lista = df_u['nome'].tolist() if not df_u.empty else [usuario_atual]

            with st.form("form_agenda_nova", clear_on_submit=True):
                titulo_ev = st.text_input(
                    "Título / Motivo",
                    value=str(_ed_row['titulo']) if _ed_row is not None else "",
                )
                tipo_ev = st.selectbox(
                    "Categoria",
                    ["Visita Técnica", "Reunião", "Férias", "Licença", "Folga"],
                    index=(["Visita Técnica","Reunião","Férias","Licença","Folga"]
                        .index(str(_ed_row['tipo'])) if _ed_row is not None
                        and str(_ed_row['tipo']) in ["Visita Técnica","Reunião","Férias","Licença","Folga"]
                        else 0),
                )
                local_ev = st.text_input(
                    "Local (opcional)",
                    value=str(_ed_row.get('local','')) if _ed_row is not None else "",
                )

                try:
                    _d_ini_def = pd.to_datetime(_ed_row['data_inicio']).date() if _ed_row is not None else datetime.now().date()
                    _d_fim_def = pd.to_datetime(_ed_row['data_fim']).date()    if _ed_row is not None else datetime.now().date()
                except Exception:
                    _d_ini_def = _d_fim_def = datetime.now().date()

                c_d1, c_d2 = st.columns(2)
                d_ini = c_d1.date_input("Início",   value=_d_ini_def)
                d_fim = c_d2.date_input("Término",  value=_d_fim_def)

                _def_resp = [r.strip() for r in str(_ed_row['responsaveis']).split(',')
                            if r.strip() in equipe_lista] if _ed_row is not None else []
                resp_ev = st.multiselect("Envolvidos", equipe_lista, default=_def_resp)

                obs_ev = st.text_area(
                    "Observações",
                    value=str(_ed_row['descricao']) if _ed_row is not None else "",
                    height=90,
                )

                cols_btn = st.columns(2)
                submit_ok = cols_btn[0].form_submit_button(
                    "💾 Salvar" if _ed_row is not None else "📌 Agendar",
                    use_container_width=True,
                )
                submit_cancel = cols_btn[1].form_submit_button("✖ Cancelar", use_container_width=True)

            if submit_cancel and 'agenda_edit_id' in st.session_state:
                del st.session_state.agenda_edit_id
                st.rerun()

            if submit_ok:
                if titulo_ev and resp_ev:
                    if _ed_row is not None:
                        db.atualizar_evento(_ed_id, titulo_ev, tipo_ev, d_ini, d_fim,
                                            resp_ev, obs_ev, local_ev)
                        db.log_aud(st.session_state.usuario, 'editar', 'agenda', _ed_id, titulo_ev)
                        if 'agenda_edit_id' in st.session_state:
                            del st.session_state.agenda_edit_id
                        st.success("Compromisso atualizado!")
                    else:
                        db.salvar_evento(titulo_ev, tipo_ev, d_ini, d_fim, resp_ev, obs_ev, local_ev)
                        db.log_aud(st.session_state.usuario, 'criar', 'agenda', None, titulo_ev)
                        st.success("Compromisso registrado!")
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
        _tipos_disp = ["Todos"] + sorted(df_agenda['tipo'].dropna().unique().tolist()) if not df_agenda.empty else ["Todos"]
        filtro_tipo   = f1.selectbox("Filtrar por categoria", _tipos_disp, key="ag_ftipo")
        filtro_membro = f2.text_input("Filtrar por membro", placeholder="nome...", key="ag_fmembro")
        filtro_futuro = f3.checkbox("Só futuros", value=False, key="ag_ffut")

        if not df_agenda.empty:
            df_show = df_agenda.copy()
            df_show['data_inicio'] = pd.to_datetime(df_show['data_inicio'], errors='coerce')
            df_show['data_fim']    = pd.to_datetime(df_show['data_fim'],    errors='coerce')

            if perfil_atual != "Gestor":
                df_show = df_show[df_show['responsaveis'].str.contains(usuario_atual, na=False)]
            if filtro_tipo != "Todos":
                df_show = df_show[df_show['tipo'] == filtro_tipo]
            if filtro_membro.strip():
                df_show = df_show[df_show['responsaveis'].str.contains(filtro_membro.strip(), case=False, na=False)]
            if filtro_futuro:
                df_show = df_show[df_show['data_fim'] >= pd.Timestamp(datetime.now().date())]

            df_show = df_show.sort_values('data_inicio')

            if df_show.empty:
                _empty_state(
                    "🔍",
                    "Nenhum compromisso encontrado",
                    "Tente afrouxar os filtros acima — pelo menos um critério "
                    "(categoria / membro / só futuros) está muito restritivo.",
                    cor_borda="#d97706",
                )
            else:
                TIPO_ICONE = {"Visita Técnica":"🏗️","Reunião":"🤝","Férias":"🏖️",
                            "Licença":"🏥","Folga":"😴"}

                for _, row in df_show.iterrows():
                    icone   = TIPO_ICONE.get(str(row['tipo']), "📅")
                    cor_tip = TIPO_COR.get(str(row['tipo']), "#475569")
                    ini_str = row['data_inicio'].strftime('%d/%m/%Y') if not pd.isna(row['data_inicio']) else '—'
                    fim_str = row['data_fim'].strftime('%d/%m/%Y')    if not pd.isna(row['data_fim'])    else '—'

                    # Calcula duração em dias
                    try:
                        dur = (row['data_fim'].date() - row['data_inicio'].date()).days + 1
                        dur_txt = f"{dur} dia{'s' if dur > 1 else ''}"
                    except Exception:
                        dur_txt = "—"

                    # Verifica se está em andamento hoje
                    hoje_ts = pd.Timestamp(datetime.now().date())
                    em_curso = (not pd.isna(row['data_inicio']) and
                                not pd.isna(row['data_fim'])    and
                                row['data_inicio'] <= hoje_ts <= row['data_fim'])
                    badge_curso = ("<span style='background:#16a34a;color:#fff;font-size:.65rem;"
                                "font-weight:700;padding:2px 8px;border-radius:10px;"
                                "margin-left:8px;'>EM ANDAMENTO</span>") if em_curso else ""

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
                    _pode_mexer = (perfil_atual == "Gestor" or
                                usuario_atual in str(row.get('responsaveis','')))
                    if _pode_mexer:
                        b1, b2, _bspc = st.columns([1, 1, 5])
                        if b1.button("✏️ Editar", key=f"ag_ed_{row['id']}", use_container_width=True):
                            st.session_state.agenda_edit_id = int(row['id'])
                            st.rerun()
                        with b2.popover("🗑️ Excluir", use_container_width=True):
                            st.markdown(f"**Excluir '{row['titulo']}'?**")
                            st.caption("Esta ação não pode ser desfeita.")
                            if st.button("✅ Sim, excluir", key=f"ag_del_conf_{row['id']}",
                                        type="primary", use_container_width=True):
                                db.excluir_evento(int(row['id']))
                                db.log_aud(st.session_state.usuario, 'excluir', 'agenda',
                                        int(row['id']), str(row['titulo']))
                                st.toast(f"'{row['titulo']}' removido.")
                                st.rerun()
        else:
            st.info("📭 Agenda vazia — adicione o primeiro compromisso ao lado.")

    # --- ABA 9: AUDITORIA (somente Gestor) ---
    if t_auditoria is not None:
        with t_auditoria:
            st.header("🛡️ Trilha de Auditoria")
            st.caption("Registro cronológico de quem fez o quê — login/logout, criação, edição e exclusão de projetos, usuários e arquivos.")

            col_af1, col_af2, col_af3 = st.columns([2, 2, 1])
            usuarios_filtro = ["(todos)"] + (df_u['nome'].tolist() if not df_u.empty else [])
            filtro_aud_user = col_af1.selectbox("Usuário", usuarios_filtro, key="aud_user")
            filtro_aud_acao = col_af2.text_input("Ação contém", placeholder="ex.: excluir, login, upload", key="aud_acao")
            filtro_aud_limit = col_af3.number_input("Linhas", min_value=20, max_value=2000, value=200, step=20, key="aud_limit")

            linhas = db.listar_auditoria(
                limit=int(filtro_aud_limit),
                filtro_usuario=None if filtro_aud_user == "(todos)" else filtro_aud_user,
                filtro_acao=filtro_aud_acao or None,
            )

            col_m1, col_m2 = st.columns([3, 1])
            col_m1.metric("Eventos exibidos", len(linhas))
            if linhas:
                # Export CSV (gera no Python sem pandas/pyarrow)
                import csv as _csv
                import io as _io
                _buf = _io.StringIO()
                _w = _csv.writer(_buf)
                _w.writerow(['ID', 'Quando', 'Usuário', 'Ação', 'Entidade', 'ID Entidade', 'Detalhes'])
                _w.writerows(linhas)
                col_m2.download_button(
                    "📥 Exportar CSV", _buf.getvalue().encode('utf-8'),
                    file_name=f"auditoria_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv", use_container_width=True,
                )
                st.divider()

                # Cores por tipo de acao
                def _cor_acao(a):
                    a = (a or '').lower()
                    if 'excluir' in a or 'falha' in a: return '#ef4444'
                    if 'login' in a or 'logout' in a: return '#6366f1'
                    if 'editar' in a:                  return '#f59e0b'
                    if 'upload' in a:                  return '#10b981'
                    return '#6b7280'

                # Tabela HTML manual (st.dataframe exige pyarrow, e pyarrow nao roda nessa CPU)
                import html as _html
                linhas_html = []
                for id_l, data_l, usuario_l, acao_l, ent_l, eid_l, det_l in linhas:
                    cor = _cor_acao(acao_l)
                    linhas_html.append(
                        f"<tr>"
                        f"<td style='white-space:nowrap;opacity:0.7;font-size:0.85em'>{_tempo_relativo(data_l)}</td>"
                        f"<td><b>{_html.escape(str(usuario_l or '—'))}</b></td>"
                        f"<td><span style='background:{cor};color:#fff;padding:2px 8px;border-radius:8px;font-size:0.78em;font-weight:600'>{_html.escape(str(acao_l))}</span></td>"
                        f"<td>{_html.escape(str(ent_l or ''))}</td>"
                        f"<td style='opacity:0.7'>{eid_l if eid_l is not None else ''}</td>"
                        f"<td style='font-size:0.85em;opacity:0.85'>{_html.escape(str(det_l or ''))}</td>"
                        f"</tr>"
                    )
                tabela = (
                    "<div style='max-height:560px;overflow-y:auto;border:1px solid rgba(128,128,128,0.2);border-radius:8px'>"
                    "<table style='width:100%;border-collapse:collapse;font-size:0.9rem'>"
                    "<thead style='position:sticky;top:0;background:rgba(0,86,179,0.12);backdrop-filter:blur(4px)'>"
                    "<tr>"
                    "<th style='padding:8px 10px;text-align:left'>Quando</th>"
                    "<th style='padding:8px 10px;text-align:left'>Usuário</th>"
                    "<th style='padding:8px 10px;text-align:left'>Ação</th>"
                    "<th style='padding:8px 10px;text-align:left'>Entidade</th>"
                    "<th style='padding:8px 10px;text-align:left'>ID</th>"
                    "<th style='padding:8px 10px;text-align:left'>Detalhes</th>"
                    "</tr></thead><tbody>"
                    + "".join(linhas_html) +
                    "</tbody></table></div>"
                )
                st.markdown(tabela, unsafe_allow_html=True)
            else:
                st.info("🔍 Nenhum evento encontrado para os filtros atuais.")

    # --- ABA: ACESSOS (somente Gestor) - revoga concessões por menção ---
    if t_acessos is not None:
        with t_acessos:
            st.header("🔑 Acessos por Menção")
            st.caption(
                "Lista de usuários que ganharam acesso a projetos porque foram "
                "mencionados (`@\"Nome\"`) no Diário. Por decisão de produto, "
                "a concessão é permanente — só você (Gestor) pode revogar aqui."
            )

            _todas_mn = db.listar_todas_mencoes_acesso()
            st.metric("Total de acessos por menção", len(_todas_mn))

            if not _todas_mn:
                st.info("Ninguém foi mencionado ainda. Quando alguém escrever "
                        "`@\"Nome\"` no Diário, a concessão aparece aqui.")
            else:
                # Filtros opcionais
                col_fa, col_fb = st.columns(2)
                _filtro_user = col_fa.text_input(
                    "Filtrar por usuário mencionado", key="acessos_filtro_user",
                    placeholder="ex.: maria",
                )
                _filtro_proj = col_fb.text_input(
                    "Filtrar por nome do projeto", key="acessos_filtro_proj",
                    placeholder="ex.: hupe",
                )
                st.divider()

                for (mn_id, usuario, proj_id, proj_nome, por, em) in _todas_mn:
                    if _filtro_user and _filtro_user.lower() not in str(usuario).lower():
                        continue
                    if _filtro_proj and _filtro_proj.lower() not in str(proj_nome or '').lower():
                        continue

                    with st.container(border=True):
                        col_a, col_b, col_c = st.columns([0.5, 0.35, 0.15])
                        col_a.markdown(
                            f"**👤 {usuario}** &nbsp;→&nbsp; "
                            f"**📂 {proj_nome or f'(projeto #{proj_id} apagado)'}**"
                        )
                        col_b.caption(f"Concedido por **{por}** em {_tempo_relativo(em)}")
                        with col_c.popover("🗑️ Revogar", use_container_width=True):
                            st.warning(
                                f"Revogar acesso de **{usuario}** ao projeto "
                                f"**{proj_nome or proj_id}**?"
                            )
                            st.caption(
                                "O usuário perde acesso na próxima render dele. "
                                "As notificações já entregues continuam visíveis."
                            )
                            if st.button(
                                "✅ Sim, revogar", key=f"rev_mn_{mn_id}",
                                type="primary", use_container_width=True,
                            ):
                                db.revogar_mencao(mn_id)
                                db.log_aud(
                                    st.session_state.usuario, 'mencao_revogada',
                                    'projeto', proj_id,
                                    f"revogou acesso de '{usuario}' (concedido por '{por}')",
                                )
                                st.toast(f"Acesso de '{usuario}' ao projeto revogado.")
                                st.rerun()

# ─────────────────────────────────────────────────────────────────
# RODAPÉ DA APLICAÇÃO (Colocar no final do arquivo, fora de abas/forms)
# ─────────────────────────────────────────────────────────────────
st.divider()

st.markdown(
    """
    <div style='text-align: center; color: #808495; font-size: 0.85em; line-height: 1.6; padding-top: 10px; padding-bottom: 20px;'>
        <b>Engenheira Sara Nolasco</b><br>
        Software Gestão de Projetos NB | Versão 1.0<br>
        © 2026 - Todos os direitos reservados
    </div>
    """, 
    unsafe_allow_html=True
)
