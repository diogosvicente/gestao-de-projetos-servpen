#!/usr/bin/env python3
"""
SERVPEN - Populador de dados realistas.

Mantem usuarios cadastrados. Apaga projetos/arquivos/diario/agenda/progresso atuais e
recria com cenarios verossimies de engenharia.

Rodar no servidor:
    sudo systemctl stop gestao-de-projetos
    sudo -u www-data /var/www/html/gestao_de_projetos/venv/bin/python /var/www/html/gestao_de_projetos/seed.py
    sudo systemctl start gestao-de-projetos
"""

import sqlite3
import os
import shutil
import random
import time
from datetime import datetime, timedelta

APP_DIR = '/var/www/html/gestao_de_projetos'
DB_EQUIPE = os.path.join(APP_DIR, 'gestao_equipe.db')
DB_SERVPEN = os.path.join(APP_DIR, 'servpen.db')
PASTA_ANEXOS = os.path.join(APP_DIR, 'anexos')

random.seed(42)  # determinismo

# -------------------- BACKUP --------------------
def backup_dbs():
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    pasta = os.path.join(APP_DIR, 'backups')
    os.makedirs(pasta, exist_ok=True)
    for db in (DB_EQUIPE, DB_SERVPEN):
        if os.path.exists(db):
            dst = os.path.join(pasta, f"{os.path.basename(db)}.{ts}.pre-seed.bak")
            shutil.copy2(db, dst)
            print(f"  backup: {dst}")

# -------------------- LIMPEZA --------------------
def limpar():
    print("==> Limpando projetos, arquivos, diario, agenda, progresso...")

    # gestao_equipe.db: projetos, diario, arquivos (mantem usuarios, sessoes, chat, auditoria)
    conn = sqlite3.connect(DB_EQUIPE); c = conn.cursor()
    for tab in ('projetos', 'diario', 'arquivos'):
        c.execute(f"DELETE FROM {tab}")
        c.execute("DELETE FROM sqlite_sequence WHERE name = ?", (tab,))
    conn.commit(); conn.close()

    # servpen.db: agenda, progresso_disciplinas
    conn = sqlite3.connect(DB_SERVPEN); c = conn.cursor()
    for tab in ('agenda', 'progresso_disciplinas'):
        try:
            c.execute(f"DELETE FROM {tab}")
            c.execute("DELETE FROM sqlite_sequence WHERE name = ?", (tab,))
        except sqlite3.OperationalError:
            pass
    conn.commit(); conn.close()

    # Anexos no disco
    if os.path.exists(PASTA_ANEXOS):
        for nome in os.listdir(PASTA_ANEXOS):
            sub = os.path.join(PASTA_ANEXOS, nome)
            if os.path.isdir(sub):
                shutil.rmtree(sub)
    os.makedirs(PASTA_ANEXOS, exist_ok=True)
    print("  OK")

# -------------------- DADOS SEMENTE --------------------
# Cada projeto: (nome, endereco, solicitante, contato, projetistas[],
#                data_pedido, data_inicio, data_fim, status, prioridade,
#                disciplinas[], link, escopo)
def hoje_mais(d):
    return (datetime.now() + timedelta(days=d)).strftime('%Y-%m-%d')

