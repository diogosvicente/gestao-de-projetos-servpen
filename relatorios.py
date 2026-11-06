"""
relatorios.py  —  SERVPEN Engenharia
Gera Excel e PDF profissionais usando reportlab + xlsxwriter.
Versão: 1.1 (Correções de renderização de tabelas e quebras de página)
"""

import io
import numbers
import os
from datetime import datetime, date, timedelta
import unicodedata
from xml.sax.saxutils import escape as _xml_escape

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether,
)
from reportlab.graphics.shapes import Drawing, Rect, String, Line


# ── Paleta SERVPEN ────────────────────────────────────────────
AZUL_ESCURO  = colors.HexColor('#003366')
AZUL_MEDIO   = colors.HexColor('#0056b3')
AZUL_CLARO   = colors.HexColor('#00a8cc')
CINZA_TITULO = colors.HexColor('#1f2937')
CINZA_LINHA  = colors.HexColor('#f3f4f6')
CINZA_BORDA  = colors.HexColor('#d1d5db')
VERDE        = colors.HexColor('#10b981')
LARANJA      = colors.HexColor('#f59e0b')
VERMELHO     = colors.HexColor('#ef4444')
ROXO         = colors.HexColor('#7c3aed')
BRANCO       = colors.white

COR_STATUS = {
    'Ativo':       colors.HexColor('#0056b3'),
    'Em Execução': colors.HexColor('#0056b3'),
    'Em Espera':   ROXO,
    '🛑 Parado':  colors.HexColor('#d35400'),
    'Parado':      colors.HexColor('#d35400'),
    'Cancelado':   colors.HexColor('#801a1a'),
    'Concluído':   colors.HexColor('#1a661a'),
    'Concluido':   colors.HexColor('#1a661a'),
}

COR_PRIORIDADE = {
    'Máxima': VERMELHO,
    'Média':  LARANJA,
    'Mínima': VERDE,
}


def _txt(val, fallback='—'):
    v = str(val or '').strip()
    return v if v and v not in ('None', 'nan', 'NaT') else fallback


def _pct(val):
    try:
        return f"{float(val):.0f}%"
    except Exception:
        return '—'


def _data_fmt(val):
    if not val or str(val).strip() in ('', 'None', 'nan', 'NaT'):
        return '—'
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%Y-%m-%d %H:%M:%S', '%d/%m/%Y %H:%M'):
        try:
            return datetime.strptime(str(val).strip(), fmt).strftime('%d/%m/%Y')
        except Exception:
            pass
    return str(val)[:10]


def _strip(txt):
    """Remove acentos e caracteres não-ASCII para compatibilidade."""
    t = unicodedata.normalize('NFKD', str(txt or ''))
    t = ''.join(c for c in t if not unicodedata.combining(c))
    return t.encode('ascii', 'ignore').decode('ascii')


# ═════════════════════════════════════════════════════════════
#  ESTILOS REPORTLAB (CORRIGIDOS)
# ═════════════════════════════════════════════════════════════
def _estilos():
    ss = getSampleStyleSheet()
    
    titulo = ParagraphStyle('Titulo', 
        fontName='Helvetica-Bold', fontSize=20, leading=24,
        textColor=BRANCO, alignment=TA_CENTER, spaceAfter=2)

    subtitulo = ParagraphStyle('Sub', 
        fontName='Helvetica', fontSize=11, leading=14,
        textColor=BRANCO, alignment=TA_CENTER, spaceAfter=0)

    secao = ParagraphStyle('Secao', 
        fontName='Helvetica-Bold', fontSize=12, leading=15,
        textColor=AZUL_ESCURO, spaceBefore=14, spaceAfter=4,
        borderPad=4, borderColor=AZUL_CLARO, borderWidth=0)

    campo_label = ParagraphStyle('CLabel', 
        fontName='Helvetica-Bold', fontSize=8, leading=11,
        textColor=colors.HexColor('#6b7280'), spaceAfter=1)

    campo_valor = ParagraphStyle('CValor', 
        fontName='Helvetica', fontSize=10, leading=13,
        textColor=CINZA_TITULO, spaceAfter=6)

    corpo = ParagraphStyle('Corpo', 
        fontName='Helvetica', fontSize=9, leading=13,
        textColor=CINZA_TITULO, spaceAfter=4)

    cabecalho_tab = ParagraphStyle('CabTab', 
        fontName='Helvetica-Bold', fontSize=8, leading=11,
        textColor=BRANCO, alignment=TA_CENTER)

    celula = ParagraphStyle('Cel', 
        fontName='Helvetica', fontSize=8, leading=11,
        textColor=CINZA_TITULO)

    rodape = ParagraphStyle('Rodape', 
        fontName='Helvetica', fontSize=7, leading=10,
        textColor=colors.HexColor('#9ca3af'), alignment=TA_CENTER)

    return dict(titulo=titulo, subtitulo=subtitulo, secao=secao,
                campo_label=campo_label, campo_valor=campo_valor,
                corpo=corpo, cabecalho_tab=cabecalho_tab,
                celula=celula, rodape=rodape)


# ── Cabeçalho e rodapé de página ─────────────────────────────
def _cabecalho_pagina(canvas, doc):
    canvas.saveState()
    w, h = A4
    canvas.setFillColor(AZUL_ESCURO)
    canvas.rect(0, h - 2.8*cm, w, 2.8*cm, fill=1, stroke=0)
    canvas.setFillColor(AZUL_CLARO)
    canvas.rect(0, h - 2.8*cm, w, 3, fill=1, stroke=0)
    canvas.setFillColor(BRANCO)
    canvas.setFont('Helvetica-Bold', 14)
    canvas.drawString(1.5*cm, h - 1.6*cm, 'SERVPEN ENGENHARIA')
    canvas.setFont('Helvetica', 9)
    canvas.drawString(1.5*cm, h - 2.2*cm, 'Gestão de Projetos de Engenharia — UERJ')
    canvas.setFont('Helvetica', 8)
    canvas.drawRightString(w - 1.5*cm, h - 1.6*cm,
                           datetime.now().strftime('%d/%m/%Y %H:%M'))
    canvas.drawRightString(w - 1.5*cm, h - 2.2*cm,
                           f'Pág. {doc.page}')
    canvas.setFillColor(colors.HexColor('#6b7280'))
    canvas.setFont('Helvetica', 7)
    canvas.drawCentredString(w / 2, 0.8*cm,
        'SERVPEN Engenharia  ·  UERJ  ·  Documento gerado automaticamente')
    canvas.setStrokeColor(CINZA_BORDA)
    canvas.line(1.5*cm, 1.2*cm, w - 1.5*cm, 1.2*cm)
    canvas.restoreState()


def _cabecalho_paisagem(canvas, doc):
    canvas.saveState()
    w, h = landscape(A4)
    canvas.setFillColor(AZUL_ESCURO)
    canvas.rect(0, h - 2.4*cm, w, 2.4*cm, fill=1, stroke=0)
    canvas.setFillColor(AZUL_CLARO)
    canvas.rect(0, h - 2.4*cm, w, 3, fill=1, stroke=0)
    canvas.setFillColor(BRANCO)
    canvas.setFont('Helvetica-Bold', 13)
    canvas.drawString(1.5*cm, h - 1.5*cm, 'SERVPEN — Cronograma de Etapas (Gantt)')
    canvas.setFont('Helvetica', 8)
    canvas.drawRightString(w - 1.5*cm, h - 1.5*cm,
                           datetime.now().strftime('%d/%m/%Y'))
    canvas.drawRightString(w - 1.5*cm, h - 2.0*cm, f'Pág. {doc.page}')
    canvas.setFillColor(colors.HexColor('#6b7280'))
    canvas.setFont('Helvetica', 7)
    canvas.drawCentredString(w / 2, 0.7*cm, 'SERVPEN Engenharia · UERJ')
    canvas.restoreState()


