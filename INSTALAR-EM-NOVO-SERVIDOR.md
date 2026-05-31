# Instalar o Sistema em um Servidor Novo

Guia para instalar o **Gestão de Projetos SERVPEN** em um servidor Linux
limpo (ex.: `152.92.238.40`). O resultado fica idêntico ao servidor
de referência: o app rodando em `http://<IP-DO-SERVIDOR>/gestao-de-projetos/`.

---

## 1. Pré-requisitos do servidor

| Item | Requisito |
|---|---|
| Sistema | Ubuntu 24.04 LTS (Noble) ou Debian 12. Pode ser 22.04 também. |
| Acesso | Conta com `sudo`. SSH liberado. |
| Internet | Sim — durante a instalação, para baixar pacotes via `apt` e `pip`. |
| Disco | ~2 GB livres (sistema + venv + apt deps). |
| RAM | 2 GB OK para até ~10 usuários. 4 GB+ recomendado para 20+. |
| CPU | Qualquer x86_64. Se for **antiga sem AVX/AVX2** (ex.: AMD Athlon II ou Core 2 Duo), funciona — o script já lida com isso (não usa `pyarrow`, usa `numpy`/`pandas` do apt). |

### Pacotes que serão instalados (você não precisa instalar à mão)

- `python3`, `python3-venv`, `python3-pip`, `python3-dev`, `build-essential`, `libffi-dev`
- `python3-numpy`, `python3-pandas`, `python3-pil`, `python3-reportlab` (versões do apt, compiladas com baseline conservador)
- `apache2`, `sqlite3` (sqlite3 fica só pra ler os `.db` legados durante a migração)
- **`postgresql`, `postgresql-client`** — banco principal a partir desta versão
- Via pip dentro do venv: `streamlit`, `plotly`, `fpdf2`, `xlsxwriter`, `openpyxl`, **`psycopg[binary]>=3.1`**

> **Mudança importante a partir de maio/2026**: o sistema migrou de SQLite
> para PostgreSQL. O instalador cuida de tudo (cria DB, role, senha, migra
> dados legados). Veja a seção 4.1 e o arquivo `docs/ROLLBACK-PARA-SQLITE.md`
> se quiser desfazer.

> **Lições aprendidas validando no 228.20 (maio/2026)**, já refletidas no
> código atual:
> - O repo tem `.gitattributes` forçando **LF** em scripts/python/configs.
>   Sem isso, edição via SMB do Windows escreve CRLF e bash linux quebra
>   com `set: invalid option name pipefail`.
> - O `install.sh` gera senha do Postgres com `openssl rand -hex 16`
>   (não com `tr ... | head` — esse último aborta silenciosamente o script
>   por `SIGPIPE + pipefail`).
> - O `database.py` expõe `criar_tabelas()` (não `criar_banco()` — atenção
>   se encontrar referências antigas na doc).
> - O `migrar-sqlite-para-postgres.py` usa `INSERT ... OVERRIDING SYSTEM VALUE`
>   nos `id`s — porque o schema usa `BIGINT GENERATED ALWAYS AS IDENTITY`,
>   que sem isso rejeita inserts com id explícito.
> - **bcrypt** substituiu SHA-256 puro (`passlib[bcrypt]`). Hashes legados
>   continuam aceitos no login e são re-gravados como bcrypt no primeiro
>   login bem-sucedido (rehash transparente). Nenhum usuário precisa
>   trocar a senha após a migração.
> - **SQLAlchemy engine** (`db.get_engine()`) com pool de conexões para
>   `pd.read_sql_query`. Resolve warning do pandas ("DBAPI desconhecido") e
>   evita abrir/fechar conexão em cada SELECT. `db.conectar()` continua
>   existindo para cursor manual em INSERT/UPDATE/DELETE.
> - **Logging estruturado**: `logging.basicConfig` no boot com formato
>   `timestamp nível módulo: mensagem`. `LOG_LEVEL` env var controla
>   (`INFO` default, `DEBUG` pra diagnosticar). Em produção via systemd o
>   log vai pra `/var/log/gestao-de-projetos.log` (vide
>   `gestao-de-projetos.service`).
> - **XSRF Protection re-habilitada** (`enableXsrfProtection = true`).
>   Funciona porque o vhost Apache usa `ProxyPreserveHost On` +
>   `RequestHeader set X-Forwarded-Host`.
> - **ruff** configurado em `pyproject.toml`. Rodar manualmente:
>   `ruff check .` (lint) e `ruff format .` (format). Não é instalado pelo
>   `install.sh` (é dev-only).

