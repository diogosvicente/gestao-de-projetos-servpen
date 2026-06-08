#!/usr/bin/env bash
# limpar-projeto.sh — Remove arquivos obsoletos/lixo do projeto.
#
# Após a modularização (app.py monolítico → core/ + views/) e a migração
# SQLite → PostgreSQL, vários arquivos ficaram órfãos. Este script limpa
# três categorias:
#
#   1. LIXO NÃO-RASTREADO (não está no git, regenerável ou backup velho):
#        - app.py.bak-*           (backups pré-modularização)
#        - **/__pycache__, *.pyc  (cache do Python)
#
#   2. BANCOS SQLITE ANTIGOS (dados originais pré-Postgres; prod já roda PG):
#        - gestao_equipe.db, servpen.db
#
#   3. OBSOLETOS RASTREADOS PELO GIT (substituídos pelo fluxo atual):
#        - deploy/                  → duplicata de setup-novo-servidor/
#        - atualizar.sh             → dev script com path antigo (228.20)
#        - publicar-no-238.40.sh    → substituído por deploy-238.sh
#        - COMO-ATUALIZAR.md        → doc do fluxo antigo
#        - seed.py                  → stub obsoleto (só imprime erro e sai)
#
# SEGURANÇA:
#   - Mostra TUDO que vai remover e pede confirmação (use --yes pra pular).
#   - Categoria 3 usa `git rm` (deixa STAGED). O script NÃO commita nem dá
#     push — você revisa, commita e faz push manualmente.
#
# Uso:
#   ./limpar-projeto.sh             # mostra o plano e pede confirmação
#   ./limpar-projeto.sh --dry-run   # só mostra, não remove nada
#   ./limpar-projeto.sh --yes       # remove sem perguntar

set -euo pipefail
cd "$(dirname "$0")"

DRY_RUN=0
ASSUME_YES=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --yes|-y)  ASSUME_YES=1 ;;
        --help|-h) sed -n '2,/^$/p' "$0" | sed 's/^# \?//'; exit 0 ;;
        *) echo "Argumento desconhecido: $arg" >&2; exit 2 ;;
    esac
done

if [ -t 1 ]; then
    B=$'\033[1m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; N=$'\033[0m'
else
    B=""; G=""; Y=""; R=""; N=""
fi

# ── Itens rastreados pelo git a remover (git rm) ───────────────────
TRACKED_OBSOLETOS=(
    "deploy"
    "atualizar.sh"
    "publicar-no-238.40.sh"
    "COMO-ATUALIZAR.md"
    "seed.py"
)

# ── Bancos SQLite antigos (delete de vez, conforme escolhido) ──────
SQLITE_ANTIGOS=(
    "gestao_equipe.db"
    "servpen.db"
)

echo
echo "${B}===== Limpeza do projeto =====${N}"
[ "$DRY_RUN" = "1" ] && echo "${Y}DRY RUN — nada será removido${N}"
echo

# ── 1) Preview: lixo não-rastreado ─────────────────────────────────
echo "${B}1) Lixo não-rastreado (backups + cache):${N}"
BAK_FILES=$(ls -1 app.py.bak-* 2>/dev/null || true)
PYCACHE=$(find . -path ./venv -prune -o -name '__pycache__' -type d -print \
          2>/dev/null || true)
if [ -n "$BAK_FILES" ]; then echo "$BAK_FILES" | sed 's/^/    /'; fi
if [ -n "$PYCACHE" ];   then echo "$PYCACHE"   | sed 's/^/    /'; fi
[ -z "$BAK_FILES$PYCACHE" ] && echo "    (nada)"
echo

# ── 2) Preview: SQLite antigos ─────────────────────────────────────
echo "${B}2) Bancos SQLite antigos (DELETE permanente):${N}"
for db in "${SQLITE_ANTIGOS[@]}"; do
    [ -f "$db" ] && echo "    $db ($(du -h "$db" | cut -f1))"
done
echo

# ── 3) Preview: obsoletos rastreados ───────────────────────────────
echo "${B}3) Obsoletos rastreados pelo git (git rm → staged):${N}"
for item in "${TRACKED_OBSOLETOS[@]}"; do
    if git ls-files --error-unmatch "$item" >/dev/null 2>&1 \
       || [ -e "$item" ]; then
        echo "    $item"
    fi
done
echo

if [ "$DRY_RUN" = "1" ]; then
    echo "${Y}DRY RUN — fim. Rode sem --dry-run pra aplicar.${N}"
    exit 0
fi

# ── Confirmação ────────────────────────────────────────────────────
if [ "$ASSUME_YES" != "1" ]; then
    echo "${R}${B}Isto vai apagar os itens acima (cat. 1 e 2 sem volta).${N}"
    read -r -p "${B}Continuar? [y/N]${N} " resp
    [ "$resp" = "y" ] || [ "$resp" = "Y" ] || { echo "abortado."; exit 1; }
fi
echo

# ── Executa 1) lixo não-rastreado ──────────────────────────────────
echo "${B}→ Removendo lixo não-rastreado...${N}"
rm -f app.py.bak-* 2>/dev/null || true
find . -path ./venv -prune -o -name '__pycache__' -type d \
    -exec rm -rf {} + 2>/dev/null || true
find . -path ./venv -prune -o -name '*.pyc' -type f \
    -delete 2>/dev/null || true
echo "${G}✓${N} lixo removido"

# ── Executa 2) SQLite antigos ──────────────────────────────────────
echo "${B}→ Apagando bancos SQLite antigos...${N}"
for db in "${SQLITE_ANTIGOS[@]}"; do
    if [ -f "$db" ]; then
        rm -f "$db"
        echo "${G}✓${N} $db apagado"
    fi
done

# ── Executa 3) git rm dos obsoletos ────────────────────────────────
echo "${B}→ Removendo obsoletos rastreados (git rm)...${N}"
for item in "${TRACKED_OBSOLETOS[@]}"; do
    if git ls-files --error-unmatch "$item" >/dev/null 2>&1; then
        git rm -r --quiet "$item"
        echo "${G}✓${N} git rm $item"
    elif [ -e "$item" ]; then
        # Existe mas não rastreado (caso raro) — remove direto
        rm -rf "$item"
        echo "${G}✓${N} rm $item (não estava no git)"
    fi
done

echo
echo "${G}${B}===== Limpeza concluída =====${N}"
echo
echo "As remoções do git estão ${B}staged${N} (não commitadas)."
echo "Revise e finalize você mesmo:"
echo
echo "    git status"
echo "    git commit -m \"chore: remove arquivos obsoletos pós-modularização\""
echo "    git push        ${Y}# (você faz o push)${N}"
echo