def _tabela_estilo(n_colunas, cor_cab=AZUL_MEDIO):
    return TableStyle([
        ('BACKGROUND',   (0, 0), (-1, 0),  cor_cab),
        ('TEXTCOLOR',    (0, 0), (-1, 0),  BRANCO),
        ('FONTNAME',     (0, 0), (-1, 0),  'Helvetica-Bold'),
        ('FONTSIZE',     (0, 0), (-1, 0),  8),
        ('ALIGN',        (0, 0), (-1, 0),  'CENTER'),
        ('VALIGN',       (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME',     (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE',     (0, 1), (-1, -1), 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [CINZA_LINHA, BRANCO]),
        ('GRID',         (0, 0), (-1, -1), 0.5, CINZA_BORDA),
        ('TOPPADDING',   (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 5),
        ('LEFTPADDING',  (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ])


# ═════════════════════════════════════════════════════════════
#  EMISSÕES E REVISÕES NOS RELATÓRIOS GERAIS
# ═════════════════════════════════════════════════════════════
# Pedido de 05/11/2026: no Excel e no PDF completos, o que é da emissão
# inicial, da R01, da R02… aparece separado. Os campos comuns do projeto se
# mantêm; o que cada revisão gerou (pedido, prazos, responsável,
# documentações, etapas e evolução técnica) fica na linha ou no bloco dela.
def _vazio(val):
    """True pra None, NaN, NaT e texto vazio (o que o pandas traz do banco)."""
    if val is None:
        return True
    try:
        if pd.isna(val):
            return True
    except (TypeError, ValueError):
        pass
    return str(val).strip() in ('', 'None', 'nan', 'NaT')


def _inteiro(val, padrao=None):
    """int de um valor do pandas — id e número podem chegar float ou NaN."""
    if _vazio(val):
        return padrao
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return padrao


def _rotulo_rev(numero):
    """0 → 'Emissão inicial'; 1 → 'R01'… (o mesmo de database.rotulo_revisao)."""
    n = _inteiro(numero, 0)
    return 'Emissão inicial' if n <= 0 else f'R{n:02d}'


def _como_data(val):
    """date (ou None) a partir de date, datetime, Timestamp ou texto."""
    if _vazio(val):
        return None
    if isinstance(val, datetime):          # inclui pd.Timestamp
        return val.date()
    if isinstance(val, date):
        return val
    txt = str(val).strip()[:19]
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%Y-%m-%d %H:%M:%S',
                '%Y-%m-%dT%H:%M:%S'):
        try:
            return datetime.strptime(txt, fmt).date()
        except ValueError:
            pass
    return None


def _data_br(val):
    """'dd/mm/aaaa', ou '' quando não há data."""
    d = _como_data(val)
    return d.strftime('%d/%m/%Y') if d else ''


def _esc(val, fallback='—'):
    """Texto do usuário pronto pro Paragraph do reportlab: escapa & < > (um
    '&' solto derrubava o PDF inteiro) e mantém as quebras de linha."""
    t = _txt(val, fallback).replace('\r\n', '\n').replace('\r', '\n')
    return _xml_escape(t).replace('\n', '<br/>')


def _registros(df_x, ids):
    """Linhas de df_x dos projetos `ids`, como dicts, com projeto_id e
    revisao_id já normalizados pra int/None."""
    if (df_x is None or getattr(df_x, 'empty', True)
            or 'projeto_id' not in df_x.columns):
        return []
    df_x = df_x.loc[:, ~df_x.columns.duplicated()]
    saida = []
    for r in df_x.to_dict('records'):
        pid = _inteiro(r.get('projeto_id'))
        if pid in ids:
            r['projeto_id'] = pid
            r['revisao_id'] = _inteiro(r.get('revisao_id'))
            saida.append(r)
    return saida


def _revisoes_por_projeto(df, df_revisoes=None, df_etapas=None,
                          df_progresso=None, df_documentos=None):
    """{projeto_id: [revisão, …]}, da emissão inicial pra mais nova.

    Cada revisão é um dict com os dados dela (numero, rotulo, atual,
    descricao, disciplinas, projetista, solicitado_em, previsao,
    entregue_em, do_zero) e o que ela gerou — `documentos`, `etapas` e
    `evolucao`, separados pelo revisao_id, do mesmo jeito que o seletor de
    revisão do Kanban mostra. Projeto ainda sem revisão (dado antigo) ganha
    uma "Emissão inicial" sem id, com as datas do próprio projeto (as mesmas
    que database.criar_revisao_inicial usaria), que junta as linhas sem
    revisão."""
    if df is None or df.empty or 'id' not in df.columns:
        return {}
    projetos = {}
    for p in df.loc[:, ~df.columns.duplicated()].to_dict('records'):
        pid = _inteiro(p.get('id'))
        if pid is not None:
            projetos[pid] = p
    ids = set(projetos)

    def _agrupar(registros):
        grupos = {}
        for r in registros:
            grupos.setdefault((r['projeto_id'], r['revisao_id']), []).append(r)
        return grupos

    revs_proj = {}
    for r in _registros(df_revisoes, ids):
        revs_proj.setdefault(r['projeto_id'], []).append(r)
    etapas = _agrupar(_registros(df_etapas, ids))
    evolucao = _agrupar(_registros(df_progresso, ids))
    documentos = _agrupar(_registros(df_documentos, ids))

    saida = {}
    for pid, p in projetos.items():
        lista = sorted(revs_proj.get(pid, []),
                       key=lambda r: (_inteiro(r.get('numero'), 0),
                                      _inteiro(r.get('id'), 0)))
        if not lista:
            _fim = (p.get('data_fim') if _vazio(p.get('data_termino'))
                    else p.get('data_termino'))
            _prev = p.get('previsao_execucao')
            lista = [{
                'id': None, 'numero': 0,
                'projetista': p.get('projetista'),
                'solicitado_em': p.get('data_recebimento'),
                'previsao': _fim if _vazio(_prev) else _prev,
                'entregue_em': (_fim if str(p.get('status') or '').strip()
                                == 'Concluído' else None),
            }]
        blocos = []
        for i, r in enumerate(lista):
            rid = _inteiro(r.get('id'))
            numero = _inteiro(r.get('numero'), 0)
            blocos.append({
                'id': rid,
                'numero': numero,
                'rotulo': _rotulo_rev(numero),
                'atual': i == len(lista) - 1,
                'descricao': _txt(r.get('descricao'), ''),
                'disciplinas': _txt(r.get('disciplinas'), ''),
                'projetista': _txt(r.get('projetista'), ''),
                'solicitado_em': _como_data(r.get('solicitado_em')),
                'previsao': _como_data(r.get('previsao')),
                'entregue_em': _como_data(r.get('entregue_em')),
                'do_zero': bool(_inteiro(r.get('do_zero'), 0)),
                'documentos': documentos.get((pid, rid), []),
                'etapas': sorted(etapas.get((pid, rid), []),
                                 key=lambda e: (_inteiro(e.get('ordem'), 0),
                                                _inteiro(e.get('id'), 0))),
                'evolucao': sorted(evolucao.get((pid, rid), []),
                                   key=lambda g: _inteiro(g.get('id'), 0)),
            })
        saida[pid] = blocos
    return saida


def _situacao_rev(rev):
    """'Entregue' ou 'Em execução' (como no card da revisão), com '(atual)'
    na revisão mais nova."""
    txt = 'Entregue' if rev['entregue_em'] else 'Em execução'
    return f'{txt} (atual)' if rev['atual'] else txt


def _progresso_rev(rev):
    """Média dos percentuais da evolução técnica da revisão (a mesma conta
    do Dashboard), ou None quando ela não tem evolução."""
    vals = [_inteiro(g.get('percentual'), 0) for g in rev['evolucao']]
    return round(sum(vals) / len(vals)) if vals else None


def _txt_documentos(rev):
    """Uma documentação por linha: 'Memorial.pdf (12/03/2026)'."""
    linhas = []
    for d in rev['documentos']:
        quando = _data_br(d.get('criado_em'))
        linhas.append(_txt(d.get('nome')) + (f' ({quando})' if quando else ''))
    return '\n'.join(linhas)


def _txt_etapas(rev):
    """Uma etapa por linha: '1. Levantamento — 100%'."""
    return '\n'.join(
        f"{_inteiro(e.get('ordem'), 0) + 1}. {_txt(e.get('nome'))} — "
        f"{_inteiro(e.get('percentual'), 0)}%"
        for e in rev['etapas'])


def _txt_evolucao(rev):
    """Uma disciplina por linha: 'Arquitetura: 100%'."""
    return '\n'.join(
        f"{_txt(g.get('disciplina'))}: {_inteiro(g.get('percentual'), 0)}%"
        for g in rev['evolucao'])


def _valor_projeto(p, campo, tipo='txt'):
    """Valor de um campo comum do projeto, já no tipo da coluna."""
    val = p.get(campo)
    if campo == 'data_termino' and _vazio(val):
        val = p.get('data_fim')
    if tipo == 'data':
        return _como_data(val)
    if tipo == 'int':
        return _inteiro(val)
    return '' if _vazio(val) else val


# ═════════════════════════════════════════════════════════════
#  1. EXCEL COMPLETO
# ═════════════════════════════════════════════════════════════
def gerar_excel(df, df_etapas=None, df_progresso=None, df_revisoes=None,
                df_documentos=None):
    """Excel completo: abas Projetos · Documentações · Etapas · Progresso
    Técnico.

    Na aba Projetos cada projeto ocupa uma linha por emissão/revisão
    (pedido de 05/11/2026): as colunas da revisão trazem o que ela gerou, e
    os dados gerais do projeto se repetem iguais em todas as linhas dele —
    assim o filtro e a ordenação do Excel continuam funcionando. As outras
    abas ganham a coluna Revisão. Só entram os projetos de `df`, que é o que
    o usuário logado pode ver."""
    if df is not None:
        df = df.copy().reset_index(drop=True)
        df = df.loc[:, ~df.columns.duplicated()]
    projetos = [] if df is None or df.empty else df.to_dict('records')
    revs_proj = _revisoes_por_projeto(df, df_revisoes, df_etapas,
                                      df_progresso, df_documentos)

    # Colunas: (zona, cabeçalho, campo, largura, tipo). Zona 'rev' é o que
    # muda de uma revisão pra outra; 'proj' e 'comum' se repetem.
    COL_PROJ = [
        ('ID',                       'id',               6,  'int'),
        ('Código',                   'codigo',           14, 'txt'),
        ('Nome do Projeto',          'projeto',          34, 'bold'),
    ]
    COL_REV = [
        ('Revisão',                  'rotulo',           15, 'bold'),
        ('Situação',                 'situacao',         19, 'txt'),
        ('Pedido em',                'solicitado_em',    12, 'data'),
        ('Previsão de entrega',      'previsao',         13, 'data'),
        ('Entregue em',              'entregue_em',      12, 'data'),
        ('Responsável(is)',          'projetista',       26, 'txt'),
        ('O que foi pedido',         'descricao',        40, 'txt'),
        ('Disciplinas da revisão',   'disciplinas',      28, 'txt'),
        ('Documentações geradas',    'documentos',       36, 'txt'),
        ('Etapas (% concluído)',     'etapas',           34, 'txt'),
        ('Evolução técnica',         'evolucao',         30, 'txt'),
        ('Progresso (%)',            'progresso',        11, 'pct'),
    ]
    COL_COMUM = [
        ('Status',                   'status',           14, 'txt'),
        ('Prioridade',               'prioridade',       12, 'txt'),
        ('Equipe do projeto',        'projetista',       30, 'txt'),
        ('Solicitante',              'solicitante',      25, 'txt'),
        ('Contato',                  'contato',          22, 'txt'),
        ('Endereço',                 'endereco',         30, 'txt'),
        ('Local',                    'local',            22, 'txt'),
        ('Nº SEI / Doc.',            'numero_sei',       18, 'txt'),
        ('Recebimento',              'data_recebimento', 13, 'data'),
        ('Prev. Execução',           'previsao_execucao', 14, 'data'),
        ('Início',                   'data_inicio',      12, 'data'),
        ('Término',                  'data_termino',     12, 'data'),
        ('Link Drive',               'link_projeto',     30, 'txt'),
        ('Escopo',                   'solicitacao',      45, 'txt'),
        ('Disciplinas do projeto',   'demandas',         36, 'txt'),
        ('Fonte de Recurso',         'fonte_recurso',    22, 'txt'),
        ('Observações',              'observacoes',      40, 'txt'),
        ('Cadastrado em',            'criado_em',        14, 'data'),
    ]
    colunas = ([('proj',) + c for c in COL_PROJ]
               + [('rev',) + c for c in COL_REV]
               + [('comum',) + c for c in COL_COMUM])
    n_cols = len(colunas)
    i_rev = len(COL_PROJ)
    i_comum = i_rev + len(COL_REV)

    # Cor de fundo por zona, alternando de projeto em projeto (todas as
    # linhas de um projeto ficam com a mesma faixa). As colunas da revisão
    # têm um tom próprio, pra se destacarem dos dados comuns.
    CORES = {
        'proj':  ('#ffffff', '#eef2f7'),
        'rev':   ('#ecfeff', '#d3f3f8'),
        'comum': ('#ffffff', '#eef2f7'),
    }
    COR_CAB = {'proj': '#003366', 'rev': '#0e7490', 'comum': '#0056b3'}

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        wb = writer.book
        fmt_titulo = wb.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#003366',
            'font_size': 12, 'align': 'left', 'valign': 'vcenter',
            'indent': 1,
        })
        fmt_sub = wb.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#0056b3',
            'border': 1, 'align': 'center', 'valign': 'vcenter',
            'font_size': 9,
        })
        fmt_vazio = wb.add_format({'italic': True, 'font_color': '#6b7280',
                                   'font_size': 9})

        def _fmt_cab(zona, grupo=False):
            props = {'bold': True, 'font_color': 'white',
                     'bg_color': COR_CAB[zona], 'border': 1,
                     'border_color': '#ffffff', 'valign': 'vcenter'}
            if grupo:
                props.update({'font_size': 9, 'align': 'left', 'indent': 1})
            else:
                props.update({'font_size': 10, 'align': 'center',
                              'text_wrap': True})
            return wb.add_format(props)

        # Formatos das células, criados sob demanda por (fundo, tipo, 1ª
        # linha do projeto). A 1ª linha de cada projeto ganha uma borda
        # superior forte, pra separar um projeto do outro.
        _cache_fmt = {}

        def _fmt(fundo, tipo='txt', topo=False):
            chave = (fundo, tipo, topo)
            if chave not in _cache_fmt:
                props = {'border': 1, 'border_color': '#d1d5db',
                         'valign': 'top', 'font_size': 9, 'bg_color': fundo}
                if topo:
                    props.update({'top': 2, 'top_color': '#003366'})
                if tipo == 'data':
                    props.update({'num_format': 'dd/mm/yyyy',
                                  'align': 'center'})
                elif tipo == 'pct':
                    props.update({'num_format': '0"%"', 'align': 'center'})
                elif tipo == 'int':
                    props['align'] = 'center'
                else:
                    props['text_wrap'] = True
                    if tipo == 'bold':
                        props['bold'] = True
                _cache_fmt[chave] = wb.add_format(props)
            return _cache_fmt[chave]

        def _escrever(ws_x, lin, col, val, formato):
            """Escreve tratando vazio (None/NaN/NaT), data e número."""
            if _vazio(val):
                ws_x.write_blank(lin, col, None, formato)
            elif isinstance(val, (datetime, date)):
                ws_x.write_datetime(lin, col, val, formato)
            elif isinstance(val, numbers.Number) and not isinstance(val, bool):
                ws_x.write_number(lin, col, val, formato)
            else:
                ws_x.write_string(lin, col, str(val), formato)

        # ── Aba Projetos: uma linha por emissão/revisão ──
        ws = wb.add_worksheet('Projetos')
        writer.sheets['Projetos'] = ws
        ws.merge_range(0, 0, 0, n_cols - 1,
                       'SERVPEN — Projetos por Emissão e Revisão  |  '
                       + datetime.now().strftime('%d/%m/%Y %H:%M'),
                       fmt_titulo)
        ws.set_row(0, 22)
        ws.merge_range(1, 0, 1, i_rev - 1, 'PROJETO', _fmt_cab('proj', True))
        ws.merge_range(1, i_rev, 1, i_comum - 1,
                       'EMISSÃO / REVISÃO — o que cada uma gerou fica na '
                       'linha dela', _fmt_cab('rev', True))
        ws.merge_range(1, i_comum, 1, n_cols - 1,
                       'DADOS GERAIS DO PROJETO — os mesmos em todas as '
                       'linhas do projeto (as datas são as da revisão atual)',
                       _fmt_cab('comum', True))
        ws.set_row(1, 18)
        _cabs = {z: _fmt_cab(z) for z in COR_CAB}
        for col, (zona, rotulo, _campo, larg, _tipo) in enumerate(colunas):
            ws.write(2, col, rotulo, _cabs[zona])
            ws.set_column(col, col, larg)
        ws.set_row(2, 30)

        lin = 3
        for i_p, p in enumerate(projetos):
            faixa = i_p % 2
            for j, rev in enumerate(revs_proj.get(_inteiro(p.get('id')), [])):
                valores_rev = {
                    'rotulo': rev['rotulo'],
                    'situacao': _situacao_rev(rev),
                    'solicitado_em': rev['solicitado_em'],
                    'previsao': rev['previsao'],
                    'entregue_em': rev['entregue_em'],
                    'projetista': rev['projetista'],
                    'descricao': rev['descricao'],
                    'disciplinas': rev['disciplinas'] or 'Demanda inteira',
                    'documentos': _txt_documentos(rev),
                    'etapas': _txt_etapas(rev),
                    'evolucao': _txt_evolucao(rev),
                    'progresso': _progresso_rev(rev),
                }
                for col, (zona, _rot, campo, _larg, tipo) in enumerate(colunas):
                    val = (valores_rev.get(campo) if zona == 'rev'
                           else _valor_projeto(p, campo, tipo))
                    _escrever(ws, lin, col, val,
                              _fmt(CORES[zona][faixa], tipo, j == 0))
                lin += 1
        if lin == 3:
            ws.write(3, 0, 'Nenhum projeto para exportar.', fmt_vazio)
        else:
            ws.autofilter(2, 0, lin - 1, n_cols - 1)
        # Fixa título e cabeçalhos, e as colunas ID…Revisão, que dizem de
        # que projeto e de que revisão é a linha enquanto se rola pro lado.
        ws.freeze_panes(3, i_rev + 1)

        # ── Abas de detalhe, todas com a coluna Revisão ──
        def _aba_detalhe(nome_aba, titulo, colunas_aba, linhas):
            """colunas_aba: [(cabeçalho, largura, tipo)]; linhas:
            [(projeto_id, [valores])], já na ordem projeto → revisão."""
            ws_x = wb.add_worksheet(nome_aba)
            writer.sheets[nome_aba] = ws_x
            n = len(colunas_aba)
            ws_x.merge_range(0, 0, 0, n - 1, titulo, fmt_sub)
            ws_x.set_row(0, 20)
            for col, (cab, larg, _tipo) in enumerate(colunas_aba):
                ws_x.write(1, col, cab, _cabs['rev' if col == 1 else 'proj'])
                ws_x.set_column(col, col, larg)
            ws_x.set_row(1, 30)
            faixa, anterior = 1, object()
            for k, (pid, valores) in enumerate(linhas):
                topo = pid != anterior
                if topo:
                    faixa, anterior = 1 - faixa, pid
                for col, ((_c, _l, tipo), val) in enumerate(
                        zip(colunas_aba, valores)):
                    zona = 'rev' if col == 1 else 'comum'
                    _escrever(ws_x, k + 2, col, val,
                              _fmt(CORES[zona][faixa], tipo, topo and k > 0))
            ws_x.autofilter(1, 0, len(linhas) + 1, n - 1)
            ws_x.freeze_panes(2, 2)

        linhas_doc, linhas_et, linhas_pg = [], [], []
        for p in projetos:
            pid = _inteiro(p.get('id'))
            nome = _txt(p.get('projeto'))
            for rev in revs_proj.get(pid, []):
                for d in rev['documentos']:
                    linhas_doc.append((pid, [
                        nome, rev['rotulo'], _txt(d.get('nome')),
                        _como_data(d.get('criado_em')),
                        _txt(d.get('criado_por'), ''),
                    ]))
                for e in rev['etapas']:
                    ini = _inteiro(e.get('dias_offset'), 0)
                    dur = _inteiro(e.get('duracao_dias'), 0)
                    linhas_et.append((pid, [
                        nome, rev['rotulo'], _inteiro(e.get('ordem'), 0) + 1,
                        _txt(e.get('nome')), ini, dur, ini + dur - 1,
                        _inteiro(e.get('percentual'), 0),
                    ]))
                for g in rev['evolucao']:
                    linhas_pg.append((pid, [
                        nome, rev['rotulo'], _txt(g.get('disciplina')),
                        'Sim' if _inteiro(g.get('concluido'), 0) else 'Não',
                        _inteiro(g.get('percentual'), 0),
                    ]))

        if linhas_doc:
            _aba_detalhe(
                'Documentações', 'SERVPEN — Documentações Geradas por Revisão',
                [('Projeto', 34, 'txt'), ('Revisão', 15, 'bold'),
                 ('Documento', 42, 'txt'), ('Registrado em', 14, 'data'),
                 ('Por', 22, 'txt')],
                linhas_doc)
        if linhas_et:
            _aba_detalhe(
                'Etapas', 'SERVPEN — Etapas dos Projetos por Revisão',
                [('Projeto', 34, 'txt'), ('Revisão', 15, 'bold'),
                 ('Ordem', 8, 'int'), ('Nome da Etapa', 30, 'txt'),
                 ('Início (dias offset)', 14, 'int'),
                 ('Duração (dias)', 12, 'int'),
                 ('Fim estimado (dias)', 14, 'int'),
                 ('Concluído (%)', 12, 'pct')],
                linhas_et)
        if linhas_pg:
            _aba_detalhe(
                'Progresso Técnico',
                'SERVPEN — Progresso por Disciplina e Revisão',
                [('Projeto', 34, 'txt'), ('Revisão', 15, 'bold'),
                 ('Disciplina', 26, 'txt'), ('Concluído', 11, 'txt'),
                 ('Percentual (%)', 14, 'pct')],
                linhas_pg)

    return output.getvalue()