---

## 2. Copie o código para o servidor

Coloque toda a pasta do projeto em `/var/www/html/gestao_de_projetos/`
no servidor de destino. Você pode usar `scp`, `rsync`, `git clone`,
ou um pendrive — qualquer um serve.

### Exemplo com `rsync` (do servidor de origem para o destino)
```bash
# No servidor antigo (152.92.228.20), como sara:
rsync -avz --exclude='venv/' --exclude='__pycache__/' --exclude='.local/' \
      --exclude='backups/' --exclude='.vscode-server/' \
      /var/www/html/gestao_de_projetos/  novo-servidor:/tmp/gdp/

# No servidor novo (152.92.238.40), como root:
sudo mkdir -p /var/www/html/gestao_de_projetos
sudo mv /tmp/gdp/* /var/www/html/gestao_de_projetos/
sudo mv /tmp/gdp/.streamlit /var/www/html/gestao_de_projetos/ 2>/dev/null || true
```

### Exemplo com `scp` (de um Windows com o `Z:\` mapeado)
```powershell
# No Windows (PowerShell):
scp -r Z:\* sara@152.92.238.40:/tmp/gdp/
# Depois no servidor (ssh) move pra pasta final como acima.
```

### O que precisa estar em `/var/www/html/gestao_de_projetos/`

```
gestao_de_projetos/
├── app.py
├── auth.py
├── database.py
├── relatorios.py
├── requirements.txt
├── migrar-sqlite-para-postgres.py    ← script ETL SQLite → Postgres
├── .gitattributes                    ← força LF em scripts/python/configs
├── gestao_equipe.db        ← (opcional, se quiser migrar os dados antigos)
├── servpen.db              ← (opcional)
├── anexos/                 ← (opcional, arquivos enviados pelos usuários)
├── setup-novo-servidor/
│   ├── install.sh
│   ├── gestao-de-projetos.conf
│   ├── gestao-de-projetos.service
│   └── db.env.example                 ← template das credenciais Postgres
└── INSTALAR-EM-NOVO-SERVIDOR.md       ← este arquivo (na raiz do projeto)
```

> Se você **não copiou os `.db`** legados, o Postgres ficará vazio depois do
> install — não tem nenhum usuário padrão garantido. Crie um manualmente:
> ```sql
> -- Como gestao_servpen no Postgres:
> INSERT INTO usuarios (nome, senha, perfil, cargo)
> VALUES ('Sara Borges', encode(digest('Senbt0408', 'sha256'), 'hex'),
>         'Gestor', 'Engenheira');
> ```
> ⚠️ A função `digest()` exige `CREATE EXTENSION pgcrypto;` antes. Ou
> calcule o SHA-256 fora e cole o hash: `echo -n 'Senbt0408' | sha256sum`.

---

## 3. Rode o instalador (1 comando)

No servidor novo, com `sudo`:

```bash
cd /var/www/html/gestao_de_projetos
sudo SERVER_IP="152.92.238.40" bash setup-novo-servidor/install.sh
```

O `install.sh` é **idempotente** — pode rodar várias vezes sem problema.
Em ~5-8 minutos ele faz tudo:

1. Backup dos `.db` SQLite legados em `backups/<timestamp>.pre-install.bak`
2. `apt install` dos pacotes (Python, numpy/pandas via apt, Apache,
   **PostgreSQL**, etc.)
3. **Cria/garante o banco PostgreSQL**: role `gestao_servpen`, database
   `gestao_servpen`, senha aleatória gerada (ou reutiliza a existente).
   Persiste credenciais em `/etc/gestao-de-projetos/db.env` (`0640
   root:www-data`).
4. Cria `venv` Linux com `--system-site-packages`
5. `pip install streamlit plotly fpdf2 xlsxwriter openpyxl psycopg[binary]`
6. **Remove** `numpy*`, `pandas*`, `pyarrow*` e outros wheels do venv que
   podem ter sido puxados como deps — força o Python a usar as versões do
   apt (compiladas com baseline conservador, funcionam em qualquer CPU)
7. Ajusta `chown www-data:www-data` + `chmod g+s` (assim você pode editar
   pelos grupos depois)
8. Escreve `.streamlit/config.toml` com o IP do servidor
9. **Cria o schema no Postgres** chamando `database.criar_tabelas()`. Se
   houver `gestao_equipe.db` ou `servpen.db` legados na pasta, **roda
   `migrar-sqlite-para-postgres.py`** — preserva IDs, hashes de senha e
   é idempotente (rodar de novo não duplica).
