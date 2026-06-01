#!/usr/bin/env bash
# deploy.sh — Envia atualizações da máquina local pro servidor de produção,
# SEM exigir git no servidor.
#
# Como funciona:
#   1. Valida working tree local + branch (precisa de git LOCAL — o dev tem)
#   2. Lê `.last-deploy` do servidor (SHA do último deploy)
#   3. Mostra os arquivos que mudaram localmente desde aquele SHA
#      (via `git diff --numstat`)
#   4. Pede MODO: [A]plicar todos / [I]nterativo / [V]er diff / [C]ancelar
#   5. Transfere via rsync (lista completa OU --files-from se interativo)
#   6. SSH no servidor pra: chown + pip (se requirements mudou) + restart
#   7. Health check externo
#   8. Grava `.last-deploy` com o SHA atual pra o próximo deploy
#
# Pré-requisitos no servidor (1ª vez):
#   - Pasta /var/www/gestao-de-projetos já existe (com app.py, etc.)
#   - rsync instalado (vem com SSH em Ubuntu/Debian)
#   - Usuário admin com SSH + sudo
#   - venv já criado em /var/www/gestao-de-projetos/venv
#
# Pré-requisitos no PC local:
#   - git, rsync, ssh, curl
#   - SSH configurado (chave) — `ssh-copy-id admin@152.92.238.40`
#
# Uso:
#   ./deploy.sh                  # deploy normal
#   ./deploy.sh --dry-run        # mostra o que faria, sem alterar nada
#   ./deploy.sh --branch=hotfix  # deploy de outra branch

set -euo pipefail

# ── CONFIG ──────────────────────────────────────────────────────────
REMOTE_USER="${REMOTE_USER:-admin}"
REMOTE_HOST="${REMOTE_HOST:-152.92.238.40}"
APP_DIR="${APP_DIR:-/var/www/gestao-de-projetos}"
BASE_URL="${BASE_URL:-http://152.92.238.40/gestao-de-projetos}"
BRANCH="main"
DRY_RUN=0

# Pastas/arquivos que NUNCA são sobrescritos no servidor (preservados):
PRESERVAR=(
    "venv"           # ambiente Python (recriar custa caro)
    "anexos"         # uploads dos usuários
    "backups"        # histórico
    ".streamlit"     # config.toml gerado com SERVER_IP
    "*.db"           # SQLite legado se houver
    ".env"
    "db.env"
    "__pycache__"
    ".git"           # se um dia colocarem git no servidor
    "*.bak-*"        # backups antigos do app.py
    ".last-deploy"   # marca de SHA do último deploy (gerenciada por este script)
)

# ── PARSE DE ARGS ───────────────────────────────────────────────────
for arg in "$@"; do
    case "$arg" in
        --dry-run)        DRY_RUN=1 ;;
        --branch=*)       BRANCH="${arg#*=}" ;;
        --help|-h)
            sed -n '2,/^$/p' "$0" | sed 's/^# \?//'
            exit 0 ;;
        *) echo "Argumento desconhecido: $arg" >&2; exit 2 ;;
    esac
done

# ── CORES ──────────────────────────────────────────────────────────
if [ -t 1 ]; then
    BOLD=$'\033[1m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'
    RED=$'\033[31m'; BLUE=$'\033[34m'; CYAN=$'\033[36m'; RESET=$'\033[0m'
else
    BOLD=""; GREEN=""; YELLOW=""; RED=""; BLUE=""; CYAN=""; RESET=""
fi

ok()    { echo "${GREEN}✓${RESET} $*"; }
info()  { echo "${BLUE}→${RESET} $*"; }
warn()  { echo "${YELLOW}⚠${RESET} $*"; }
fail()  { echo "${RED}✗${RESET} $*" >&2; exit 1; }

# Roda comando local respeitando dry-run
run_local() {
    if [ "${DRY_RUN}" = "1" ]; then
        echo "  ${YELLOW}[dry-run]${RESET} $*"
    else
        eval "$@"
    fi
}

# SSH não-interativo (captura output)
remote() {
    ssh -o LogLevel=ERROR -o StrictHostKeyChecking=accept-new \
        "${REMOTE_USER}@${REMOTE_HOST}" "$@"
}

# ── 0. CD pro root do repo (rsync precisa do path correto) ──────────
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[ -n "${REPO_ROOT}" ] || fail "Você não está dentro de um repo git."
cd "${REPO_ROOT}"

# ── HEADER ──────────────────────────────────────────────────────────
echo
echo "${BOLD}===== Deploy: local → ${REMOTE_HOST} =====${RESET}"
echo "Branch:   ${BOLD}${BRANCH}${RESET}"
echo "Remote:   ${REMOTE_USER}@${REMOTE_HOST}"
echo "App dir:  ${APP_DIR}"
[ "${DRY_RUN}" = "1" ] && warn "DRY RUN — nada será realmente executado"
echo

