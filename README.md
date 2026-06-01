# Gestão de Projetos SERVPEN

App Streamlit + PostgreSQL pra gerenciar projetos de engenharia.
Produção em http://152.92.238.40/gestao-de-projetos/.

## Pré-requisitos (uma vez)

Dev em **WSL Ubuntu** (Windows) ou Linux nativo. Tudo abaixo roda
dentro do shell do WSL — não no PowerShell.

```bash
# Python 3.13 recomendado (ou a versão compatível da distribuição):
sudo apt-get install -y python3 python3-venv

# Docker Engine + Docker Compose v2 (plugin moderno):
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# Sai e abre o WSL de novo pra o grupo `docker` entrar em efeito.

# Confere:
docker --version
docker compose version    # note: SEM hífen — é o plugin v2
```

> **Alternativa**: se preferir, dá pra usar **Docker Desktop no Windows**
> com integração WSL ativada em `Settings → Resources → WSL Integration`.
> O comando `docker` fica disponível dentro do WSL sem precisar instalar
> nada lá. Mais memória/recursos consumidos, porém.

## Setup local (uma vez)

```bash
git clone git@github.com:diogosvicente/gestao-de-projetos-servpen.git
cd gestao-de-projetos-servpen
./setup-local.sh                                # cria venv + instala libs
./venv/bin/pip install 'bcrypt<4'               # workaround passlib+bcrypt4
```

## Rodar localmente

```bash
./run-local.sh                                  # http://localhost:8501
```

Sobe Postgres no Docker, garante schema, abre Streamlit.
Pra parar: `Ctrl+C`. Postgres mantém os dados no volume.

### Criar usuário pra testar login

```bash
./py-local.sh -c "
import database as db
db.salvar_usuario('Diogo', 'Teste@123456', 'Gestor', 'Programador')
print('ok')
"
```

## Deploy pra produção (152.92.238.40)

Pré-requisito: SSH key configurada pra `admin@152.92.238.40`:
```bash
ssh-copy-id admin@152.92.238.40
```

Fluxo:

```bash
git add ...
git commit -m "..."
./deploy-238.sh                                 # --dry-run pra simular
```

O script faz: rsync dos arquivos rastreados pelo git (preserva
`venv/`, `anexos/`, `backups/`, `.streamlit/` no servidor) +
`pip install` se `requirements.txt` mudou + restart do serviço +
health check.

## Estrutura

```
app.py                  ← entry: login + sidebar + st.navigation
core/                   ← módulos compartilhados (helpers, data, auth_ui, ...)
views/                  ← 1 página por arquivo (dashboard, kanban, chat, ...)
database.py             ← schema + queries PostgreSQL
auth.py                 ← validação de login + rate limit
relatorios.py           ← geração de PDF/Excel
setup-novo-servidor/    ← arquivos de infra (install.sh, vhost, systemd)
docker-compose.yml      ← Postgres dev local
db.env.local            ← creds dev (gitignored; criado a partir do .example)
db.env.local.example    ← template versionado das creds dev
```

## Docs detalhadas

- `DEV.md` — fluxo de dev, troubleshooting, comandos úteis
- `INSTALAR-EM-NOVO-SERVIDOR.md` — instalação do zero num servidor novo

## Troubleshooting rápido

| Sintoma | Solução |
|---|---|
| `ModuleNotFoundError` ao rodar | `./venv/bin/pip install -r requirements.txt` |
| `password cannot be longer than 72 bytes` | `./venv/bin/pip install 'bcrypt<4'` |
| Postgres "no password supplied" no terminal | use `./py-local.sh` em vez de `./venv/bin/python` |
| URL mostra `152.92.238.40:80` em vez de localhost | já corrigido no `run-local.sh` — pull e tenta de novo |