10. Substitui `__APP_DIR__` no systemd e `__SERVER_IP__` no vhost Apache,
    instala em `/etc/systemd/system/` e `/etc/apache2/conf-available/`
11. Habilita os módulos do Apache (`proxy`, `proxy_http`, `rewrite`, `headers`),
    valida a config e dá reload
12. Testa o endpoint `/_stcore/health` interno e via Apache

No final imprime:
```
DONE. Acesse: http://152.92.238.40/gestao-de-projetos/
Login inicial: Sara Borges / Senbt0408
```

---

## 4. Variáveis que dá pra customizar

Passe como env var antes do `bash setup-novo-servidor/install.sh`:

| Variável | Default | Quando alterar |
|---|---|---|
| `SERVER_IP` | IP detectado de `hostname -I` | Sempre passe o IP público real |
| `APP_DIR` | `/var/www/html/gestao_de_projetos` | Se quiser instalar em outro caminho |
| `STREAMLIT_PORT` | `8501` | Se a 8501 já estiver em uso |
| `URL_PATH` | `gestao-de-projetos` | Se quiser outro caminho na URL (ex.: `app`) |
| `DB_NAME` | `gestao_servpen` | Renomear o database no Postgres |
| `DB_USER` | `gestao_servpen` | Renomear o role/usuário do Postgres |
| `DB_PASSWORD` | gerada automaticamente | Fornecer senha pré-definida (ex.: ambiente com cofre de segredos) |
| `SKIP_MIGRATION` | `0` | Setar `1` se você **não quer** migrar dados dos `.db` legados |

### 4.1. Onde fica a senha do Postgres

O `install.sh` cria `/etc/gestao-de-projetos/db.env` com modo `0640`
(`root:www-data`). O `systemd` lê esse arquivo via `EnvironmentFile=`. Pra
inspecionar ou trocar:

```bash
sudo cat /etc/gestao-de-projetos/db.env
sudo nano /etc/gestao-de-projetos/db.env   # editar senha
sudo systemctl restart gestao-de-projetos  # aplicar
```

Pra conectar manualmente no banco com `psql`:

```bash
# Pega a senha
sudo grep DB_PASSWORD /etc/gestao-de-projetos/db.env
# Conecta
psql -h localhost -U gestao_servpen -d gestao_servpen
```

Exemplo customizado:
```bash
sudo SERVER_IP="10.0.0.50" URL_PATH="servpen" \
     bash setup-novo-servidor/install.sh
# vai ficar em http://10.0.0.50/servpen/
```

---

## 5. Primeira validação

Depois do install, no próprio servidor:

```bash
# 1. Serviço de pé?
sudo systemctl status gestao-de-projetos --no-pager -l | head -8
# Esperado: Active: active (running) ...

# 2. Endpoint responde?
curl -sI http://127.0.0.1:8501/gestao-de-projetos/_stcore/health
curl -sI http://152.92.238.40/gestao-de-projetos/_stcore/health
# Esperado: HTTP/1.1 200 OK

# 3. Log sem stack trace?
sudo tail -20 /var/log/gestao-de-projetos.log
# Esperado: banner "You can now view your Streamlit app..."
```

No navegador: **http://152.92.238.40/gestao-de-projetos/**

Login inicial: **`Sara Borges`** / **`Senbt0408`**

A Sara (ou qualquer Gestor) pode então cadastrar os outros usuários
pela aba **👥 Equipe**.

---

## 6. Restrição importante de hardware

**Se a CPU do servidor não tem AVX/AVX2** (CPUs anteriores a ~2013, como
AMD Athlon II ou Intel Core 2 Duo), os wheels modernos do PyPI de
`numpy`, `pandas`, `pyarrow`, `scipy` quebram com **`Illegal instruction
(core dumped)`** ao serem importados.

O `install.sh` **já trata isso**:

- Usa `python3-numpy`, `python3-pandas`, `python3-pil`, `python3-reportlab`
  do **apt** (compilados pelo Ubuntu com baseline x86-64-v1 — funciona em
  qualquer CPU desde 2003)
- Apaga os equivalentes do venv para forçar o fallthrough
- **NÃO instala `pyarrow`** — não tem versão CPU-safe no Noble e o app
  não usa funcionalidades que dependem dele