# ── 1. WORKING TREE LIMPO? ──────────────────────────────────────────
info "Verificando working tree local..."
if ! git diff --quiet || ! git diff --cached --quiet; then
    git status --short
    fail "Você tem mudanças não comitadas. Commit (ou stash) antes de deployar."
fi
ok "working tree limpo"

# ── 2. BRANCH CORRETA? ──────────────────────────────────────────────
CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "${CURRENT_BRANCH}" != "${BRANCH}" ]; then
    warn "Você está em ${BOLD}${CURRENT_BRANCH}${RESET}, esperado ${BOLD}${BRANCH}${RESET}."
    read -r -p "Continuar mesmo assim? [y/N] " resp
    [ "${resp}" = "y" ] || [ "${resp}" = "Y" ] || fail "abortado pelo user"
fi
ok "branch: ${CURRENT_BRANCH}"

LOCAL_HEAD="$(git rev-parse HEAD)"
LOCAL_HEAD_SHORT="$(git rev-parse --short HEAD)"

# ── 3. LÊ .last-deploy DO SERVIDOR ──────────────────────────────────
info "Lendo último deploy no servidor..."
LAST_SHA="$(remote "cat ${APP_DIR}/.last-deploy 2>/dev/null || echo ''" || echo '')"
LAST_SHA="$(echo "${LAST_SHA}" | tr -d '[:space:]')"

if [ -z "${LAST_SHA}" ]; then
    warn "Sem registro de último deploy (.last-deploy não encontrado)."
    USE_GIT_DIFF=0
elif [ "${LAST_SHA}" = "${LOCAL_HEAD}" ]; then
    ok "Servidor já está no commit ${LOCAL_HEAD_SHORT} — nada a deployar"
    echo
    info "App: ${BASE_URL}/"
    exit 0
elif ! git cat-file -e "${LAST_SHA}" 2>/dev/null; then
    warn "Commit ${LAST_SHA:0:7} (último deploy) não existe no repo local."
    warn "Pode ter sido feito de outra máquina ou de uma branch que não está aqui."
    USE_GIT_DIFF=0
else
    ok "Último deploy: ${LAST_SHA:0:7} ($(git log -1 --format='%cr' "${LAST_SHA}"))"
    USE_GIT_DIFF=1
fi

# ── 4. LISTA DE ARQUIVOS A ALTERAR ──────────────────────────────────
if [ "${USE_GIT_DIFF}" = "1" ]; then
    # Caso normal — usa diff local entre LAST_SHA e HEAD
    NUMSTAT="$(git diff --numstat "${LAST_SHA}" HEAD -- \
        $(printf ":(exclude)%s " "${PRESERVAR[@]}"))"
    DIFF_SOURCE="git diff ${LAST_SHA:0:7}..HEAD"
else
    # Primeiro deploy — lista ARQUIVOS DO GIT (não do filesystem todo).
    #
    # Por que `git ls-files` em vez de `rsync --dry-run ./`:
    #   rsync vê o filesystem inteiro: pega .local/, .cache/, IDE folders,
    #   __pycache__, arquivos temp, etc. Mesmo com `--exclude`, é fácil
    #   esquecer alguma pasta nova. `git ls-files` é a verdade absoluta
    #   sobre "o que pertence ao projeto" — se não está no git, não vai.
    #
    # Listamos só "?    ?    arquivo" (sem +/- linhas — não temos como
    # saber sem ter o estado do servidor pra comparar).
    info "Listando arquivos rastreados pelo git..."
    NUMSTAT="$(git ls-files | awk '$0 != "" {print "?\t?\t" $0}')"
    DIFF_SOURCE="git ls-files (primeiro deploy)"
fi

if [ -z "${NUMSTAT}" ] || ! echo "${NUMSTAT}" | grep -q .; then
    ok "Sem diferenças detectadas — nada a deployar"
    echo
    info "App: ${BASE_URL}/"
    exit 0
fi

TOTAL_FILES=$(echo "${NUMSTAT}" | grep -c . || true)
if [ "${USE_GIT_DIFF}" = "1" ]; then
    TOTAL_ADD=$(echo "${NUMSTAT}" | awk '{s+=$1} END {print s}')
    TOTAL_DEL=$(echo "${NUMSTAT}" | awk '{s+=$2} END {print s}')
fi

echo
echo "${BOLD}Arquivos a serem alterados (${TOTAL_FILES}, fonte: ${DIFF_SOURCE}):${RESET}"
echo "${NUMSTAT}" | awk -v g="${GREEN}" -v r="${RED}" -v R="${RESET}" \
    '{printf "    %s+%s%s / %s-%s%s   %s\n", g, $1, R, r, $2, R, $3}'
