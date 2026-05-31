"""database.py — camada de acesso ao PostgreSQL.

Migrado do SQLite. Conexão via env vars:
  - DATABASE_URL=postgresql://user:pass@host:port/dbname   (preferida)
ou individualmente:
  - DB_HOST=localhost
  - DB_PORT=5432
  - DB_NAME=gestao_servpen
  - DB_USER=gestao_servpen
  - DB_PASSWORD=...

O caller é responsável por commit() e close() (ou usar `with conn:`).
"""

import logging
import psycopg
import hashlib
import secrets
import time
import os
from functools import lru_cache
from urllib.parse import quote_plus

from passlib.hash import bcrypt as _bcrypt
from sqlalchemy import create_engine


# ─── LOGGER ─────────────────────────────────────────────────
# Logger nomeado pelo módulo. Configuração global (nível, formato, handler)
# fica em `app.py` no boot — aqui só usamos.
log = logging.getLogger(__name__)


# ─── CONEXÃO ──────────────────────────────────────────────
def conectar():
    """Abre uma nova conexão Postgres (psycopg3).

    Use para cursor manual em INSERT/UPDATE/DELETE. Para SELECT com
    pandas (`pd.read_sql_query`), prefira `get_engine()` — evita warning
    do pandas e reusa conexões do pool.
    """
    url = os.environ.get('DATABASE_URL')
    if url:
        return psycopg.connect(url)
    return psycopg.connect(
        host=os.environ.get('DB_HOST', 'localhost'),
        port=int(os.environ.get('DB_PORT', '5432')),
        dbname=os.environ.get('DB_NAME', 'gestao_servpen'),
        user=os.environ.get('DB_USER', 'gestao_servpen'),
        password=os.environ.get('DB_PASSWORD', ''),
    )


def _montar_database_url():
    """Constrói uma URL SQLAlchemy-friendly a partir das env vars do servidor.

    Prioridade:
      1. DATABASE_URL — se já estiver no formato `postgresql+psycopg://...`,
         retorna como está. Se for o formato curto `postgresql://...`,
         injeta `+psycopg` pra forçar o driver psycopg3.
      2. DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD — monta a URL.
    """
    url = os.environ.get('DATABASE_URL')
    if url:
        if url.startswith('postgresql+'):
            return url
        if url.startswith('postgresql://'):
            return 'postgresql+psycopg://' + url[len('postgresql://'):]
        if url.startswith('postgres://'):  # Heroku-style
            return 'postgresql+psycopg://' + url[len('postgres://'):]
        return url  # entrega como veio — usuário sabe o que está fazendo

    host = os.environ.get('DB_HOST', 'localhost')
    port = os.environ.get('DB_PORT', '5432')
    dbname = os.environ.get('DB_NAME', 'gestao_servpen')
    user = os.environ.get('DB_USER', 'gestao_servpen')
    password = os.environ.get('DB_PASSWORD', '')
    return (
        f"postgresql+psycopg://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{port}/{dbname}"
    )


@lru_cache(maxsize=1)
def get_engine():
    """Engine SQLAlchemy compartilhado, com pool de conexões.

    Usado por `pd.read_sql_query(sql, db.get_engine(), ...)` em vez da
    conexão psycopg crua — satisfaz o pandas (sem warning de DBAPI
    desconhecido) e reusa conexões do pool entre queries.

    Cacheado com `lru_cache(maxsize=1)` em vez de `@st.cache_resource` pra
    funcionar fora do runtime Streamlit (scripts standalone, REPL, etc.).
    Em processos Streamlit isso ainda dá single instance por processo, que
    é o que queremos — o servidor de prod tem 1 processo Streamlit só.

    Configuração do pool:
      - pool_size=5    → 5 conexões persistentes
      - max_overflow=5 → até 5 conexões extras sob pressão
      - pool_recycle=3600 → recicla conexões com >1h pra evitar idle timeout
      - pool_pre_ping=True → testa conexão antes de cada uso (pega conn morta)
    """
    return create_engine(
        _montar_database_url(),
        pool_size=5,
        max_overflow=5,
        pool_recycle=3600,
        pool_pre_ping=True,
        future=True,
    )


# ─── HASH DE SENHA ────────────────────────────────────────
# Maio/2026: troca de SHA-256 puro pra bcrypt.
#
# `gerar_hash()` agora gera bcrypt (com salt aleatório). Hashes antigos
# SHA-256 (64 chars hex) continuam aceitos via `verificar_hash()` — quando
# um usuário com hash legado faz login com sucesso, o hash é **re-gravado
# como bcrypt** automaticamente (rehash transparente). Após todos os
# usuários ativos logarem ao menos uma vez, todos os hashes terão migrado.
#
# Para forçar migração sem esperar login: o admin troca a senha pelo
# painel "Membros" — o INSERT/UPDATE já vai com bcrypt.

def _eh_sha256_hex(s):
    """True se s parece ser SHA-256 puro: 64 chars hexadecimais."""
    if not isinstance(s, str) or len(s) != 64:
        return False
    try:
        int(s, 16)
        return True
    except ValueError:
        return False


def gerar_hash(senha):
    """Gera hash bcrypt da senha (salt aleatório, custo default ~12).

    Substituiu SHA-256 puro em maio/2026 — hashes antigos continuam
    aceitos no login via `verificar_hash` + rehash transparente.
    """
    return _bcrypt.hash(str(senha))


def verificar_hash(senha_plain, hash_armazenado):
    """Verifica `senha_plain` contra `hash_armazenado`.

    Retorna `(valido, precisa_rehash)`:
      - `valido=True` se a senha bate (via bcrypt OU SHA-256 legado).
      - `precisa_rehash=True` quando o hash armazenado é SHA-256 legado
        e o caller deve re-gravar via `gerar_hash(senha_plain)` pra migrar.
    """
    if not hash_armazenado or senha_plain is None:
        return False, False
    if _eh_sha256_hex(hash_armazenado):
        # Hash legado SHA-256 puro
        atual = hashlib.sha256(str(senha_plain).encode()).hexdigest()
        return (atual == hash_armazenado, True) if atual == hash_armazenado \
               else (False, False)
    # Tenta bcrypt
    try:
        return (_bcrypt.verify(str(senha_plain), hash_armazenado), False)
    except (ValueError, TypeError):
        # Hash em formato desconhecido — trata como inválido em vez de explodir.
        return (False, False)