# ═════════════════════════════════════════════════════════════
#  2. PDF COMPLETO
# ═════════════════════════════════════════════════════════════
def gerar_excel_historico(df):
    """Gera um .xlsx do HISTÓRICO DE ALTERAÇÕES dos projetos.

    `df` deve ter as colunas: data, projeto_nome, campo, valor_anterior,
    valor_novo, autor (qualquer subconjunto é tolerado). Retorna bytes.
    """
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        wb = writer.book
        ws = wb.add_worksheet('Histórico')
        writer.sheets['Histórico'] = ws

        fmt_titulo = wb.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#003366',
            'align': 'center', 'valign': 'vcenter', 'font_size': 12,
        })
        fmt_cab = wb.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#0056b3',
            'border': 1, 'align': 'center', 'valign': 'vcenter',
            'font_size': 10,
        })
        fmt_cel = wb.add_format({
            'border': 1, 'valign': 'vcenter', 'font_size': 9,
            'text_wrap': True,
        })
        fmt_alt = wb.add_format({
            'border': 1, 'valign': 'vcenter', 'font_size': 9,
            'bg_color': '#f3f4f6', 'text_wrap': True,
        })

        COLS = [
            ('Data/Hora',      'data',            18),
            ('Projeto',        'projeto_nome',    32),
            ('Campo',          'campo',           20),
            ('Valor Anterior', 'valor_anterior',  28),
            ('Novo Valor',     'valor_novo',      28),
            ('Autor',          'autor',           18),
        ]
        ws.merge_range(
            0, 0, 0, len(COLS) - 1,
            'SERVPEN — Histórico de Alterações  |  '
            + datetime.now().strftime('%d/%m/%Y %H:%M'),
            fmt_titulo,
        )
        ws.set_row(0, 24)
        for j, (titulo, _, larg) in enumerate(COLS):
            ws.write(1, j, titulo, fmt_cab)
            ws.set_column(j, j, larg)

        if df is None or df.empty:
            ws.merge_range(2, 0, 2, len(COLS) - 1,
                           'Sem alterações registradas.', fmt_cel)
        else:
            df = df.copy()
            # Formata a data pra dd/mm/yyyy HH:MM (string)
            if 'data' in df.columns:
                df['data'] = pd.to_datetime(
                    df['data'], errors='coerce'
                ).dt.strftime('%d/%m/%Y %H:%M')
            for i, (_, row) in enumerate(df.iterrows()):
                fmt = fmt_alt if i % 2 else fmt_cel
                for j, (_, chave, _l) in enumerate(COLS):
                    val = row.get(chave, '')
                    ws.write(i + 2, j, '' if pd.isna(val) else str(val), fmt)
        ws.freeze_panes(2, 0)

    return output.getvalue()


