#!/usr/bin/env bash
# setup-local.sh — Configura o ambiente local UMA VEZ.
#
# Cria venv, instala requirements.txt. Idempotente — pode rodar de novo
# sem problema, mas usa cache do pip.
#
# Pré-requisitos:
#   - python3.13 recomendado (ou Python compatível da distribuição) + módulo venv
#     Instalar: sudo apt-get install -y python3 python3-venv
#   - docker (pra rodar Postgres local depois)
#
# Depois desse setup, use ./run-local.sh pra subir o app.

set -euo pipefail

cd "$(dirname "$0")"

# ── 1) Acha um Python compatível ────────────────────────────────────
PYTHON=""
for cand in python3.13 python3.12 python3.11 python3; do
    if command -v "$cand" >/dev/null 2>&1; then
        PYTHON="$cand"
        break
    fi
done
[ -n "${PYTHON}" ] || { echo "ERRO: nenhum python3 encontrado." >&2; exit 1; }
echo "→ Python: $(${PYTHON} --version) (${PYTHON})"
PYTHON_VENV_PACKAGE="${PYTHON}-venv"

# ── 0) Cria db.env.local a partir do template se ainda não existe ──
if [ -f db.env.local ]; then
    echo "✓ db.env.local já existe"
elif [ -f db.env.local.example ]; then
    cp db.env.local.example db.env.local
    echo "→ db.env.local criado a partir do template"
    echo "  (edite se precisar mudar credenciais; gitignored)"
fi

# ── 2) Cria venv se ainda não existe (ou recria se quebrado) ────────
# Detecta venv quebrado: pasta existe mas sem o pip executável. Acontece
# quando o `python3-venv` não estava instalado na 1ª tentativa — venv
# fica meio-criado, sem `bin/pip`.
if [ -d venv ] && { [ ! -x venv/bin/python ] || [ ! -x venv/bin/pip ]; }; then
    echo "⚠ venv existe mas está incompleto — apagando pra recriar..."
    rm -rf venv
fi

if [ ! -d venv ]; then
    echo "→ Criando venv..."
    if ! "${PYTHON}" -m venv --upgrade-deps venv; then
        cat >&2 <<HELP

ERRO ao criar venv. No Ubuntu/Debian, instala o pacote:

    sudo apt-get install -y ${PYTHON_VENV_PACKAGE}

E roda este script de novo.
HELP
        exit 1
    fi
    echo "✓ venv criado"
else
    echo "✓ venv já existe (./venv)"
fi

# ── 3) Atualiza pip + instala requirements ──────────────────────────
echo "→ Atualizando pip/wheel..."
./venv/bin/pip install --upgrade -q pip wheel

echo "→ Instalando requirements.txt..."
./venv/bin/pip install -r requirements.txt

# ── 4) Sanity check: importa as libs principais ─────────────────────
echo "→ Validando instalação..."
./venv/bin/python -c "
import streamlit, pandas, plotly, psycopg, sqlalchemy
print(f'  streamlit  {streamlit.__version__}')
print(f'  pandas     {pandas.__version__}')
print(f'  plotly     {plotly.__version__}')
print(f'  psycopg    {psycopg.__version__}')
print(f'  sqlalchemy {sqlalchemy.__version__}')
"

# ── 5) Confere Docker (pro Postgres local) ──────────────────────────
echo
if command -v docker >/dev/null 2>&1; then
    echo "✓ Docker: $(docker --version)"
else
    cat <<'HELP'
⚠  Docker não encontrado. Você vai precisar pra subir Postgres local.
   Instala:  https://docs.docker.com/engine/install/ubuntu/
   Ou usa Postgres nativo: sudo apt install postgresql
HELP
fi

echo
echo "============================================="
echo "  Setup concluído."
echo "  Próximo passo:  ./run-local.sh"
echo "============================================="