def atualizar_hash_senha(usuario, nova_senha_plain):
    """Re-grava o hash da senha (gera bcrypt fresco). Usado tanto pra trocar
    senha como pra migrar SHA-256 → bcrypt transparente no login."""
    conn = conectar(); c = conn.cursor()
    try:
        c.execute(
            "UPDATE usuarios SET senha = %s WHERE nome = %s",
            (gerar_hash(nova_senha_plain), usuario),
        )
        conn.commit()
    finally:
        conn.close()


# ─── RECUPERAÇÃO DE SENHA (pergunta secreta) ──────────────
def definir_pergunta_secreta(usuario, pergunta, resposta):
    """Salva a pergunta secreta e o HASH da resposta para um usuário.
    A resposta é normalizada (strip + lower) antes do hash pra ser tolerante a
    maiúsculas/espaços — 'Rex' e 'rex ' batem igual."""
    conn = conectar(); c = conn.cursor()
    try:
        resp_hash = gerar_hash(str(resposta).strip().lower()) if resposta else None
        c.execute(
            "UPDATE usuarios SET pergunta_secreta = %s, resposta_secreta = %s WHERE nome = %s",
            (pergunta or None, resp_hash, usuario),
        )
        conn.commit()
    finally:
        conn.close()

def obter_pergunta_secreta(usuario):
    """Retorna a pergunta secreta do usuário (ou None se não cadastrou)."""
    conn = conectar(); c = conn.cursor()
    try:
        c.execute("SELECT pergunta_secreta FROM usuarios WHERE nome = %s", (usuario,))
        row = c.fetchone()
        return row[0] if row and row[0] else None
    finally:
        conn.close()

def validar_resposta_secreta(usuario, resposta):
    """True se a resposta (normalizada) bate com o hash guardado.

    Aceita hashes SHA-256 legados e bcrypt. Se for legado e bater, re-grava
    como bcrypt (mesma estratégia de rehash transparente das senhas).
    """
    if not resposta:
        return False
    resp_norm = str(resposta).strip().lower()
    conn = conectar(); c = conn.cursor()
    try:
        c.execute("SELECT resposta_secreta FROM usuarios WHERE nome = %s", (usuario,))
        row = c.fetchone()
        if not row or not row[0]:
            return False
        hash_guardado = row[0]
        valido, precisa_rehash = verificar_hash(resp_norm, hash_guardado)
        if valido and precisa_rehash:
            try:
                c.execute(
                    "UPDATE usuarios SET resposta_secreta = %s WHERE nome = %s",
                    (gerar_hash(resp_norm), usuario),
                )
                conn.commit()
            except Exception:
                conn.rollback()  # rehash falhou — não bloqueia o login
        return valido
    finally:
        conn.close()

def redefinir_senha(usuario, nova_senha):
    """Grava a NOVA senha já hasheada para o usuário."""
    conn = conectar(); c = conn.cursor()
    try:
        c.execute(
            "UPDATE usuarios SET senha = %s WHERE nome = %s",
            (gerar_hash(nova_senha), usuario),
        )
        conn.commit()
    finally:
        conn.close()


# ─── PERFIL DO USUÁRIO (edição própria) ───────────────────
def obter_usuario(nome):
    """Retorna dict com os dados do usuário (ou None)."""
    conn = conectar(); c = conn.cursor()
    try:
        c.execute(
            "SELECT id, nome, perfil, cargo, email, pergunta_secreta, avatar_path "
            "FROM usuarios WHERE nome = %s",
            (nome,),
        )
        row = c.fetchone()
        if not row:
            return None
        return {
            'id': row[0], 'nome': row[1], 'perfil': row[2], 'cargo': row[3],
            'email': row[4], 'pergunta_secreta': row[5], 'avatar_path': row[6],
        }
    finally:
        conn.close()

def atualizar_perfil(nome, cargo=None, email=None, avatar_path=None):
    """Atualiza dados do PRÓPRIO usuário (não mexe em nome/perfil/senha).
    Só altera os campos passados (None = não mexe naquele campo)."""
    sets, params = [], []
    if cargo is not None:
        sets.append("cargo = %s"); params.append(cargo)
    if email is not None:
        sets.append("email = %s"); params.append(email)
    if avatar_path is not None:
        sets.append("avatar_path = %s"); params.append(avatar_path)
    if not sets:
        return
    params.append(nome)
    conn = conectar(); c = conn.cursor()
    try:
        c.execute(f"UPDATE usuarios SET {', '.join(sets)} WHERE nome = %s", params)
        conn.commit()
    finally:
        conn.close()

def verificar_senha(usuario, senha):
    """True se a senha (texto puro) bate com o hash guardado.

    Usado pra confirmar a senha atual antes de trocar (painel "Meu Perfil").
    Aceita hashes SHA-256 legados e bcrypt. Re-grava como bcrypt se o hash
    armazenado for legado (rehash transparente).
    """
    if senha is None:
        return False
    conn = conectar(); c = conn.cursor()
    try:
        c.execute("SELECT senha FROM usuarios WHERE nome = %s", (usuario,))
        row = c.fetchone()
        if not row or not row[0]:
            return False
        valido, precisa_rehash = verificar_hash(senha, row[0])
        if valido and precisa_rehash:
            try:
                c.execute(
                    "UPDATE usuarios SET senha = %s WHERE nome = %s",
                    (gerar_hash(senha), usuario),
                )
                conn.commit()
            except Exception:
                conn.rollback()  # rehash falhou — não bloqueia a verificação
        return valido
    finally:
        conn.close()


# ─── RATE LIMITING DE LOGIN ───────────────────────────────
# Constantes ajustadas em maio/2026 após bcrypt. Pra mudar:
#   - LIMITE_FALHAS_LOGIN: tolerância antes de bloquear (humano)
#   - JANELA_MIN_LOGIN: janela em minutos pra contar falhas e duração do bloqueio
LIMITE_FALHAS_LOGIN = 5
JANELA_MIN_LOGIN = 15


