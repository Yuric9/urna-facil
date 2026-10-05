import sqlite3
from contextlib import closing
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "data_cache" / "urna_facil.sqlite3"


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS votos_secao (
        eleicao INTEGER NOT NULL, cargo INTEGER NOT NULL, uf TEXT NOT NULL,
        municipio TEXT NOT NULL, zona TEXT NOT NULL, secao TEXT NOT NULL,
        numero TEXT NOT NULL, partido INTEGER, votos INTEGER NOT NULL,
        fonte TEXT NOT NULL, atualizado_em TEXT NOT NULL,
        PRIMARY KEY (eleicao,cargo,uf,municipio,zona,secao,numero)
    )""")
    # Uma linha aqui significa "o BU desta seção já foi processado", mesmo que um cargo não tenha votos.
    c.execute("""CREATE TABLE IF NOT EXISTS fontes_secao (
        eleicao INTEGER NOT NULL, uf TEXT NOT NULL, municipio TEXT NOT NULL,
        zona TEXT NOT NULL, secao TEXT NOT NULL, origem TEXT NOT NULL,
        atualizado_em TEXT NOT NULL,
        PRIMARY KEY (eleicao,uf,municipio,zona,secao)
    )""")
    c.commit()
    return c


def get_section(eleicao, cargo, uf, municipio, zona, secao):
    """Retorna a lista de votos da seção, ou None se o BU dela ainda não foi processado."""
    with closing(_conn()) as c:
        fonte = c.execute("SELECT origem FROM fontes_secao WHERE eleicao=? AND uf=? AND municipio=? AND zona=? AND secao=?",
                          (eleicao, uf, municipio, zona, secao)).fetchone()
        if not fonte: return None
        rows = c.execute("SELECT * FROM votos_secao WHERE eleicao=? AND cargo=? AND uf=? AND municipio=? AND zona=? AND secao=? ORDER BY numero",
                         (eleicao, cargo, uf, municipio, zona, secao)).fetchall()
        return [dict(r) for r in rows]


def get_fonte(eleicao, uf, municipio, zona, secao):
    with closing(_conn()) as c:
        r = c.execute("SELECT origem FROM fontes_secao WHERE eleicao=? AND uf=? AND municipio=? AND zona=? AND secao=?",
                      (eleicao, uf, municipio, zona, secao)).fetchone()
        return r["origem"] if r else None


def save_eleicao(eleicao, uf, municipio, zona, secao, votos_por_cargo, fonte, updated):
    """Salva todos os cargos de uma eleição do BU de uma só vez: {cargo: [votos...]}."""
    with closing(_conn()) as c:
        c.execute("DELETE FROM votos_secao WHERE eleicao=? AND uf=? AND municipio=? AND zona=? AND secao=?", (eleicao, uf, municipio, zona, secao))
        for cargo, votos in votos_por_cargo.items():
            for v in votos:
                c.execute("INSERT OR REPLACE INTO votos_secao VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                          (eleicao, cargo, uf, municipio, zona, secao, str(v['numero']), v.get('partido'), int(v['votos']), fonte, updated))
        c.execute("INSERT OR REPLACE INTO fontes_secao VALUES (?,?,?,?,?,?,?)", (eleicao, uf, municipio, zona, secao, fonte, updated))
        c.commit()


def cache_count():
    with closing(_conn()) as c:
        return c.execute("SELECT COUNT(*) n FROM votos_secao").fetchone()[0]