PROJETOS = [
    (
        "Edifício Residencial Vila Mariana",
        "Rua Vila Mariana, 250 - Tijuca, Rio de Janeiro/RJ",
        "Construtora Verde Vida Ltda",
        "(21) 99876-5432 | verdevida@construtora.com.br",
        ["Rodrigo", "Sara Borges"],
        hoje_mais(-30), hoje_mais(-20), hoje_mais(120),
        "Ativo", "Máxima",
        ["Elétrica", "Hidráulica", "Incêndio", "Estrutural", "HVAC"],
        "https://drive.google.com/drive/folders/seed-vilamariana",
        ("Projeto completo de instalações para edifício residencial de 12 pavimentos + "
         "subsolo e cobertura. 48 unidades habitacionais, 96 vagas de garagem. "
         "Inclui memoriais descritivos, plantas e ART de cada disciplina."),
    ),
    (
        "Reforma Centro Cirúrgico HUPE",
        "Hospital Universitário Pedro Ernesto - Bloco A, 4º andar",
        "Hospital Universitário Pedro Ernesto",
        "(21) 2868-8000 | engenharia@hupe.uerj.br",
        ["Leticia", "Sara Borges"],
        hoje_mais(-60), hoje_mais(-50), hoje_mais(45),
        "Ativo", "Máxima",
        ["Elétrica", "HVAC", "Gases Medicinais", "Incêndio"],
        "https://drive.google.com/drive/folders/seed-hupe-cc",
        ("Adequação completa de 6 salas cirúrgicas conforme RDC ANVISA 50. "
         "Substituição de painéis elétricos com no-break, rede de gases medicinais "
         "(O₂, ar comprimido medicinal, vácuo, N₂O), HVAC com classe ISO 7 e "
         "sistema de detecção de fumaça redundante."),
    ),
    (
        "Substituição QGBT Faculdade de Direito UERJ",
        "Av. São Francisco Xavier, 524 - Maracanã, Rio de Janeiro/RJ",
        "PROPLAN/UERJ - Coordenadoria de Obras",
        "(21) 2334-0270 | proplan@uerj.br",
        ["Rodrigo"],
        hoje_mais(-15), hoje_mais(-5), hoje_mais(90),
        "Ativo", "Média",
        ["Elétrica"],
        "https://drive.google.com/drive/folders/seed-direito-qgbt",
        ("Substituição do Quadro Geral de Baixa Tensão (QGBT) da Faculdade de Direito, "
         "incluindo proteções DR, DPS classe II, supervisão de demanda e novo cabeamento "
         "de prumadas verticais. Carga atual: 380 kVA."),
    ),
    (
        "Galpão Industrial Duque de Caxias",
        "Rod. Washington Luís, km 105 - Duque de Caxias/RJ",
        "InduMetal Indústria e Comércio S/A",
        "(21) 3344-5566 | obras@indumetal.com",
        ["Test Dev 1", "diogo"],
        hoje_mais(-90), hoje_mais(-75), hoje_mais(30),
        "🛑 Parado", "Média",
        ["Elétrica", "Hidráulica", "Estrutural"],
        "https://drive.google.com/drive/folders/seed-indumetal",
        ("Galpão industrial de 4.800 m² para fabricação de estruturas metálicas. "
         "Pé-direito 12m, ponte rolante 10t. ATENÇÃO: projeto pausado aguardando "
         "definição do cliente sobre ampliação do mezanino administrativo."),
    ),
    (
        "Sistema Hidráulico Bloco F - UERJ",
        "Campus Maracanã, Bloco F - 8º andar",
        "UERJ - Departamento de Engenharia",
        "(21) 2334-0270 | engenharia@uerj.br",
        ["Leticia"],
        hoje_mais(-180), hoje_mais(-165), hoje_mais(-30),
        "Concluído", "Média",
        ["Hidráulica", "Incêndio"],
        "https://drive.google.com/drive/folders/seed-blocof-hidro",
        ("Substituição completa da prumada hidráulica do Bloco F (8 pavimentos), "
         "novo barrilete em cobertura, hidrantes de parede em todos os pavimentos. "
         "OBRA ENTREGUE e AS BUILT consolidado."),
    ),
    (
        "Subestação Abaixadora 13.8kV - Maracanã",
        "Pavilhão João Lyra Filho - Subsolo técnico",
        "UERJ - Reitoria",
        "(21) 2334-0270 | reitoria@uerj.br",
        ["Rodrigo", "Sara Borges"],
        hoje_mais(-20), hoje_mais(-10), hoje_mais(180),
        "Ativo", "Máxima",
        ["Elétrica"],
        "https://drive.google.com/drive/folders/seed-subestacao-mrc",
        ("Subestação abaixadora 13.8 kV / 380-220 V, potência 1500 kVA, dois "
         "transformadores a seco em paralelo. Inclui projeto de aterramento, "
         "para-raios, malha de equipotencialização e SPCI da casa de máquinas."),
    ),
    (
        "Projeto de Acessibilidade Pavilhão Reitor",
        "Pavilhão Reitor João Lyra Filho - Térreo e 1º pavto.",
        "UERJ - Acessibilidade",
        "(21) 2334-0270 | acessibilidade@uerj.br",
        ["diogo"],
        hoje_mais(-10), hoje_mais(-3), hoje_mais(60),
        "Ativo", "Mínima",
        ["Estrutural", "Hidráulica"],
        "https://drive.google.com/drive/folders/seed-acessibilidade",
        ("Adequação de circulações, rampas e sanitários PCD conforme NBR 9050. "
         "Inclui novo elevador acessível no fosso técnico existente."),
    ),
    (
        "Modernização Climatização CT-UERJ",
        "Centro de Tecnologia - Campus Maracanã, 3º pavto.",
        "UERJ - Centro de Tecnologia",
        "(21) 2334-0270 | ct@uerj.br",
        ["Sara Borges", "Leticia"],
        hoje_mais(-120), hoje_mais(-100), hoje_mais(-60),
        "Cancelado", "Média",
        ["HVAC", "Elétrica"],
        "",
        ("Modernização do sistema central de climatização do CT (chillers + AHUs). "
         "PROJETO CANCELADO em comum acordo com o cliente por falta de orçamento — "
         "será reapresentado no ciclo orçamentário de 2027."),
    ),
]