def registrar_falha_login(usuario, ip=None):
    """Loga uma tentativa de login falha. Best-effort: não interrompe o login."""
    conn = conectar(); c = conn.cursor()
    try:
        c.execute(
            "INSERT INTO login_falhas (usuario, ip) VALUES (%s, %s)",
            (usuario, ip),
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        log.warning("não consegui registrar falha de login pra %s: %s", usuario, e)
    finally:
        conn.close()


def contar_falhas_login_recentes(usuario, janela_min=None):
    """Quantas falhas de login esse usuário acumulou nos últimos `janela_min`."""
    j = int(janela_min if janela_min is not None else JANELA_MIN_LOGIN)
    conn = conectar(); c = conn.cursor()
    try:
        # f-string com cast a int blinda contra SQL injection (PG não aceita
        # placeholder dentro de literal INTERVAL; o cast int() acima fecha o gap).
        c.execute(
            f"SELECT COUNT(*) FROM login_falhas "
            f"WHERE usuario = %s AND criado_em > NOW() - INTERVAL '{j} minutes'",
            (usuario,),
        )
        return int(c.fetchone()[0] or 0)
    finally:
        conn.close()


def proxima_tentativa_login_em(usuario, janela_min=None):
    """Quando o bloqueio expira (= falha mais antiga na janela + janela_min).
    Retorna `datetime` ou `None` se não há falhas na janela."""
    j = int(janela_min if janela_min is not None else JANELA_MIN_LOGIN)
    conn = conectar(); c = conn.cursor()
    try:
        c.execute(
            f"SELECT MIN(criado_em) + INTERVAL '{j} minutes' "
            f"FROM login_falhas "
            f"WHERE usuario = %s AND criado_em > NOW() - INTERVAL '{j} minutes'",
            (usuario,),
        )
        row = c.fetchone()
        return row[0] if row and row[0] else None
    finally:
        conn.close()


def limpar_falhas_login(usuario):
    """Apaga histórico de falhas pra um usuário (chamado em login bem-sucedido)."""
    conn = conectar(); c = conn.cursor()
    try:
        c.execute("DELETE FROM login_falhas WHERE usuario = %s", (usuario,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        log.warning("não consegui limpar falhas de login pra %s: %s", usuario, e)
    finally:
        conn.close()


def purgar_falhas_login_antigas(horas=24):
    """Remove registros com mais de N horas. Mantém a tabela enxuta. Chame de
    tempos em tempos (não é crítico — a contagem usa janela curta de qualquer
    jeito, mas evita inflar a tabela)."""
    h = int(horas)
    conn = conectar(); c = conn.cursor()
    try:
        c.execute(
            f"DELETE FROM login_falhas "
            f"WHERE criado_em < NOW() - INTERVAL '{h} hours'"
        )
        conn.commit()
        return c.rowcount
    except Exception as e:
        conn.rollback()
        log.warning("não consegui purgar falhas antigas: %s", e)
        return 0
    finally:
        conn.close()


# ─── SESSÕES ──────────────────────────────────────────────
def criar_tabela_sessoes():
    conn = conectar(); c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS sessoes (
        token TEXT PRIMARY KEY,
        usuario TEXT NOT NULL,
        expires_at BIGINT NOT NULL
    )''')
    conn.commit(); conn.close()

def criar_sessao(usuario, dias=7):
    token = secrets.token_urlsafe(18)
    expires = int(time.time()) + dias * 86400
    conn = conectar(); c = conn.cursor()
    c.execute("INSERT INTO sessoes (token, usuario, expires_at) VALUES (%s,%s,%s)",
              (token, usuario, expires))
    conn.commit(); conn.close()
    return token

def validar_sessao(token):
    if not token:
        return None
    conn = conectar(); c = conn.cursor()
    c.execute("""
        SELECT s.usuario, u.perfil
        FROM sessoes s
        JOIN usuarios u ON s.usuario = u.nome
        WHERE s.token = %s AND s.expires_at > %s
    """, (token, int(time.time())))
    row = c.fetchone()
    conn.close()
    return row

def deletar_sessao(token):
    if not token:
        return
    conn = conectar(); c = conn.cursor()
    c.execute("DELETE FROM sessoes WHERE token = %s", (token,))
    conn.commit(); conn.close()

def limpar_sessoes_expiradas():
    conn = conectar(); c = conn.cursor()
    c.execute("DELETE FROM sessoes WHERE expires_at < %s", (int(time.time()),))
    conn.commit(); conn.close()


# ─── CRIAÇÃO DE TABELAS / MIGRAÇÕES ───────────────────────
def criar_tabelas():
    """Cria todas as tabelas (CREATE IF NOT EXISTS) e adiciona colunas faltantes
    em bancos pré-existentes via ALTER TABLE ADD COLUMN IF NOT EXISTS (PG 9.6+)."""
    conn = conectar()
    c = conn.cursor()
    try:
        # ── PROJETOS ──
        c.execute('''CREATE TABLE IF NOT EXISTS projetos (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            projetista TEXT,
            projeto TEXT,
            endereco TEXT,
            solicitante TEXT,
            contato TEXT,
            numero_sei TEXT,
            data_recebimento DATE,
            previsao_execucao DATE,
            data_inicio DATE,
            data_termino DATE,
            data_fim DATE,
            status TEXT DEFAULT 'Ativo',
            link_projeto TEXT,
            demandas TEXT,
            solicitacao TEXT,
            prioridade TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        # ── USUÁRIOS ──
        c.execute('''CREATE TABLE IF NOT EXISTS usuarios (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            nome TEXT UNIQUE,
            senha TEXT,
            perfil TEXT,
            cargo TEXT
        )''')

        # ── DIÁRIO ──
        c.execute('''CREATE TABLE IF NOT EXISTS diario (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            projeto_id BIGINT,
            data TEXT,
            executado TEXT,
            autor TEXT,
            disciplina TEXT,
            horas REAL,
            anexo TEXT,
            resposta_gestor TEXT,
            resolvido INTEGER DEFAULT 0
        )''')

        # ── CHAT ──
        c.execute('''CREATE TABLE IF NOT EXISTS chat (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            remetente TEXT,
            destinatario TEXT,
            mensagem TEXT,
            data TEXT,
            lido_em TIMESTAMP
        )''')

        # ── AGENDA ──
        c.execute('''CREATE TABLE IF NOT EXISTS agenda (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            titulo TEXT,
            tipo TEXT,
            data_inicio DATE,
            data_fim DATE,
            responsaveis TEXT,
            descricao TEXT,
            local TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        # ── PROGRESSO DE DISCIPLINAS ──
        c.execute('''CREATE TABLE IF NOT EXISTS progresso_disciplinas (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            projeto_id BIGINT,
            disciplina TEXT,
            concluido INTEGER DEFAULT 0,
            percentual INTEGER DEFAULT 0
        )''')

        # ── ETAPAS DO PROJETO ──
        c.execute('''CREATE TABLE IF NOT EXISTS etapas_projeto (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            projeto_id BIGINT NOT NULL,
            nome TEXT NOT NULL,
            dias_offset INTEGER DEFAULT 0,
            duracao_dias INTEGER DEFAULT 1,
            ordem INTEGER DEFAULT 0,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (projeto_id) REFERENCES projetos(id) ON DELETE CASCADE
        )''')
        c.execute("CREATE INDEX IF NOT EXISTS idx_etapas_projeto ON etapas_projeto(projeto_id, ordem)")

        # ── AUDITORIA ──
        c.execute('''CREATE TABLE IF NOT EXISTS auditoria (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            data TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            usuario TEXT,
            acao TEXT NOT NULL,
            entidade TEXT,
            entidade_id BIGINT,
            detalhes TEXT
        )''')
        c.execute("CREATE INDEX IF NOT EXISTS idx_auditoria_data ON auditoria(data DESC)")

        # ── ARQUIVOS ──
        c.execute('''CREATE TABLE IF NOT EXISTS arquivos (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            projeto_id BIGINT NOT NULL,
            nome_original TEXT NOT NULL,
            path_arquivo TEXT NOT NULL,
            descricao TEXT,
            autor TEXT,
            data_upload TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            tamanho_bytes BIGINT,
            mime_type TEXT
        )''')

        # ── MENÇÕES NO DIÁRIO ──
        # ACESSO: 1 linha por (usuario, projeto). Idempotente via UNIQUE.
        c.execute('''CREATE TABLE IF NOT EXISTS mencoes_acesso (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            usuario_mencionado TEXT NOT NULL,
            projeto_id BIGINT NOT NULL,
            concedido_por TEXT NOT NULL,
            concedido_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            relato_id BIGINT,
            UNIQUE(usuario_mencionado, projeto_id)
        )''')
        # NOTIFICAÇÕES: 1 linha por evento (mesmo se o usuário já tinha acesso).
        # Dois carimbos de tempo separados:
        #   visto_em      = quando abriu o Diário (evita duplicar toast)
        #   dispensado_em = quando clicou em "✕ Fechar" (some do painel)
        c.execute('''CREATE TABLE IF NOT EXISTS mencoes_notificacoes (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            usuario_mencionado TEXT NOT NULL,
            projeto_id BIGINT NOT NULL,
            relato_id BIGINT,
            mencionado_por TEXT NOT NULL,
            contexto TEXT,
            data TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            visto_em TIMESTAMP,
            dispensado_em TIMESTAMP
        )''')
        c.execute('''CREATE INDEX IF NOT EXISTS idx_mencoes_notif_usuario_visto
                     ON mencoes_notificacoes(usuario_mencionado, visto_em)''')
        c.execute('''CREATE INDEX IF NOT EXISTS idx_mencoes_notif_usuario_disp
                     ON mencoes_notificacoes(usuario_mencionado, dispensado_em)''')

        # ── DIÁRIO LEITURAS ──
        c.execute('''CREATE TABLE IF NOT EXISTS diario_leituras (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            diario_id BIGINT NOT NULL,
            usuario TEXT NOT NULL,
            lido_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(diario_id, usuario)
        )''')
        c.execute("CREATE INDEX IF NOT EXISTS idx_dl_usuario ON diario_leituras(usuario)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_dl_diario  ON diario_leituras(diario_id)")

        # ── RATE LIMITING DE LOGIN ──
        # Rastreia falhas recentes pra brecar brute-force.
        # `validar_login()` em auth.py conta falhas dos últimos `JANELA_MIN`
        # minutos pra cada usuário; ao atingir `LIMITE_FALHAS`, recusa novos
        # logins até a janela expirar. Login bem-sucedido limpa o histórico
        # daquele usuário.
        c.execute('''CREATE TABLE IF NOT EXISTS login_falhas (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            usuario TEXT NOT NULL,
            ip TEXT,
            criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )''')
        c.execute("CREATE INDEX IF NOT EXISTS idx_login_falhas_usuario_data "
                  "ON login_falhas(usuario, criado_em)")

        # ── MIGRAÇÕES INCREMENTAIS (PG 9.6+: ADD COLUMN IF NOT EXISTS) ──
        # Pra bancos pré-existentes onde a tabela já existe sem essas colunas.
        migracoes = [
            ("projetos",              "data_pedido",        "DATE"),
            ("projetos",              "previsao_execucao",  "DATE"),
            ("projetos",              "numero_sei",         "TEXT"),
            ("projetos",              "data_recebimento",   "DATE"),
            ("projetos",              "data_inicio",        "DATE"),
            ("projetos",              "data_termino",       "DATE"),
            ("usuarios",              "cargo",              "TEXT DEFAULT 'Colaborador'"),
            ("usuarios",              "pergunta_secreta",   "TEXT"),
            ("usuarios",              "resposta_secreta",   "TEXT"),
            ("usuarios",              "email",              "TEXT"),
            ("usuarios",              "avatar_path",        "TEXT"),
            ("projetos",              "prioridade",         "TEXT"),
            # Tags livres separadas por vírgula. Ex.: "Crítico,Aguardando Cliente".
            # Schema TEXT (não tabela normalizada) é OK na escala atual (dezenas
            # de projetos). Pra ler como lista: split(',') + strip(). Pra filtrar
            # pesquisa SQL: WHERE tags LIKE '%,Crítico,%' (com comma-padding).
            ("projetos",              "tags",               "TEXT"),
            ("diario",                "resposta_gestor",    "TEXT"),
            ("diario",                "anexo",              "TEXT"),
            ("diario",                "resolvido",          "INTEGER DEFAULT 0"),
            ("chat",                  "lido_em",            "TIMESTAMP"),
            ("agenda",                "local",              "TEXT"),
            ("mencoes_notificacoes",  "dispensado_em",      "TIMESTAMP"),
        ]
        for tab, col, tipo in migracoes:
            try:
                c.execute(f"ALTER TABLE {tab} ADD COLUMN IF NOT EXISTS {col} {tipo}")
            except Exception:
                # PG < 9.6 não suporta IF NOT EXISTS no ALTER TABLE — fallback:
                try:
                    c.execute(f"ALTER TABLE {tab} ADD COLUMN {col} {tipo}")
                except Exception:
                    pass

        # Índice para ordenar por prioridade no kanban
        c.execute("""CREATE INDEX IF NOT EXISTS idx_projetos_status_prior
                     ON projetos(status, prioridade)""")

        conn.commit()
    except Exception as e:
        log.exception("Erro ao inicializar banco: %s", e)
        conn.rollback()
    finally:
        conn.close()

# Stubs de compatibilidade — agora tudo está em criar_tabelas()
def criar_tabela_agenda():            criar_tabelas()
def criar_tabela_progresso():         criar_tabelas()
def criar_tabela_arquivos():          criar_tabelas()
def criar_tabela_auditoria():         criar_tabelas()
def criar_tabela_mencoes():           criar_tabelas()
def criar_tabela_diario_leituras():   criar_tabelas()


# ─── TAGS DE PROJETO ──────────────────────────────────────
# Tags vivem na coluna `projetos.tags` como CSV (string separada por vírgula).
# Aqui só helpers utilitários — quem grava/atualiza é o app.py via
# `atualizar_campo_projeto` ou no INSERT/UPDATE direto.

def parse_tags(s):
    """Converte string de tags ('a,b ,c') em lista limpa (['a','b','c']).
    Resiliente: lida com None, vírgulas extras, espaços, duplicatas."""
    if not s:
        return []
    visto = set()
    out = []
    for t in str(s).split(','):
        t = t.strip()
        if not t:
            continue
        key = t.lower()
        if key in visto:
            continue
        visto.add(key)
        out.append(t)
    return out


def serializar_tags(tags_iter):
    """Inverso de parse_tags: lista → CSV pra gravar no banco."""
    return ",".join(parse_tags(",".join(tags_iter or [])))


def listar_tags_existentes():
    """Retorna lista única de TODAS as tags atualmente em uso em projetos.
    Útil pra alimentar autocomplete/dropdown na UI."""
    conn = conectar(); c = conn.cursor()
    try:
        c.execute("SELECT tags FROM projetos WHERE tags IS NOT NULL AND tags <> ''")
        rows = c.fetchall()
    finally:
        conn.close()
    visto = set()
    todas = []
    for (s,) in rows:
        for t in parse_tags(s):
            key = t.lower()
            if key not in visto:
                visto.add(key)
                todas.append(t)
    todas.sort(key=str.lower)
    return todas


# ─── PROJETOS ─────────────────────────────────────────────
def salvar_projeto(dados):
    """Insere um novo projeto e retorna o id (via RETURNING).

    `dados` aceita 16 ou 17 valores:
      16: projetista, projeto, endereco, solicitante, contato, numero_sei,
          data_recebimento, previsao_execucao, data_inicio, data_termino,
          data_fim, status, link_projeto, demandas, solicitacao, prioridade.
      17: os 16 acima + `tags` (string CSV de tags, ou None).

    Manter o overload pra não quebrar callers existentes (compatibilidade
    com versões antigas do app.py que ainda passam 16).
    """
    if len(dados) == 16:
        dados = (*dados, None)  # tags = NULL
    elif len(dados) != 17:
        raise ValueError(f"salvar_projeto: esperava 16 ou 17 valores, veio {len(dados)}")

    conn = conectar(); c = conn.cursor()
    try:
        c.execute('''INSERT INTO projetos
                     (projetista, projeto, endereco, solicitante, contato,
                      numero_sei, data_recebimento, previsao_execucao,
                      data_inicio, data_termino, data_fim,
                      status, link_projeto, demandas, solicitacao, prioridade,
                      tags)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                     RETURNING id''', dados)
        novo_id = c.fetchone()[0]
        conn.commit()
        return novo_id
    except Exception as e:
        log.exception("Erro ao salvar projeto: %s", e)
        conn.rollback()
        return None
    finally:
        conn.close()

def atualizar_projeto_completo(id_p, dados):
    """dados = (projetista, projeto, endereco, solicitante, contato,
                numero_sei, data_recebimento, data_inicio, data_termino, data_fim,
                link_projeto, demandas, solicitacao, prioridade)"""
    conn = conectar(); c = conn.cursor()
    try:
        c.execute('''UPDATE projetos SET
                     projetista=%s, projeto=%s, endereco=%s, solicitante=%s, contato=%s,
                     numero_sei=%s, data_recebimento=%s, data_inicio=%s, data_termino=%s,
                     data_fim=%s, link_projeto=%s, demandas=%s, solicitacao=%s, prioridade=%s
                     WHERE id=%s''', (*dados, id_p))
        conn.commit()
    finally:
        conn.close()

def atualizar_campo_projeto(id_p, coluna, valor):
    conn = conectar(); c = conn.cursor()
    try:
        c.execute(f"UPDATE projetos SET {coluna} = %s WHERE id = %s", (valor, int(id_p)))
        conn.commit()
    finally:
        conn.close()

def excluir_projeto(id_p):
    conn = conectar(); c = conn.cursor()
    try:
        c.execute("DELETE FROM etapas_projeto WHERE projeto_id = %s", (int(id_p),))
        # CASCADE manual das menções (acesso + notificações) para não deixar órfãos
        c.execute("DELETE FROM mencoes_acesso WHERE projeto_id = %s", (int(id_p),))
        c.execute("DELETE FROM mencoes_notificacoes WHERE projeto_id = %s", (int(id_p),))
        c.execute("DELETE FROM projetos WHERE id = %s", (int(id_p),))
        conn.commit()
    finally:
        conn.close()


# ─── ETAPAS ───────────────────────────────────────────────
def salvar_etapas(projeto_id, etapas):
    """etapas = lista de dicts: {nome, dias_offset, duracao_dias, ordem}.
    Substitui todas as etapas do projeto."""
    conn = conectar(); c = conn.cursor()
    try:
        c.execute("DELETE FROM etapas_projeto WHERE projeto_id = %s", (int(projeto_id),))
        for et in etapas:
            c.execute('''INSERT INTO etapas_projeto
                         (projeto_id, nome, dias_offset, duracao_dias, ordem)
                         VALUES (%s,%s,%s,%s,%s)''',
                      (int(projeto_id),
                       et['nome'],
                       int(et.get('dias_offset', 0)),
                       max(1, int(et.get('duracao_dias', 1))),
                       int(et.get('ordem', 0))))
        conn.commit()
    finally:
        conn.close()

def listar_etapas(projeto_id):
    """Retorna lista de dicts ordenada por 'ordem'."""
    conn = conectar(); c = conn.cursor()
    c.execute('''SELECT id, nome, dias_offset, duracao_dias, ordem
                 FROM etapas_projeto WHERE projeto_id = %s
                 ORDER BY ordem ASC''', (int(projeto_id),))
    cols = ['id', 'nome', 'dias_offset', 'duracao_dias', 'ordem']
    rows = [dict(zip(cols, r)) for r in c.fetchall()]
    conn.close()
    return rows

def listar_etapas_todos_projetos():
    """Retorna todas as etapas com nome do projeto — usado no Gantt."""
    conn = conectar(); c = conn.cursor()
    c.execute('''SELECT e.projeto_id, p.projeto, p.data_inicio,
                        e.nome, e.dias_offset, e.duracao_dias, e.ordem
                 FROM etapas_projeto e
                 JOIN projetos p ON e.projeto_id = p.id
                 ORDER BY e.projeto_id, e.ordem''')
    cols = ['projeto_id','projeto','data_inicio','nome','dias_offset','duracao_dias','ordem']
    rows = [dict(zip(cols, r)) for r in c.fetchall()]
    conn.close()
    return rows


# ─── AGENDA ───────────────────────────────────────────────
def salvar_evento(titulo, tipo, d_ini, d_fim, resp, desc, local=''):
    conn = conectar(); c = conn.cursor()
    resp_str = ", ".join(resp) if isinstance(resp, list) else resp
    c.execute('''INSERT INTO agenda
                 (titulo, tipo, data_inicio, data_fim, responsaveis, descricao, local)
                 VALUES (%s,%s,%s,%s,%s,%s,%s)
                 RETURNING id''',
              (titulo, tipo, str(d_ini), str(d_fim), resp_str, desc, local))
    novo_id = c.fetchone()[0]
    conn.commit()
    conn.close()
    return novo_id

def atualizar_evento(id_ev, titulo, tipo, d_ini, d_fim, resp, desc, local=''):
    conn = conectar(); c = conn.cursor()
    resp_str = ", ".join(resp) if isinstance(resp, list) else resp
    c.execute('''UPDATE agenda SET
                 titulo=%s, tipo=%s, data_inicio=%s, data_fim=%s,
                 responsaveis=%s, descricao=%s, local=%s
                 WHERE id=%s''',
              (titulo, tipo, str(d_ini), str(d_fim), resp_str, desc, local, int(id_ev)))
    conn.commit()
    conn.close()

def excluir_evento(id_ev):
    conn = conectar(); c = conn.cursor()
    c.execute("DELETE FROM agenda WHERE id = %s", (int(id_ev),))
    conn.commit()
    conn.close()


# ─── DIÁRIO ───────────────────────────────────────────────
def excluir_registro_diario(id_relato):
    conn = conectar(); c = conn.cursor()
    try:
        c.execute("DELETE FROM diario WHERE id = %s", (id_relato,))
        conn.commit()
    finally:
        conn.close()


# ─── CHAT ─────────────────────────────────────────────────
def excluir_mensagem_chat(id_msg):
    conn = conectar(); c = conn.cursor()
    try:
        c.execute("DELETE FROM chat WHERE id = %s", (id_msg,))
        conn.commit()
    finally:
        conn.close()

def editar_mensagem_chat(id_msg, nova_mensagem):
    conn = conectar(); c = conn.cursor()
    try:
        c.execute("UPDATE chat SET mensagem = %s WHERE id = %s", (nova_mensagem, id_msg))
        conn.commit()
    finally:
        conn.close()

def contar_nao_lidas(usuario, remetente=None):
    conn = conectar(); c = conn.cursor()
    if remetente:
        c.execute("SELECT COUNT(*) FROM chat WHERE destinatario=%s AND remetente=%s AND lido_em IS NULL",
                  (usuario, remetente))
    else:
        c.execute("SELECT COUNT(*) FROM chat WHERE destinatario=%s AND lido_em IS NULL", (usuario,))
    n = c.fetchone()[0]
    conn.close()
    return int(n or 0)

def listar_remetentes_com_nao_lidas(usuario):
    conn = conectar(); c = conn.cursor()
    c.execute("""SELECT remetente, COUNT(*) FROM chat
                 WHERE destinatario=%s AND lido_em IS NULL
                 GROUP BY remetente""", (usuario,))
    rows = c.fetchall()
    conn.close()
    return [(r[0], int(r[1])) for r in rows]

def marcar_lidas(usuario, remetente):
    conn = conectar(); c = conn.cursor()
    c.execute("""UPDATE chat SET lido_em=CURRENT_TIMESTAMP
                 WHERE destinatario=%s AND remetente=%s AND lido_em IS NULL""",
              (usuario, remetente))
    conn.commit()
    conn.close()


# ─── USUÁRIOS ─────────────────────────────────────────────
def salvar_usuario(nome, senha, perfil, cargo="Colaborador"):
    conn = conectar(); c = conn.cursor()
    try:
        c.execute("INSERT INTO usuarios (nome, senha, perfil, cargo) VALUES (%s,%s,%s,%s)",
                  (nome, gerar_hash(senha), perfil, cargo))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()


# ─── AUDITORIA ────────────────────────────────────────────
def log_aud(usuario, acao, entidade='', entidade_id=None, detalhes=''):
    try:
        conn = conectar(); c = conn.cursor()
        c.execute("""INSERT INTO auditoria (usuario, acao, entidade, entidade_id, detalhes)
                     VALUES (%s,%s,%s,%s,%s)""",
                  (usuario or '', acao, entidade or '',
                   int(entidade_id) if entidade_id is not None else None,
                   str(detalhes)[:500]))
        conn.commit(); conn.close()
    except Exception:
        pass

def listar_auditoria(limit=200, filtro_usuario=None, filtro_acao=None):
    conn = conectar(); c = conn.cursor()
    where, params = [], []
    if filtro_usuario:
        where.append("usuario = %s"); params.append(filtro_usuario)
    if filtro_acao:
        where.append("acao ILIKE %s"); params.append(f"%{filtro_acao}%")
    sql = "SELECT id, data, usuario, acao, entidade, entidade_id, detalhes FROM auditoria"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY data DESC LIMIT %s"; params.append(int(limit))
    c.execute(sql, params)
    rows = c.fetchall()
    conn.close()
    return rows


# ─── ARQUIVOS ─────────────────────────────────────────────
PASTA_ANEXOS = 'anexos'

def salvar_arquivo(projeto_id, nome_original, path_arquivo, descricao, autor,
                   tamanho_bytes, mime_type=''):
    conn = conectar(); c = conn.cursor()
    c.execute('''INSERT INTO arquivos
                 (projeto_id, nome_original, path_arquivo, descricao, autor, tamanho_bytes, mime_type)
                 VALUES (%s,%s,%s,%s,%s,%s,%s)''',
              (int(projeto_id), nome_original, path_arquivo, descricao or '',
               autor or '', int(tamanho_bytes or 0), mime_type or ''))
    conn.commit(); conn.close()

def listar_arquivos(projeto_id=None):
    conn = conectar(); c = conn.cursor()
    if projeto_id is not None:
        c.execute('''SELECT id, projeto_id, nome_original, path_arquivo,
                            descricao, autor, data_upload, tamanho_bytes
                     FROM arquivos WHERE projeto_id=%s ORDER BY data_upload DESC''',
                  (int(projeto_id),))
    else:
        c.execute('''SELECT id, projeto_id, nome_original, path_arquivo,
                            descricao, autor, data_upload, tamanho_bytes
                     FROM arquivos ORDER BY data_upload DESC''')
    rows = c.fetchall()
    conn.close()
    return rows

def excluir_arquivo(id_arq):
    conn = conectar(); c = conn.cursor()
    c.execute("SELECT path_arquivo FROM arquivos WHERE id=%s", (int(id_arq),))
    row = c.fetchone()
    if row and row[0] and os.path.exists(row[0]):
        try:
            os.remove(row[0])
        except Exception:
            pass
    c.execute("DELETE FROM arquivos WHERE id=%s", (int(id_arq),))
    conn.commit(); conn.close()

def caminho_seguro_para_anexo(projeto_id, nome_original):
    import re
    nome_seguro = re.sub(r'[^A-Za-z0-9._\-]', '_', nome_original)[:120]
    ts = time.strftime('%Y%m%d_%H%M%S')
    pasta = os.path.join(PASTA_ANEXOS, str(int(projeto_id)))
    return pasta, os.path.join(pasta, f"{ts}_{nome_seguro}")


# ─── DIÁRIO LEITURAS ──────────────────────────────────────
def marcar_diario_lido(diario_id, usuario):
    """Marca um registro do diário como lido por um usuário (idempotente)."""
    try:
        conn = conectar(); c = conn.cursor()
        c.execute("""INSERT INTO diario_leituras (diario_id, usuario)
                     VALUES (%s,%s)
                     ON CONFLICT (diario_id, usuario) DO NOTHING""",
                  (int(diario_id), usuario))
        conn.commit(); conn.close()
    except Exception:
        pass

def marcar_projeto_diario_lido(projeto_id, usuario):
    """Marca todos os registros de um projeto como lidos pelo usuário (idempotente)."""
    try:
        conn = conectar(); c = conn.cursor()
        # Uma única query (mais eficiente que loop)
        c.execute("""INSERT INTO diario_leituras (diario_id, usuario)
                     SELECT id, %s FROM diario WHERE projeto_id = %s
                     ON CONFLICT (diario_id, usuario) DO NOTHING""",
                  (usuario, int(projeto_id)))
        conn.commit(); conn.close()
    except Exception:
        pass

def contar_nao_lidos_diario(usuario):
    """Retorna dict {projeto_id: qtd_nao_lidos} para o usuário."""
    try:
        conn = conectar(); c = conn.cursor()
        c.execute("""
            SELECT d.projeto_id, COUNT(*) as nao_lidos
            FROM diario d
            WHERE d.autor != %s
              AND NOT EXISTS (
                  SELECT 1 FROM diario_leituras dl
                  WHERE dl.diario_id = d.id AND dl.usuario = %s
              )
            GROUP BY d.projeto_id
        """, (usuario, usuario))
        rows = c.fetchall()
        conn.close()
        return {int(r[0]): int(r[1]) for r in rows}
    except Exception:
        return {}

def total_nao_lidos_diario(usuario):
    """Total geral de registros não lidos no diário para o usuário."""
    try:
        mapa = contar_nao_lidos_diario(usuario)
        return sum(mapa.values())
    except Exception:
        return 0

def total_nao_lidos_diario_visivel(usuario, projeto_ids_visiveis):
    """Total de relatos não lidos restritos aos projetos que o usuário pode ver.
    `projeto_ids_visiveis`: lista de ints. Se vazia, retorna 0.
    Se None, retorna o total bruto (= Gestor)."""
    try:
        if projeto_ids_visiveis is None:
            return total_nao_lidos_diario(usuario)
        if not projeto_ids_visiveis:
            return 0
        ids_set = {int(x) for x in projeto_ids_visiveis}
        mapa = contar_nao_lidos_diario(usuario)
        return sum(qtd for pid, qtd in mapa.items() if pid in ids_set)
    except Exception:
        return 0


# ─── STATUS Em Espera ─────────────────────────────────────
def migrar_status_em_espera():
    """Garante índice de prioridade para ordenação no kanban Em Espera."""
    conn = conectar(); c = conn.cursor()
    try:
        c.execute("""CREATE INDEX IF NOT EXISTS idx_projetos_status_prior
                     ON projetos(status, prioridade)""")
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


# ─── MENÇÕES NO DIÁRIO ────────────────────────────────────
# Modelo: duas tabelas (mencoes_acesso + mencoes_notificacoes).
#   - mencoes_acesso: 1 linha por (usuário, projeto). UNIQUE garante idempotência.
#     Representa o "direito permanente" de ver o projeto via menção.
#   - mencoes_notificacoes: 1 linha por evento (mesmo se usuário já tinha acesso).
#     Serve pro badge "não vistas" e pro toast em tempo real.

def conceder_acesso_por_mencao(usuario, projeto_id, concedido_por, relato_id=None):
    """INSERT idempotente. Retorna True se foi NOVA concessão (pra log de auditoria
    saber se vale logar), False se o usuário já tinha acesso."""
    conn = conectar(); c = conn.cursor()
    try:
        c.execute(
            """INSERT INTO mencoes_acesso
               (usuario_mencionado, projeto_id, concedido_por, relato_id)
               VALUES (%s,%s,%s,%s)
               ON CONFLICT (usuario_mencionado, projeto_id) DO NOTHING""",
            (usuario, int(projeto_id), concedido_por, relato_id),
        )
        criou = c.rowcount > 0
        conn.commit()
    finally:
        conn.close()
    return criou

def registrar_notificacao_mencao(usuario, projeto_id, relato_id, mencionado_por, contexto='relato'):
    """Cria 1 linha de notificação por evento. contexto: 'relato' ou 'resposta_gestor'."""
    conn = conectar(); c = conn.cursor()
    try:
        c.execute(
            """INSERT INTO mencoes_notificacoes
               (usuario_mencionado, projeto_id, relato_id, mencionado_por, contexto)
               VALUES (%s,%s,%s,%s,%s)""",
            (usuario, int(projeto_id), relato_id, mencionado_por, contexto),
        )
        conn.commit()
    finally:
        conn.close()

def listar_projetos_por_mencao(usuario):
    """Retorna lista de IDs de projetos onde o usuário ganhou acesso por menção."""
    if not usuario:
        return []
    conn = conectar(); c = conn.cursor()
    try:
        c.execute(
            "SELECT projeto_id FROM mencoes_acesso WHERE usuario_mencionado = %s",
            (usuario,),
        )
        return [int(r[0]) for r in c.fetchall()]
    finally:
        conn.close()

def contar_mencoes_nao_vistas(usuario):
    """Total de notificações de menção não vistas para esse usuário."""
    if not usuario:
        return 0
    conn = conectar(); c = conn.cursor()
    try:
        c.execute(
            "SELECT COUNT(*) FROM mencoes_notificacoes "
            "WHERE usuario_mencionado = %s AND visto_em IS NULL",
            (usuario,),
        )
        return int(c.fetchone()[0] or 0)
    finally:
        conn.close()

def listar_mencoes_nao_vistas(usuario):
    """Retorna lista [(remetente, projeto_id, contexto), ...] de notificações pendentes."""
    if not usuario:
        return []
    conn = conectar(); c = conn.cursor()
    try:
        c.execute(
            "SELECT mencionado_por, projeto_id, contexto "
            "FROM mencoes_notificacoes "
            "WHERE usuario_mencionado = %s AND visto_em IS NULL "
            "ORDER BY id ASC",
            (usuario,),
        )
        return c.fetchall()
    finally:
        conn.close()

def marcar_mencoes_vistas(usuario):
    """Marca todas as notificações pendentes do usuário como vistas (= ele abriu o Diário)."""
    if not usuario:
        return
    conn = conectar(); c = conn.cursor()
    try:
        c.execute(
            "UPDATE mencoes_notificacoes SET visto_em = CURRENT_TIMESTAMP "
            "WHERE usuario_mencionado = %s AND visto_em IS NULL",
            (usuario,),
        )
        conn.commit()
    finally:
        conn.close()


# === MENÇÕES — PAINEL PERSISTENTE (dispensar manualmente) ============================
def contar_mencoes_pendentes(usuario):
    """Quantas menções AINDA aparecem no painel (não dispensadas)."""
    if not usuario:
        return 0
    conn = conectar(); c = conn.cursor()
    try:
        c.execute(
            "SELECT COUNT(*) FROM mencoes_notificacoes "
            "WHERE usuario_mencionado = %s AND dispensado_em IS NULL",
            (usuario,),
        )
        return int(c.fetchone()[0] or 0)
    finally:
        conn.close()

def listar_mencoes_pendentes(usuario):
    """Lista menções com info enriquecida pra montar o painel:
       (id, projeto_id, nome_projeto, relato_id, mencionado_por, data,
        contexto, snippet_relato)
       Ordem: mais recente primeiro."""
    if not usuario:
        return []
    conn = conectar(); c = conn.cursor()
    try:
        c.execute(
            """SELECT n.id, n.projeto_id, p.projeto, n.relato_id, n.mencionado_por,
                      n.data, n.contexto,
                      COALESCE(SUBSTR(d.executado, 1, 140), '') AS snippet
               FROM mencoes_notificacoes n
               LEFT JOIN projetos p   ON p.id = n.projeto_id
               LEFT JOIN diario   d   ON d.id = n.relato_id
               WHERE n.usuario_mencionado = %s AND n.dispensado_em IS NULL
               ORDER BY n.id DESC""",
            (usuario,),
        )
        return c.fetchall()
    finally:
        conn.close()

def dispensar_mencao(id_notif):
    """Marca UMA notificação como dispensada (clicou em fechar)."""
    conn = conectar(); c = conn.cursor()
    try:
        c.execute(
            "UPDATE mencoes_notificacoes SET dispensado_em = CURRENT_TIMESTAMP "
            "WHERE id = %s",
            (int(id_notif),),
        )
        conn.commit()
    finally:
        conn.close()

def dispensar_todas_mencoes(usuario):
    """Marca TODAS as menções pendentes do usuário como dispensadas (botão 'limpar tudo')."""
    if not usuario:
        return
    conn = conectar(); c = conn.cursor()
    try:
        c.execute(
            "UPDATE mencoes_notificacoes SET dispensado_em = CURRENT_TIMESTAMP "
            "WHERE usuario_mencionado = %s AND dispensado_em IS NULL",
            (usuario,),
        )
        conn.commit()
    finally:
        conn.close()

def listar_todas_mencoes_acesso():
    """Para a aba 'Acessos' (Gestor). Junta com nome do projeto."""
    conn = conectar(); c = conn.cursor()
    try:
        c.execute(
            """SELECT m.id, m.usuario_mencionado, m.projeto_id,
                      p.projeto, m.concedido_por, m.concedido_em
               FROM mencoes_acesso m
               LEFT JOIN projetos p ON p.id = m.projeto_id
               ORDER BY m.concedido_em DESC"""
        )
        return c.fetchall()
    finally:
        conn.close()

def revogar_mencao(id_mencao):
    """Apaga uma concessão (chamado pelo Gestor na aba Acessos)."""
    conn = conectar(); c = conn.cursor()
    try:
        c.execute("DELETE FROM mencoes_acesso WHERE id = %s", (int(id_mencao),))
        conn.commit()
    finally:
        conn.close()
