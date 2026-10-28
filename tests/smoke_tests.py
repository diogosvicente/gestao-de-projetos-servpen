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


def db_tarefas_proj_rec():
    print("Projeto + Recorrência:")
    nm = "ZZsmoke_pr"
    conn = db.conectar(); c = conn.cursor()
    c.execute("DELETE FROM tarefas WHERE usuario=%s", (nm,))
    c.execute("INSERT INTO projetos (projetista,projeto,status) "
              "VALUES (%s,%s,%s) RETURNING id",
              ("ZZsmoke", "ZZ Smoke Proj", "Ativo"))
    pid = c.fetchone()[0]
    conn.commit(); conn.close()

    db.criar_tarefa(nm, "vinc+rec", privada=False, criado_por=nm,
                    data=date(2026, 7, 1), projeto_id=pid,
                    recorrencia="semanal")
    _t = db.listar_tarefas_de(nm)[0]
    _check("vinculo: projeto_nome retornado",
           _t.get("projeto_nome") == "ZZ Smoke Proj")
    _check("vinculo aparece em listar_tarefas_por_projeto",
           len(db.listar_tarefas_por_projeto(pid)) == 1)

    db.atualizar_projeto_tarefa(_t["id"], None)
    _check("desvincular projeto",
           db.listar_tarefas_de(nm)[0].get("projeto_nome") is None)

    db.atualizar_recorrencia_tarefa(_t["id"], "nenhuma")
    db.alternar_tarefa(_t["id"], True)
    db.criar_proxima_ocorrencia(_t["id"])
    _check("recorrencia parada NAO gera proxima",
           len(db.listar_tarefas_de(nm)) == 1)

    db.criar_tarefa(nm, "rec-ativa", privada=False, criado_por=nm,
                    data=date(2026, 8, 1), recorrencia="mensal")
    _ra = [x for x in db.listar_tarefas_de(nm)
           if x["descricao"] == "rec-ativa"][0]
    db.alternar_tarefa(_ra["id"], True)
    db.criar_proxima_ocorrencia(_ra["id"])
    _prox = [x for x in db.listar_tarefas_de(nm)
             if x["descricao"] == "rec-ativa" and not x["concluida"]]
    _check("recorrencia ativa gera proxima (01/09)",
           bool(_prox) and str(_prox[0]["data"]) == "2026-09-01")

    db.criar_tarefa(nm, "antiga atrasada", privada=False, criado_por=nm,
                    data=date(2020, 1, 1))
    _check("conta tarefa atrasada (>=1)",
           db.contar_tarefas_atrasadas(nm) >= 1)
    db.excluir_tarefas_concluidas(nm)
    _check("limpar concluidas: nenhuma concluida resta",
           all(not x["concluida"] for x in db.listar_tarefas_de(nm)))

    conn = db.conectar(); c = conn.cursor()
    c.execute("DELETE FROM tarefas WHERE usuario=%s", (nm,))
    c.execute("DELETE FROM projetos WHERE id=%s", (pid,))
    conn.commit(); conn.close()


def db_documentos_etapas():
    print("Documentações geradas + % das etapas:")
    nm = "ZZsmoke_docs"
    conn = db.conectar(); c = conn.cursor()
    c.execute("INSERT INTO projetos (projetista,projeto,status) "
              "VALUES (%s,%s,%s) RETURNING id",
              (nm, "ZZ Smoke Docs", "Ativo"))
    pid = c.fetchone()[0]
    conn.commit(); conn.close()

    def _espelho():
        cc = db.conectar(); cx = cc.cursor()
        cx.execute("SELECT documentacoes_geradas FROM projetos WHERE id=%s",
                   (pid,))
        v = cx.fetchone()[0]
        cc.close()
        return v or ""

    try:
        reg, rep = db.adicionar_documentos_projeto(
            pid, ["Memorial.pdf", "ART.pdf", "memorial.PDF", "  "],
            criado_por=nm)
        _check("registra nomes; ignora repetido e vazio",
               reg == ["Memorial.pdf", "ART.pdf"] and rep == ["memorial.PDF"],
               f"{reg} / {rep}")
        _docs = {d["nome"]: d for d in db.listar_documentos_projeto(pid)}
        _check("lista traz autor e data do registro",
               set(_docs) == {"Memorial.pdf", "ART.pdf"}
               and all(d["criado_por"] == nm and d["criado_em"]
                       for d in _docs.values()))
        _dia = _docs["ART.pdf"]["criado_em"].strftime("%d/%m/%Y")
        _check("espelho em texto (Excel/PDF), na ordem de registro",
               _espelho() == f"Memorial.pdf ({_dia}); ART.pdf ({_dia})",
               _espelho())
        _check("excluir devolve o nome removido",
               db.excluir_documento_projeto(_docs["ART.pdf"]["id"])
               == "ART.pdf")
        _check("espelho atualizado depois de excluir",
               _espelho() == f"Memorial.pdf ({_dia})", _espelho())

        db.salvar_etapas(pid, [
            {"nome": "Levantamento", "duracao_dias": 5, "dias_offset": 0,
             "ordem": 0, "percentual": 10},
            {"nome": "Projeto", "duracao_dias": 10, "dias_offset": 5,
             "ordem": 1, "percentual": 0},
        ])
        _et = db.listar_etapas(pid)
        _n = db.atualizar_percentual_etapas(
            pid, [(_et[1]["id"], 60), (999999999, 50)])
        _et2 = db.listar_etapas(pid)
        _check("% da etapa gravado sem mexer no resto",
               _n == 1 and _et2[1]["percentual"] == 60
               and _et2[0]["percentual"] == 10
               and [e["nome"] for e in _et2] == ["Levantamento", "Projeto"],
               f"n={_n} {_et2}")
    finally:
        db.excluir_projeto(pid)
        cc = db.conectar(); cx = cc.cursor()
        cx.execute("SELECT COUNT(*) FROM projeto_documentos "
                   "WHERE projeto_id=%s", (pid,))
        _sobra = cx.fetchone()[0]
        cc.close()
        _check("excluir o projeto leva as documentações junto", _sobra == 0)


