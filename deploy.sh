#!/usr/bin/env bash
# Atualiza o VintedBot no Pi: git pull, dependências (se mudaram), testes e reinício do serviço.
#   ./deploy.sh           só reinicia se houver código novo
#   ./deploy.sh --force   reinicia mesmo sem alterações
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

if [ ! -x .venv/bin/python ]; then
    echo "Ainda não há .venv: corre primeiro ./vintedbot.sh install"
    exit 1
fi

before=$(git rev-parse HEAD)
echo "A atualizar o código..."
git pull --ff-only
after=$(git rev-parse HEAD)

if [ "$before" = "$after" ]; then
    echo "Já estava atualizado: $(git log -1 --format='%h %s')"
    if [ "${1:-}" != "--force" ]; then
        exit 0
    fi
else
    git log --oneline "$before..$after"
    if ! git diff --quiet "$before" "$after" -- requirements.txt; then
        echo "O requirements.txt mudou: a instalar dependências..."
        .venv/bin/pip install -r requirements.txt
    fi
fi

echo "A correr os testes..."
if ! .venv/bin/python -m pytest -q -p no:warnings; then
    echo "❌ Os testes falharam: o serviço NÃO foi reiniciado e continua com a versão anterior."
    exit 1
fi

echo "A reiniciar o serviço..."
sudo systemctl restart vintedbot
sleep 5
if systemctl is-active --quiet vintedbot; then
    echo "✅ VintedBot atualizado e a correr."
    journalctl -u vintedbot -n 5 --no-pager
else
    echo "❌ O serviço não arrancou. Últimas linhas do log:"
    journalctl -u vintedbot -n 30 --no-pager
    exit 1
fi
