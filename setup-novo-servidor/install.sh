#!/usr/bin/env bash
# install.sh — Sobe o app Streamlit "Gestão de Projetos SERVPEN" em um servidor
# Ubuntu/Debian.  Idempotente: pode rodar várias vezes.
#
# Uso (na pasta do projeto):
#   sudo SERVER_IP="152.92.238.40" bash setup-novo-servidor/install.sh
#
# Variáveis de ambiente (opcionais):
#   SERVER_IP        IP público que o app vai aparecer (default: detecta)
#   APP_DIR          Pasta do projeto (default: /var/www/html/gestao_de_projetos)
#   STREAMLIT_PORT   Porta interna do Streamlit (default: 8501)
#   URL_PATH         Caminho do app no Apache (default: gestao-de-projetos)

set -euo pipefail

APP_DIR="${APP_DIR:-/var/www/html/gestao_de_projetos}"
SERVICE_NAME="gestao-de-projetos"
APACHE_CONF_NAME="gestao-de-projetos"
STREAMLIT_PORT="${STREAMLIT_PORT:-8501}"
URL_PATH="${URL_PATH:-gestao-de-projetos}"

# Detecta IP do servidor se SERVER_IP não foi passado
if [ -z "${SERVER_IP:-}" ]; then
    SERVER_IP="$(hostname -I | awk '{print $1}')"
    echo "==> SERVER_IP não informado; usando IP detectado: ${SERVER_IP}"
fi

echo "============================================================"
echo "Instalando em:  ${APP_DIR}"
echo "URL pública:    http://${SERVER_IP}/${URL_PATH}/"
echo "============================================================"

# --- 1/10 — Pré-requisitos básicos no projeto -------------------------------
echo "==>  1/10 Verificando ${APP_DIR}/app.py"
test -f "${APP_DIR}/app.py" || { echo "ERRO: ${APP_DIR}/app.py não encontrado. Copie o código antes." ; exit 1; }
test -f "${APP_DIR}/database.py" || { echo "ERRO: database.py não encontrado." ; exit 1; }

# --- 2/10 — Backup dos bancos antes de mexer --------------------------------
echo "==>  2/10 Backup dos bancos SQLite (se existirem)"
TS="$(date +%Y%m%d-%H%M%S)"
mkdir -p "${APP_DIR}/backups"
for db in gestao_equipe.db servpen.db; do
    if [ -f "${APP_DIR}/${db}" ]; then
        cp -a "${APP_DIR}/${db}" "${APP_DIR}/backups/${db}.${TS}.pre-install.bak"
        echo "     backup: backups/${db}.${TS}.pre-install.bak"
    fi
done

# --- 3/10 — apt packages (Python + libs CPU-safe + Apache) ------------------
echo "==>  3/10 Instalando pacotes do sistema via apt"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq --allow-releaseinfo-change
apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip python3-dev \
    build-essential libffi-dev \
    python3-numpy python3-pandas python3-pil python3-reportlab \
    apache2 sqlite3

# --- 4/10 — venv com --system-site-packages ---------------------------------
echo "==>  4/10 Criando venv Linux com --system-site-packages"
# Se existir uma venv antiga (ex.: Windows com Scripts/), reciclar
if [ -d "${APP_DIR}/venv" ]; then
    if [ -d "${APP_DIR}/venv/Scripts" ] || [ ! -f "${APP_DIR}/venv/bin/python" ]; then
        echo "     apagando venv inválida"
        rm -rf "${APP_DIR}/venv"
    fi
fi
[ -d "${APP_DIR}/venv" ] || python3 -m venv --system-site-packages "${APP_DIR}/venv"
"${APP_DIR}/venv/bin/pip" install --upgrade pip wheel

# --- 5/10 — pip libs puras-Python (sem numpy/pandas/pyarrow) ----------------
echo "==>  5/10 Instalando libs Python puras (Streamlit, Plotly, fpdf2, xlsxwriter, openpyxl)"
"${APP_DIR}/venv/bin/pip" install \
    'streamlit==1.39.0' \
    'plotly==5.24.1' \
    'fpdf2==2.8.1' \
    'xlsxwriter==3.2.0' \
    'openpyxl==3.1.5'

# --- 6/10 — Apaga wheels do PyPI que dão SIGILL em CPUs sem AVX2 ------------
# numpy/pandas/scipy/reportlab/pil já vieram do apt (baseline x86-64-v1).
# pyarrow não tem versão apt no Noble — fica AUSENTE do projeto.
# Apagar os equivalentes do venv força o Python a usar a versão do apt.
echo "==>  6/10 Removendo wheels PyPI conflitantes (caso pip tenha puxado)"
for mod in numpy pandas pyarrow scipy bottleneck numexpr; do
    rm -rf "${APP_DIR}/venv/lib/python3."*/site-packages/${mod}* 2>/dev/null || true
done
# Apaga também o ~/.local da sara (HOME = APP_DIR) — pip --user salva aqui e
# vence o venv. Já causou "pyarrow voltou dos mortos" na produção anterior.
rm -rf "${APP_DIR}/.local/lib/python3."*/site-packages/{numpy,pandas,pyarrow,scipy,bottleneck,numexpr}* 2>/dev/null || true

# --- 7/10 — Ownership + permissões -----------------------------------------
echo "==>  7/10 Ajustando dono/permissões (www-data:www-data, setgid em dirs)"
mkdir -p "${APP_DIR}/anexos" "${APP_DIR}/anexos/avatars" "${APP_DIR}/backups" "${APP_DIR}/.streamlit"
chown -R www-data:www-data "${APP_DIR}"
chmod -R u+rwX,g+rwX "${APP_DIR}"
find "${APP_DIR}" -type d -exec chmod g+s {} \; 2>/dev/null || true

# --- 8/10 — Streamlit config ------------------------------------------------
echo "==>  8/10 Escrevendo .streamlit/config.toml com SERVER_IP=${SERVER_IP}"
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

# --- 9/10 — Habilita WAL no SQLite (concorrência sem lock) ------------------
echo "==>  9/10 Habilitando WAL no banco principal"
if [ -f "${APP_DIR}/gestao_equipe.db" ]; then
    sqlite3 "${APP_DIR}/gestao_equipe.db" "PRAGMA journal_mode=WAL;" >/dev/null || true
else
    echo "     (banco ainda não existe — será criado pelo app no 1º boot e WAL é setado em conectar())"
fi

# --- 10/10 — systemd + Apache ----------------------------------------------
echo "==> 10/10 Instalando systemd unit + vhost Apache"
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

# --- Health-check final -----------------------------------------------------
echo
echo "==> Aguardando Streamlit subir..."
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
echo "============================================================"
