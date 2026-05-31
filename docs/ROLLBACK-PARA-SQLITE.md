# Rollback: voltar ao estado SQLite estável (antes da migração PostgreSQL)

Este documento explica como **reverter completamente** o sistema ao estado
anterior à migração pra PostgreSQL, caso algo dê errado.

## O que foi salvo como ponto de retorno

| Artefato | Onde está | O que cobre |
|---|---|---|
| **Tag git** `v1-sqlite-stable` | `git tag -l` no repo + push pro GitHub | Snapshot **do código** no estado pré-migração |
| **Branch principal** `main` | Não foi tocada — toda a migração rolou em `feature/postgres-migration` | Caminho pra voltar atrás sem mexer no histórico |
| **Backups dos `.db`** | `backups/pre-postgres-<timestamp>.gestao_equipe.db` e `.servpen.db` | Snapshot **dos dados** no estado pré-migração |

## Procedimento de rollback completo

### 1. Para o serviço

```bash
sudo systemctl stop gestao-de-projetos
```

### 2. Volta o código pro estado salvo

```bash
cd /var/www/html/gestao_de_projetos
git fetch --tags origin
git checkout main
git reset --hard v1-sqlite-stable
```

> Isso volta `app.py`, `database.py`, `setup-novo-servidor/install.sh` e
> tudo mais pro código que estava funcionando com SQLite.

### 3. (Se necessário) Restaura os dados

Se durante a migração os `.db` foram modificados (improvável, mas possível
se você rodou o sistema apontando pro SQLite e pro Postgres ao mesmo tempo
em algum momento), restaura o snapshot:

```bash
ls -lh backups/pre-postgres-*
# escolhe o mais recente

cp backups/pre-postgres-<timestamp>.gestao_equipe.db gestao_equipe.db
cp backups/pre-postgres-<timestamp>.servpen.db        servpen.db

sudo chown www-data:www-data gestao_equipe.db servpen.db
```

### 4. Reinstala libs e sobe

```bash
# Garante que numpy/pandas estão como apt (sem pyarrow), sem psycopg
sudo /var/www/html/gestao_de_projetos/venv/bin/pip uninstall -y \
    psycopg psycopg2-binary 2>/dev/null || true

sudo systemctl start gestao-de-projetos
sudo systemctl status gestao-de-projetos --no-pager -l | head -10
```

### 5. (Opcional) Para o PostgreSQL se estiver rodando

Se você não quer manter o daemon do Postgres consumindo recursos:

```bash
sudo systemctl stop postgresql
sudo systemctl disable postgresql
# Não precisa desinstalar - basta deixar parado
```

## Para descartar a branch de migração (se quiser)

```bash
# Local
git branch -D feature/postgres-migration

# Remoto
git push origin --delete feature/postgres-migration
```

## Para apagar o save point (quando tudo estiver estável em produção)

Só faça isso depois de **semanas** sem incidentes:

```bash
git tag -d v1-sqlite-stable                       # local
git push origin --delete v1-sqlite-stable         # remoto
rm backups/pre-postgres-*.db                      # backups locais
```

---

**Bottom line**: enquanto a tag `v1-sqlite-stable` e os arquivos
`backups/pre-postgres-*.db` existirem, o rollback é um comando de 30
segundos. Não precisa entrar em pânico se algo quebrar.
