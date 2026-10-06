"""Eleições anteriores a partir dos Dados Abertos do TSE (arquivo "votacao_secao").

O TSE publica um ZIP por ano e estado com os votos de cada candidato em cada seção:
    https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_secao/votacao_secao_{ANO}_{UF}.zip
Dentro há um CSV (latin1, separado por ";") com colunas como NR_TURNO, CD_MUNICIPIO,
NR_ZONA, NR_SECAO, CD_CARGO, NR_VOTAVEL, NM_VOTAVEL e QT_VOTOS.

O ZIP de um estado é grande, então: baixamos uma vez (fica em data_cache/downloads) e
importamos para o SQLite só o município pedido. Outro município do mesmo estado e ano
reaproveita o ZIP já baixado.
"""
import csv
import io
import threading
import time
import zipfile
from contextlib import closing
from pathlib import Path

import requests

import cache
from tse_client import HEADERS

URL_ZIP = "https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_secao/votacao_secao_{ano}_{uf}.zip"

# Anos disponíveis e os cargos de cada tipo de eleição (códigos CD_CARGO do TSE).
CARGOS_GERAIS = {1: "Presidente", 3: "Governador", 5: "Senador", 6: "Deputado Federal", 7: "Deputado Estadual", 8: "Deputado Distrital"}
CARGOS_MUNICIPAIS = {11: "Prefeito", 13: "Vereador"}
ANOS = {2024: CARGOS_MUNICIPAIS, 2022: CARGOS_GERAIS, 2020: CARGOS_MUNICIPAIS, 2018: CARGOS_GERAIS}
CARGOS_PROPORCIONAIS = {6, 7, 8, 13}  # nesses cargos, números de 2 dígitos são voto de legenda
NAO_NOMINAIS = {"95", "96", "97"}      # branco, nulo, anulado

# Situação das importações em andamento, consultada pela tela para mostrar o progresso.
_status = {}
_lock = threading.Lock()


def _conn():
    c = cache._conn()
    c.execute("""CREATE TABLE IF NOT EXISTS votos_historico (
        ano INTEGER NOT NULL, turno INTEGER NOT NULL, uf TEXT NOT NULL, municipio TEXT NOT NULL,
        zona TEXT NOT NULL, secao TEXT NOT NULL, cargo INTEGER NOT NULL,
        numero TEXT NOT NULL, nome TEXT, votos INTEGER NOT NULL,
        PRIMARY KEY (ano,turno,uf,municipio,zona,secao,cargo,numero)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS importacoes_historico (
        ano INTEGER NOT NULL, uf TEXT NOT NULL, municipio TEXT NOT NULL,
        linhas INTEGER NOT NULL, importado_em TEXT NOT NULL,
        PRIMARY KEY (ano,uf,municipio)
    )""")
    c.commit()
    return c


def _chave(ano, uf, municipio):
    return f"{int(ano)}-{uf.lower()}-{str(municipio).zfill(5)}"


def ja_importado(ano, uf, municipio):
    with closing(_conn()) as c:
        return c.execute("SELECT 1 FROM importacoes_historico WHERE ano=? AND uf=? AND municipio=?",
                         (int(ano), uf.lower(), str(municipio).zfill(5))).fetchone() is not None


def status(ano, uf, municipio):
    with _lock:
        s = dict(_status.get(_chave(ano, uf, municipio), {}))
    if not s and ja_importado(ano, uf, municipio):
        s = {"fase": "pronto"}
    return s or {"fase": "nao_importado"}


def _atualiza(chave, **dados):
    with _lock:
        _status.setdefault(chave, {}).update(dados)


def caminho_zip(ano, uf):
    return cache.DB_PATH.parent / "downloads" / f"votacao_secao_{int(ano)}_{uf.upper()}.zip"


def baixar_zip(ano, uf, chave):
    destino = caminho_zip(ano, uf)
    if destino.exists():
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    url = URL_ZIP.format(ano=int(ano), uf=uf.upper())
    temp = destino.with_suffix(".parcial")
    with requests.get(url, stream=True, timeout=60, headers=HEADERS) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0)
        baixado = 0
        with open(temp, "wb") as f:
            for parte in r.iter_content(1024 * 1024):
                f.write(parte); baixado += len(parte)
                _atualiza(chave, fase="baixando", baixado=baixado, total=total)
    temp.replace(destino)  # só vira o arquivo final quando o download termina inteiro
    return destino


def ler_csv(arquivo_zip, ano, uf):
    """Lê as linhas do(s) CSV(s) de votação por seção dentro do ZIP, como dicionários."""
    with zipfile.ZipFile(arquivo_zip) as zf:
        nomes = [n for n in zf.namelist() if n.lower().endswith(".csv") and "votacao_secao" in n.lower()]
        if not nomes:
            raise RuntimeError(f"O ZIP não tem o CSV de votação por seção. Arquivos: {', '.join(zf.namelist()[:10])}")
        for nome in nomes:
            with zf.open(nome) as bruto:
                yield from csv.DictReader(io.TextIOWrapper(bruto, encoding="latin1", newline=""), delimiter=";")


