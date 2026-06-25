"""Cria ARQUIVOS fake (arquivos REAIS no disco + registros na tabela `arquivos`)
para os projetos do seed, na aba "📁 Arquivos".

Por que é um .py e não SQL: o app guarda o arquivo físico em
`anexos/<id_projeto>/...` e o download lê do disco — uma linha sem o arquivo
mostra "Arquivo perdido ⚠️". Então precisamos CRIAR os arquivos, não só inserir
linhas. Usa as funções do próprio app (mesmos caminhos/validações).

Rodar DEPOIS do seed-dados-teste.sql (precisa dos projetos SP-2026-*):

    cd ~/gestao-de-projetos-servpen
    set -a; . ./db.env.local; set +a
    ./venv/bin/python docs/seed_arquivos.py

É idempotente: remove os arquivos (disco + linha) dos projetos do seed e recria.
"""

from __future__ import annotations

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database as db  # noqa: E402


def _pdf(titulo, linhas):
    """Gera um PDF mínimo VÁLIDO (1 página) — abre normalmente no leitor."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(60, 790, "SERVPEN - " + titulo)
    c.setFont("Helvetica", 11)
    y = 750
    for ln in linhas:
        c.drawString(60, y, ln)
        y -= 22
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(60, 60, "Documento de exemplo (seed de demonstracao).")
    c.showPage()
    c.save()
    return buf.getvalue()


def _csv(linhas):
    return ("\n".join(linhas) + "\n").encode("utf-8")


# {codigo_projeto: [(nome, descricao, autor, bytes), ...]}
ARQUIVOS = {
    "SP-2026-001": [
        ("Memorial-de-calculo-eletrico.pdf",
         "Memorial de cálculo da rede elétrica", "Carla Ribeiro",
         _pdf("Memorial de Calculo Eletrico", [
             "Projeto: Reforma Eletrica - Pavilhao Joao Lyra Filho",
             "Carga total estimada: 138 kVA",
             "Disjuntor geral: 150 A   Cabo: 50 mm2",
             "Responsavel: Eng. Carla Ribeiro - CREA-RJ"])),
        ("Lista-de-materiais.csv",
         "Lista de materiais e quantitativos", "Carla Ribeiro",
         _csv(["item;quantidade;unidade",
               "Disjuntor tripolar 150A;1;un",
               "Cabo 50mm2 (rolo 100m);3;rolo",
               "Eletroduto 2pol;120;m",
               "Quadro de distribuicao 24 div;1;un"])),
    ],
    "SP-2026-002": [
        ("Mapa-de-cameras.pdf",
         "Planta com a locação das câmeras", "Rafael Lima",
         _pdf("Mapa de Cameras - CFTV", [
             "Projeto: Sistema CFTV - Campus Maracana",
             "Total de cameras: 48",
             "Gravacao: NVR 64 canais, 30 dias de retencao"])),
        ("Lista-de-equipamentos.csv",
         "Equipamentos de CFTV", "Rafael Lima",
         _csv(["item;quantidade;unidade",
               "Camera bullet IP67 IR30;20;un",
               "Camera dome IP;28;un",
               "NVR 64 canais;1;un",
               "Switch PoE 24 portas;3;un"])),
    ],
    "SP-2026-003": [
        ("Calculo-carga-termica.pdf",
         "Cálculo de carga térmica das salas", "Patrícia Souza",
         _pdf("Calculo de Carga Termica", [
             "Projeto: Climatizacao HVAC - Biblioteca CTC",
             "Demanda total: 18 TR",
             "Solucao adotada: sistema VRF"])),
    ],
    "SP-2026-005": [
        ("Laudo-aterramento.pdf",
         "Laudo de medição de aterramento", "Carla Ribeiro",
         _pdf("Laudo de Aterramento - SPDA", [
             "Projeto: Projeto SPDA - Bloco F",
             "Resistencia medida: 8 ohms (limite: 10 ohms)",
             "Resultado: APROVADO"])),
        ("ART-SPDA.pdf",
         "ART do projeto SPDA", "Carla Ribeiro",
         _pdf("ART - Projeto SPDA Bloco F", [
             "Anotacao de Responsabilidade Tecnica",
             "Responsavel: Eng. Carla Ribeiro - CREA-RJ",
             "Servico: Projeto e execucao do SPDA"])),
    ],
}

_MIME = {".pdf": "application/pdf", ".csv": "text/csv"}


def _projeto_id(codigo):
    conn = db.conectar(); c = conn.cursor()
    try:
        c.execute("SELECT id FROM projetos WHERE codigo=%s", (codigo,))
        r = c.fetchone()
        return int(r[0]) if r else None
    finally:
        conn.close()


def main():
    db.criar_tabelas()
    criados = 0
    for codigo, arqs in ARQUIVOS.items():
        pid = _projeto_id(codigo)
        if pid is None:
            print(f"  [pulado] projeto {codigo} nao existe — rode o "
                  "seed-dados-teste.sql primeiro.")
            continue
        # Idempotência: remove arquivos anteriores deste projeto (disco + linha).
        for row in db.listar_arquivos(projeto_id=pid):
            db.excluir_arquivo(row[0])
        for nome, desc, autor, conteudo in arqs:
            pasta, path = db.caminho_seguro_para_anexo(pid, nome)
            os.makedirs(pasta, exist_ok=True)
            with open(path, "wb") as f:
                f.write(conteudo)
            ext = os.path.splitext(nome)[1].lower()
            db.salvar_arquivo(
                projeto_id=pid, nome_original=nome, path_arquivo=path,
                descricao=desc, autor=autor, tamanho_bytes=len(conteudo),
                mime_type=_MIME.get(ext, ""),
            )
            criados += 1
            print(f"  OK {codigo}: {nome} ({len(conteudo)} B)")
    print(f"\nTotal de arquivos criados: {criados}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
