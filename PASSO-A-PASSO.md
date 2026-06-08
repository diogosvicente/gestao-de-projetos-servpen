# 📋 Passo a passo — Alterar, salvar e publicar

Guia rápido do fluxo de trabalho. São **3 etapas**:

1. **Rodar local** → testar a alteração na sua máquina
2. **Commit + push** → salvar no GitHub
3. **Deploy** → publicar em produção (o site que todos usam)

> Sempre faça nessa ordem. Nunca pule direto pro deploy sem testar local.

---

## 1️⃣ Rodar o projeto localmente

No terminal (WSL/Ubuntu), dentro da pasta do projeto:

```bash
./run-local.sh
```

**O que faz:** sobe o banco de dados (Postgres no Docker) e abre o sistema
no navegador em `http://localhost:8501`. É uma cópia de teste, **separada da
produção** — pode mexer à vontade que não afeta ninguém.

**Faça suas alterações** nos arquivos e veja o resultado no navegador
(o site atualiza sozinho ao salvar um arquivo).

Quando terminar de testar, **pare o servidor** com `Ctrl + C` no terminal.

> 💡 Se aparecer erro de Docker, confira se o Docker está aberto/rodando.

---

## 2️⃣ Salvar no GitHub (commit + push)

Depois que a alteração ficou boa no teste local, salve no GitHub:

```bash
git add .
git commit -m "texto explicando o que mudou"
git push
```

**O que cada comando faz:**

| Comando | Para que serve |
|---|---|
| `git add .` | Marca **todos os arquivos alterados** pra serem salvos. O `.` significa "tudo". |
| `git commit -m "..."` | Cria um **ponto de salvamento** com uma mensagem que descreve a mudança. Troque o texto entre aspas por algo claro, ex.: `"ajuste na cor do botão de login"`. |
| `git push` | **Envia** esse salvamento pro GitHub (a nuvem). Sem isso, a mudança fica só na sua máquina. |

> 💡 A mensagem do commit deve ser curta e dizer **o que** mudou, não como.
> Exemplos bons: `"corrige data errada na agenda"`, `"adiciona campo de telefone"`.

---

## 3️⃣ Publicar em produção (deploy)

Com a alteração já no GitHub, é hora de colocar no ar:

```bash
./deploy-238.sh
```

**O que faz:** envia os arquivos pro servidor de produção
(`152.92.238.40`), reinicia o sistema lá e confere se subiu certo. Depois
disso, **todos os usuários já veem a mudança** no site real.

O script vai **mostrar o que vai enviar e pedir confirmação** — leia, e se
estiver tudo certo, digite `y` e aperte Enter.

No fim, ele mostra o endereço do site:
`http://152.92.238.40/gestao-de-projetos/`

> ⚠️ Só rode o deploy **depois** de testar local E dar o push. O deploy pega
> o que está salvo — então a sequência das 3 etapas importa.

---

## ✅ Resumo (cola rápida)

```bash
# 1. Testar local
./run-local.sh
#    (faça as alterações, teste no navegador, Ctrl+C pra parar)

# 2. Salvar no GitHub
git add .
git commit -m "descreva a mudança aqui"
git push

# 3. Publicar em produção
./deploy-238.sh
```

---

## ❓ Perguntas comuns

**Esqueci de testar local e já dei push, e agora?**
Sem problema — só rode `./run-local.sh` e teste antes de fazer o deploy.
O que **não** pode é deployar algo quebrado.

**Dei push mas esqueci o deploy. A mudança está no ar?**
Não. O `git push` só salva no GitHub. Pra aparecer no site, precisa do
`./deploy-238.sh`.

**Apareceu erro no `git push` pedindo usuário/senha ou chave.**
A conexão com o GitHub pode não estar configurada nessa máquina. Chame o
Diogo pra configurar a chave SSH (é uma vez só).

**O deploy deu erro no meio.**
Copie a mensagem de erro e mande pro Diogo. Nada foi quebrado no site se o
deploy não terminou — ele só publica no fim, se tudo deu certo.
