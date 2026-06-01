# deploy.ps1 — Versão PowerShell do deploy.sh (Windows nativo).
#
# Uso:
#   .\deploy.ps1                  # deploy normal
#   .\deploy.ps1 -DryRun          # mostra o que faria, sem executar
#   .\deploy.ps1 -SkipPush        # pula git push (já fez manual)
#   .\deploy.ps1 -Branch hotfix   # deploy de outra branch
#
# Configuração (env vars opcionais — set antes de chamar):
#   $env:REMOTE_USER  Usuário SSH (default: admin)
#   $env:REMOTE_HOST  IP do servidor (default: 152.92.238.40)
#   $env:SETUP_DIR    Path do atualizar-app.sh (default: /var/www/setup-novo-servidor)
#   $env:BASE_URL     URL base do app (default: http://152.92.238.40/gestao-de-projetos)
#
# Equivalente em Linux/Mac/WSL/Git Bash: ./deploy.sh

[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$SkipPush,
    [string]$Branch = "main"
)

$ErrorActionPreference = "Stop"

# ── CONFIG ──────────────────────────────────────────────────────────
$REMOTE_USER = if ($env:REMOTE_USER) { $env:REMOTE_USER } else { "admin" }
$REMOTE_HOST = if ($env:REMOTE_HOST) { $env:REMOTE_HOST } else { "152.92.238.40" }
$SETUP_DIR   = if ($env:SETUP_DIR)   { $env:SETUP_DIR }   else { "/var/www/setup-novo-servidor" }
$BASE_URL    = if ($env:BASE_URL)    { $env:BASE_URL }    else { "http://152.92.238.40/gestao-de-projetos" }

# ── HELPERS ─────────────────────────────────────────────────────────
function Write-Ok    ($m) { Write-Host "✓ $m" -ForegroundColor Green }
function Write-Info  ($m) { Write-Host "→ $m" -ForegroundColor Cyan  }
function Write-Warn  ($m) { Write-Host "⚠ $m" -ForegroundColor Yellow }
function Write-Fail  ($m) { Write-Host "✗ $m" -ForegroundColor Red   ; exit 1 }

function Invoke-Step ($cmd) {
    if ($DryRun) {
        Write-Host "  [dry-run] $cmd" -ForegroundColor Yellow
    } else {
        Invoke-Expression $cmd
        if ($LASTEXITCODE -ne 0) {
            Write-Fail "comando falhou (exit $LASTEXITCODE): $cmd"
        }
    }
}

# ── HEADER ──────────────────────────────────────────────────────────
Write-Host ""
Write-Host "===== Deploy: local → $REMOTE_HOST =====" -ForegroundColor White
Write-Host "Branch:  $Branch"
Write-Host "Remote:  $REMOTE_USER@$REMOTE_HOST"
if ($DryRun) { Write-Warn "DRY RUN — nada será realmente executado" }
Write-Host ""

# ── 1. WORKING TREE LIMPO? ──────────────────────────────────────────
Write-Info "Verificando working tree..."
$dirty = (git status --porcelain 2>$null) -join "`n"
if ($dirty) {
    git status --short
    Write-Fail "Você tem mudanças não comitadas. Commit (ou stash) antes de deployar."
}
Write-Ok "working tree limpo"

# ── 2. BRANCH CORRETA? ──────────────────────────────────────────────
$currentBranch = (git rev-parse --abbrev-ref HEAD).Trim()
if ($currentBranch -ne $Branch) {
    Write-Warn "Você está em '$currentBranch', esperado '$Branch'."
    $resp = Read-Host "Continuar mesmo assim? [y/N]"
    if ($resp -notmatch '^[yY]') { Write-Fail "abortado pelo user" }
}
Write-Ok "branch: $currentBranch"

# ── 3. PREVIEW DOS COMMITS ──────────────────────────────────────────
git fetch origin $Branch --quiet 2>$null | Out-Null
$localHead  = (git rev-parse HEAD).Trim()
$remoteHead = ""
try { $remoteHead = (git rev-parse "origin/$Branch" 2>$null).Trim() } catch {}

if ($remoteHead -and ($localHead -eq $remoteHead)) {
    Write-Info "Local e origin/$Branch estão no mesmo commit — nada novo a empurrar"
    $SkipPush = $true
} else {
    Write-Host ""
    Write-Info "Commits que vão ser deployados:"
    if ($remoteHead) {
        git log --oneline "$remoteHead..HEAD" | ForEach-Object { Write-Host "    $_" }
    } else {
        Write-Host "    (origin/$Branch desconhecido — primeiro push)"
    }
    Write-Host ""
}

# ── 4. CONFIRMAÇÃO ──────────────────────────────────────────────────
if (-not $DryRun) {
    $resp = Read-Host "Deploy agora? [y/N]"
    if ($resp -notmatch '^[yY]') { Write-Fail "abortado pelo user" }
}

# ── 5. GIT PUSH ─────────────────────────────────────────────────────
if ($SkipPush) {
    Write-Info "Pulando git push (já no remote ou -SkipPush)"
} else {
    Write-Info "Push pra origin/$Branch..."
    Invoke-Step "git push origin $Branch"
    Write-Ok "push OK"
}

# ── 6. SSH + ATUALIZAR-APP.SH ───────────────────────────────────────
Write-Host ""
Write-Info "Executando atualizar-app.sh no servidor..."
Write-Host "─── output remoto ─────────────────────────────────" -ForegroundColor Cyan
# -t força TTY (output em tempo real + sudo interativo se precisar de senha)
Invoke-Step "ssh -t $REMOTE_USER@$REMOTE_HOST 'sudo bash $SETUP_DIR/atualizar-app.sh'"
Write-Host "───────────────────────────────────────────────────" -ForegroundColor Cyan
Write-Ok "atualizar-app.sh terminou"

# ── 7. HEALTH CHECK EXTERNO ─────────────────────────────────────────
if (-not $DryRun) {
    Write-Host ""
    Write-Info "Health check externo..."
    try {
        $resp = Invoke-WebRequest -Uri "$BASE_URL/_stcore/health" `
                                  -UseBasicParsing -TimeoutSec 15
        if ($resp.StatusCode -eq 200) {
            Write-Ok "$BASE_URL/_stcore/health → HTTP 200"
        } else {
            Write-Warn "health check retornou HTTP $($resp.StatusCode)"
            exit 3
        }
    } catch {
        Write-Warn "health check falhou: $($_.Exception.Message)"
        Write-Warn "olha o log: ssh $REMOTE_USER@$REMOTE_HOST 'sudo journalctl -u gestao-de-projetos -n 50 --no-pager'"
        exit 3
    }
}

Write-Host ""
Write-Host "===== Deploy concluído =====" -ForegroundColor Green
Write-Host "App: $BASE_URL/"
Write-Host ""
Write-Host "Rollback (se algo deu errado):"
Write-Host "  ssh $REMOTE_USER@$REMOTE_HOST '``"
Write-Host "    cd /var/www/gestao-de-projetos && ``"
Write-Host "    sudo -u www-data git reset --hard HEAD~1 && ``"
Write-Host "    sudo systemctl restart gestao-de-projetos'"
Write-Host ""