if [ "${USE_GIT_DIFF}" = "1" ]; then
    echo
    echo "${BOLD}Total: ${GREEN}+${TOTAL_ADD}${RESET} ${BOLD}/${RESET} ${RED}-${TOTAL_DEL}${RESET} linhas em ${TOTAL_FILES} arquivo(s)"
fi
echo

# ── 5. MENU DE MODO ─────────────────────────────────────────────────
choose_mode() {
    while true; do
        echo "${BOLD}Como aplicar?${RESET}"
        echo "  ${BOLD}[A]${RESET}plicar todos          (rsync de tudo de uma vez)"
        echo "  ${BOLD}[I]${RESET}nterativo             (confirmar 1 por 1 — pode quebrar deps)"
        if [ "${USE_GIT_DIFF}" = "1" ]; then
            echo "  ${BOLD}[V]${RESET}er diff completo      (git diff paginado, volta ao menu)"
        fi
        echo "  ${BOLD}[C]${RESET}ancelar               (nada será aplicado)"
        read -r -p "Escolha [A/i/v/c]: " choice
        case "${choice:-a}" in
            a|A) echo "all";    return ;;
            i|I) echo "inter";  return ;;
            v|V)
                if [ "${USE_GIT_DIFF}" = "1" ]; then
                    echo "view"; return
                else
                    warn "Opção [V] indisponível (primeiro deploy)."
                fi ;;
            c|C) echo "cancel"; return ;;
            *) warn "opção inválida" ;;
        esac
    done
}

while true; do
    MODE=$(choose_mode)
    case "${MODE}" in
        cancel)
            warn "Cancelado. NADA foi aplicado no servidor."
            exit 0
            ;;
        view)
            echo
            info "Diff completo (q pra sair):"
            git diff "${LAST_SHA}" HEAD -- \
                $(printf ":(exclude)%s " "${PRESERVAR[@]}") \
                | less -R
            echo
            ;;
        all|inter)
            break
            ;;
    esac
done

# ── 6. DEFINE LISTA FINAL DE ARQUIVOS ───────────────────────────────
FILES_TO_TRANSFER=()
REQUIREMENTS_CHANGED=0

if [ "${MODE}" = "all" ]; then
    while IFS=$'\t' read -r _ _ f; do
        [ -n "$f" ] && FILES_TO_TRANSFER+=("$f")
    done <<< "${NUMSTAT}"
    [ "$(echo "${NUMSTAT}" | awk '$3=="requirements.txt"' | wc -l)" -gt 0 ] && REQUIREMENTS_CHANGED=1