**Consequência**: `st.dataframe`, `st.table` e leitura/escrita de Parquet
**não funcionam** neste app (são as features que dependem do pyarrow).
Use HTML table via `st.markdown` no lugar, ou plotly tables. A aba
Auditoria, por exemplo, já é renderizada como tabela HTML por isso.

Se a CPU do novo servidor for moderna (Intel ≥ Sandy Bridge ou AMD ≥ Bulldozer
de 2013+), tecnicamente daria pra instalar pyarrow normal e usar
`st.dataframe`. Mas só vale a pena se você for usar essas features.

---

## 7. Manutenção depois da instalação

| Quando | Comando |
|---|---|
| Mexeu em `app.py` | Nada — só `Ctrl+Shift+R` no navegador. O `fileWatcherType=poll` pega em ~1s. |
| Mexeu em `auth.py`, `database.py`, `relatorios.py` ou `.streamlit/config.toml` | `sudo systemctl restart gestao-de-projetos` |
| Trocou senha em `/etc/gestao-de-projetos/db.env` | `sudo systemctl restart gestao-de-projetos` |
| Ver logs ao vivo | `sudo tail -f /var/log/gestao-de-projetos.log` |
| Status do serviço | `sudo systemctl status gestao-de-projetos --no-pager -l` |
| Reiniciar | `sudo systemctl restart gestao-de-projetos` |
| Parar | `sudo systemctl stop gestao-de-projetos` |
| Backup manual ad-hoc do Postgres | `sudo /usr/local/bin/backup-gestao-de-projetos.sh` |
| Forçar backup automático fora do horário | `sudo systemctl start backup-gestao-de-projetos.service` |
| Ver próximo horário do backup automático | `systemctl list-timers backup-gestao-de-projetos.timer` |
| Ver log dos backups | `journalctl -u backup-gestao-de-projetos.service -n 50 --no-pager` |
| Listar backups disponíveis | `ls -lh /var/www/html/gestao_de_projetos/backups/postgres-*.sql.gz` |
| Restaurar backup do Postgres | `gunzip -c backups/postgres-gestao_servpen-YYYYMMDD-HHMMSS.sql.gz \| sudo -u postgres psql gestao_servpen` |
| Status do Postgres | `sudo systemctl status postgresql --no-pager -l` |

---

## 7.1. Backup automático do PostgreSQL (timer systemd)

A partir de maio/2026, o `install.sh` instala um **timer systemd** que faz
backup do Postgres **diariamente às 03:00** (UTC do servidor). É a defesa
principal contra perda de dados.

### Como funciona

| Componente | Onde fica | O que faz |
|---|---|---|
| Script | `/usr/local/bin/backup-gestao-de-projetos.sh` | Roda `pg_dump`, comprime com gzip, ajusta perms |
| Service unit | `/etc/systemd/system/backup-gestao-de-projetos.service` | Wrapper one-shot do script |
| Timer unit | `/etc/systemd/system/backup-gestao-de-projetos.timer` | Agenda execução diária às 03h |
| Destino | `${APP_DIR}/backups/postgres-gestao_servpen-YYYYMMDD-HHMMSS.sql.gz` | Arquivo gzipado |
| Retenção | 30 dias (configurável via env `RETAIN_DAYS`) | Apaga sozinho o que envelheceu |

### Recuperação rápida

```bash
# 1. Para o app (impede escrita durante restore)
sudo systemctl stop gestao-de-projetos

# 2. Lista backups disponíveis
ls -lh /var/www/html/gestao_de_projetos/backups/postgres-*.sql.gz

# 3. Drop + recreate do DB (apaga o estado corrompido)
sudo -u postgres dropdb gestao_servpen
sudo -u postgres createdb -O gestao_servpen gestao_servpen

# 4. Restaura escolhendo o arquivo
gunzip -c /var/www/html/gestao_de_projetos/backups/postgres-gestao_servpen-20260531-030000.sql.gz \
    | sudo -u postgres psql gestao_servpen

# 5. Sobe o app
sudo systemctl start gestao-de-projetos
```

### Verificação rotineira (mensal)

Garanta que o timer continua armado e backups recentes existem:

```bash
# Tem que mostrar "active (waiting)" e próxima execução em <24h
systemctl status backup-gestao-de-projetos.timer

# Backups recentes (últimos 7)
ls -lt /var/www/html/gestao_de_projetos/backups/postgres-*.sql.gz | head -7

# Testar uma restauração em DB de descarte (recomendado a cada ~6 meses):
sudo -u postgres createdb gestao_servpen_test
gunzip -c backups/postgres-gestao_servpen-AAAAMMDD-HHMMSS.sql.gz \
    | sudo -u postgres psql gestao_servpen_test
sudo -u postgres psql gestao_servpen_test -c "SELECT COUNT(*) FROM projetos;"
sudo -u postgres dropdb gestao_servpen_test
```

> **Off-site (recomendado quando for pra produção real)**: o backup local
> só protege contra corrupção de DB. Pra proteger contra falha de disco /
> roubo / fogo, copie `backups/postgres-*.sql.gz` periodicamente pra um
> bucket S3, NFS, Google Drive, ou outra máquina. Um simples `rsync` no
> cron do dia seguinte resolve.

---

## 8. (Opcional) Configurar um usuário Linux pra desenvolvimento

Se você quer SSH/SFTP/VS Code Remote com acesso direto à pasta do projeto:

```bash
# Cria/usa um usuário 'sara' e aponta o HOME pra pasta do projeto
sudo useradd -m sara 2>/dev/null || true       # se ainda não existe
sudo usermod -d /var/www/html/gestao_de_projetos sara
sudo usermod -aG sudo,www-data sara
sudo passwd sara                                # define senha

# A sara entra direto na pasta do projeto e pode editar
ssh sara@152.92.238.40
# (cai em /var/www/html/gestao_de_projetos/)
```

> Atenção: como a HOME da sara é a pasta do projeto, o `~/.vscode-server`
> e `~/.local` ficam dentro dela. Pra evitar que o `pip install --user`
> da sara polua o venv (o `pyarrow` ressuscitou várias vezes assim), o
> `install.sh` já apaga essa pasta.

### (Opcional) Compartilhamento SMB para editar pelo Windows

Se quiser mapear `\\152.92.238.40\www\gestao_de_projetos` como drive
de rede no Windows, instale o Samba e configure um share `[www]` apontando
pra `/var/www/html` com `valid users` da sara/seu user, `force group = www-data`
e `create mask = 0775`. Veja o `smb.conf` do servidor antigo como referência.

---

## 9. Troubleshooting comum

| Sintoma | Causa | Solução |
|---|---|---|
| `Illegal instruction (core dumped)` no log do systemd | Wheel do PyPI usando AVX/AVX2 | Confirma que o `install.sh` removeu `numpy*`/`pandas*`/`pyarrow*` do venv: `ls /var/www/html/gestao_de_projetos/venv/lib/python3.*/site-packages/ \| grep -iE '^(numpy\|pandas\|pyarrow)'` deve estar vazio |
| `ModuleNotFoundError: No module named 'X'` | Lib não instalada | `sudo /var/www/html/gestao_de_projetos/venv/bin/pip install X` + `sudo systemctl restart gestao-de-projetos` |
| `Port 8501 is already in use` | systemd já tá rodando | É normal — não rode manual; use `sudo systemctl restart gestao-de-projetos` |
| Browser fica em "CONNECTING..." | WebSocket bloqueado | Confirma `a2enmod proxy proxy_http` e que o vhost tem `upgrade=websocket` no `ProxyPass` |
| HTTP 502 / 503 do Apache | Streamlit caiu | `sudo journalctl -u gestao-de-projetos -n 50 --no-pager` mostra o motivo |
| `database is locked` com vários usuários | (não acontece mais — agora é Postgres) | Se aparecer em log antigo, ignorar |
| `psycopg.OperationalError: connection refused` | Postgres parado | `sudo systemctl start postgresql` |
| `psycopg.OperationalError: FATAL: password authentication failed` | Senha em `/etc/gestao-de-projetos/db.env` divergiu do role | Rodar `install.sh` de novo (regrava a senha no role) ou usar `ALTER ROLE gestao_servpen PASSWORD '...'` no psql |
| `psycopg.OperationalError: FATAL: database "gestao_servpen" does not exist` | DB foi dropado | `sudo -u postgres createdb -O gestao_servpen gestao_servpen` + `sudo systemctl restart gestao-de-projetos` |
| Migração SQLite→Postgres parou no meio | Erro em alguma linha (raro) | Ler o output, corrigir a linha problemática, **rodar de novo** (é idempotente — só insere o que falta) |
| `cannot insert a non-DEFAULT value into column "id"` na migração | Schema usa `GENERATED ALWAYS AS IDENTITY` — o INSERT precisa de `OVERRIDING SYSTEM VALUE` | Já está no `migrar-sqlite-para-postgres.py` atual. Se você está com versão antiga, atualiza pelo git. |
| `install.sh: line 19: $'\r': command not found` ou `set: invalid option name pipefail` | CRLF em vez de LF no script (editado pelo Windows via SMB) | `sed -i 's/\r$//' setup-novo-servidor/install.sh` no servidor. O `.gitattributes` do repo previne recidiva. |
| `install.sh` morre silenciosamente após "Configurando PostgreSQL" sem mensagem | `tr -dc … \| head -c N` aborta script via SIGPIPE + `pipefail` | Já corrigido: trocado por `openssl rand -hex 16`. Se voltar, atualiza do git. |
| `ProgrammingError: the query has 0 placeholders but 2 parameters were passed` no login | Algum arquivo Python ainda usa `?` (placeholder de SQLite) em vez de `%s` (psycopg) | Grep `[\?][\s,\)]` nos .py. Trocar todos por `%s`. Foi o caso de `auth.py` em maio/2026. |
| `AttributeError: module 'database' has no attribute 'criar_banco'` | Nome correto da função é `criar_tabelas` | Já corrigido no install.sh e migrar.py atuais. |
| Login não funciona mas DB existe | Postgres vazio (migração não rodou ou rodou e migrou 0) | `psql ... SELECT COUNT(*) FROM usuarios` — se 0, rodar migração novamente. Conferir output: linhas devem ser "X lidas, X novas". |
| Sara/Diogo não consegue logar | Não há usuário "default" garantido após migração para Postgres | Migrar do `.db` legado, ou inserir manual via psql (`INSERT INTO usuarios ...`). |
| Não vejo as mudanças no `app.py` | Cache do browser OU módulo cacheado | `Ctrl+Shift+R` no navegador; se for `auth.py`/`database.py`, restart do serviço |
| Apache `configtest` falha | Sintaxe do vhost | `apache2ctl configtest` mostra a linha; verifica `/etc/apache2/conf-available/gestao-de-projetos.conf` |
| `chown` ou `chmod` falha | Sem sudo | Tudo aqui exige `sudo` |

