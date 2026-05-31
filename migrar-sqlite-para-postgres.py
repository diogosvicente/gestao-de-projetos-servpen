#!/usr/bin/env python3
"""
migrar-sqlite-para-postgres.py — Migra dados de um ou mais bancos SQLite legados
para o PostgreSQL configurado em variáveis de ambiente (DATABASE_URL ou DB_HOST/etc).

Uso:
    python migrar-sqlite-para-postgres.py [arquivo1.db arquivo2.db ...]

Se nenhum arquivo for passado, tenta os defaults: gestao_equipe.db e servpen.db.

Comportamento:
  - Idempotente: usa INSERT ... ON CONFLICT DO NOTHING. Rodar de novo não duplica.
  - Preserva IDs (importante por causa das foreign keys lógicas).
  - Após inserir, avança a sequência de cada tabela pra MAX(id), pra próximos
    INSERTs do app não colidirem.
  - Hashes de senha são copiados como string opaca (SHA-256 atual continua valendo).
  - Reporta contadores por tabela ao final.

Requer: psycopg[binary]>=3.1
Não requer: sqlalchemy, alembic ou qualquer ORM (sqlite3 + psycopg puro).
"""
from __future__ import annotations

import os
import sys
import sqlite3
from pathlib import Path
from typing import Iterable

import psycopg


# Ordem importa: usuarios e projetos primeiro (são referenciados pelas demais)
TABELAS = [
    "usuarios",
    "projetos",
    "diario",
    "chat",
    "agenda",
    "progresso_disciplinas",
    "etapas_projeto",
    "auditoria",
    "arquivos",
    "mencoes_acesso",
    "mencoes_notificacoes",
    "diario_leituras",
    "sessoes",
]


def conectar_pg():
    """Mesma lógica do database.py: DATABASE_URL ou variáveis individuais."""
    url = os.environ.get("DATABASE_URL")
    if url:
        return psycopg.connect(url)
    return psycopg.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", "5432")),
        dbname=os.environ.get("DB_NAME", "gestao_servpen"),
        user=os.environ.get("DB_USER", "gestao_servpen"),
        password=os.environ.get("DB_PASSWORD", ""),
    )


def colunas_sqlite(con_sq: sqlite3.Connection, tabela: str) -> list[str]:
    cur = con_sq.execute(f"PRAGMA table_info({tabela})")
    return [row[1] for row in cur.fetchall()]


def colunas_pg(cur_pg, tabela: str) -> list[str]:
    cur_pg.execute(
        """
        SELECT column_name FROM information_schema.columns
         WHERE table_schema = 'public' AND table_name = %s
         ORDER BY ordinal_position
        """,
        (tabela,),
    )
    return [r[0] for r in cur_pg.fetchall()]


def tem_tabela_sqlite(con_sq: sqlite3.Connection, tabela: str) -> bool:
    cur = con_sq.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (tabela,),
    )
    return cur.fetchone() is not None


def tem_tabela_pg(cur_pg, tabela: str) -> bool:
    cur_pg.execute(
        "SELECT to_regclass('public.' || %s) IS NOT NULL",
        (tabela,),
    )
    return cur_pg.fetchone()[0]


