#!/usr/bin/env bash
# install.sh — Sobe o app Streamlit "Gestão de Projetos SERVPEN" em um servidor
# Ubuntu/Debian, COM PostgreSQL como banco principal.  Idempotente: pode rodar
# várias vezes sem perder dados.
#
# Uso (na pasta do projeto):
#   sudo SERVER_IP="152.92.238.40" bash setup-novo-servidor/install.sh
#
# Variáveis de ambiente (opcionais):
#   SERVER_IP        IP público que o app vai aparecer (default: detecta)
#   APP_DIR          Pasta do projeto (default: /var/www/html/gestao_de_projetos)
#   STREAMLIT_PORT   Porta interna do Streamlit (default: 8501)
#   URL_PATH         Caminho do app no Apache (default: gestao-de-projetos)
#   DB_NAME          Nome do banco Postgres (default: gestao_servpen)
#   DB_USER          Usuário Postgres (default: gestao_servpen)
#   DB_PASSWORD      Senha do usuário Postgres (default: gerada aleatória se
#                    db.env não existir; reutilizada se já existir)
#   SKIP_MIGRATION   Se "1", pula a migração dos .db SQLite legados

set -euo pipefail

APP_DIR="${APP_DIR:-/var/www/html/gestao_de_projetos}"
SERVICE_NAME="gestao-de-projetos"
APACHE_CONF_NAME="gestao-de-projetos"
STREAMLIT_PORT="${STREAMLIT_PORT:-8501}"
URL_PATH="${URL_PATH:-gestao-de-projetos}"
DB_NAME="${DB_NAME:-gestao_servpen}"
DB_USER="${DB_USER:-gestao_servpen}"
DB_ENV_DIR="/etc/gestao-de-projetos"
DB_ENV_FILE="${DB_ENV_DIR}/db.env"

# Detecta IP do servidor se SERVER_IP não foi passado
if [ -z "${SERVER_IP:-}" ]; then
    SERVER_IP="$(hostname -I | awk '{print $1}')"
    echo "==> SERVER_IP não informado; usando IP detectado: ${SERVER_IP}"
fi

echo "============================================================"
echo "Instalando em:  ${APP_DIR}"
echo "URL pública:    http://${SERVER_IP}/${URL_PATH}/"
echo "Banco:          PostgreSQL ${DB_NAME} (usuario ${DB_USER})"
echo "============================================================"

# --- 1/12 — Pré-requisitos básicos no projeto -------------------------------
echo "==>  1/12 Verificando ${APP_DIR}/app.py"
test -f "${APP_DIR}/app.py" || { echo "ERRO: ${APP_DIR}/app.py não encontrado. Copie o código antes." ; exit 1; }
test -f "${APP_DIR}/database.py" || { echo "ERRO: database.py não encontrado." ; exit 1; }

# --- 2/12 — Backup dos bancos SQLite legados antes de migrar ----------------
echo "==>  2/12 Backup dos bancos SQLite legados (se existirem)"
TS="$(date +%Y%m%d-%H%M%S)"
mkdir -p "${APP_DIR}/backups"
for db in gestao_equipe.db servpen.db; do
    if [ -f "${APP_DIR}/${db}" ]; then
        cp -a "${APP_DIR}/${db}" "${APP_DIR}/backups/${db}.${TS}.pre-install.bak"
        echo "     backup: backups/${db}.${TS}.pre-install.bak"
    fi
done

# --- 3/12 — apt packages (Python + libs CPU-safe + Apache + PostgreSQL) -----
echo "==>  3/12 Instalando pacotes do sistema via apt"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq --allow-releaseinfo-change
apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip python3-dev \
    build-essential libffi-dev \
    python3-numpy python3-pandas python3-pil python3-reportlab \
    apache2 sqlite3 \
    postgresql postgresql-client

# --- 4/12 — PostgreSQL: garante role + database + db.env --------------------
echo "==>  4/12 Configurando PostgreSQL (role + database + senha)"

systemctl enable --now postgresql

# Se db.env já existe, reutiliza a senha; senão gera uma nova e persiste.
if [ -f "${DB_ENV_FILE}" ]; then
    # shellcheck disable=SC1090
    . "${DB_ENV_FILE}"
    echo "     db.env já existe — reutilizando credenciais"
fi
if [ -z "${DB_PASSWORD:-}" ]; then
    # openssl rand: 16 bytes hex = 32 chars [0-9a-f]. Sem pipe, sem SIGPIPE.
    # (`tr ... | head -c N` aborta o script via set -e + pipefail quando head
    # fecha o pipe — head termina antes do tr e gera SIGPIPE no tr.)
    DB_PASSWORD="$(openssl rand -hex 16)"
    echo "     senha do Postgres gerada automaticamente"