# Arquivos fake (1KB) por projeto - cada item: (nome, descricao)
def gerar_arquivos_de(prj_idx, demandas):
    base = [
        ("Memorial_Descritivo_v3.pdf", "Memorial técnico consolidado"),
        ("Cronograma_Fisico_Financeiro.xlsx", "Cronograma com curva S"),
        ("ART_Coordenacao.pdf", "ART de coordenação geral - CREA-RJ"),
    ]
    extras = {
        "Elétrica":      [("Planta_Eletrica_Pav_Tipo.dwg", "Planta baixa - Pav. Tipo"),
                          ("Diagrama_Unifilar.dwg", "Diagrama unifilar geral"),
                          ("Quadro_Cargas.xlsx", "Levantamento de cargas")],
        "Hidráulica":    [("Planta_Hidraulica.dwg", "Rede de água fria/quente/esgoto"),
                          ("Isometrico_Barrilete.dwg", "Detalhe isométrico do barrilete")],
        "Incêndio":      [("Planta_SPDA.dwg", "Sistema de Proteção contra Descargas Atmosféricas"),
                          ("Rota_Fuga_Pav_Tipo.dwg", "Rotas de fuga e sinalização")],
        "Estrutural":    [("Planta_Forma.dwg", "Planta de fôrma"),
                          ("Quantitativo_Aco.xlsx", "Aço CA-50/CA-60")],
        "HVAC":          [("Layout_Dutos.dwg", "Layout de dutos e difusores"),
                          ("Memorial_Termico.docx", "Cálculo de carga térmica")],
        "Gases Medicinais": [("Rede_Gases_Medicinais.dwg", "Rede O₂/Ar/Vácuo/N₂O")],
    }
    arquivos = list(base)
    for disc in demandas[:3]:  # pega até 3 disciplinas
        arquivos.extend(extras.get(disc, []))
    # Adiciona algumas fotos/zips para parecer real
    if prj_idx % 2 == 0:
        arquivos.append((f"Foto_Visita_{prj_idx:02d}_001.jpg", "Foto da visita técnica"))
        arquivos.append((f"Foto_Visita_{prj_idx:02d}_002.jpg", "Foto da visita técnica"))
    arquivos.append(("As_Built_Versao_Inicial.zip", "Pacote de entregas iniciais"))
    return arquivos