# ═════════════════════════════════════════════════════════════
def gerar_pdf(df, df_etapas=None, df_progresso=None, df_revisoes=None,
              df_documentos=None):
    """PDF completo: capa, resumo, relação geral e a ficha de cada projeto.

    Na ficha vêm primeiro os dados gerais do projeto e, depois, um bloco
    por emissão/revisão com o que ela gerou — pedido, prazos, responsável,
    documentações, etapas e evolução técnica (pedido de 05/11/2026). Só
    entram os projetos de `df`."""
    # ── SOLUÇÃO CONTRA DUPLICIDADE: HIGIENIZAÇÃO DE ÍNDICES E COLUNAS ──
    if df is not None:
        df = df.copy().reset_index(drop=True)
        df = df.loc[:, ~df.columns.duplicated()]
    revs_proj = _revisoes_por_projeto(df, df_revisoes, df_etapas,
                                      df_progresso, df_documentos)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=3.2*cm, bottomMargin=2*cm,
    )
    doc.onFirstPage = _cabecalho_pagina
    doc.onLaterPages = _cabecalho_pagina

    st = _estilos()
    story = []
    w_util = A4[0] - 3*cm

    # Cor própria das emissões/revisões (a mesma das colunas da revisão no
    # Excel) e estilos dos blocos.
    COR_REV = colors.HexColor('#0e7490')
    st_rev_tit = ParagraphStyle('RevTit', fontName='Helvetica-Bold',
                                fontSize=10, leading=13, textColor=BRANCO)
    st_rev_sit = ParagraphStyle('RevSit', fontName='Helvetica', fontSize=8,
                                leading=11, textColor=BRANCO,
                                alignment=TA_RIGHT)
    st_rev_sub = ParagraphStyle('RevSub', fontName='Helvetica-Bold',
                                fontSize=9, leading=12, textColor=COR_REV,
                                spaceBefore=6, spaceAfter=3)
    st_nota = ParagraphStyle('Nota', fontName='Helvetica-Oblique', fontSize=8,
                             leading=11, textColor=colors.HexColor('#6b7280'),
                             spaceAfter=4)

    def _hr():
        return HRFlowable(width='100%', thickness=0.5,
                          color=CINZA_BORDA, spaceAfter=6, spaceBefore=6)

    def _secao(txt):
        return Paragraph(f'<b>{txt}</b>', st['secao'])

    def _par_campos(pares):
        rows = []
        for i in range(0, len(pares), 2):
            left  = pares[i]
            right = pares[i+1] if i+1 < len(pares) else ('', '')
            rows.append([
                Paragraph(left[0],  st['campo_label']),
                Paragraph(_esc(left[1]),  st['campo_valor']),
                Paragraph(right[0], st['campo_label']),
                Paragraph(_esc(right[1]) if right[0] else '', st['campo_valor']),
            ])
        t = Table(rows, colWidths=[3.5*cm, w_util/2-3.5*cm, 3.5*cm, w_util/2-3.5*cm])
        t.setStyle(TableStyle([
            ('VALIGN',       (0,0),(-1,-1), 'TOP'),
            ('TOPPADDING',   (0,0),(-1,-1), 3),
            ('BOTTOMPADDING',(0,0),(-1,-1), 3),
            ('LEFTPADDING',  (0,0),(-1,-1), 2),
            ('RIGHTPADDING', (0,0),(-1,-1), 4),
            ('LINEBELOW',    (0,0),(-1,-2), 0.3, CINZA_BORDA),
        ]))
        return t

    def _tabela_rev(cabecalhos, linhas, larguras):
        t = Table([[Paragraph(c, st['cabecalho_tab']) for c in cabecalhos]]
                  + [[Paragraph(v, st['celula']) for v in lin] for lin in linhas],
                  colWidths=larguras, repeatRows=1)
        t.setStyle(_tabela_estilo(len(cabecalhos), COR_REV))
        return t

    def _bloco_revisao(rev):
        """Faixa com o rótulo e a situação, os dados da revisão e o que ela
        gerou. Cada parte anda junta com o seu título na quebra de página."""
        sit = (f"Entregue em {rev['entregue_em'].strftime('%d/%m/%Y')}"
               if rev['entregue_em'] else 'Em execução')
        if rev['atual']:
            sit += '  ·  revisão atual'
        barra = Table([[Paragraph(_esc(rev['rotulo'].upper()), st_rev_tit),
                        Paragraph(sit, st_rev_sit)]],
                      colWidths=[w_util * 0.45, w_util * 0.55])
        barra.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,-1), COR_REV),
            ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
            ('TOPPADDING',    (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('LEFTPADDING',   (0,0), (-1,-1), 8),
            ('RIGHTPADDING',  (0,0), (-1,-1), 8),
        ]))
        pares = [
            ('Pedido em',           _data_fmt(rev['solicitado_em'])),
            ('Previsão de entrega', _data_fmt(rev['previsao'])),
            ('Entregue em',         _data_fmt(rev['entregue_em'])),
            ('Responsável(is)',     rev['projetista']),
            ('Disciplinas',         rev['disciplinas'] or 'Demanda inteira'),
        ]
        if rev['numero'] > 0:
            pares.append(('Partiu de', 'Do zero (0%)' if rev['do_zero']
                          else 'Da revisão anterior'))
        cabeca = [barra, Spacer(1, 0.15*cm), _par_campos(pares)]
        if rev['descricao']:
            cabeca.append(Paragraph('<b>O que foi pedido:</b> '
                                    + _esc(rev['descricao']), st['corpo']))
        partes = [KeepTogether(cabeca)]

        tit = Paragraph('Documentações geradas', st_rev_sub)
        if rev['documentos']:
            partes.append(KeepTogether([tit, _tabela_rev(
                ['Documento', 'Registrado em', 'Por'],
                [[_esc(d.get('nome')), _data_br(d.get('criado_em')) or '—',
                  _esc(d.get('criado_por'))] for d in rev['documentos']],
                [w_util - 6*cm, 2.8*cm, 3.2*cm])]))
        else:
            partes.append(KeepTogether([tit, Paragraph(
                'Nenhuma documentação registrada nesta revisão.', st_nota)]))

        tit = Paragraph('Etapas', st_rev_sub)
        if rev['etapas']:
            _linhas_et = []
            for e in rev['etapas']:
                ini = _inteiro(e.get('dias_offset'), 0)
                dur = _inteiro(e.get('duracao_dias'), 0)
                _linhas_et.append([
                    str(_inteiro(e.get('ordem'), 0) + 1), _esc(e.get('nome')),
                    str(ini), str(dur), str(ini + dur - 1),
                    f"{_inteiro(e.get('percentual'), 0)}%",
                ])
            partes.append(KeepTogether([tit, _tabela_rev(
                ['Ord.', 'Etapa', 'Início (dias)', 'Duração (dias)',
                 'Fim (dias)', 'Concluído'],
                _linhas_et,
                [1.3*cm, w_util - 11.3*cm, 2.5*cm, 2.5*cm, 2.5*cm, 2.5*cm])]))
        else:
            partes.append(KeepTogether([tit, Paragraph(
                'Nenhuma etapa cadastrada nesta revisão.', st_nota)]))

        tit = Paragraph('Evolução técnica por disciplina', st_rev_sub)
        if rev['evolucao']:
            partes.append(KeepTogether([tit, _tabela_rev(
                ['Disciplina', 'Progresso', 'Concluída'],
                [[_esc(g.get('disciplina')),
                  f"{_inteiro(g.get('percentual'), 0)}%",
                  'Sim' if _inteiro(g.get('concluido'), 0) else 'Não']
                 for g in rev['evolucao']],
                [w_util*0.5, w_util*0.25, w_util*0.25])]))
        else:
            partes.append(KeepTogether([tit, Paragraph(
                'Sem evolução técnica registrada nesta revisão.', st_nota)]))

        partes.append(Spacer(1, 0.4*cm))
        return partes

    # 🧱 CAPA DO RELATÓRIO
    capa_tbl = Table(
        [[Paragraph('RELATÓRIO DE GESTÃO DE PROJETOS', st['titulo'])],
         [Paragraph(f'SERVPEN Engenharia  ·  UERJ  ·  Emissão: {datetime.now().strftime("%d/%m/%Y %H:%M")}', st['subtitulo'])]],
        colWidths=[w_util],
    )
    capa_tbl.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), AZUL_ESCURO),
        ('TOPPADDING',    (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
        ('LEFTPADDING',   (0,0), (-1,-1), 12),
        ('RIGHTPADDING',  (0,0), (-1,-1), 12),
        ('ROUNDEDCORNERS', [6]),
    ]))
    story.append(capa_tbl)
    story.append(Spacer(1, 0.5*cm))

    # 📊 RESUMO EXECUTIVO (CONTAGEM DE STATUS)
    if df is not None and not df.empty:
        stat_counts = df['status'].value_counts().to_dict()
        tot_rows = [[
            Paragraph('<b>STATUS</b>', st['cabecalho_tab']),
            Paragraph('<b>QUANTIDADE</b>', st['cabecalho_tab']),
        ]]
        for s, n in stat_counts.items():
            tot_rows.append([
                Paragraph(_esc(s), st['celula']),
                Paragraph(str(n), st['celula']),
            ])
        tot_rows.append([
            Paragraph('<b>TOTAL</b>', st['cabecalho_tab']),
            Paragraph(f'<b>{len(df)}</b>', st['cabecalho_tab']),
        ])
        t_tot = Table(tot_rows, colWidths=[w_util*0.6, w_util*0.4])
        t_tot.setStyle(_tabela_estilo(2))
        # A linha TOTAL usa o estilo do cabeçalho (texto branco): sem fundo
        # escuro ela saía invisível.
        t_tot.setStyle(TableStyle([
            ('BACKGROUND', (0, -1), (-1, -1), AZUL_ESCURO),
        ]))
        story.append(_secao('📊 Resumo Executivo'))
        story.append(t_tot)
        story.append(Spacer(1, 0.4*cm))

        # 📋 TABELA INICIAL AJUSTADA: APENAS OS 6 CAMPOS SOLICITADOS
        story.append(_secao('📋 Relação Geral de Empreendimentos'))

        dem_rows = [[
            Paragraph('<b>ID</b>', st['cabecalho_tab']),
            Paragraph('<b>CÓDIGO</b>', st['cabecalho_tab']),
            Paragraph('<b>NOME DO PROJETO</b>', st['cabecalho_tab']),
            Paragraph('<b>PROJETISTA</b>', st['cabecalho_tab']),
            Paragraph('<b>ENDEREÇO DA OBRA</b>', st['cabecalho_tab']),
            Paragraph('<b>LOCAL</b>', st['cabecalho_tab']),
            Paragraph('<b>STATUS</b>', st['cabecalho_tab']),
            Paragraph('<b>RECEBIMENTO</b>', st['cabecalho_tab']),
        ]]

        for _, proj in df.iterrows():
            dem_rows.append([
                Paragraph(str(proj.get('id', '—')), st['celula']),
                Paragraph(_esc(proj.get('codigo', '—')), st['celula']),
                Paragraph(f"<b>{_esc(proj['projeto'])}</b>", st['celula']),
                Paragraph(_esc(proj.get('projetista', '—')), st['celula']),
                Paragraph(_esc(proj.get('endereco', '—')), st['celula']),
                Paragraph(_esc(proj.get('local', '—')), st['celula']),
                Paragraph(_esc(proj.get('status', '—')), st['celula']),
                Paragraph(_data_fmt(proj.get('data_recebimento', ''))),
            ])

        # Distribuição milimétrica das colunas para os 18cm úteis da página retrato
        # ID(0.9) Código(2.0) Nome(3.6) Projetista(2.2) Endereço(3.3) Local(1.8) Status(1.9) Receb.(2.3)
        larguras_colunas = [
            0.9 * cm, 2.0 * cm, 3.6 * cm, 2.2 * cm, 3.3 * cm, 1.8 * cm, 1.9 * cm, 2.3 * cm
        ]

        t_dem = Table(dem_rows, colWidths=larguras_colunas)
        t_dem.setStyle(_tabela_estilo(8))
        story.append(t_dem)
        story.append(Spacer(1, 0.5 * cm))

    # 🔎 DETALHAMENTO DOS TÓPICOS DOS PROJETOS (ENUMERADOS)
    if df is not None and not df.empty:
        st_hdr_proj = ParagraphStyle('HdrProj', fontName='Helvetica-Bold', fontSize=13, textColor=BRANCO, leading=16)
        st_hdr_status = ParagraphStyle('HdrStat', fontName='Helvetica-Bold', fontSize=8, textColor=BRANCO, alignment=TA_CENTER, leading=10)
        st_hdr_prio = ParagraphStyle('HdrPrio', fontName='Helvetica-Bold', fontSize=8, textColor=BRANCO, alignment=TA_CENTER, leading=10)

        for row_idx, (_, proj) in enumerate(df.iterrows()):
            story.append(PageBreak())

            cor_st = COR_STATUS.get(str(proj.get('status','')), AZUL_MEDIO)
            cor_pr = COR_PRIORIDADE.get(str(proj.get('prioridade','')), AZUL_CLARO)

            num_projeto_txt = f"{row_idx + 1}. {proj['projeto']}"

            hdr = Table([[
                Paragraph(f'<b>{_esc(num_projeto_txt)}</b>', st_hdr_proj),
                Table([[
                    Paragraph(_esc(proj.get('status','—')), st_hdr_status),
                    Paragraph(_esc(proj.get('prioridade','—')), st_hdr_prio),
                ]], colWidths=[2.8*cm, 2.4*cm],
                    style=TableStyle([
                        ('BACKGROUND', (0,0), (0,0), cor_st),
                        ('BACKGROUND', (1,0), (1,0), cor_pr),
                        ('TOPPADDING',    (0,0),(-1,-1), 5),
                        ('BOTTOMPADDING', (0,0),(-1,-1), 5),
                        ('GRID',          (0,0),(-1,-1), 0, BRANCO),
                        ('ROUNDEDCORNERS', [4]),
                    ])),
            ]], colWidths=[w_util - 6*cm, 6*cm])
            hdr.setStyle(TableStyle([
                ('BACKGROUND',    (0,0), (-1,-1), AZUL_ESCURO),
                ('TOPPADDING',    (0,0), (-1,-1), 10),
                ('BOTTOMPADDING', (0,0), (-1,-1), 10),
                ('LEFTPADDING',   (0,0), (0,0),  12),
                ('RIGHTPADDING',  (-1,0),(-1,-1), 8),
                ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
            ]))
            story.append(hdr)
            story.append(Spacer(1, 0.3*cm))

            revs = revs_proj.get(_inteiro(proj.get('id')), [])

            # ── Dados gerais: os mesmos pra todas as revisões ──
            story.append(_secao('Identificação'))
            story.append(_par_campos([
                ('Código do Projeto',     proj.get('codigo','')),
                ('Nº SEI / Documento',   proj.get('numero_sei','')),
                ('Projetista(s)',         proj.get('projetista','')),
                ('Solicitante / Cliente', proj.get('solicitante','')),
                ('Contato',               proj.get('contato','')),
                ('Endereço da Obra',     proj.get('endereco','')),
                ('Local',                 proj.get('local','')),
                ('Link da Pasta',        proj.get('link_projeto','')),
                ('Fonte de Recurso',     proj.get('fonte_recurso','')),
            ]))
            story.append(Spacer(1, 0.2*cm))

            story.append(_secao('Cronograma'))
            story.append(_par_campos([
                ('Data de Recebimento',    _data_fmt(proj.get('data_recebimento',''))),
                ('Prev. Início Execução',  _data_fmt(proj.get('previsao_execucao',''))),
                ('Data de Início',         _data_fmt(proj.get('data_inicio',''))),
                ('Data de Término',        _data_fmt(proj.get('data_termino', proj.get('data_fim','')))),
            ]))
            if len(revs) > 1:
                story.append(Paragraph(
                    f"Datas da revisão atual ({revs[-1]['rotulo']}). As de "
                    "cada emissão estão em Emissões e Revisões, abaixo.",
                    st_nota))
            story.append(Spacer(1, 0.2*cm))

            esc = _txt(proj.get('solicitacao',''))
            if esc != '—':
                story.append(_secao('Escopo / Descrição'))
                story.append(Paragraph(_esc(esc), st['corpo']))
                story.append(Spacer(1, 0.15*cm))

            dem_ind = _txt(proj.get('demandas',''))
            if dem_ind != '—':
                story.append(_secao('Disciplinas'))
                story.append(Paragraph(_esc(dem_ind), st['corpo']))
                story.append(Spacer(1, 0.15*cm))

            _obs = _txt(proj.get('observacoes', ''))
            if _obs != '—':
                story.append(_secao('Observações'))
                story.append(Paragraph(_esc(_obs), st['corpo']))
                story.append(Spacer(1, 0.15*cm))

            # ── O que cada emissão/revisão gerou, da inicial pra mais nova ──
            if revs:
                story.append(_secao('Emissões e Revisões'))
                for rev in revs:
                    story.extend(_bloco_revisao(rev))

            story.append(_hr())

    doc.build(story, onFirstPage=_cabecalho_pagina, onLaterPages=_cabecalho_pagina)
    return buf.getvalue()