def db_revisoes():
    print("Revisões da demanda:")
    nm = "ZZsmoke_rev"
    conn = db.conectar(); c = conn.cursor()
    c.execute("INSERT INTO projetos (projetista,projeto,status,demandas,"
              "data_recebimento,data_termino,data_fim) "
              "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
              (nm, "ZZ Smoke Rev", "Concluído", "Elétrica, CFTV",
               date(2026, 1, 10), date(2026, 2, 10), date(2026, 2, 10)))
    pid = c.fetchone()[0]
    for _d in ("Elétrica", "CFTV"):
        c.execute("INSERT INTO progresso_disciplinas (projeto_id, disciplina,"
                  " concluido, percentual) VALUES (%s,%s,1,100)", (pid, _d))
    conn.commit(); conn.close()

    def _proj():
        cc = db.conectar(); cx = cc.cursor()
        cx.execute("SELECT demandas, projetista, status, data_recebimento, "
                   "data_termino, revisao_atual FROM projetos WHERE id=%s",
                   (pid,))
        r = cx.fetchone()
        cc.close()
        return r

    try:
        db.criar_revisao_inicial(pid)
        _r = db.listar_revisoes(pid)
        _check("emissão inicial nasce com os dados do projeto",
               len(_r) == 1 and _r[0]["rotulo"] == "Emissão inicial"
               and _r[0]["projetista"] == nm
               and _r[0]["entregue_em"] == date(2026, 2, 10), _r)

        db.salvar_etapas(pid, [{"nome": "Projeto", "duracao_dias": 5,
                                "dias_offset": 0, "ordem": 0,
                                "percentual": 100}])
        _id_rv, _num_rv = db.abrir_revisao(
            pid, "acréscimo de tomadas", disciplinas="Elétrica, SPDA",
            projetista="ZZsmoke_outro", solicitado_em=date(2026, 5, 2),
            previsao=date(2026, 6, 1), do_zero=True, criado_por=nm)
        _check("numeração automática (R01)", _num_rv == 1 and bool(_id_rv),
               (_id_rv, _num_rv))
        _r = db.listar_revisoes(pid)
        _check("abrir a nova fecha a anterior",
               len(_r) == 2 and _r[0]["entregue_em"] is not None
               and _r[1]["rotulo"] == "R01")

        _dem, _eq, _stt, _drec, _dterm, _ratual = _proj()
        _check("disciplina nova entra no projeto; equipe soma o designado",
               "SPDA" in _dem and "ZZsmoke_outro" in _eq and nm in _eq,
               (_dem, _eq))
        _check("projeto passa a seguir as datas da revisão e volta a executar",
               _stt == "Ativo" and _drec == date(2026, 5, 2)
               and _dterm == date(2026, 6, 1), (_stt, _drec, _dterm))
        _check("rótulo da revisão espelhado no projeto", _ratual == "R01",
               _ratual)

        def _evol(rid):
            cc = db.conectar(); cx = cc.cursor()
            cx.execute("SELECT disciplina, percentual FROM "
                       "progresso_disciplinas WHERE revisao_id=%s", (rid,))
            r = dict(cx.fetchall())
            cc.close()
            return r

        _id_ini = db.listar_revisoes(pid)[0]["id"]
        _check("emissão inicial fica guardada como foi entregue",
               _evol(_id_ini) == {"Elétrica": 100, "CFTV": 100}
               and [e["percentual"] for e
                    in db.listar_etapas(pid, revisao_id=_id_ini)] == [100],
               (_evol(_id_ini), db.listar_etapas(pid, revisao_id=_id_ini)))
        _check("R01 'do zero' ganha evolução e etapas próprias em 0%",
               _evol(_id_rv) == {"Elétrica": 0, "SPDA": 0}
               and [(e["nome"], e["percentual"])
                    for e in db.listar_etapas(pid)] == [("Projeto", 0)],
               (_evol(_id_rv), db.listar_etapas(pid)))

        _id_r0 = db.listar_revisoes(pid)[0]["id"]
        db.adicionar_documentos_projeto(pid, ["Planta.dwg"], criado_por=nm,
                                        revisao_id=_id_r0)
        db.adicionar_documentos_projeto(pid, ["Planta.dwg"], criado_por=nm,
                                        revisao_id=_id_rv)
        _docs = db.listar_documentos_projeto(pid)
        _check("mesmo documento pode ser reemitido noutra revisão",
               len(_docs) == 2
               and {d["revisao"] for d in _docs} == {"Emissão inicial", "R01"},
               [(d["nome"], d["revisao"]) for d in _docs])
        _rep = db.adicionar_documentos_projeto(pid, ["planta.DWG"],
                                               criado_por=nm,
                                               revisao_id=_id_rv)[1]
        _check("repetido na MESMA revisão é ignorado", _rep == ["planta.DWG"],
               _rep)

        _check("desfazer devolve o rótulo da revisão",
               db.excluir_revisao(_id_rv) == "R01")
        _docs = db.listar_documentos_projeto(pid)
        _check("documentos da revisão desfeita voltam pra anterior",
               all(d["revisao"] == "Emissão inicial" for d in _docs),
               [(d["nome"], d["revisao"]) for d in _docs])
        _check("anterior é reaberta e o rótulo do projeto volta",
               db.listar_revisoes(pid)[0]["entregue_em"] is None
               and _proj()[5] == "Emissão inicial")
        _check("emissão inicial não pode ser desfeita",
               db.excluir_revisao(db.listar_revisoes(pid)[0]["id"]) is None)
        _p = _proj()
        _check("desfazer: projeto volta às datas da revisão anterior",
               _p[3] == date(2026, 1, 10) and _p[4] == date(2026, 2, 10), _p)
        _check("desfazer leva a evolução e as etapas da revisão junto",
               _evol(_id_rv) == {}
               and not db.listar_etapas(pid, revisao_id=_id_rv))

        # "Continua a anterior", da demanda inteira: cada disciplina parte do
        # último % que teve; as etapas copiam os da anterior.
        _id_r1, _ = db.abrir_revisao(
            pid, "ajuste", previsao=date(2026, 7, 1), do_zero=False,
            criado_por=nm)
        _check("'continua a anterior' parte dos percentuais anteriores",
               _evol(_id_r1) == {"Elétrica": 100, "CFTV": 100, "SPDA": 0}
               and [(e["nome"], e["percentual"])
                    for e in db.listar_etapas(pid)] == [("Projeto", 100)],
               (_evol(_id_r1), db.listar_etapas(pid)))

        _ok_ed = db.atualizar_revisao(
            _id_r1, "ajuste revisto", "Elétrica, Hidráulica",
            nm + ", ZZsmoke_outro", date(2026, 7, 5), date(2026, 8, 1), None)
        _p = _proj()
        _check("editar revisão ajusta a evolução às disciplinas dela",
               _ok_ed and _evol(_id_r1) == {"Elétrica": 100, "Hidráulica": 0},
               _evol(_id_r1))
        _check("editar a revisão atual: projeto segue as novas datas",
               _p[3] == date(2026, 7, 5) and _p[4] == date(2026, 8, 1)
               and "Hidráulica" in _p[0] and "ZZsmoke_outro" in _p[1], _p)
        _check("editar não mexe na emissão inicial",
               _evol(_id_ini) == {"Elétrica": 100, "CFTV": 100})
        _check("etapas sem revisão indicada = as da revisão atual",
               [e["percentual"] for e in db.listar_etapas(pid)] == [100]
               and len(db.listar_etapas(pid, revisao_id=_id_ini)) == 1)
    finally:
        db.excluir_projeto(pid)
        cc = db.conectar(); cx = cc.cursor()
        cx.execute("SELECT COUNT(*) FROM projeto_revisoes WHERE projeto_id=%s",
                   (pid,))
        _sobra = cx.fetchone()[0]
        cx.execute("SELECT COUNT(*) FROM progresso_disciplinas "
                   "WHERE projeto_id=%s", (pid,))
        _sobra_ev = cx.fetchone()[0]
        cc.close()
        _check("excluir o projeto leva as revisões junto", _sobra == 0)
        _check("excluir o projeto leva a evolução junto", _sobra_ev == 0)


def main():
    db.criar_tabelas()
    db_tarefas()
    db_tarefas_proj_rec()
    db_documentos_etapas()
    db_revisoes()
    # 1 tarefa pro usuário das views, pra exercitar o data_editor de Tarefas.
    db.criar_tarefa("ZZsmoke_gestor", "render check", privada=True,
                    criado_por="ZZsmoke_gestor", data=date.today())
    render_views()
    _cc = db.conectar(); _cx = _cc.cursor()
    _cx.execute("DELETE FROM tarefas WHERE usuario=%s", ("ZZsmoke_gestor",))
    _cc.commit(); _cc.close()
    print()
    if _FALHAS:
        print(f"FALHOU: {len(_FALHAS)} item(ns) -> {_FALHAS}")
        return 1
    print("OK: todos os smoke tests passaram.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