# Algumas frases para relatos no Diário
RELATOS = [
    ("[Relato de Atividade] Visita técnica realizada. Identificadas inconsistências entre o projeto antigo e o estado atual.", 0),
    ("[Relato de Atividade] Compatibilização entre disciplinas concluída. Encaminhado para revisão final.", 1),
    ("[❓ Dúvida Técnica] Cliente solicitou avaliar troca de tubulação PEAD por PPR. Qual orientação?", 0),
    ("[🛑 Impedimento] Falta liberação da NBR-13714 atualizada por parte do solicitante.", 0),
    ("[Relato de Atividade] Cálculo de demanda elétrica revisado, pico ajustado para 380kVA com fator de simultaneidade 0,72.", 1),
    ("[Relato de Atividade] Reunião de alinhamento com fiscalização. Definidos próximos prazos.", 1),
]

# Agenda
EVENTOS_AGENDA = [
    ("Visita Técnica HUPE - levantamento", "Visita Técnica", -3, -3, ["Leticia", "Sara Borges"], "Levantamento de canalizações existentes no pavimento técnico"),
    ("Reunião de alinhamento - Vila Mariana", "Reunião", 7, 7, ["Rodrigo", "Sara Borges"], "Apresentação dos memoriais ao cliente"),
    ("Apresentação UERJ - Subestação Maracanã", "Reunião", 14, 14, ["Rodrigo", "Sara Borges"], "Aprovação do diagrama unifilar pela PROPLAN"),
    ("Férias - Leticia", "Férias", 30, 44, ["Leticia"], "Férias regulamentares - 15 dias"),
    ("Visita Técnica - Subestação 13.8kV", "Visita Técnica", 21, 21, ["Rodrigo"], "Inspeção do local de instalação dos transformadores"),
    ("Licença Médica - Test Dev 1", "Licença", -7, -1, ["Test Dev 1"], "Atestado médico de 7 dias"),
    ("Folga - Diogo Cardoso", "Folga", 5, 5, ["diogo"], "Compensação de banco de horas"),
]

