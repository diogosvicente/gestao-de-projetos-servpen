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
├── gestao_equipe.db        ← (opcional, se quiser migrar os dados)
├── anexos/                 ← (opcional, arquivos enviados pelos usuários)
├── setup-novo-servidor/    ← pasta com install.sh, vhost, .service
│   ├── install.sh
│   ├── gestao-de-projetos.conf
│   ├── gestao-de-projetos.service
│   └── INSTALAR-EM-NOVO-SERVIDOR.md  (este arquivo)
└── (outros .md de referência, opcionais)
```

> Se você **não copiou os `.db`**, eles serão criados vazios no primeiro boot.
> O usuário `Sara Borges` com senha `Senbt0408` é garantido pelo
> `database.py` em todo boot — sempre dá pra entrar.

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
9. **Cria o schema no Postgres** chamando `database.criar_banco()`. Se
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
| Backup manual do Postgres | `sudo -u postgres pg_dump gestao_servpen \| gzip > ~/bkp-$(date +%F).sql.gz` |
| Restaurar backup do Postgres | `gunzip -c ~/bkp-YYYY-MM-DD.sql.gz \| sudo -u postgres psql gestao_servpen` |
| Status do Postgres | `sudo systemctl status postgresql --no-pager -l` |

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
| Sara não consegue logar | Senha do banco diferente | A senha `Senbt0408` é regravada a CADA boot pelo `database.py` — basta restartar |
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