def migrar_tabela(con_sq: sqlite3.Connection, con_pg, tabela: str) -> tuple[int, int]:
    """Retorna (linhas_lidas, linhas_inseridas)."""
    cur_pg = con_pg.cursor()

    if not tem_tabela_sqlite(con_sq, tabela):
        return (0, 0)
    if not tem_tabela_pg(cur_pg, tabela):
        print(f"  [pular]  {tabela}: não existe no Postgres (rode o app uma vez pra criar)")
        return (0, 0)

    cols_sq = colunas_sqlite(con_sq, tabela)
    cols_pg = set(colunas_pg(cur_pg, tabela))
    # Só copia as colunas que existem em ambos (defensivo contra schemas drift)
    cols = [c for c in cols_sq if c in cols_pg]
    if not cols:
        print(f"  [pular]  {tabela}: nenhuma coluna em comum")
        return (0, 0)

    cur_sq = con_sq.execute(f"SELECT {', '.join(cols)} FROM {tabela}")
    linhas = cur_sq.fetchall()
    if not linhas:
        return (0, 0)

    placeholders = ",".join(["%s"] * len(cols))
    cols_sql = ",".join(cols)

    # Se tem 'id', conflict no id. Caso especial pra diario_leituras (sem id, unique composta).
    if "id" in cols:
        conflict_clause = "ON CONFLICT (id) DO NOTHING"
    elif tabela == "diario_leituras":
        conflict_clause = "ON CONFLICT (diario_id, usuario) DO NOTHING"
    elif tabela == "sessoes":
        conflict_clause = "ON CONFLICT (token) DO NOTHING"
    else:
        conflict_clause = "ON CONFLICT DO NOTHING"

    sql = f"INSERT INTO {tabela} ({cols_sql}) VALUES ({placeholders}) {conflict_clause}"

    inseridas = 0
    for linha in linhas:
        try:
            cur_pg.execute(sql, linha)
            inseridas += cur_pg.rowcount or 0
        except psycopg.Error as e:
            con_pg.rollback()
            print(f"    [erro] {tabela} linha {linha[:3]}…: {e}")
            cur_pg = con_pg.cursor()
            continue
    con_pg.commit()

    # Avança sequência pra MAX(id)+1 se a tabela tem id
    if "id" in cols:
        try:
            cur_pg.execute(
                f"""
                SELECT setval(
                    pg_get_serial_sequence('{tabela}', 'id'),
                    COALESCE((SELECT MAX(id) FROM {tabela}), 1),
                    true
                )
                """
            )
            con_pg.commit()
        except psycopg.Error as e:
            con_pg.rollback()
            print(f"    [warn] setval falhou em {tabela}: {e}")

    return (len(linhas), inseridas)


def migrar_arquivo(caminho: Path, con_pg) -> dict[str, tuple[int, int]]:
    print(f"\n=== Migrando {caminho} ===")
    if not caminho.exists():
        print(f"  arquivo não existe, pulando")
        return {}
    con_sq = sqlite3.connect(str(caminho))
    con_sq.row_factory = None  # tuplas mesmo, já é o default
    resultados: dict[str, tuple[int, int]] = {}
    try:
        for tabela in TABELAS:
            lidas, inseridas = migrar_tabela(con_sq, con_pg, tabela)
            if lidas:
                print(f"  {tabela:25s}: {lidas:6d} lidas, {inseridas:6d} novas")
            resultados[tabela] = (lidas, inseridas)
    finally:
        con_sq.close()
    return resultados


def main(argv: list[str]) -> int:
    arquivos: Iterable[Path]
    if len(argv) > 1:
        arquivos = [Path(a) for a in argv[1:]]
    else:
        # Defaults: rodar do diretório do projeto
        defaults = ["gestao_equipe.db", "servpen.db"]
        arquivos = [Path(p) for p in defaults if Path(p).exists()]
        if not arquivos:
            print("Nenhum arquivo SQLite encontrado. Passe os caminhos como argumento.")
            print(f"Uso: {argv[0]} caminho/para/arquivo.db [outro.db ...]")
            return 1

    print(f"Migração SQLite → PostgreSQL")
    print(f"Origens: {[str(a) for a in arquivos]}")
    print(f"Destino: DATABASE_URL ou DB_HOST={os.environ.get('DB_HOST', 'localhost')} "
          f"DB_NAME={os.environ.get('DB_NAME', 'gestao_servpen')}")

    try:
        con_pg = conectar_pg()
    except psycopg.Error as e:
        print(f"\nERRO: não conectou no Postgres: {e}")
        print("Verifique DATABASE_URL ou DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD")
        return 2

    try:
        # IMPORTANTE: o schema do Postgres tem que existir. database.py cria
        # as tabelas no primeiro boot. Se você ainda não rodou o app, rode antes:
        #   python -c "import database as db; db.criar_tabelas()"
        from database import criar_tabelas
        print("\nGarantindo schema no Postgres (criar_tabelas)…")
        criar_tabelas()
    except Exception as e:
        print(f"  [warn] não consegui chamar database.criar_tabelas(): {e}")
        print(f"  Continuando — assumindo que o schema já existe")

    total: dict[str, tuple[int, int]] = {t: (0, 0) for t in TABELAS}
    for arquivo in arquivos:
        resultados = migrar_arquivo(arquivo, con_pg)
        for t, (l, i) in resultados.items():
            tl, ti = total.get(t, (0, 0))
            total[t] = (tl + l, ti + i)

    con_pg.close()

    print("\n=== TOTAL ===")
    for t in TABELAS:
        l, i = total[t]
        if l:
            print(f"  {t:25s}: {l:6d} lidas, {i:6d} novas")
    print("\nMigração concluída.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