# -------------------- INSERCAO --------------------
def inserir():
    print("==> Inserindo projetos e dados relacionados...")

    conn_eq = sqlite3.connect(DB_EQUIPE)
    conn_sp = sqlite3.connect(DB_SERVPEN)
    c_eq = conn_eq.cursor()
    c_sp = conn_sp.cursor()

    for i, prj in enumerate(PROJETOS, start=1):
        (nome, endereco, solicit, contato, projetistas, dt_ped, dt_ini, dt_fim,
         status, prioridade, demandas, link, escopo) = prj
        projetista_str = ", ".join(projetistas)
        demandas_str = ", ".join(demandas)

        c_eq.execute('''INSERT INTO projetos
            (projetista, projeto, endereco, solicitante, contato,
             data_pedido, previsao_execucao, data_inicio, data_fim,
             status, link_projeto, demandas, solicitacao, prioridade)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (projetista_str, nome, endereco, solicit, contato,
             dt_ped, dt_ini, dt_ini, dt_fim,
             status, link, demandas_str, escopo, prioridade))
        prj_id = c_eq.lastrowid

        # progresso por disciplina - varia por status
        for disc in demandas:
            if status == "Concluído":
                pct = 100; conc = 1
            elif status == "Cancelado":
                pct = random.randint(20, 60); conc = 0
            elif status == "🛑 Parado":
                pct = random.randint(35, 75); conc = 0
            else:  # Ativo
                pct = random.randint(10, 85); conc = 1 if pct == 100 else 0
            c_sp.execute('''INSERT INTO progresso_disciplinas
                (projeto_id, disciplina, concluido, percentual) VALUES (?,?,?,?)''',
                (prj_id, disc, conc, pct))

        # arquivos fake (1 KB cada, conteudo lixo)
        pasta_prj = os.path.join(PASTA_ANEXOS, str(prj_id))
        os.makedirs(pasta_prj, exist_ok=True)
        for nome_arq, desc_arq in gerar_arquivos_de(i, demandas):
            ts = (datetime.now() - timedelta(days=random.randint(1, 30))).strftime('%Y%m%d_%H%M%S')
            path_fisico = os.path.join(pasta_prj, f"{ts}_{nome_arq}")
            # gera ~1024 bytes de conteudo arbitrario
            with open(path_fisico, 'wb') as f:
                f.write(f"FAKE - {nome_arq} - Projeto: {nome}\n".encode('utf-8'))
                f.write(os.urandom(900))
            tamanho = os.path.getsize(path_fisico)
            autor = random.choice(projetistas)
            c_eq.execute('''INSERT INTO arquivos
                (projeto_id, nome_original, path_arquivo, descricao, autor, tamanho_bytes, mime_type)
                VALUES (?,?,?,?,?,?,?)''',
                (prj_id, nome_arq, path_fisico, desc_arq, autor, tamanho, ''))

        # 2-3 relatos no diario
        for _ in range(random.randint(2, 3)):
            relato, resolvido = random.choice(RELATOS)
            disc = random.choice(demandas)
            data_relato = (datetime.now() - timedelta(days=random.randint(1, 60))).strftime('%d/%m/%Y')
            autor = random.choice(projetistas)
            resposta = ""
            if resolvido or random.random() < 0.4:
                resposta = "Orientação acolhida. Seguir conforme alinhado em reunião."
            c_eq.execute('''INSERT INTO diario
                (projeto_id, data, executado, autor, disciplina, horas, anexo,
                 resposta_gestor, resolvido)
                VALUES (?,?,?,?,?,?,?,?,?)''',
                (prj_id, data_relato, relato, autor, disc, 0, '', resposta, resolvido))

        print(f"  [{prj_id:2}] {status:12} {prioridade:7} {nome}")

    # Agenda
    print("==> Inserindo eventos na agenda...")
    for titulo, tipo, off_ini, off_fim, resps, desc in EVENTOS_AGENDA:
        d_ini = hoje_mais(off_ini)
        d_fim = hoje_mais(off_fim)
        c_sp.execute('''INSERT INTO agenda
            (titulo, tipo, data_inicio, data_fim, responsaveis, descricao)
            VALUES (?,?,?,?,?,?)''',
            (titulo, tipo, d_ini, d_fim, ", ".join(resps), desc))

    conn_eq.commit(); conn_sp.commit()
    conn_eq.close(); conn_sp.close()
    print("  OK")

def auditoria_seed():
    """Loga no audit log que o seed rodou."""
    try:
        conn = sqlite3.connect(DB_EQUIPE); c = conn.cursor()
        c.execute('''INSERT INTO auditoria (usuario, acao, entidade, detalhes)
                     VALUES (?,?,?,?)''',
                  ('seed.py', 'seed_dados', 'sistema',
                   f"{len(PROJETOS)} projetos, {len(EVENTOS_AGENDA)} eventos de agenda inseridos"))
        conn.commit(); conn.close()
    except Exception as e:
        print(f"  (audit log skip: {e})")

# -------------------- MAIN --------------------
if __name__ == '__main__':
    print(f"SERVPEN seed - {datetime.now().isoformat(timespec='seconds')}")
    print("==> Backup dos bancos antes de mexer...")
    backup_dbs()
    limpar()
    inserir()
    auditoria_seed()
    print("\n✅ Pronto. Faca:")
    print("   sudo chown -R www-data:www-data /var/www/html/gestao_de_projetos/anexos")
    print("   sudo systemctl restart gestao-de-projetos")