# ═════════════════════════════════════════════════════════════
#  3. PDF GANTT — CRONOGRAMA EM PAISAGEM (CORRIGIDO)
# ═════════════════════════════════════════════════════════════
def gerar_pdf_gantt(df_projetos, df_etapas):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=2.8*cm, bottomMargin=1.5*cm,
    )
    st = _estilos()
    story = []
    W, H  = landscape(A4)
    w_util = W - 3*cm

    CORES_PROJETO = [
        colors.HexColor('#0056b3'), colors.HexColor('#10b981'),
        colors.HexColor('#f59e0b'), colors.HexColor('#ef4444'),
        colors.HexColor('#7c3aed'), colors.HexColor('#ec4899'),
        colors.HexColor('#14b8a6'), colors.HexColor('#f97316'),
    ]

    story.append(Spacer(1, 0.3*cm))
    
    estilo_titulo_gantt = ParagraphStyle('GH', fontName='Helvetica-Bold', fontSize=13, textColor=AZUL_ESCURO, leading=16, spaceAfter=8)
    texto_gantt = f'<b>Cronograma de Etapas — Gantt</b> &nbsp; <font size="9" color="grey">Emissão: {datetime.now().strftime("%d/%m/%Y %H:%M")}</font>'
    story.append(Paragraph(texto_gantt, estilo_titulo_gantt))

    if df_etapas is None or df_etapas.empty:
        story.append(Paragraph('Nenhuma etapa cadastrada.', st['corpo']))
        doc.build(story, onFirstPage=_cabecalho_paisagem, onLaterPages=_cabecalho_paisagem)
        return buf.getvalue()

    projetos_ids = df_etapas['projeto_id'].unique().tolist() if 'projeto_id' in df_etapas.columns else []

    max_dia = 0
    for _, row in df_etapas.iterrows():
        fim = int(row.get('dias_offset',0)) + int(row.get('duracao_dias',0))
        max_dia = max(max_dia, fim)
    max_dia = max(max_dia, 1)

    COL_NOME   = 5*cm
    COL_BARRA  = w_util - COL_NOME - 2*cm
    ALTURA_LIN = 0.55*cm

    cab_rows = [[
        Paragraph('<b>Projeto / Etapa</b>', st['cabecalho_tab']),
        Paragraph('<b>Cronograma (dias corridos a partir do início do projeto)</b>', st['cabecalho_tab']),
    ]]
    t_cab = Table(cab_rows, colWidths=[COL_NOME, COL_BARRA + 2*cm])
    t_cab.setStyle(TableStyle([
        ('BACKGROUND',   (0,0),(-1,-1), AZUL_ESCURO),
        ('TEXTCOLOR',    (0,0),(-1,-1), BRANCO),
        ('TOPPADDING',   (0,0),(-1,-1), 6),
        ('BOTTOMPADDING',(0,0),(-1,-1), 6),
        ('LEFTPADDING',  (0,0),(-1,-1), 6),
        ('FONTNAME',     (0,0),(-1,-1), 'Helvetica-Bold'),
        ('FONTSIZE',     (0,0),(-1,-1), 9),
    ]))
    story.append(t_cab)

    gantt_rows = []
    proj_idx   = {}
    
    st_gantt_header = ParagraphStyle('GntHdr', fontName='Helvetica-Bold', fontSize=8, textColor=BRANCO, leading=10)
    st_gantt_row = ParagraphStyle('GntRow', fontName='Helvetica', fontSize=7.5, textColor=CINZA_TITULO, leading=10)

    for i, pid in enumerate(projetos_ids):
        proj_idx[pid] = i
        et_proj = df_etapas[df_etapas['projeto_id'] == pid].sort_values('ordem') if 'projeto_id' in df_etapas.columns else pd.DataFrame()
        if et_proj.empty:
            continue
        proj_nome = _txt(et_proj.iloc[0].get('projeto', f'Projeto {pid}'))
        cor_proj  = CORES_PROJETO[i % len(CORES_PROJETO)]

        gantt_rows.append([
            Paragraph(f'<b>{proj_nome[:38]}</b>', st_gantt_header),
            '',
            True, cor_proj,
        ])

        for _, et in et_proj.iterrows():
            inicio  = int(et.get('dias_offset', 0))
            duracao = int(et.get('duracao_dias', 1))
            fim     = inicio + duracao
            gantt_rows.append([
                Paragraph(f'  ↳ {_txt(et.get("nome",""))}', st_gantt_row),
                (inicio, fim, max_dia, cor_proj),
                False, cor_proj,
            ])

    # CORRIGIDO: Identação do loop interno de renderização das tabelas
    for row in gantt_rows:
        nome_cell = row[0]
        barra_dat = row[1]
        is_header = row[2]
        cor       = row[3]

        if is_header:
            t = Table([[nome_cell, '']], colWidths=[COL_NOME, COL_BARRA + 2*cm])
            t.setStyle(TableStyle([
                ('BACKGROUND',   (0,0),(-1,-1), cor),
                ('TOPPADDING',   (0,0),(-1,-1), 5),
                ('BOTTOMPADDING',(0,0),(-1,-1), 5),
                ('LEFTPADDING',  (0,0),(-1,-1), 6),
            ]))
        else:
            ini, fim_d, max_d, cor_b = barra_dat
            pct_ini = ini / max_d
            pct_fim = fim_d / max_d

            d_w  = COL_BARRA + 2*cm
            d_h  = ALTURA_LIN * 1.4
            drw  = Drawing(d_w, d_h)

            drw.add(Rect(0, 0, d_w, d_h, fillColor=colors.HexColor('#f3f4f6'), strokeColor=CINZA_BORDA, strokeWidth=0.3))
            x1 = pct_ini * d_w
            x2 = pct_fim * d_w
            bar_w = max(x2 - x1, 3)
            drw.add(Rect(x1, d_h*0.15, bar_w, d_h*0.7, fillColor=cor_b, strokeColor=cor_b, strokeWidth=0))

            for p in range(0, 101, 10):
                xm = (p / 100) * d_w
                drw.add(Line(xm, 0, xm, d_h*0.15, strokeColor=CINZA_BORDA, strokeWidth=0.5))

            label_txt = f'{ini}d–{fim_d}d'
            lx = x1 + bar_w / 2
            ly = d_h * 0.25
            if bar_w > 40:
                drw.add(String(lx, ly, label_txt, fontSize=6, fillColor=BRANCO, textAnchor='middle'))
            else:
                drw.add(String(min(x2 + 4, d_w - 2), ly, label_txt, fontSize=6, fillColor=CINZA_TITULO, textAnchor='start'))

            t = Table([[nome_cell, drw]], colWidths=[COL_NOME, d_w])
            t.setStyle(TableStyle([
                ('VALIGN',       (0,0),(-1,-1), 'MIDDLE'),
                ('TOPPADDING',   (0,0),(-1,-1), 2),
                ('BOTTOMPADDING',(0,0),(-1,-1), 2),
                ('LEFTPADDING',  (0,0),(0,0),  6),
                ('LINEBELOW',    (0,0),(-1,-1), 0.3, CINZA_BORDA),
                ('ROWBACKGROUNDS',(0,0),(-1,-1), [BRANCO]),
            ]))

        # CORRIGIDO: Agora o append ocorre DENTRO do loop principal para cada linha cadastrada!
        story.append(t)

    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph(
        f'<font size="7" color="grey">Escala: 0 a {max_dia} dias corridos a partir da data de início de cada projeto. As barras são proporcionais ao total de dias do projeto.</font>',
        st['corpo'],
    ))

    doc.build(story, onFirstPage=_cabecalho_paisagem, onLaterPages=_cabecalho_paisagem)
    return buf.getvalue()


