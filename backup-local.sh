#!/usr/bin/env bash
# backup-local.sh — backup do Postgres LOCAL (container Docker) do "Gestão de
# Projetos SERVPEN".
#
# Para o ambiente WSL+Docker (./run-local.sh), onde o banco roda DENTRO do
# container `gestao-postgres-local`. É diferente do servidor de produção, que
# usa systemd + pg_dump do Postgres do sistema (setup-novo-servidor/).
#
# Uso:
#   ./backup-local.sh
#
# Agendar (ex.: todo dia 23h via cron do WSL — `crontab -e`):
#   0 23 * * *  cd ~/gestao-de-projetos-servpen && ./backup-local.sh >> backups/backup.log 2>&1
#
# Restaurar um backup específico:
#   gunzip -c backups/local-gestao_servpen-AAAAMMDD-HHMMSS.sql.gz \
#     | docker exec -i gestao-postgres-local psql -U gestao_servpen -d gestao_servpen

set -euo pipefail
cd "$(dirname "$0")"

CONTAINER="${CONTAINER:-gestao-postgres-local}"
DB_NAME="${DB_NAME:-gestao_servpen}"
DB_USER="${DB_USER:-gestao_servpen}"
RETAIN_DAYS="${RETAIN_DAYS:-30}"

BACKUP_DIR="backups"
TS="$(date +%Y%m%d-%H%M%S)"
OUT="${BACKUP_DIR}/local-${DB_NAME}-${TS}.sql.gz"

mkdir -p "${BACKUP_DIR}"

# Container precisa estar no ar.
if ! docker exec "${CONTAINER}" pg_isready -U "${DB_USER}" -d "${DB_NAME}" \
        >/dev/null 2>&1; then
    echo "ERRO: container '${CONTAINER}' não está pronto." >&2
    echo "Suba o banco antes: ./run-local.sh (ou docker start ${CONTAINER})." >&2
    exit 1
fi

# Dump plain SQL -> gzip. --no-owner/--no-privileges facilita restaurar em
# qualquer instância.
docker exec "${CONTAINER}" \
    pg_dump --no-owner --no-privileges -U "${DB_USER}" "${DB_NAME}" \
    | gzip -9 > "${OUT}"

# Limpa backups com mais de RETAIN_DAYS dias.
DELETED="$(find "${BACKUP_DIR}" -maxdepth 1 -type f \
    -name "local-${DB_NAME}-*.sql.gz" -mtime "+${RETAIN_DAYS}" \
    -print -delete | wc -l)"

SIZE_HUM="$(numfmt --to=iec --suffix=B "$(stat -c%s "${OUT}")" 2>/dev/null \
    || echo '?')"
KEPT="$(find "${BACKUP_DIR}" -maxdepth 1 -type f \
    -name "local-${DB_NAME}-*.sql.gz" | wc -l)"

echo "backup ok: ${OUT} (${SIZE_HUM})"
echo "retenção: ${KEPT} mantidos, ${DELETED} apagados (>${RETAIN_DAYS}d)"