elif [ "${MODE}" = "inter" ]; then
    warn "Modo interativo — pular arquivos PODE quebrar dependências."
    warn "  Ex.: aceitar 'views/dashboard.py' mas pular 'core/helpers.py'"
    warn "  pode causar ImportError se dashboard usa um helper novo."
    echo

    ACCEPTED=()
    SKIPPED=()
    IDX=0
    while IFS=$'\t' read -r added removed filename; do
        [ -z "$filename" ] && continue
        IDX=$((IDX + 1))
        echo
        echo "${BOLD}[${IDX}/${TOTAL_FILES}]${RESET} ${filename}  ${GREEN}+${added}${RESET} / ${RED}-${removed}${RESET}"

        while true; do
            read -r -p "  [Y]aceitar / [n]pular / [v]er diff / [q]cancelar tudo: " ans
            case "${ans:-y}" in
                y|Y|"")
                    ACCEPTED+=("${filename}")
                    [ "${filename}" = "requirements.txt" ] && REQUIREMENTS_CHANGED=1
                    ok "    aceito"; break ;;
                n|N)
                    SKIPPED+=("${filename}")
                    warn "    pulado"; break ;;
                v|V)
                    if [ "${USE_GIT_DIFF}" = "1" ]; then
                        echo "  ${CYAN}--- diff ---${RESET}"
                        git diff "${LAST_SHA}" HEAD -- "${filename}" | head -60
                        echo "  ${CYAN}--- fim do diff ---${RESET}"
                    else
                        warn "diff individual indisponível (sem .last-deploy)"
                    fi ;;
                q|Q)
                    warn "Cancelado. NADA foi aplicado no servidor."
                    exit 0 ;;
                *) warn "opção inválida" ;;
            esac
        done
    done <<< "${NUMSTAT}"

    FILES_TO_TRANSFER=("${ACCEPTED[@]}")

    echo
    echo "${BOLD}Resumo:${RESET}"
    echo "  Aceitos: ${#ACCEPTED[@]}"
    echo "  Pulados: ${#SKIPPED[@]}"

    if [ ${#FILES_TO_TRANSFER[@]} -eq 0 ]; then
        warn "Nenhum arquivo aceito. Saindo sem aplicar nada."
        exit 0
    fi

    echo
    read -r -p "Aplicar os ${#FILES_TO_TRANSFER[@]} aceitos no servidor? [Y/n] " resp
    case "${resp:-y}" in
        n|N) fail "abortado pelo user" ;;
    esac
fi

# ── 7. RSYNC PRA O SERVIDOR ─────────────────────────────────────────
echo
info "Transferindo ${#FILES_TO_TRANSFER[@]} arquivo(s) via rsync..."

# SEMPRE usa --files-from com lista explícita.
# Garante que SÓ arquivos do repo são enviados — nada de .local/, .cache/,
# IDE folders, __pycache__, secrets, ou qualquer coisa que esteja no
# filesystem mas não no git.
TMPLIST="$(mktemp)"
trap 'rm -f "$TMPLIST"' EXIT
printf '%s\n' "${FILES_TO_TRANSFER[@]}" > "${TMPLIST}"

if [ "${DRY_RUN}" = "1" ]; then
    echo "  ${YELLOW}[dry-run]${RESET} rsync -avzc --files-from=<lista> ./ ${REMOTE_USER}@${REMOTE_HOST}:${APP_DIR}/"
    echo "  ${YELLOW}[dry-run]${RESET} arquivos que seriam enviados (${#FILES_TO_TRANSFER[@]}):"
    sed 's/^/    /' "${TMPLIST}"
else
    rsync -avzc --files-from="${TMPLIST}" \
        ./ "${REMOTE_USER}@${REMOTE_HOST}:${APP_DIR}/"
fi
ok "rsync terminou"

# ── 8. SSH: chown + pip + restart ──────────────────────────────────
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
echo '==> systemctl restart gestao-de-projetos'
sudo systemctl restart gestao-de-projetos
sleep 2
sudo systemctl --no-pager -l status gestao-de-projetos | head -8"

if [ "${DRY_RUN}" = "1" ]; then
    echo "  ${YELLOW}[dry-run]${RESET} (script remoto):"
    echo "${REMOTE_CMDS}" | sed 's/^/    /'
else
    echo "${CYAN}─── output remoto ─────────────────────────────────${RESET}"
    ssh -t "${REMOTE_USER}@${REMOTE_HOST}" "bash -s" <<< "${REMOTE_CMDS}"
    echo "${CYAN}───────────────────────────────────────────────────${RESET}"
fi
ok "restart OK"

# ── 9. ATUALIZA .last-deploy ────────────────────────────────────────
# Só atualiza se foi modo [A]. Modo [I] deixa servidor em estado misto;
# atualizar .last-deploy enganaria o próximo deploy.
if [ "${MODE}" = "all" ] && [ "${DRY_RUN}" != "1" ]; then
    remote "echo '${LOCAL_HEAD}' | sudo tee ${APP_DIR}/.last-deploy >/dev/null" \
        && ok "registro .last-deploy atualizado pra ${LOCAL_HEAD_SHORT}"
fi

# ── 10. HEALTH CHECK ────────────────────────────────────────────────
if [ "${DRY_RUN}" != "1" ]; then
    echo
    info "Health check externo..."
    HTTP="$(curl -fsS -o /dev/null -w '%{http_code}' \
        "${BASE_URL}/_stcore/health" 2>/dev/null || echo 000)"
    if [ "${HTTP}" = "200" ]; then
        ok "${BASE_URL}/_stcore/health → HTTP 200"
    else
        warn "health check retornou HTTP ${HTTP}"
        warn "olha o log: ssh ${REMOTE_USER}@${REMOTE_HOST} 'sudo journalctl -u gestao-de-projetos -n 50 --no-pager'"
        exit 3
    fi
fi

# ── 11. RESUMO + ROLLBACK INFO ──────────────────────────────────────
echo
echo "${GREEN}${BOLD}===== Deploy concluído =====${RESET}"
echo "App: ${BASE_URL}/"
echo

if [ "${MODE}" = "inter" ] && [ ${#SKIPPED[@]:-0} -gt 0 ]; then
    warn "Atenção: você PULOU ${#SKIPPED[@]} arquivo(s):"
    for f in "${SKIPPED[@]}"; do echo "    - ${f}"; done
    warn ".last-deploy NÃO foi atualizado (servidor está em estado misto)."
    warn "Próximo deploy mostrará novamente esses arquivos como pendentes."
    echo
fi

echo "Rollback rápido (volta pro último deploy):"
if [ -n "${LAST_SHA}" ]; then
    echo "  cd ${REPO_ROOT}"
    echo "  git stash"
    echo "  git checkout ${LAST_SHA:0:7}"
    echo "  ./deploy.sh                    # re-deploya o estado anterior"
    echo "  git checkout ${BRANCH}"
    echo "  git stash pop                  # se tinha mudanças no stash"
else
    echo "  (sem registro de último deploy — restaure manualmente do backup)"
fi
echo