# ═════════════════════════════════════════════════════════════
#  4. PDF DIÁRIO
# ═════════════════════════════════════════════════════════════
def _hr_diario():
    """Régua fina entre registros do diário."""
    return HRFlowable(width='100%', thickness=0.5,
                      color=CINZA_BORDA, spaceAfter=4, spaceBefore=4)


def _total_horas(df_diario):
    """Soma a coluna `horas`, tolerando NULL/texto. 0.0 se não houver."""
    if df_diario is None or df_diario.empty or 'horas' not in df_diario.columns:
        return 0.0
    return float(pd.to_numeric(df_diario['horas'],
                               errors='coerce').fillna(0).sum())


def _corpo_pdf_diario(story, st, w_util, df_diario, msg_vazio):
    """Resumo + histórico completo dos registros do diário.

    É a parte que NÃO depende de projeto — por isso serve igual pro
    relatório por projeto e pro relatório por pessoa. Quem chama monta a
    capa (que é o que muda entre os dois) e depois entrega o `story` aqui.

    Retorna False se não havia registro (quem chamou já pode fechar o PDF).
    """
    if df_diario is None or df_diario.empty:
        story.append(Paragraph(msg_vazio, st['corpo']))
        return False

    # Resumo numérico
    n_relatos    = len(df_diario[~df_diario['executado'].astype(str).str.contains('Impedimento|Dúvida|❓|🛑', na=False)])
    n_duvidas    = len(df_diario[df_diario['executado'].astype(str).str.contains('Dúvida|❓', na=False)])
    n_impedim    = len(df_diario[df_diario['executado'].astype(str).str.contains('Impedimento|🛑', na=False)])
    n_resolvidos = len(df_diario[df_diario['resolvido'] == 1])
    _horas = _total_horas(df_diario)

    res_rows = [[
        Paragraph('Relatos', st['cabecalho_tab']),
        Paragraph('Dúvidas', st['cabecalho_tab']),
        Paragraph('Impedimentos', st['cabecalho_tab']),
        Paragraph('Resolvidos', st['cabecalho_tab']),
        Paragraph('Total', st['cabecalho_tab']),
        Paragraph('Horas', st['cabecalho_tab']),
    ], [
        Paragraph(str(n_relatos),      st['celula']),
        Paragraph(str(n_duvidas),      st['celula']),
        Paragraph(str(n_impedim),      st['celula']),
        Paragraph(str(n_resolvidos),   st['celula']),
        Paragraph(str(len(df_diario)), st['celula']),
        Paragraph(f'{_horas:.2f} h',   st['celula']),
    ]]
    t_res = Table(res_rows, colWidths=[w_util/6]*6)
    t_res.setStyle(_tabela_estilo(6))
    story.append(Paragraph('<b>Resumo do Histórico</b>', st['secao']))
    story.append(t_res)
    story.append(Spacer(1, 0.5*cm))

    story.append(Paragraph('<b>Histórico Completo — ordem cronológica</b>', st['secao']))
    story.append(_hr_diario())

    # Estilos específicos do diário
    st_diario_hdr_l = ParagraphStyle('DiaHdrL', fontName='Helvetica-Bold', fontSize=9, textColor=BRANCO, leading=12)
    st_diario_hdr_r = ParagraphStyle('DiaHdrR', fontName='Helvetica',      fontSize=8, textColor=BRANCO, alignment=TA_RIGHT, leading=11)
    st_diario_orient = ParagraphStyle('DiaOrient', fontName='Helvetica',   fontSize=9, textColor=AZUL_ESCURO, leftIndent=10, leading=13)
    st_diario_status = ParagraphStyle('DiaStatus', fontName='Helvetica-Bold', fontSize=8, alignment=TA_RIGHT, spaceAfter=6, leading=10)

    for i, (_, reg) in enumerate(df_diario.sort_values('id').iterrows()):
        txt_exec = str(reg.get('executado', ''))

        # Classificação do tipo de registro
        if 'Impedimento' in txt_exec or '🛑' in txt_exec:
            tipo_str = 'IMPEDIMENTO'
            cor_tipo = VERMELHO
        elif 'Dúvida' in txt_exec or '❓' in txt_exec:
            tipo_str = 'DÚVIDA TÉCNICA'
            cor_tipo = LARANJA
        else:
            tipo_str = 'RELATO DE ATIVIDADE'
            cor_tipo = AZUL_MEDIO

        resolvido = bool(reg.get('resolvido', 0))
        cor_status_d = VERDE if resolvido else cor_tipo

        # Disciplina só aparece quando existe (atividade pessoal não tem);
        # horas do registro entram no cabeçalho quando preenchidas.
        _disc = _txt(reg.get('disciplina', '') or '', fallback='')
        _h_reg = reg.get('horas') or 0
        try:
            _h_reg = float(_h_reg)
        except (TypeError, ValueError):
            _h_reg = 0.0
        _partes_cab = [p for p in (
            _disc,
            f'Por: {_txt(reg.get("autor",""))}',
            _txt(reg.get('data', '')),
            (f'⏱ {_h_reg:.2f} h' if _h_reg else ''),
        ) if p and p != '—']

        # Cabeçalho de cada entrada do diário
        cab_d = Table([[
            Paragraph(f'<b>#{i+1} — {tipo_str}</b>', st_diario_hdr_l),
            Paragraph(f'<font size="8">{"  ·  ".join(_partes_cab)}</font>', st_diario_hdr_r),
        ]], colWidths=[w_util*0.55, w_util*0.45])
        cab_d.setStyle(TableStyle([
            ('BACKGROUND',    (0,0),(-1,-1), cor_status_d),
            ('TOPPADDING',    (0,0),(-1,-1), 6),
            ('BOTTOMPADDING', (0,0),(-1,-1), 6),
            ('LEFTPADDING',   (0,0),(0,0),   8),
            ('RIGHTPADDING',  (-1,0),(-1,-1),8),
            ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
        ]))

        # QUEBRA EM LINHAS SEPARADAS NO PDF
        linhas_relato = [Paragraph(l.strip(), st['corpo'])
                         for l in txt_exec.split('\n') if l.strip()]

        if not linhas_relato:
            linhas_relato = [Paragraph('—', st['corpo'])]

        dados_tabela_relato = [[p] for p in linhas_relato]

        estilo_corpo_relato = TableStyle([
            ('BACKGROUND',    (0,0),(-1,-1), CINZA_LINHA),
            ('TOPPADDING',    (0,0),(-1,-1), 4),
            ('BOTTOMPADDING', (0,0),(-1,-1), 4),
            ('LEFTPADDING',   (0,0),(-1,-1), 10),
            ('RIGHTPADDING',  (0,0),(-1,-1), 10),
            # linha fininha separando as linhas do relato (exceto a última)
            ('LINEBELOW',     (0,0),(-1,-2), 0.25, CINZA_BORDA),
        ])

        t_corpo = Table(dados_tabela_relato, colWidths=[w_util], style=estilo_corpo_relato)

        story.append(KeepTogether([
            cab_d,
            t_corpo,
        ]))

        # Orientação / resposta do gestor
        resp = str(reg.get('resposta_gestor', '') or '')
        if resp.strip() and resp not in ('None', 'nan'):
            # quebra a resposta em linhas
            linhas_resp = [l.strip() for l in resp.split('\n') if l.strip()]

            if not linhas_resp:
                linhas_resp = ['—']

            # primeira linha com o título
            paragrafos = [Paragraph(f'<b>💡 Orientação do Gestor:</b> {linhas_resp[0]}', st_diario_orient)]
            # demais linhas, cada uma em um parágrafo separado
            for linha in linhas_resp[1:]:
                paragrafos.append(Paragraph(linha, st_diario_orient))

            dados_resp = [[p] for p in paragrafos]

            t_resp = Table(
                dados_resp,
                colWidths=[w_util],
                style=TableStyle([
                    ('BACKGROUND',    (0,0),(-1,-1), colors.HexColor('#eff6ff')),
                    ('TOPPADDING',    (0,0),(-1,-1), 4),
                    ('BOTTOMPADDING', (0,0),(-1,-1), 4),
                    ('LEFTPADDING',   (0,0),(-1,-1), 8),
                    ('RIGHTPADDING',  (0,0),(-1,-1), 8),
                    # linha fininha entre as respostas, exceto a última
                    ('LINEBELOW',     (0,0),(-1,-2), 0.25, AZUL_CLARO),
                    ('VALIGN',        (0,0),(-1,-1), 'TOP'),
                ])
            )
            story.append(t_resp)

        # Status RESOLVIDO/PENDENTE
        status_text = f'<font color="{"#10b981" if resolvido else "#ef4444"}">{"✔ RESOLVIDO" if resolvido else "✗ PENDENTE"}</font>'
        story.append(Paragraph(status_text, st_diario_status))
        story.append(_hr_diario())

    return True


