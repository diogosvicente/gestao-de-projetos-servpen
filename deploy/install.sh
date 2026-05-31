#!/usr/bin/env bash
# install.sh - Deploy idempotente do app Streamlit Gestao de Projetos
# Rodar como root (ou via sudo) no servidor 152.92.228.20.
set -euo pipefail

# Auto-detecta APP_DIR como o diretorio acima de deploy/ (onde este script vive)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SERVICE_NAME="gestao-de-projetos"
APACHE_CONF_NAME="gestao-de-projetos"
PY_BIN="python3"
echo "APP_DIR detectado: ${APP_DIR}"

echo "==> 1/9 Verificando pre-requisitos do projeto em ${APP_DIR}"
test -f "${APP_DIR}/app.py" || { echo "ERRO: ${APP_DIR}/app.py nao encontrado"; exit 1; }
test -f "${APP_DIR}/requirements.txt" || { echo "ERRO: requirements.txt nao encontrado"; exit 1; }

echo "==> 2/9 Backup dos bancos SQLite (com timestamp)"
TS="$(date +%Y%m%d-%H%M%S)"
mkdir -p "${APP_DIR}/backups"
for db in servpen.db gestao_equipe.db; do
    if [ -f "${APP_DIR}/${db}" ]; then
        cp -a "${APP_DIR}/${db}" "${APP_DIR}/backups/${db}.${TS}.bak"
        echo "   backup: backups/${db}.${TS}.bak"
    fi
done

echo "==> 3/9 Instalando Python3 + venv + build tools (apt)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq --allow-releaseinfo-change
apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip python3-dev \
    build-essential libffi-dev

echo "==> 4/9 Removendo venv antigo (Windows) e criando venv Linux"
if [ -d "${APP_DIR}/venv" ]; then
    # Se for o venv Windows (tem Scripts/), apagamos
    if [ -d "${APP_DIR}/venv/Scripts" ] || [ ! -f "${APP_DIR}/venv/bin/python" ]; then
        echo "   apagando venv Windows existente"
        rm -rf "${APP_DIR}/venv"
    fi
fi
if [ ! -d "${APP_DIR}/venv" ]; then
    ${PY_BIN} -m venv "${APP_DIR}/venv"
fi
"${APP_DIR}/venv/bin/pip" install --upgrade pip wheel
"${APP_DIR}/venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

echo "==> 5/9 Ajustando ownership para www-data (necessario para systemd)"
chown -R www-data:www-data "${APP_DIR}"
# Pasta anexos e backups precisam ser graváveis
mkdir -p "${APP_DIR}/anexos" "${APP_DIR}/backups"
chown -R www-data:www-data "${APP_DIR}/anexos" "${APP_DIR}/backups"
chmod -R u+rwX,g+rwX "${APP_DIR}"

echo "==> 6/9 Instalando service systemd (substituindo __APP_DIR__ por ${APP_DIR})"
sed "s|__APP_DIR__|${APP_DIR}|g" "${APP_DIR}/deploy/${SERVICE_NAME}.service" \
    > "/etc/systemd/system/${SERVICE_NAME}.service"
chmod 0644 "/etc/systemd/system/${SERVICE_NAME}.service"
touch /var/log/${SERVICE_NAME}.log
chown www-data:www-data /var/log/${SERVICE_NAME}.log
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

echo "==> 7/9 Habilitando modulos Apache"
a2enmod proxy proxy_http proxy_wstunnel rewrite headers >/dev/null

echo "==> 8/9 Instalando conf do Apache"
install -m 0644 "${APP_DIR}/deploy/${APACHE_CONF_NAME}.conf" "/etc/apache2/conf-available/${APACHE_CONF_NAME}.conf"
a2enconf "${APACHE_CONF_NAME}" >/dev/null
apache2ctl configtest
systemctl reload apache2

echo "==> 9/9 Aguardando Streamlit subir e testando endpoint"
for i in 1 2 3 4 5 6 7 8 9 10; do
    sleep 2
    if curl -fsS -o /dev/null -w "%{http_code}" "http://127.0.0.1:8501/gestao-de-projetos/_stcore/health" 2>/dev/null | grep -q 200; then
        echo "   Streamlit OK (tentativa $i)"
        break
    fi
done
echo "--- status streamlit ---"
systemctl --no-pager -l status "${SERVICE_NAME}" | head -15 || true
echo "--- health interno ---"
curl -sS -o /dev/null -w "interno  : HTTP %{http_code}\n" "http://127.0.0.1:8501/gestao-de-projetos/_stcore/health" || true
echo "--- via apache ---"
curl -sS -o /dev/null -w "via apache: HTTP %{http_code}\n" "http://127.0.0.1/gestao-de-projetos/_stcore/health" || true

echo
echo "============================================================"
echo "DONE. Acesse: http://152.92.228.20/gestao-de-projetos/"
echo "Logs: tail -f /var/log/${SERVICE_NAME}.log"
echo "Servico: systemctl status ${SERVICE_NAME}"
echo "============================================================"