---

## 10. Como reinstalar do zero (caso queira)

O `install.sh` é idempotente, então basta rodar de novo. Mas se quiser
um "estado limpo" REAL:

```bash
sudo systemctl stop gestao-de-projetos
sudo rm -rf /var/www/html/gestao_de_projetos/venv
sudo rm -rf /var/www/html/gestao_de_projetos/.local
sudo a2disconf gestao-de-projetos
sudo rm -f /etc/apache2/conf-available/gestao-de-projetos.conf
sudo rm -f /etc/systemd/system/gestao-de-projetos.service
sudo systemctl daemon-reload
sudo systemctl reload apache2

# Aí roda o install de novo:
sudo SERVER_IP="152.92.238.40" bash /var/www/html/gestao_de_projetos/setup-novo-servidor/install.sh
```

O **banco PostgreSQL** e o **db.env** **não são tocados** nesse processo
(estão preservados). Se quiser começar com banco vazio também:

```bash
# Apaga o banco Postgres (NÃO DÁ PRA DESFAZER — faça backup antes!)
sudo -u postgres dropdb gestao_servpen
sudo rm -f /etc/gestao-de-projetos/db.env

# Move os .db legados pra fora (se ainda houver)
sudo mv /var/www/html/gestao_de_projetos/gestao_equipe.db /tmp/old-db.bak 2>/dev/null || true
sudo mv /var/www/html/gestao_de_projetos/servpen.db       /tmp/old-db.bak 2>/dev/null || true
```

E rode o `install.sh`. O `database.py` cria todas as tabelas e o usuário
`Sara Borges` automaticamente no primeiro boot.

---

## 11. Resumo "Tudo em 5 passos"

```bash
# 1. Servidor novo (152.92.238.40), com sudo + internet
ssh user@152.92.238.40

# 2. Copia o código pra /var/www/html/gestao_de_projetos/
#    (do servidor antigo, do git, do pendrive — como preferir)

# 3. Roda o instalador
cd /var/www/html/gestao_de_projetos
sudo SERVER_IP="152.92.238.40" bash setup-novo-servidor/install.sh

# 4. Abre no navegador
#    http://152.92.238.40/gestao-de-projetos/

# 5. Loga como Sara Borges / Senbt0408 e cadastra os outros usuários
#    pela aba 👥 Equipe.
```

Pronto.
