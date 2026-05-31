# Manual de Atualização — Gestão de Projetos SERVPEN

Como aplicar alterações no app rodando em
**http://152.92.228.20/gestao-de-projetos/**.

---

## 1. Topologia

| Onde | O quê |
|---|---|
| `/var/www/html/gestao_de_projetos/` (Linux) | Pasta raiz do projeto no servidor |
| `Z:\` (Windows, via SMB) | Mesma pasta acima, mapeada como drive de rede |
| `gestao-de-projetos.service` (systemd) | Processo Streamlit rodando em background |
| `127.0.0.1:8501` | Porta interna onde o Streamlit escuta |
| Apache (porta 80) | Faz proxy reverso de `/gestao-de-projetos/` |
| URL pública | `http://152.92.228.20/gestao-de-projetos/` |

A HOME do usuário `sara` foi configurada para `/var/www/html/gestao_de_projetos/`,
então ao logar via SSH ele cai direto na pasta certa.

---

## 2. Como editar o código

Três caminhos equivalentes — todos alteram os mesmos arquivos:

### A. SMB (Windows)
Edita direto em `Z:\` (ex.: `Z:\app.py`) com qualquer editor. Salva.

### B. SSH terminal
```bash
ssh sara@152.92.228.20      # cai direto em /var/www/html/gestao_de_projetos/
nano app.py                 # ou vim, micro, etc.
```

### C. VS Code Remote-SSH
`Ctrl+Shift+P` → `Remote-SSH: Connect to Host` → `sara@152.92.228.20`.
A pasta do projeto abre automaticamente.

---

## 3. Quando precisa reiniciar o serviço

| Arquivo alterado | Restart necessário? |
|---|---|
| `app.py` | **Não** — basta `Ctrl+Shift+R` no browser (`fileWatcherType=poll` detecta) |
| `auth.py` | **Sim** |
| `database.py` | **Sim** |
| `relatorios.py` | **Sim** |
| `.streamlit/config.toml` | **Sim** |
| Qualquer outro `.py` que `app.py` faz `import` | **Sim** |
| `.db` (dados — usuários, projetos, etc.) | **Não** |
| `anexos/*` (arquivos anexados) | **Não** |
| `deploy/*.service` | **Sim** (e `sudo systemctl daemon-reload`) |
| `deploy/*.conf` (Apache) | **Sim** (e `sudo systemctl reload apache2`) |

**Regra geral:** se mudou um `.py` que o `app.py` importa, restart. Se mudou só
o `app.py`, basta refresh no browser.

### Como restartar
```bash
sudo systemctl restart gestao-de-projetos
sudo systemctl status gestao-de-projetos --no-pager -l | head -10
```

---

## 4. Como instalar uma biblioteca nova

```bash
cd /var/www/html/gestao_de_projetos
./venv/bin/pip install nome-do-pacote
sudo systemctl restart gestao-de-projetos
```

### Duas armadilhas críticas

**1. NUNCA use `pip install --user`** (sem o `./venv/bin/`).
Isso instala em `~/.local/` da sara, que é literalmente
`/var/www/html/gestao_de_projetos/.local/` — fica fora do venv mas o Python
acha mesmo assim, e prioriza sobre o venv. Já causou downtime no projeto
(foi como o pyarrow ressuscitou e crashou tudo).

**2. Libs com binário compilado podem dar `Illegal instruction`** porque a CPU
do servidor (AMD Athlon II X2 250) não tem AVX/AVX2 que os wheels modernos do
PyPI exigem. Casos confirmados: `numpy`, `pandas`, `pyarrow`, `scipy`.
Para essas, instale via apt:

```bash
sudo apt install -y python3-NOME    # Ubuntu compila com baseline CPU-conservador
# se a versão do PyPI já foi baixada no venv, apague pra forçar uso da apt:
sudo rm -rf venv/lib/python3.12/site-packages/NOME*
sudo systemctl restart gestao-de-projetos
```

**Já instalados via apt:** `python3-numpy`, `python3-pandas`, `python3-reportlab`,
`python3-pil`.

**Intencionalmente ausente:** `pyarrow`. Causa SIGILL imediato. Por causa
disso `st.dataframe`, `st.table` e leitura/escrita de Parquet **não funcionam**
neste app — use HTML tables (`st.markdown` com `<table>`) no lugar.

---

## 5. Como verificar que a alteração funcionou

```bash
# Status do serviço
sudo systemctl status gestao-de-projetos --no-pager -l | head -10

# Log ao vivo (Ctrl+C pra sair)
sudo tail -f /var/log/gestao-de-projetos.log

# Endpoint de saúde — deve retornar 200 OK
curl -sI http://152.92.228.20/gestao-de-projetos/_stcore/health
```

No browser, use **Ctrl+Shift+R** (hard reload) pra invalidar cache do navegador.

---

## 6. Debug em foreground

Quando o app está crashando e você precisa ver o traceback ao vivo:

```bash
sudo systemctl stop gestao-de-projetos
cd /var/www/html/gestao_de_projetos
./venv/bin/streamlit run app.py
# Ctrl+C pra parar
sudo systemctl start gestao-de-projetos
```

A URL continua a mesma (`http://152.92.228.20/gestao-de-projetos/`) — Streamlit
em foreground também escuta na 8501 e o Apache continua proxy-ando.

Você verá no terminal:
- O banner "You can now view your Streamlit app..."
- Qualquer `print()` ou stack trace que o app gerar em tempo real

---

## 7. Backup e rollback

### Backups automáticos
Toda vez que `deploy/install.sh` roda, faz backup dos `.db` em
`/var/www/html/gestao_de_projetos/backups/` com timestamp:
```
backups/gestao_equipe.db.20260526-164532.bak
backups/servpen.db.20260526-164532.bak
```

### Backup manual antes de uma mudança grande
```bash
cd /var/www/html/gestao_de_projetos
TS=$(date +%F-%H%M)
cp gestao_equipe.db backups/gestao_equipe.db.manual-$TS.bak
cp servpen.db       backups/servpen.db.manual-$TS.bak
cp app.py           backups/app.py.manual-$TS.bak
```

### Restaurar se quebrou
```bash
sudo systemctl stop gestao-de-projetos
cp backups/app.py.manual-2026-05-26-1645.bak app.py
# (ou o .db correspondente)
sudo systemctl start gestao-de-projetos
```

---

## 8. Erros comuns e como resolver

| Sintoma | Causa | Solução |
|---|---|---|
| `Illegal instruction (core dumped)` | Lib compilada usando AVX | Instale via apt + apague do venv (seção 4) |
| `Port 8501 is already in use` | systemd já está rodando | `sudo systemctl stop gestao-de-projetos` antes |
| `ModuleNotFoundError: No module named 'X'` | Dep faltando no venv | `./venv/bin/pip install X` + restart |
| `FormMixin.form_submit_button() got an unexpected keyword argument 'key'` | `st.form_submit_button` não aceita `key=` | Remover `key=...` da chamada (Streamlit auto-gera) |
| `StreamlitSetPageConfigMustBeFirstCommandError` | `st.set_page_config()` chamado mais de uma vez | Deixar somente 1 chamada, no topo do `app.py` |
| Browser em loop "CONNECTING..." | App crasha a cada request | Ver log: `sudo tail -50 /var/log/gestao-de-projetos.log` |
| Mudança no `.py` não aparece | Cache de módulo Python | `sudo systemctl restart gestao-de-projetos` |
| Sem permissão pra editar via SMB | Dono é `www-data`, grupo SMB sem write | `sudo chmod -R g+rwX /var/www/html/gestao_de_projetos` |
| `Could not chdir to home directory` no SSH | HOME do usuário inválida | `sudo usermod -d /var/www/html/gestao_de_projetos sara` |

---

## 9. Restrição de hardware

O servidor tem CPU **AMD Athlon II X2 250** (2009, arquitetura K10) sem AVX,
AVX2 nem SSE4.2. Implicações:

- Wheels modernos do PyPI compilados com `-march=x86-64-v2` ou superior dão
  `SIGILL` ao serem importados
- Pacotes do `apt` do Ubuntu são compilados com baseline `x86-64-v1`
  (funciona em qualquer CPU desde 2003)
- Sempre prefira `apt install python3-NOME` para libs com binário compilado

---

## 10. Layout dos arquivos

### No projeto
```
/var/www/html/gestao_de_projetos/
├── app.py                          # Entrada principal do Streamlit
├── auth.py                         # Login / logout
├── database.py                     # Tabelas, queries, migrações
├── relatorios.py                   # Geração de PDF (usa reportlab)
├── gestao_equipe.db                # SQLite: usuários, projetos, diário, arquivos
├── servpen.db                      # SQLite: agenda, progresso_disciplinas
├── anexos/                         # Arquivos enviados pelos usuários
├── backups/                        # Backups automáticos dos .db
├── venv/                           # Virtualenv Linux com --system-site-packages
├── .streamlit/
│   └── config.toml                 # port, baseUrlPath, fileWatcherType, tema
├── .local/                         # ~/.local da sara - NÃO instalar nada aqui
└── deploy/
    ├── install.sh                  # Script idempotente de deploy
    ├── gestao-de-projetos.service  # Unit do systemd
    └── gestao-de-projetos.conf     # Conf do Apache (proxy + WebSocket)
```

### Fora do projeto, no servidor
```
/etc/systemd/system/gestao-de-projetos.service     # cópia do deploy/
/etc/apache2/conf-enabled/gestao-de-projetos.conf  # link do deploy/
/var/log/gestao-de-projetos.log                    # stdout/stderr do serviço
```

---

## 11. Re-deploy completo (do zero)

Se algo der muito errado e você quiser reconstruir o ambiente sem perder dados:

```bash
sudo bash /var/www/html/gestao_de_projetos/deploy/install.sh
```

O `install.sh` é **idempotente** — pode rodar quantas vezes quiser. Ele faz:

1. Backup dos `.db` em `backups/`
2. `apt install python3 python3-venv build-essential python3-numpy python3-pandas`
3. Recria a `venv/` com `--system-site-packages`
4. `pip install streamlit plotly fpdf2 xlsxwriter openpyxl`
5. Apaga `numpy*`, `pandas*`, `pyarrow*` do venv (força usar versão apt CPU-safe)
6. `chown -R www-data` + `chmod g+s` (pra você continuar conseguindo escrever via SMB)
7. Instala/atualiza o systemd unit, ativa e reinicia
8. Habilita módulos do Apache, instala o vhost, valida e recarrega
9. Testa o `_stcore/health` interno e via Apache

No fim imprime `DONE. Acesse: http://152.92.228.20/gestao-de-projetos/`.

---

## 12. Workflow recomendado para uma alteração

1. **Backup defensivo** (opcional mas barato):
   ```bash
   cp app.py backups/app.py.antes-de-mexer-$(date +%F-%H%M).bak
   ```

2. **Edita** o arquivo (SMB, SSH ou VS Code).

3. **Aplica**:
   - Mexeu só em `app.py` → `Ctrl+Shift+R` no browser
   - Mexeu em outro `.py` → `sudo systemctl restart gestao-de-projetos`

4. **Valida**:
   - Abre `http://152.92.228.20/gestao-de-projetos/` com `Ctrl+Shift+R`
   - Se algo quebrar: `sudo tail -30 /var/log/gestao-de-projetos.log`

5. **Se quebrou**: rollback do passo 1, ou `git checkout` se estiver com versionamento.

---

## 13. Logs e diagnóstico rápido

```bash
# Log completo do app (stdout + stderr do Streamlit)
sudo tail -50 /var/log/gestao-de-projetos.log

# Log do systemd (inclui sinais como SIGILL, crashes, restarts)
sudo journalctl -u gestao-de-projetos -n 50 --no-pager

# Log do Apache (se o proxy estiver dando 502/503)
sudo tail -30 /var/log/apache2/error.log

# Status detalhado
sudo systemctl status gestao-de-projetos --no-pager -l

# Quem está escutando na 8501?
sudo ss -tlnp | grep 8501
```

---

## 14. Login no app

Existe um usuário garantido pelo `database.py` (é regravado em todo boot,
não pode ser apagado pela UI sem voltar):

- **Usuário:** `Sara Borges`
- **Senha:** `Senbt0408`
- **Perfil:** Gestor (acesso total)

Use esse para entrar a primeira vez ou se algo bloquear o login.
Outros usuários podem ser cadastrados pela aba **👥 Equipe** (visível só
para Gestor).