fi
# Sanity: se chegou aqui vazio é bug. Para com mensagem em vez de silenciosamente.
if [ -z "${DB_PASSWORD:-}" ]; then
    echo "ERRO: DB_PASSWORD ficou vazia após geração. Abortando." >&2
    exit 3
fi

# Cria role idempotente
sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
   IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DB_USER}') THEN
      CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASSWORD}';
   ELSE
      ALTER ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASSWORD}';
   END IF;
END
\$\$;
SQL

# Cria DB idempotente (CREATE DATABASE não suporta IF NOT EXISTS dentro de DO)
DB_EXISTS="$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'")"
if [ "${DB_EXISTS}" != "1" ]; then
    sudo -u postgres createdb -O "${DB_USER}" "${DB_NAME}"
    echo "     database ${DB_NAME} criado"
else
    sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
ALTER DATABASE ${DB_NAME} OWNER TO ${DB_USER};
SQL
    echo "     database ${DB_NAME} já existe (owner ajustado)"
fi

# Escreve /etc/gestao-de-projetos/db.env com 0640 (root:www-data)
mkdir -p "${DB_ENV_DIR}"
cat > "${DB_ENV_FILE}" <<EOF
# Gerado automaticamente por install.sh em ${TS}.
# Editar à mão é permitido; preservar permissões 0640 root:www-data.
DB_HOST=localhost
DB_PORT=5432
DB_NAME=${DB_NAME}
DB_USER=${DB_USER}
DB_PASSWORD=${DB_PASSWORD}
EOF
chown root:www-data "${DB_ENV_FILE}"
chmod 0640 "${DB_ENV_FILE}"
echo "     credenciais persistidas em ${DB_ENV_FILE}"

# Exporta pro restante do script (criar_banco + migração precisam)
export DB_HOST=localhost DB_PORT=5432 DB_NAME DB_USER DB_PASSWORD

# --- 5/12 — venv com --system-site-packages ---------------------------------
echo "==>  5/12 Criando venv Linux com --system-site-packages"
if [ -d "${APP_DIR}/venv" ]; then
    if [ -d "${APP_DIR}/venv/Scripts" ] || [ ! -f "${APP_DIR}/venv/bin/python" ]; then
        echo "     apagando venv inválida"
        rm -rf "${APP_DIR}/venv"
    fi
fi
[ -d "${APP_DIR}/venv" ] || python3 -m venv --system-site-packages "${APP_DIR}/venv"
"${APP_DIR}/venv/bin/pip" install --upgrade pip wheel

# --- 6/12 — pip libs puras-Python + psycopg3 --------------------------------
echo "==>  6/12 Instalando libs Python (Streamlit, Plotly, fpdf2, xlsxwriter, openpyxl, psycopg3)"
"${APP_DIR}/venv/bin/pip" install \
    'streamlit==1.39.0' \
    'plotly==5.24.1' \
    'fpdf2==2.8.1' \
    'xlsxwriter==3.2.0' \
    'openpyxl==3.1.5' \
    'psycopg[binary]>=3.1,<4'

# --- 7/12 — Apaga wheels do PyPI que dão SIGILL em CPUs sem AVX2 ------------
# Mantido por defesa — em CPUs modernas é no-op. numpy/pandas/scipy/reportlab/pil
# vêm do apt (baseline x86-64-v1). pyarrow continua AUSENTE.
echo "==>  7/12 Removendo wheels PyPI conflitantes (caso pip tenha puxado)"
for mod in numpy pandas pyarrow scipy bottleneck numexpr; do
    rm -rf "${APP_DIR}/venv/lib/python3."*/site-packages/${mod}* 2>/dev/null || true
done
rm -rf "${APP_DIR}/.local/lib/python3."*/site-packages/{numpy,pandas,pyarrow,scipy,bottleneck,numexpr}* 2>/dev/null || true

# --- 8/12 — Ownership + permissões -----------------------------------------
echo "==>  8/12 Ajustando dono/permissões (www-data:www-data, setgid em dirs)"
mkdir -p "${APP_DIR}/anexos" "${APP_DIR}/anexos/avatars" "${APP_DIR}/backups" "${APP_DIR}/.streamlit"
chown -R www-data:www-data "${APP_DIR}"
chmod -R u+rwX,g+rwX "${APP_DIR}"
find "${APP_DIR}" -type d -exec chmod g+s {} \; 2>/dev/null || true

# --- 9/12 — Streamlit config ------------------------------------------------
echo "==>  9/12 Escrevendo .streamlit/config.toml com SERVER_IP=${SERVER_IP}"
cat > "${APP_DIR}/.streamlit/config.toml" <<EOF
[server]
headless = true
address = "127.0.0.1"
port = ${STREAMLIT_PORT}
baseUrlPath = "${URL_PATH}"
enableCORS = false
enableXsrfProtection = false
enableWebsocketCompression = false
maxUploadSize = 100
fileWatcherType = "poll"

