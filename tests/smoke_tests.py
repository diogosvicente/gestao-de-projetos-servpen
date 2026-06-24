"""Smoke tests do app — roda SEM pytest:

    set -a; . ./db.env.local; set +a
    ./venv/bin/python tests/smoke_tests.py

Requer o Postgres no ar. Renderiza cada view via streamlit AppTest (pega
exceções de import/render) e valida os helpers críticos de Tarefas. Sai com
código != 0 se algo falhar — bom como checagem rápida antes de um deploy.
"""

from __future__ import annotations

import os
import sys
from datetime import date

# Raiz do projeto no path (permite rodar de tests/ ou da raiz).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from streamlit.testing.v1 import AppTest  # noqa: E402
import database as db  # noqa: E402

_FALHAS = []


def _check(nome, cond, detalhe=""):
    ok = bool(cond)
    print(("  OK  " if ok else "  XX  ") + nome
          + ("" if ok else f"   -> {detalhe}"))
    if not ok:
        _FALHAS.append(nome)


def _seed(at, **extra):
    s = {
        "usuario": "ZZsmoke_gestor", "perfil": "Gestor", "equipe": "GERAL",
        "tema": "dark", "autenticado": True,
        "lista_checklist": db.listar_disciplinas() or ["CFTV"],
    }
    s.update(extra)
    for k, v in s.items():
        at.session_state[k] = v


VIEWS = [
    "views/dashboard.py", "views/kanban.py", "views/agenda.py",
    "views/diario.py", "views/tarefas.py", "views/novo_projeto.py",
    "views/equipe.py", "views/arquivos.py", "views/chat.py",
    "views/auditoria.py", "views/acessos.py",
]


def render_views():
    print("Render das views (perfil Gestor):")
    for v in VIEWS:
        try:
            at = AppTest.from_file(v, default_timeout=90)
            _seed(at)
            at.run()
            _check(v, not at.exception,
                   str(at.exception[0].value)[:140] if at.exception else "")
        except Exception as e:  # noqa: BLE001
            _check(v, False, repr(e)[:140])


def db_tarefas():
    print("Helpers de Tarefas:")
    nm = "ZZsmoke_user"

    def _limpa():
        conn = db.conectar(); c = conn.cursor()
        c.execute("DELETE FROM tarefas WHERE usuario=%s OR criado_por=%s",
                  (nm, nm))
        conn.commit(); conn.close()

    _limpa()
    db.criar_tarefa(nm, "propria", privada=True, criado_por=nm,
                    data=date.today())
    _check("tarefa propria nao vira 'nao vista'",
           db.contar_tarefas_nao_vistas(nm) == 0)

    db.criar_tarefa(nm, "atribuida", privada=False, criado_por="ChefeSmoke",
                    data=date.today())
    _check("tarefa atribuida vira 'nao vista'",
           db.contar_tarefas_nao_vistas(nm) == 1)

    db.marcar_tarefas_vistas(nm)
    _check("abrir a aba zera 'nao vista'",
           db.contar_tarefas_nao_vistas(nm) == 0)

    _t = db.listar_tarefas_de(nm)
    _check("listar traz 'data' e 'concluida_em'",
           bool(_t) and "data" in _t[0] and "concluida_em" in _t[0])

    _ids = {t["descricao"]: t["id"] for t in _t}
    db.alternar_tarefa(_ids["propria"], True)
    _lst = db.listar_tarefas_de(nm)
    _check("ordenado: pendente antes da concluida",
           (not _lst[0]["concluida"]) and _lst[-1]["concluida"])
    _check("data de conclusao gravada",
           any(t["concluida_em"] for t in _lst if t["concluida"]))

    _limpa()


def main():
    db.criar_tabelas()
    db_tarefas()
    render_views()
    print()
    if _FALHAS:
        print(f"FALHOU: {len(_FALHAS)} item(ns) -> {_FALHAS}")
        return 1
    print("OK: todos os smoke tests passaram.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
