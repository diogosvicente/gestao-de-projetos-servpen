"""
relatorios.py  —  SERVPEN Engenharia
Gera Excel e PDF profissionais usando reportlab + xlsxwriter.
Versão: 1.1 (Correções de renderização de tabelas e quebras de página)
"""

import io
import os
from datetime import datetime, date, timedelta
import unicodedata

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
#  1. EXCEL COMPLETO
# ═════════════════════════════════════════════════════════════
def gerar_excel(df, df_etapas=None, df_progresso=None):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        wb  = writer.book
        fmt_cab = wb.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#003366',
            'border': 1, 'align': 'center', 'valign': 'vcenter',
            'font_size': 10,
        })
        fmt_sub = wb.add_format({
            'bold': True, 'font_color': 'white', 'bg_color': '#0056b3',
            'border': 1, 'align': 'center', 'valign': 'vcenter',
            'font_size': 9,
        })
        fmt_cel = wb.add_format({
            'border': 1, 'valign': 'vcenter', 'font_size': 9,
            'text_wrap': True,
        })
        fmt_alt = wb.add_format({
            'border': 1, 'valign': 'vcenter', 'font_size': 9,
            'bg_color': '#f3f4f6', 'text_wrap': True,
        })
        fmt_pct = wb.add_format({
            'border': 1, 'valign': 'vcenter', 'font_size': 9,
            'num_format': '0"%"',
        })
        fmt_data = wb.add_format({
            'border': 1, 'valign': 'vcenter', 'font_size': 9,
            'num_format': 'dd/mm/yyyy',
        })

        if df is not None and not df.empty:
            ws = wb.add_worksheet('Projetos')
            writer.sheets['Projetos'] = ws

            COLUNAS = [
                ('ID',                 'id',                 6),
                ('Nome do Projeto',    'projeto',            35),
                ('Status',             'status',             14),
                ('Prioridade',         'prioridade',         12),
                ('Projetista(s)',       'projetista',         30),
                ('Solicitante',        'solicitante',        25),
                ('Contato',            'contato',            22),
                ('Endereço',           'endereco',           30),
                ('Nº SEI / Doc.',      'numero_sei',         18),
                ('Recebimento',        'data_recebimento',   14),
                ('Prev. Execução',     'previsao_execucao',  15),
                ('Início',             'data_inicio',        13),
                ('Término',            'data_termino',       13),
                ('Link Drive',         'link_projeto',       30),
                ('Escopo',             'solicitacao',        45),
                ('Disciplinas/Demandas','demandas',          40),
                ('Cadastrado em',      'criado_em',          18),
            ]

            ws.merge_range(0, 0, 0, len(COLUNAS)-1,
                           'SERVPEN — Relatório de Projetos  |  '
                           + datetime.now().strftime('%d/%m/%Y %H:%M'),
                           wb.add_format({
                               'bold': True, 'font_color': 'white',
                               'bg_color': '#003366', 'font_size': 12,
                               'align': 'center', 'valign': 'vcenter',
                           }))
            ws.set_row(0, 22)

            for col_i, (label, _, larg) in enumerate(COLUNAS):
                ws.write(1, col_i, label, fmt_cab)
                ws.set_column(col_i, col_i, larg)
            ws.set_row(1, 18)

            CAMPOS_DATA = {'data_recebimento', 'previsao_execucao',
                           'data_inicio', 'data_termino', 'criado_em'}
            for row_i, (_, row) in enumerate(df.iterrows()):
                fmt_row = fmt_alt if row_i % 2 == 0 else fmt_cel
                for col_i, (_, campo, _) in enumerate(COLUNAS):
                    val = row.get(campo, '')
                    val = '' if str(val) in ('None', 'nan', 'NaT') else val
                    f   = fmt_data if campo in CAMPOS_DATA else fmt_row
                    ws.write(row_i + 2, col_i, val, f)

            ws.autofilter(1, 0, 1 + len(df), len(COLUNAS) - 1)
            ws.freeze_panes(2, 0)

        if df_etapas is not None and not df_etapas.empty:
            ws2 = wb.add_worksheet('Etapas')
            writer.sheets['Etapas'] = ws2
            ws2.merge_range(0, 0, 0, 5, 'SERVPEN — Etapas dos Projetos', fmt_sub)
            ws2.set_row(0, 20)
            cab_et = ['Projeto', 'Ordem', 'Nome da Etapa',
                      'Início (dias offset)', 'Duração (dias)', 'Fim estimado (dias)']
            for i, c in enumerate(cab_et):
                ws2.write(1, i, c, fmt_cab)
            ws2.set_column(0, 0, 32); ws2.set_column(2, 2, 28)
            ws2.set_column(1, 1, 8);  ws2.set_column(3, 5, 18)
            for ri, (_, r) in enumerate(df_etapas.iterrows()):
                fmt_r = fmt_alt if ri % 2 == 0 else fmt_cel
                fim_d = int(r.get('dias_offset', 0)) + int(r.get('duracao_dias', 0)) - 1
                ws2.write(ri+2, 0, _txt(r.get('projeto','')), fmt_r)
                ws2.write(ri+2, 1, int(r.get('ordem', 0))+1, fmt_r)
                ws2.write(ri+2, 2, _txt(r.get('nome','')), fmt_r)
                ws2.write(ri+2, 3, int(r.get('dias_offset', 0)), fmt_r)
                ws2.write(ri+2, 4, int(r.get('duracao_dias', 0)), fmt_r)
                ws2.write(ri+2, 5, fim_d, fmt_r)

        if df_progresso is not None and not df_progresso.empty:
            ws3 = wb.add_worksheet('Progresso Técnico')
            writer.sheets['Progresso Técnico'] = ws3
            ws3.merge_range(0, 0, 0, 3, 'SERVPEN — Progresso por Disciplina', fmt_sub)
            ws3.set_row(0, 20)
            cab_pr = ['Projeto', 'Disciplina', 'Concluído', 'Percentual (%)']
            for i, c in enumerate(cab_pr):
                ws3.write(1, i, c, fmt_cab)
            ws3.set_column(0, 0, 32); ws3.set_column(1, 1, 24)
            ws3.set_column(2, 2, 12); ws3.set_column(3, 3, 16)
            for ri, (_, r) in enumerate(df_progresso.iterrows()):
                fmt_r = fmt_alt if ri % 2 == 0 else fmt_cel
                ws3.write(ri+2, 0, _txt(r.get('projeto','')), fmt_r)
                ws3.write(ri+2, 1, _txt(r.get('disciplina','')), fmt_r)
                ws3.write(ri+2, 2, 'Sim' if r.get('concluido') else 'Não', fmt_r)
                ws3.write(ri+2, 3, int(r.get('percentual', 0)), fmt_pct)

    return output.getvalue()


