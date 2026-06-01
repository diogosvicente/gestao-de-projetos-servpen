# Deploy local → produção (152.92.238.40)

Workflow: você desenvolve no PC, comita, e roda **um único comando** que
envia tudo pra produção com segurança (backup automático, rollback em 1
linha se quebrar).

## Comando do dia-a-dia

**Windows (PowerShell):**
```powershell
.\deploy.ps1
```

**Linux/Mac/WSL/Git Bash:**
```bash
./deploy.sh
```

O script vai:

1. Confirmar que você não tem mudanças não comitadas
2. Confirmar que está na branch `main`
3. Mostrar a **lista de commits** que vão pra produção
4. Pedir confirmação pra fazer push
5. `git push origin main`
6. **Conectar no servidor, fazer `git fetch`, e mostrar a LISTA DE ARQUIVOS
   alterados com stats** (+linhas / −linhas por arquivo, total geral)
7. Perguntar o **modo de aplicação**:

   ```
   Como aplicar?
     [A]plicar todos          (recomendado, usa atualizar-app.sh)
     [I]nterativo             (confirmar 1 por 1 — pode quebrar deps)
     [V]er diff completo      (paginado, depois volta ao menu)
     [C]ancelar               (nada será aplicado)
   ```

   No modo `[I]`, pra cada arquivo:
   ```
   [3/8] views/dashboard.py  +12 / -5
     [Y]aceitar / [n]pular / [v]er diff / [q]cancelar tudo:
   ```

8. Aplicar os arquivos confirmados + restart do serviço
9. Health check externo (`/_stcore/health`)
10. Mostrar a URL do app + linha pronta pra rollback

Tempo típico:
- Modo `[A]`: ~30s a 1min
- Modo `[I]`: depende de quantos arquivos você revisa

## Opções

| Flag | O que faz |
|---|---|
| `--dry-run` (sh) / `-DryRun` (ps1) | Mostra o que faria, sem executar nada |
| `--skip-push` / `-SkipPush` | Pula `git push` (se você já pushed manualmente) |
| `--branch=hotfix` / `-Branch hotfix` | Deploy de outra branch (normalmente `main`) |
| `--help` (sh) | Imprime essa ajuda |

## Cuidado com o modo Interativo `[I]`

Pular arquivos é tecnicamente possível mas **pode quebrar o app**: se você
pula `core/helpers.py` mas aceita `views/dashboard.py` que importa um helper
NOVO de lá, dashboard quebra com `ImportError`.

Quando o modo interativo aplica parcial, o **HEAD do git no servidor não
avança** — fica no commit antigo, com o working tree "modificado". O script
faz **backup automático** antes (`backups/codigo.<TS>.pre-partial-deploy.tar.gz`)
e te avisa quais arquivos foram pulados ao final.

**No próximo deploy**:
- Se você escolher `[A]plicar todos`, os arquivos pulados antes vão ser
  sobrescritos pelo `origin/main`.
- Se quiser MANTER a versão antiga, pule de novo no próximo deploy.

Recomendação: use `[V]er diff completo` pra revisar tudo, depois `[A]plicar
todos`. Modo `[I]` só pra casos especiais (ex.: hotfix que mudou 1 arquivo
específico e o resto pode esperar).

> **Modo PowerShell**: o `deploy.ps1` no Windows hoje oferece apenas `[A]/[C]`.
> Pra usar o interativo `[I]` no Windows, rode `deploy.sh` via **Git Bash**
> (que vem com o Git for Windows).

## Setup uma vez (no servidor 238.40)

Você só precisa fazer isso **1 vez** no servidor pra habilitar o
workflow de deploy. Depois, o ciclo é só `./deploy.sh` da máquina local.

> **Não precisa git no servidor.** O `deploy.sh` faz rsync direto do PC
> pro servidor. O git fica só no seu PC (que é o lugar correto pra ele).

### A) Verificar pré-requisitos no servidor

Conecta no servidor e checa que essas coisas existem:

```bash
ssh admin@152.92.238.40

# rsync precisa estar instalado (em geral já vem):
which rsync || sudo apt install -y rsync

# A pasta do app deve existir com app.py + venv:
ls /var/www/gestao-de-projetos/app.py
ls /var/www/gestao-de-projetos/venv/bin/pip

# Serviço systemd deve estar configurado:
systemctl status gestao-de-projetos | head -3
```

