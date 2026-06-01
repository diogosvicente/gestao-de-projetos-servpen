#!/usr/bin/env bash
# deploy-238.sh — Publica o código local no servidor 152.92.238.40.
#
# Como funciona:
#   1. Valida que você está num clone git, na branch certa, sem mudanças
#      não comitadas (proteção contra deploy parcial inconsistente).
#   2. Mostra a lista de COMMITS desde o último deploy (lê .last-deploy
#      do servidor via SSH).
#   3. Pede confirmação.
#   4. rsync dos arquivos do REPO (git ls-files) pro servidor —
#      preserva venv/, anexos/, backups/, .streamlit/, *.db.
#   5. SSH no servidor: chown + pip install (se requirements mudou) + restart.
#   6. Grava .last-deploy com o SHA atual.
#   7. Health check externo.
#
# Pré-requisitos no servidor:
#   - rsync, ssh, sudo configurados pro usuário admin
#   - /var/www/gestao-de-projetos com app + venv já instalados
#   - serviço systemd "gestao-de-projetos" rodando
#
# Uso:
#   ./deploy-238.sh                   # deploy normal
#   ./deploy-238.sh --dry-run         # mostra o que faria, sem enviar
#
# Para sobrescrever onde aplica:
#   REMOTE_USER=admin REMOTE_HOST=152.92.238.40 ./deploy-238.sh

set -euo pipefail

REMOTE_USER="${REMOTE_USER:-admin}"
REMOTE_HOST="${REMOTE_HOST:-152.92.238.40}"
APP_DIR="${APP_DIR:-/var/www/gestao-de-projetos}"
BASE_URL="${BASE_URL:-http://152.92.238.40/gestao-de-projetos}"
SERVICE="${SERVICE:-gestao-de-projetos}"
DRY_RUN=0

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --help|-h) sed -n '2,/^$/p' "$0" | sed 's/^# \?//'; exit 0 ;;
        *) echo "Argumento desconhecido: $arg" >&2; exit 2 ;;
    esac
done

# ── Cores ──────────────────────────────────────────────────────────
if [ -t 1 ]; then
    B=$'\033[1m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'
    BL=$'\033[34m'; C=$'\033[36m'; N=$'\033[0m'
else
    B=""; G=""; Y=""; R=""; BL=""; C=""; N=""
fi
ok()   { echo "${G}✓${N} $*"; }
info() { echo "${BL}→${N} $*"; }
warn() { echo "${Y}⚠${N} $*"; }
fail() { echo "${R}✗${N} $*" >&2; exit 1; }

cd "$(git rev-parse --show-toplevel 2>/dev/null)" \
    || fail "Você não está num repo git."

echo
echo "${B}===== Deploy: local → ${REMOTE_HOST} =====${N}"
echo "App dir:  ${APP_DIR}"
[ "${DRY_RUN}" = "1" ] && warn "DRY RUN — nada será realmente alterado"
echo

# ── Pre-checks locais ──────────────────────────────────────────────
info "Verificando working tree..."
if ! git diff --quiet || ! git diff --cached --quiet; then
    git status --short
    fail "Você tem mudanças não comitadas. Commit (ou stash) antes de deployar."
fi
ok "working tree limpo"

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
ok "branch: ${CURRENT_BRANCH}"
LOCAL_HEAD="$(git rev-parse HEAD)"
LOCAL_HEAD_SHORT="$(git rev-parse --short HEAD)"

# ── Lê .last-deploy do servidor ────────────────────────────────────
info "Lendo último deploy no servidor..."
LAST_SHA="$(ssh -o StrictHostKeyChecking=accept-new \
    "${REMOTE_USER}@${REMOTE_HOST}" \
    "cat ${APP_DIR}/.last-deploy 2>/dev/null || true" \
    | tr -d '[:space:]')"

if [ -z "${LAST_SHA}" ]; then
    warn ".last-deploy não encontrado — primeiro deploy ou foi apagado."
elif [ "${LAST_SHA}" = "${LOCAL_HEAD}" ]; then
    ok "Servidor já está em ${LOCAL_HEAD_SHORT} — nada a fazer"
    echo
    info "App: ${BASE_URL}/"
    exit 0
elif ! git cat-file -e "${LAST_SHA}" 2>/dev/null; then
    warn "Commit ${LAST_SHA:0:7} (.last-deploy) não existe localmente."
    warn "Pode ter sido deployado de outra máquina/branch."
    LAST_SHA=""
else
    ok "Último deploy: ${LAST_SHA:0:7} ($(git log -1 --format='%cr' "${LAST_SHA}"))"
fi

