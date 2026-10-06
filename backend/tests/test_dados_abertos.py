import sys
import time
import zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))

import pytest
from fastapi.testclient import TestClient
import cache, dados_abertos, main

CABECALHO = ("DT_GERACAO;HH_GERACAO;ANO_ELEICAO;CD_TIPO_ELEICAO;NM_TIPO_ELEICAO;NR_TURNO;CD_ELEICAO;DS_ELEICAO;"
             "DT_ELEICAO;TP_ABRANGENCIA;SG_UF;SG_UE;NM_UE;CD_MUNICIPIO;NM_MUNICIPIO;NR_ZONA;NR_SECAO;CD_CARGO;"
             "DS_CARGO;NR_VOTAVEL;NM_VOTAVEL;QT_VOTOS;NR_LOCAL_VOTACAO;SQ_CANDIDATO")


def linha(mun, zona, secao, cargo, numero, nome, votos, turno=1):
    return (f'"01/10/2024";"10:00:00";"2024";"2";"Eleição Ordinária";"{turno}";"619";"Eleições Municipais 2024";'
            f'"06/10/2024";"M";"GO";"{mun}";"TRINDADE";"{mun}";"TRINDADE";"{zona}";"{secao}";"{cargo}";"Vereador";'
            f'"{numero}";"{nome}";"{votos}";"1015";"90000000001"')


@pytest.fixture
def zip_2024(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, 'DB_PATH', tmp_path / 'cache.sqlite3')
    linhas = [CABECALHO,
              linha("96253", "49", "1", "13", "15123", "JOSÉ DA CONCEIÇÃO", 40),
              linha("96253", "49", "1", "13", "55777", "MARIA", 25),
              linha("96253", "49", "1", "13", "15", "MDB", 7),            # legenda: não é voto nominal
              linha("96253", "49", "1", "13", "95", "VOTO BRANCO", 3),
              linha("96253", "49", "1", "13", "96", "VOTO NULO", 5),
              linha("96253", "49", "2", "13", "15123", "JOSÉ DA CONCEIÇÃO", 30),
              linha("96253", "49", "2", "11", "15", "PREFEITO QUINZE", 90),  # prefeito: 2 dígitos É nominal
              linha("93734", "49", "1", "13", "15123", "JOSÉ DA CONCEIÇÃO", 999)]  # outro município
    arq = dados_abertos.caminho_zip(2024, "go"); arq.parent.mkdir(parents=True)
    with zipfile.ZipFile(arq, "w") as zf:
        zf.writestr("votacao_secao_2024_GO.csv", "\r\n".join(linhas).encode("latin1"))
    return arq


def test_importa_so_o_municipio_e_le_acentos(zip_2024):
    dados_abertos.importar_municipio(2024, "go", "96253")
    assert dados_abertos.status(2024, "go", "96253")["fase"] == "pronto"
    votos = {v["numero"]: v for v in dados_abertos.votos_secao(2024, 1, "go", "96253", "49", "1", 13)}
    assert set(votos) == {"15123", "55777"}  # sem legenda, branco e nulo
    assert votos["15123"]["nome"] == "JOSÉ DA CONCEIÇÃO" and votos["15123"]["votos"] == 40
    assert dados_abertos.secoes(2024, 1, "go", "96253", "49", 13) == ["0001", "0002"]


def test_prefeito_com_dois_digitos_e_nominal(zip_2024):
    dados_abertos.importar_municipio(2024, "go", "96253")
    assert dados_abertos.votos_secao(2024, 1, "go", "96253", "49", "2", 11)[0]["votos"] == 90


def test_municipio_inexistente_vira_erro_claro(zip_2024):
    dados_abertos.importar_municipio(2024, "go", "11111")
    s = dados_abertos.status(2024, "go", "11111")
    assert s["fase"] == "erro" and "Nenhuma linha do município 11111" in s["erro"]


def test_api_historico_ponta_a_ponta(zip_2024):
    client = TestClient(main.app)
    p = {"ano": 2024, "turno": 1, "uf": "go", "municipio": "96253", "zona": "0049", "secoes": "0001,0002", "cargo": 13}
    assert client.get("/pesquisa-multiplas", params=p).status_code == 409  # ainda não importado

    client.post("/historico/importar", params={"ano": 2024, "uf": "go", "municipio": "96253"})
    for _ in range(50):
        if client.get("/historico/status", params={"ano": 2024, "uf": "go", "municipio": "96253"}).json()["fase"] == "pronto": break
        time.sleep(0.05)

    assert client.get("/historico/secoes/go/96253/0049", params={"ano": 2024, "cargo": 13}).json()["secoes"] == ["0001", "0002"]
    d = client.get("/pesquisa-multiplas", params=p).json()
    assert d["total"] == 40 + 25 + 30
    assert d["candidatos"][0] == {"numero": "15123", "partido": 15, "total": 70, "por_secao": {"0001": 40, "0002": 30},
                                  "nome": "JOSÉ DA CONCEIÇÃO", "sigla": None}
    d = client.get("/pesquisa-multiplas", params={**p, "candidato": "55777"}).json()
    assert d["total"] == 25 and d["nome"] == "MARIA"


def test_anos_lista_atual_e_historicos():
    d = TestClient(main.app).get("/anos").json()["anos"]
    assert d[0]["ano"] == 2026 and d[0]["fonte"] == "bu"
    assert {a["ano"] for a in d[1:]} == {2024, 2022, 2020, 2018}