[browser]
gatherUsageStats = false
serverAddress = "${SERVER_IP}"
serverPort = 80

[logger]
level = "info"

[theme]
base = "dark"
EOF
chown www-data:www-data "${APP_DIR}/.streamlit/config.toml"

# --- 10/12 — Cria schema no Postgres + migra dados do SQLite (se houver) ----
echo "==> 10/12 Criando schema no Postgres + migrando dados do SQLite (se houver .db)"
sudo -u www-data \
    DATABASE_URL= DB_HOST="${DB_HOST}" DB_PORT="${DB_PORT}" \
    DB_NAME="${DB_NAME}" DB_USER="${DB_USER}" DB_PASSWORD="${DB_PASSWORD}" \
    "${APP_DIR}/venv/bin/python" -c "
import sys
sys.path.insert(0, '${APP_DIR}')
import database as db
db.criar_banco()
print('     schema garantido')
"

if [ "${SKIP_MIGRATION:-0}" != "1" ]; then
    HAS_LEGACY=0
    for f in "${APP_DIR}/gestao_equipe.db" "${APP_DIR}/servpen.db"; do
        [ -f "$f" ] && HAS_LEGACY=1
    done
    if [ "${HAS_LEGACY}" = "1" ] && [ -f "${APP_DIR}/migrar-sqlite-para-postgres.py" ]; then
        echo "     SQLite legado detectado — rodando migração de dados"
        ( cd "${APP_DIR}" && sudo -u www-data \
            DATABASE_URL= DB_HOST="${DB_HOST}" DB_PORT="${DB_PORT}" \
            DB_NAME="${DB_NAME}" DB_USER="${DB_USER}" DB_PASSWORD="${DB_PASSWORD}" \
            "${APP_DIR}/venv/bin/python" migrar-sqlite-para-postgres.py )
    else
        echo "     sem .db legado ou sem script de migração — pulando"
    fi
else
    echo "     SKIP_MIGRATION=1 — migração pulada por opção"
fi

# --- 11/12 — systemd + Apache ----------------------------------------------
echo "==> 11/12 Instalando systemd unit + vhost Apache"
DEPLOY_SRC="${APP_DIR}/setup-novo-servidor"
[ -f "${DEPLOY_SRC}/${SERVICE_NAME}.service" ] || DEPLOY_SRC="${APP_DIR}/deploy"

# systemd — substitui __APP_DIR__ pelo caminho real
sed "s|__APP_DIR__|${APP_DIR}|g" "${DEPLOY_SRC}/${SERVICE_NAME}.service" \
    > "/etc/systemd/system/${SERVICE_NAME}.service"
chmod 0644 "/etc/systemd/system/${SERVICE_NAME}.service"

touch "/var/log/${SERVICE_NAME}.log"
chown www-data:www-data "/var/log/${SERVICE_NAME}.log"

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

# Apache — substitui __SERVER_IP__ pelo IP do servidor
a2enmod proxy proxy_http rewrite headers >/dev/null
sed "s|__SERVER_IP__|${SERVER_IP}|g" "${DEPLOY_SRC}/${APACHE_CONF_NAME}.conf" \
    > "/etc/apache2/conf-available/${APACHE_CONF_NAME}.conf"
a2enconf "${APACHE_CONF_NAME}" >/dev/null
apache2ctl configtest
systemctl reload apache2

# --- 12/12 — Health-check final --------------------------------------------
echo
echo "==> 12/12 Aguardando Streamlit subir..."
for i in 1 2 3 4 5 6 7 8 9 10; do
    sleep 2
    if curl -fsS -o /dev/null -w "%{http_code}" "http://127.0.0.1:${STREAMLIT_PORT}/${URL_PATH}/_stcore/health" 2>/dev/null | grep -q 200; then
        echo "     Streamlit OK (tentativa $i)"
        break
    fi
done

echo
echo "--- status systemd ---"
systemctl --no-pager -l status "${SERVICE_NAME}" | head -12 || true
echo "--- health checks ---"
curl -sS -o /dev/null -w "  interno  : HTTP %{http_code}\n" "http://127.0.0.1:${STREAMLIT_PORT}/${URL_PATH}/_stcore/health" || true
curl -sS -o /dev/null -w "  via apache: HTTP %{http_code}\n" "http://127.0.0.1/${URL_PATH}/_stcore/health" || true

echo
echo "============================================================"
echo "DONE. Acesse: http://${SERVER_IP}/${URL_PATH}/"
echo "Login inicial: Sara Borges / Senbt0408"
echo "Logs:    tail -f /var/log/${SERVICE_NAME}.log"
echo "Serviço: systemctl status ${SERVICE_NAME}"
echo "Banco:   psql -h localhost -U ${DB_USER} ${DB_NAME}   (senha em ${DB_ENV_FILE})"
echo "============================================================"