# ── Mostra commits a deployar (se tem como comparar) ───────────────
echo
if [ -n "${LAST_SHA}" ]; then
    echo "${B}Commits desde o último deploy:${N}"
    git log --oneline "${LAST_SHA}..HEAD" | sed 's/^/    /'
    echo
    echo "${B}Arquivos a publicar:${N}"
    git diff --name-status "${LAST_SHA}" HEAD | sed 's/^/    /'
else
    echo "${B}Vai enviar tudo do repo (primeiro deploy):${N}"
    git ls-files | sed 's/^/    /'
    echo
    git ls-files | wc -l | xargs printf "    Total: %s arquivo(s) rastreados pelo git\n"
fi
echo

if [ "${DRY_RUN}" != "1" ]; then
    read -r -p "${B}Deploy agora? [y/N]${N} " resp
    [ "${resp}" = "y" ] || [ "${resp}" = "Y" ] || fail "abortado pelo user"
fi

# ── Detecta se requirements.txt mudou ──────────────────────────────
REQUIREMENTS_CHANGED=0
if [ -n "${LAST_SHA}" ]; then
    git diff --name-only "${LAST_SHA}" HEAD | grep -qx "requirements.txt" \
        && REQUIREMENTS_CHANGED=1
fi

# ── rsync (somente arquivos rastreados pelo git) ───────────────────
echo
info "Transferindo arquivos via rsync..."

TMPLIST="$(mktemp)"
trap 'rm -f "$TMPLIST"' EXIT
git ls-files > "${TMPLIST}"

if [ "${DRY_RUN}" = "1" ]; then
    echo "  ${Y}[dry-run]${N} rsync -avzc --files-from=<lista> ./ ${REMOTE_USER}@${REMOTE_HOST}:${APP_DIR}/"
    echo "  ${Y}[dry-run]${N} $(wc -l < "${TMPLIST}") arquivos seriam enviados"
else
    rsync -avzc --files-from="${TMPLIST}" \
        ./ "${REMOTE_USER}@${REMOTE_HOST}:${APP_DIR}/"
fi
ok "rsync terminou"

# ── SSH: chown + pip + restart ─────────────────────────────────────
echo
info "Ajustando permissões + restart no servidor..."

REMOTE_CMDS="set -e
sudo chown -R www-data:www-data ${APP_DIR}
sudo find ${APP_DIR} -type d -exec chmod g+s {} \\; 2>/dev/null || true"

if [ "${REQUIREMENTS_CHANGED}" = "1" ]; then
    REMOTE_CMDS+="
echo '==> requirements.txt mudou — pip install'
sudo ${APP_DIR}/venv/bin/pip install --upgrade -r ${APP_DIR}/requirements.txt"
fi

REMOTE_CMDS+="
echo '==> systemctl restart ${SERVICE}'
sudo systemctl restart ${SERVICE}
sleep 2
sudo systemctl --no-pager -l status ${SERVICE} | head -8"

if [ "${DRY_RUN}" = "1" ]; then
    echo "  ${Y}[dry-run]${N} comandos remotos:"
    echo "${REMOTE_CMDS}" | sed 's/^/    /'
else
    echo "${C}─── output remoto ─────────────────────────────────${N}"
    ssh -t "${REMOTE_USER}@${REMOTE_HOST}" "bash -s" <<< "${REMOTE_CMDS}"
    echo "${C}───────────────────────────────────────────────────${N}"
fi
ok "restart OK"

# ── Atualiza .last-deploy ──────────────────────────────────────────
if [ "${DRY_RUN}" != "1" ]; then
    ssh "${REMOTE_USER}@${REMOTE_HOST}" \
        "echo '${LOCAL_HEAD}' | sudo tee ${APP_DIR}/.last-deploy >/dev/null"
    ok ".last-deploy = ${LOCAL_HEAD_SHORT}"
fi

# ── Health check externo ───────────────────────────────────────────
if [ "${DRY_RUN}" != "1" ]; then
    echo
    info "Health check externo..."
    HTTP="$(curl -fsS -o /dev/null -w '%{http_code}' \
        "${BASE_URL}/_stcore/health" 2>/dev/null || echo 000)"
    if [ "${HTTP}" = "200" ]; then
        ok "${BASE_URL}/_stcore/health → HTTP 200"
    else
        warn "health check retornou HTTP ${HTTP}"
        warn "log: ssh ${REMOTE_USER}@${REMOTE_HOST} 'sudo journalctl -u ${SERVICE} -n 50 --no-pager'"
        exit 3
    fi
fi

echo
echo "${G}${B}===== Deploy concluído =====${N}"
echo "App: ${BASE_URL}/"
[ -n "${LAST_SHA}" ] && {
    echo
    echo "Rollback (se algo deu errado):"
    echo "  git checkout ${LAST_SHA:0:7}"
    echo "  ./deploy-238.sh"
    echo "  git checkout ${CURRENT_BRANCH}"
}
echo