Se a pasta NÃO existe ainda, faça a instalação inicial via
`setup-novo-servidor/install.sh` (ver `INSTALAR-EM-NOVO-SERVIDOR.md`).

### B) SSH sem senha do PC pro servidor

Do PC local (uma vez):
```bash
# Gera chave (se ainda não tem):
ssh-keygen -t ed25519

# Manda pro servidor:
ssh-copy-id admin@152.92.238.40

# Testa — não deve pedir senha:
ssh admin@152.92.238.40 'whoami'
```

### C) `sudo` sem senha (opcional, recomendado pra deploy automático)

Por padrão os comandos `sudo` que o `deploy.sh` envia vão pedir a senha
do `admin`. Pra deploy sem prompts, edite `/etc/sudoers.d/deploy`:

```bash
sudo visudo -f /etc/sudoers.d/deploy
```

Cole (os comandos exatos que o deploy.sh dispara):
```
admin ALL=(ALL) NOPASSWD: /usr/bin/chown, /usr/bin/find, /usr/bin/systemctl, /usr/bin/tee, /var/www/gestao-de-projetos/venv/bin/pip
```

Salva e fecha. Agora o deploy roda sem pedir senha — mas só esses
comandos específicos, nada mais.

## Rollback (se algo der errado)

O `deploy.sh` mantém `.last-deploy` no servidor com o SHA do último
deploy. Pra rollback:

```bash
# Localmente:
cd Z:\
git stash                                       # se tiver mudanças locais
git checkout <SHA-anterior-ou-tag>
./deploy.sh                                     # re-deploya o estado anterior
git checkout main
git stash pop                                   # restaura mudanças locais
```

O próprio `deploy.sh` já te mostra essa receita no fim de cada deploy
com o SHA exato do estado anterior.

### Alternativa: backup tar.gz no servidor (modo interativo)

Quando você usa modo `[I]nterativo`, o script faz backup automático
antes de aplicar:

```bash
ssh admin@152.92.238.40
ls /var/www/gestao-de-projetos/backups/codigo.*.pre-partial-deploy.tar.gz | tail -3
sudo systemctl stop gestao-de-projetos
sudo tar xzf /var/www/gestao-de-projetos/backups/codigo.<TIMESTAMP>.tar.gz \
     -C /var/www/
sudo systemctl start gestao-de-projetos
```

## Pre-flight check antes do primeiro deploy

```bash
# 1. SSH funciona (sem senha de preferência)?
ssh admin@152.92.238.40 'echo OK'

# 2. rsync existe no servidor?
ssh admin@152.92.238.40 'which rsync'

# 3. Pasta do app + venv existem?
ssh admin@152.92.238.40 'ls -la /var/www/gestao-de-projetos/app.py /var/www/gestao-de-projetos/venv/bin/pip'

# 4. Serviço systemd existe?
ssh admin@152.92.238.40 'systemctl status gestao-de-projetos | head -3'

# 5. Health check direto:
curl -sI http://152.92.238.40/gestao-de-projetos/_stcore/health
```

Se os 5 derem OK, está pronto pra `./deploy.sh`.

## Estrutura mental

```
PC local (Windows/Mac/Linux)
  │ git commit -m "..."  ← git só fica AQUI
  │ ./deploy.sh
  │
  │ 1) lê .last-deploy via ssh
  │ 2) git diff <last>..HEAD → lista de arquivos
  │ 3) menu [A]/[I]/[V]/[C]
  │ 4) rsync arquivos selecionados
  ▼
Servidor 152.92.238.40 (SEM git)
  │ /var/www/gestao-de-projetos/    ← arquivos do app (sobrescritos pelo rsync)
  │   ├── .last-deploy              ← SHA do último deploy (gerenciado pelo script)
  │   ├── venv/                     ← preservado entre deploys
  │   ├── anexos/                   ← preservado entre deploys
  │   └── backups/                  ← histórico
  │ /etc/gestao-de-projetos/db.env  ← credenciais Postgres
  │
  │ ssh → sudo chown + pip (se reqs) + systemctl restart
  ▼
Streamlit (systemd) → Apache → http://152.92.238.40/gestao-de-projetos/
```