def gerar_pdf_diario_pessoa(pessoa_nome, df_diario):
    """PDF do diário de UMA PESSOA (as "Minhas Atividades" dela).

    Mesma estrutura do relatório por projeto — muda só a capa: em vez da
    identificação do projeto, traz o nome da pessoa e o total de horas.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=3.2*cm, bottomMargin=2*cm,
    )
    st = _estilos()
    story = []
    w_util = A4[0] - 3*cm

    _horas = _total_horas(df_diario)
    _n = 0 if df_diario is None or df_diario.empty else len(df_diario)

    capa = Table([[
        Paragraph('DIÁRIO DE ATIVIDADES — POR PESSOA', st['titulo']),
        Paragraph(_txt(pessoa_nome), st['subtitulo']),
        Paragraph(f'Emissão: {datetime.now().strftime("%d/%m/%Y %H:%M")}', st['subtitulo']),
    ]], colWidths=[w_util])
    capa.setStyle(TableStyle([
        ('BACKGROUND',    (0,0),(-1,-1), AZUL_ESCURO),
        ('TOPPADDING',    (0,0),(-1,-1), 10),
        ('BOTTOMPADDING', (0,0),(-1,-1), 10),
        ('LEFTPADDING',   (0,0),(-1,-1), 12),
    ]))
    story.append(capa)
    story.append(Spacer(1, 0.4*cm))

    story.append(Paragraph('<b>Identificação</b>', st['secao']))
    info_rows = [
        [Paragraph('Pessoa',    st['campo_label']),
         Paragraph(_txt(pessoa_nome), st['campo_valor']),
         Paragraph('Registros', st['campo_label']),
         Paragraph(str(_n), st['campo_valor'])],
        [Paragraph('Horas totais', st['campo_label']),
         Paragraph(f'{_horas:.2f} h', st['campo_valor']),
         Paragraph('Emissão',    st['campo_label']),
         Paragraph(datetime.now().strftime('%d/%m/%Y %H:%M'), st['campo_valor'])],
    ]
    t_inf = Table(info_rows, colWidths=[3*cm, w_util/2-3*cm, 3*cm, w_util/2-3*cm])
    t_inf.setStyle(TableStyle([
        ('VALIGN',       (0,0),(-1,-1), 'TOP'),
        ('TOPPADDING',   (0,0),(-1,-1), 4),
        ('BOTTOMPADDING',(0,0),(-1,-1), 4),
        ('LINEBELOW',    (0,0),(-1,-2), 0.3, CINZA_BORDA),
    ]))
    story.append(t_inf)
    story.append(Spacer(1, 0.4*cm))

    _corpo_pdf_diario(
        story, st, w_util, df_diario,
        'Nenhuma atividade registrada por esta pessoa.',
    )
    doc.build(story, onFirstPage=_cabecalho_pagina, onLaterPages=_cabecalho_pagina)
    return buf.getvalue()


def gerar_pdf_diario(projeto_row, df_diario):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=3.2*cm, bottomMargin=2*cm,
    )
    st = _estilos()
    story = []
    w_util = A4[0] - 3*cm

    proj_nome = _txt(projeto_row.get('projeto', 'Projeto'))

    capa = Table([[
        Paragraph('DIÁRIO DE EVOLUÇÃO DO PROJETO', st['titulo']),
        Paragraph(proj_nome, st['subtitulo']),
        Paragraph(f'Emissão: {datetime.now().strftime("%d/%m/%Y %H:%M")}', st['subtitulo']),
    ]], colWidths=[w_util])
    capa.setStyle(TableStyle([
        ('BACKGROUND',    (0,0),(-1,-1), AZUL_ESCURO),
        ('TOPPADDING',    (0,0),(-1,-1), 10),
        ('BOTTOMPADDING', (0,0),(-1,-1), 10),
        ('LEFTPADDING',   (0,0),(-1,-1), 12),
    ]))
    story.append(capa)
    story.append(Spacer(1, 0.4*cm))

    story.append(Paragraph('<b>Identificação do Projeto</b>', st['secao']))
    info_rows = [
        [Paragraph('Nome',        st['campo_label']),
         Paragraph(_txt(projeto_row.get('projeto','')), st['campo_valor']),
         Paragraph('Status',      st['campo_label']),
         Paragraph(_txt(projeto_row.get('status','')),  st['campo_valor'])],
        [Paragraph('Projetista',  st['campo_label']),
         Paragraph(_txt(projeto_row.get('projetista','')), st['campo_valor']),
         Paragraph('Prioridade',  st['campo_label']),
         Paragraph(_txt(projeto_row.get('prioridade','')), st['campo_valor'])],
        [Paragraph('Solicitante', st['campo_label']),
         Paragraph(_txt(projeto_row.get('solicitante','')), st['campo_valor']),
         Paragraph('Nº SEI',      st['campo_label']),
         Paragraph(_txt(projeto_row.get('numero_sei','')), st['campo_valor'])],
        [Paragraph('Início',      st['campo_label']),
         Paragraph(_data_fmt(projeto_row.get('data_inicio','')), st['campo_valor']),
         Paragraph('Término',     st['campo_label']),
         Paragraph(_data_fmt(projeto_row.get('data_termino', projeto_row.get('data_fim',''))), st['campo_valor'])],
    ]
    t_inf = Table(info_rows, colWidths=[3*cm, w_util/2-3*cm, 3*cm, w_util/2-3*cm])
    t_inf.setStyle(TableStyle([
        ('VALIGN',       (0,0),(-1,-1), 'TOP'),
        ('TOPPADDING',   (0,0),(-1,-1), 4),
        ('BOTTOMPADDING',(0,0),(-1,-1), 4),
        ('LINEBELOW',    (0,0),(-1,-2), 0.3, CINZA_BORDA),
    ]))
    story.append(t_inf)
    story.append(Spacer(1, 0.4*cm))

    _corpo_pdf_diario(
        story, st, w_util, df_diario,
        'Nenhum registro no diário para este projeto.',
    )
    doc.build(story, onFirstPage=_cabecalho_pagina, onLaterPages=_cabecalho_pagina)
    return buf.getvalue()
