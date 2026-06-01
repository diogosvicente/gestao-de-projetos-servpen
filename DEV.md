# Desenvolvimento local + deploy

Guia rápido pra rodar o sistema no seu PC e publicar no servidor 238.40.

## Pré-requisitos (uma vez)

- **Python 3.13 recomendado** (ou a versão compatível da distribuição) com `python3-venv`:
  ```bash
  sudo apt-get install -y python3 python3-venv
  ```
- **Docker** (pra Postgres local):
  ```bash
  # https://docs.docker.com/engine/install/ubuntu/
  docker --version  # confirma instalado
  ```
- **SSH** configurado pro servidor:
  ```bash
  ssh-keygen -t ed25519                       # se ainda não tem chave
  ssh-copy-id admin@152.92.238.40             # pede a senha do admin uma vez
  ssh admin@152.92.238.40 'echo OK'           # testa
  ```

## Setup uma vez

```bash
./setup-local.sh
```

Esse script:
- Cria `venv/` na raiz
- Instala `requirements.txt`
- Valida que as libs importam OK
- Confere se Docker está instalado

## Rodar o sistema localmente

```bash
./run-local.sh
```

Esse script:
- Sobe Postgres no Docker (porta 5432, expõe só em localhost)
- Garante o schema do banco (`database.criar_tabelas()`)
- Sobe Streamlit em `http://localhost:8501`

Opções:
- `./run-local.sh --no-docker` — não sobe Postgres (use se já tem rodando)
- `./run-local.sh --port=8502` — Streamlit em outra porta

Pra parar: `Ctrl+C` no Streamlit. Pra parar o Postgres:
```bash
docker compose down              # mantém os dados no volume
docker compose down -v           # APAGA os dados (--volumes)
```

## Banco local

| Item | Valor |
|---|---|
| Host / port | `localhost:5432` |
| Database | `gestao_servpen` |
| User / pass | `gestao_servpen` / `dev_local_pwd` |
| Config file | `db.env.local` (gitignored) |
| Volume | `gestao-pgdata-local` (Docker) |

Pra abrir psql no banco local:
```bash
docker compose exec postgres psql -U gestao_servpen
```

Pra criar usuário inicial pra testar login:
```bash
./venv/bin/python -c "
import database as db
db.criar_tabelas()
db.salvar_usuario('Sara Borges', 'minha_senha', 'Gestor', 'Engenheira')
"
```

## Deploy pra produção (238.40)

```bash
./deploy-238.sh
```

Esse script:
1. Valida working tree limpo + branch atual
2. Lê `.last-deploy` do servidor pra mostrar commits desde o último deploy
3. Mostra resumo do que vai ser alterado + pede confirmação
4. **rsync apenas arquivos rastreados pelo git** (`git ls-files`) pro servidor — preserva `venv/`, `anexos/`, `backups/`, `.streamlit/`, `*.db` no destino
5. SSH no servidor pra: chown + `pip install` (se requirements mudou) + restart
6. Atualiza `.last-deploy` no servidor com o SHA atual
7. Health check externo

### Opções

```bash
./deploy-238.sh --dry-run                 # mostra o que faria, sem enviar
REMOTE_USER=outro ./deploy-238.sh         # outro usuário SSH
REMOTE_HOST=outro-host ./deploy-238.sh    # outro servidor
```

### Rollback rápido

Quando o deploy quebra algo, volta pro commit anterior e re-deploya:

```bash
git checkout <SHA-anterior>     # o deploy-238.sh mostra o SHA no final do deploy
./deploy-238.sh
git checkout main               # volta pra branch
```

O script `.last-deploy` te ajuda a saber qual era o SHA anterior.

## Fluxo do dia-a-dia

```
1. ./setup-local.sh              # (1x) só primeira vez
2. ./run-local.sh                # sobe ambiente local
   ... edita código no editor ... # Streamlit recarrega sozinho
   Ctrl+C                        # para Streamlit
3. git add -A
4. git commit -m "..."
5. git push origin main          # opcional, pra ficar no GitHub também
6. ./deploy-238.sh               # publica em produção
```

## Estrutura mental

```
SEU PC (WSL Ubuntu)
  ├── venv/                      ← Python isolado (gitignored)
  ├── db.env.local               ← credenciais Postgres local (gitignored)
  ├── docker-compose.yml         ← Postgres dev (versionado)
  ├── setup-local.sh             ← cria venv + instala deps
  ├── run-local.sh               ← sobe Docker + Streamlit
  ├── deploy-238.sh              ← rsync pro 238.40
  └── app.py, core/, views/...   ← código

PostgreSQL local (Docker)
  └── localhost:5432             ← dados em volume gestao-pgdata-local

Servidor 152.92.238.40 (produção)
  └── /var/www/gestao-de-projetos/
      ├── app.py, core/, views/...  ← sincronizado via rsync
      ├── venv/                     ← preservado entre deploys
      ├── anexos/, backups/         ← preservados
      └── .last-deploy              ← SHA do último deploy
```

## Resolução de problemas

### "Postgres não respondeu em 10s"
```bash
docker compose logs postgres
docker compose restart postgres
```

### "Authentication failed for user gestao_servpen"
Banco subiu com outras credenciais. Resetar:
```bash
docker compose down -v
docker compose up -d
```

### Streamlit pede senha de psql no boot
Conferir que `db.env.local` foi carregado:
```bash
source db.env.local
env | grep DB_
```

### Deploy diz "Servidor já está em XXX — nada a fazer"
Seu HEAD bate com o `.last-deploy` do servidor. Faz commit novo e tenta de novo.

### Deploy falha em "Permission denied" no rsync
Provavelmente SSH key não configurada. Roda:
```bash
ssh-copy-id admin@152.92.238.40
ssh admin@152.92.238.40 'echo OK'
```
