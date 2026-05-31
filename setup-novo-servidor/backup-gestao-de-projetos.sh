#!/usr/bin/env bash
# backup-gestao-de-projetos.sh — Dump diário do Postgres do "Gestão de Projetos
# SERVPEN". Acionado pelo timer systemd `backup-gestao-de-projetos.timer`.
#
# Operação:
#   1. `pg_dump --no-owner --no-privileges <DB>` (formato plain SQL)
#   2. comprime com gzip pro arquivo em ${APP_DIR}/backups/
#   3. ajusta permissões pra 0640 root:www-data (dado sensível)
#   4. apaga backups com mais de ${RETAIN_DAYS} dias
#   5. reporta status pro journal (visível em `journalctl -u backup-gestao-de-projetos`)
#
# Variáveis de ambiente (com defaults sensatos):
#   APP_DIR       Pasta do projeto    (default: /var/www/html/gestao_de_projetos)
#   DB_NAME       Nome do banco       (default: gestao_servpen)
#   RETAIN_DAYS   Dias de retenção    (default: 30)
#
# Restaurar de um backup específico:
#   gunzip -c backups/postgres-gestao_servpen-AAAAMMDD-HHMMSS.sql.gz \
#       | sudo -u postgres psql gestao_servpen

set -euo pipefail

APP_DIR="${APP_DIR:-/var/www/html/gestao_de_projetos}"
DB_NAME="${DB_NAME:-gestao_servpen}"
RETAIN_DAYS="${RETAIN_DAYS:-30}"

BACKUP_DIR="${APP_DIR}/backups"
TS="$(date +%Y%m%d-%H%M%S)"
OUT="${BACKUP_DIR}/postgres-${DB_NAME}-${TS}.sql.gz"

mkdir -p "${BACKUP_DIR}"

# Roda pg_dump como o user postgres (acesso natural ao DB). O pipe pra gzip
# acontece no shell deste script (root) — sem necessidade do user postgres
# ter permissão de escrita no BACKUP_DIR.
sudo -u postgres pg_dump --no-owner --no-privileges "${DB_NAME}" \
    | gzip -9 > "${OUT}"

# Permissões: dado sensível (contém hashes de senha, audit log, etc.)
chmod 0640 "${OUT}"
chown root:www-data "${OUT}" 2>/dev/null || true

# Limpa backups antigos
DELETED="$(find "${BACKUP_DIR}" -maxdepth 1 -type f \
    -name "postgres-${DB_NAME}-*.sql.gz" \
    -mtime "+${RETAIN_DAYS}" -print -delete | wc -l)"

# Reporta no journal
SIZE_HUM="$(numfmt --to=iec --suffix=B "$(stat -c%s "${OUT}")" 2>/dev/null || echo '?')"
KEPT="$(find "${BACKUP_DIR}" -maxdepth 1 -type f \
        -name "postgres-${DB_NAME}-*.sql.gz" | wc -l)"

echo "backup ok: ${OUT##*/} (${SIZE_HUM})"
echo "retenção: ${KEPT} backups mantidos, ${DELETED} apagados (>${RETAIN_DAYS}d)"