def importar_municipio(ano, uf, municipio):
    """Baixa (se preciso) o ZIP do estado e grava no SQLite só as linhas do município."""
    ano = int(ano); uf = uf.lower(); m = str(municipio).zfill(5); chave = _chave(ano, uf, m)
    try:
        _atualiza(chave, fase="baixando", baixado=0, total=0, erro=None)
        arquivo = baixar_zip(ano, uf, chave)
        _atualiza(chave, fase="importando", lidas=0, importadas=0)
        lote, lidas, importadas = [], 0, 0
        with closing(_conn()) as c:
            c.execute("DELETE FROM votos_historico WHERE ano=? AND uf=? AND municipio=?", (ano, uf, m))
            for linha in ler_csv(arquivo, ano, uf):
                lidas += 1
                if lidas % 50000 == 0: _atualiza(chave, lidas=lidas, importadas=importadas)
                if str(linha.get("CD_MUNICIPIO", "")).strip().zfill(5) != m: continue
                try:
                    votos = int(linha["QT_VOTOS"])
                    registro = (ano, int(linha.get("NR_TURNO") or 1), uf, m,
                                str(int(linha["NR_ZONA"])).zfill(4), str(int(linha["NR_SECAO"])).zfill(4),
                                int(linha["CD_CARGO"]), str(linha["NR_VOTAVEL"]).strip(),
                                (linha.get("NM_VOTAVEL") or "").strip() or None, votos)
                except (KeyError, ValueError):
                    continue  # linha incompleta: ignora em vez de interromper a importação
                lote.append(registro); importadas += 1
                if len(lote) >= 5000:
                    c.executemany("INSERT OR REPLACE INTO votos_historico VALUES (?,?,?,?,?,?,?,?,?,?)", lote); lote = []
            if lote: c.executemany("INSERT OR REPLACE INTO votos_historico VALUES (?,?,?,?,?,?,?,?,?,?)", lote)
            if importadas == 0:
                c.rollback()
                raise RuntimeError(f"Nenhuma linha do município {m} no arquivo de {ano} ({uf.upper()}). Confira o código do município.")
            c.execute("INSERT OR REPLACE INTO importacoes_historico VALUES (?,?,?,?,?)",
                      (ano, uf, m, importadas, time.strftime("%Y-%m-%dT%H:%M:%S")))
            c.commit()
        _atualiza(chave, fase="pronto", lidas=lidas, importadas=importadas)
    except Exception as e:
        _atualiza(chave, fase="erro", erro=str(e))


def iniciar_importacao(ano, uf, municipio):
    """Roda a importação em segundo plano; a tela acompanha pelo status()."""
    if status(ano, uf, municipio).get("fase") in ("baixando", "importando"):
        return
    _atualiza(_chave(ano, uf, municipio), fase="baixando", baixado=0, total=0, erro=None)
    threading.Thread(target=importar_municipio, args=(ano, uf, municipio), daemon=True).start()


def secoes(ano, turno, uf, municipio, zona, cargo):
    with closing(_conn()) as c:
        rows = c.execute("""SELECT DISTINCT secao FROM votos_historico
                            WHERE ano=? AND turno=? AND uf=? AND municipio=? AND zona=? AND cargo=? ORDER BY secao""",
                         (int(ano), int(turno), uf.lower(), str(municipio).zfill(5), str(zona).zfill(4), int(cargo))).fetchall()
        return [r["secao"] for r in rows]


def eh_nominal(numero, cargo):
    return numero not in NAO_NOMINAIS and not (int(cargo) in CARGOS_PROPORCIONAIS and len(numero) <= 2)


def votos_secao(ano, turno, uf, municipio, zona, secao, cargo):
    """Votos nominais da seção no mesmo formato usado para o BU: [{numero, partido, votos, nome}]."""
    with closing(_conn()) as c:
        rows = c.execute("""SELECT numero, nome, SUM(votos) votos FROM votos_historico
                            WHERE ano=? AND turno=? AND uf=? AND municipio=? AND zona=? AND secao=? AND cargo=?
                            GROUP BY numero, nome""",
                         (int(ano), int(turno), uf.lower(), str(municipio).zfill(5), str(zona).zfill(4),
                          str(secao).zfill(4), int(cargo))).fetchall()
    return [{"numero": r["numero"], "partido": int(r["numero"][:2]) if r["numero"][:2].isdigit() else None,
             "votos": r["votos"], "nome": r["nome"]} for r in rows if eh_nominal(r["numero"], cargo)]
