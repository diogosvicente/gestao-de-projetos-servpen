#!/usr/bin/env bash
# dev.sh - Roda o Streamlit em foreground pra desenvolver/testar.
# Para o systemd antes (pra liberar a 8501), e religa ao sair com Ctrl+C.
#
# Uso:
#   ./dev.sh           # roda na 8501 (URL normal funciona)
#   ./dev.sh 8510      # roda em outra porta (pra ter 2 instancias em paralelo)
set -u

PROJ="/var/www/html/gestao_de_projetos"
PORT="${1:-8501}"

cd "$PROJ"

# Funcao chamada no Ctrl+C ou ao sair: religa o systemd
cleanup() {
    echo
    echo "==> Encerrando. Religando o systemd em background..."
    sudo systemctl start gestao-de-projetos
    sudo systemctl is-active gestao-de-projetos && echo "    OK, servico de producao ativo de novo."
}
trap cleanup EXIT INT TERM

# Se for usar a 8501, precisa parar o systemd antes
if [ "$PORT" = "8501" ]; then
    echo "==> Parando o servico de producao (libera 8501)..."
    sudo systemctl stop gestao-de-projetos
    EXTRA_ARGS=""
    echo "==> URL: http://152.92.228.20/gestao-de-projetos/   (via Apache proxy)"
else
    echo "==> Rodando em paralelo ao servico de producao."
    echo "==> URL: http://152.92.228.20:${PORT}/              (direto, sem Apache)"
    EXTRA_ARGS="--server.port=${PORT} --server.baseUrlPath="
fi

echo "==> Ctrl+C pra parar e voltar pro modo producao."
echo
./venv/bin/streamlit run app.py $EXTRA_ARGS