# ═════════════════════════════════════════════════════════════
#  2. PDF COMPLETO
# ═════════════════════════════════════════════════════════════
def gerar_pdf(df, df_etapas=None, df_progresso=None):
    # ── SOLUÇÃO CONTRA DUPLICIDADE: HIGIENIZAÇÃO DE ÍNDICES E COLUNAS ──
    if df is not None:
        df = df.copy().reset_index(drop=True)
        df = df.loc[:, ~df.columns.duplicated()]
    if df_etapas is not None:
        df_etapas = df_etapas.copy().reset_index(drop=True)
        df_etapas = df_etapas.loc[:, ~df_etapas.columns.duplicated()]
        for col_conflito in ['projeto', 'status', 'prioridade', 'projetista']:
            if col_conflito in df_etapas.columns:
                df_etapas = df_etapas.drop(columns=[col_conflito])
    if df_progresso is not None:
        df_progresso = df_progresso.copy().reset_index(drop=True)
        df_progresso = df_progresso.loc[:, ~df_progresso.columns.duplicated()]
        for col_conflito in ['projeto', 'status', 'prioridade', 'projetista']:
            if col_conflito in df_progresso.columns:
                df_progresso = df_progresso.drop(columns=[col_conflito])

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

    def _hr():
        return HRFlowable(width='100%', thickness=0.5,
                          color=CINZA_BORDA, spaceAfter=6, spaceBefore=6)

    def _secao(txt):
        return Paragraph(f'<b>{txt}</b>', st['secao'])

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
                Paragraph(_txt(s), st['celula']),
                Paragraph(str(n), st['celula']),
            ])
        tot_rows.append([
            Paragraph('<b>TOTAL</b>', st['cabecalho_tab']),
            Paragraph(f'<b>{len(df)}</b>', st['cabecalho_tab']),
        ])
        t_tot = Table(tot_rows, colWidths=[w_util*0.6, w_util*0.4])
        t_tot.setStyle(_tabela_estilo(2))
        story.append(_secao('📊 Resumo Executivo'))
        story.append(t_tot)
        story.append(Spacer(1, 0.4*cm))

        # 📋 TABELA INICIAL AJUSTADA: APENAS OS 6 CAMPOS SOLICITADOS
        story.append(_secao('📋 Relação Geral de Empreendimentos'))
        
        dem_rows = [[
            Paragraph('<b>ID</b>', st['cabecalho_tab']),
            Paragraph('<b>NOME DO PROJETO</b>', st['cabecalho_tab']),
            Paragraph('<b>PROJETISTA</b>', st['cabecalho_tab']),
            Paragraph('<b>ENDEREÇO DA OBRA</b>', st['cabecalho_tab']),
            Paragraph('<b>STATUS</b>', st['cabecalho_tab']),
            Paragraph('<b>RECEBIMENTO</b>', st['cabecalho_tab']),
        ]]
        
        for _, proj in df.iterrows():
            dem_rows.append([
                Paragraph(str(proj.get('id', '—')), st['celula']),
                Paragraph(f"<b>{_txt(proj['projeto'])}</b>", st['celula']),
                Paragraph(_txt(proj.get('projetista', '—')), st['celula']),
                Paragraph(_txt(proj.get('endereco', '—')), st['celula']),
                Paragraph(_txt(proj.get('status', '—')), st['celula']),
                Paragraph(_data_fmt(proj.get('data_recebimento', ''))),
            ])
            
        # Distribuição milimétrica das colunas para os 18cm úteis da página retrato
        # ID(1.0cm), Nome(4.5cm), Projetista(2.5cm), Endereço(4.5cm), Status(2.5cm), Recebimento(3.0cm)
        larguras_colunas = [
            1.0 * cm, 4.5 * cm, 2.5 * cm, 4.5 * cm, 2.5 * cm, 3.0 * cm
        ]
        
        t_dem = Table(dem_rows, colWidths=larguras_colunas)
        t_dem.setStyle(_tabela_estilo(6))
        story.append(t_dem)
        story.append(Spacer(1, 0.5 * cm))

    # 🔎 DETALHAMENTO DOS TÓPICOS DOS PROJETOS (ENUMERADOS)
    if df is not None and not df.empty:
        for row_idx, (_, proj) in enumerate(df.iterrows()):
            story.append(PageBreak())

            cor_st = COR_STATUS.get(str(proj.get('status','')), AZUL_MEDIO)
            cor_pr = COR_PRIORIDADE.get(str(proj.get('prioridade','')), AZUL_CLARO)

            st_hdr_proj = ParagraphStyle('HdrProj', fontName='Helvetica-Bold', fontSize=13, textColor=BRANCO, leading=16)
            st_hdr_status = ParagraphStyle('HdrStat', fontName='Helvetica-Bold', fontSize=8, textColor=BRANCO, alignment=TA_CENTER, leading=10)
            st_hdr_prio = ParagraphStyle('HdrPrio', fontName='Helvetica-Bold', fontSize=8, textColor=BRANCO, alignment=TA_CENTER, leading=10)

            num_projeto_txt = f"{row_idx + 1}. {proj['projeto']}"

            hdr = Table([[
                Paragraph(f'<b>{_txt(num_projeto_txt)}</b>', st_hdr_proj),
                Table([[
                    Paragraph(_txt(proj.get('status','—')), st_hdr_status),
                    Paragraph(_txt(proj.get('prioridade','—')), st_hdr_prio),
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

            def _par_campos(pares):
                rows = []
                for i in range(0, len(pares), 2):
                    left  = pares[i]
                    right = pares[i+1] if i+1 < len(pares) else ('', '')
                    rows.append([
                        Paragraph(left[0],  st['campo_label']),
                        Paragraph(_txt(left[1]),  st['campo_valor']),
                        Paragraph(right[0], st['campo_label']),
                        Paragraph(_txt(right[1]), st['campo_valor']),
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

            story.append(_secao('Identificação'))
            story.append(_par_campos([
                ('Nº SEI / Documento',   proj.get('numero_sei','')),
                ('Projetista(s)',         proj.get('projetista','')),
                ('Solicitante / Cliente', proj.get('solicitante','')),
                ('Contato',               proj.get('contato','')),
                ('Endereço da Obra',     proj.get('endereco','')),
                ('Link da Pasta',        proj.get('link_projeto','')),
            ]))
            story.append(Spacer(1, 0.2*cm))

            story.append(_secao('Cronograma'))
            story.append(_par_campos([
                ('Data de Recebimento',    _data_fmt(proj.get('data_recebimento',''))),
                ('Prev. Início Execução',  _data_fmt(proj.get('previsao_execucao',''))),
                ('Data de Início',         _data_fmt(proj.get('data_inicio',''))),
                ('Data de Término',        _data_fmt(proj.get('data_termino', proj.get('data_fim','')))),
            ]))
            story.append(Spacer(1, 0.2*cm))

            esc = _txt(proj.get('solicitacao',''))
            if esc != '—':
                story.append(_secao('Escopo / Descrição'))
                story.append(Paragraph(esc, st['corpo']))
                story.append(Spacer(1, 0.15*cm))

            dem_ind = _txt(proj.get('demandas',''))
            if dem_ind != '—':
                story.append(_secao('Disciplinas e Demandas Detalhadas'))
                story.append(Paragraph(dem_ind, st['corpo']))
                story.append(Spacer(1, 0.15*cm))

            proj_id = proj.get('id')
            if df_etapas is not None and not df_etapas.empty and proj_id is not None:
                et_proj = df_etapas[df_etapas['projeto_id'] == proj_id] if 'projeto_id' in df_etapas.columns else pd.DataFrame()
                if not et_proj.empty:
                    story.append(_secao('Etapas do Projeto'))
                    et_rows = [[
                        Paragraph('Ord.', st['cabecalho_tab']),
                        Paragraph('Etapa', st['cabecalho_tab']),
                        Paragraph('Início (dias)', st['cabecalho_tab']),
                        Paragraph('Duração (dias)', st['cabecalho_tab']),
                        Paragraph('Fim (dias)', st['cabecalho_tab']),
                    ]]
                    for _, e in et_proj.iterrows():
                        fim = int(e.get('dias_offset',0)) + int(e.get('duracao_dias',0)) - 1
                        et_rows.append([
                            Paragraph(str(int(e.get('ordem',0))+1), st['celula']),
                            Paragraph(_txt(e.get('nome','')), st['celula']),
                            Paragraph(str(int(e.get('dias_offset',0))), st['celula']),
                            Paragraph(str(int(e.get('duracao_dias',0))), st['celula']),
                            Paragraph(str(fim), st['celula']),
                        ])
                    t_et = Table(et_rows, colWidths=[1*cm, w_util-10*cm, 2.8*cm, 2.8*cm, 2.8*cm])
                    t_et.setStyle(_tabela_estilo(5))
                    story.append(t_et)
                    story.append(Spacer(1, 0.2*cm))

            if df_progresso is not None and not df_progresso.empty and proj_id is not None:
                pg_proj = df_progresso[df_progresso['projeto_id'] == proj_id] if 'projeto_id' in df_progresso.columns else pd.DataFrame()
                if not pg_proj.empty:
                    story.append(_secao('Evolução Técnica por Disciplina'))
                    pg_rows = [[
                        Paragraph('Disciplina', st['cabecalho_tab']),
                        Paragraph('Progresso', st['cabecalho_tab']),
                        Paragraph('Concluída', st['cabecalho_tab']),
                    ]]
                    for _, pg in pg_proj.iterrows():
                        pct_val = int(pg.get('percentual', 0))
                        conc    = '✔ Sim' if pg.get('concluido') else '✗ Não'
                        pg_rows.append([
                            Paragraph(_txt(pg.get('disciplina','')), st['celula']),
                            Paragraph(f'{pct_val}%', st['celula']),
                            Paragraph(conc, st['celula']),
                        ])
                    t_pg = Table(pg_rows, colWidths=[w_util*0.5, w_util*0.25, w_util*0.25])
                    t_pg.setStyle(_tabela_estilo(3))
                    story.append(t_pg)

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

    def _hr():
        return HRFlowable(width='100%', thickness=0.5,
                          color=CINZA_BORDA, spaceAfter=4, spaceBefore=4)

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

    if df_diario is None or df_diario.empty:
        story.append(Paragraph('Nenhum registro no diário para este projeto.', st['corpo']))
        doc.build(story, onFirstPage=_cabecalho_pagina, onLaterPages=_cabecalho_pagina)
        return buf.getvalue()

    # Resumo numérico
    n_relatos    = len(df_diario[~df_diario['executado'].astype(str).str.contains('Impedimento|Dúvida|❓|🛑', na=False)])
    n_duvidas    = len(df_diario[df_diario['executado'].astype(str).str.contains('Dúvida|❓', na=False)])
    n_impedim    = len(df_diario[df_diario['executado'].astype(str).str.contains('Impedimento|🛑', na=False)])
    n_resolvidos = len(df_diario[df_diario['resolvido'] == 1])

    res_rows = [[
        Paragraph('Relatos', st['cabecalho_tab']),
        Paragraph('Dúvidas', st['cabecalho_tab']),
        Paragraph('Impedimentos', st['cabecalho_tab']),
        Paragraph('Resolvidos', st['cabecalho_tab']),
        Paragraph('Total', st['cabecalho_tab']),
    ], [
        Paragraph(str(n_relatos),      st['celula']),
        Paragraph(str(n_duvidas),      st['celula']),
        Paragraph(str(n_impedim),      st['celula']),
        Paragraph(str(n_resolvidos),   st['celula']),
        Paragraph(str(len(df_diario)), st['celula']),
    ]]
    t_res = Table(res_rows, colWidths=[w_util/5]*5)
    t_res.setStyle(_tabela_estilo(5))
    story.append(Paragraph('<b>Resumo do Histórico</b>', st['secao']))
    story.append(t_res)
    story.append(Spacer(1, 0.5*cm))

    story.append(Paragraph('<b>Histórico Completo — ordem cronológica</b>', st['secao']))
    story.append(_hr())

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

        # Cabeçalho de cada entrada do diário
        cab_d = Table([[
            Paragraph(f'<b>#{i+1} — {tipo_str}</b>', st_diario_hdr_l),
            Paragraph(f'<font size="8">{_txt(reg.get("disciplina","Geral"))}  ·  Por: {_txt(reg.get("autor",""))}  ·  {_txt(reg.get("data",""))}</font>', st_diario_hdr_r),
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
        story.append(_hr())

    doc.build(story, onFirstPage=_cabecalho_pagina, onLaterPages=_cabecalho_pagina)
    return buf.getvalue()