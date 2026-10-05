import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))

import pytest
from fastapi.testclient import TestClient
import cache, main, tse_client
from tse_client import _find_bu, bu_relativo

FIXTURE = Path(__file__).parent / 'fixtures' / 'boletim_trindade_0049_0001.dat'

# Formato do aux.json publicado pelo TSE (EA18).
AUX = {
    "dg": "06/10/2026", "st": "Totalizada",
    "hashes": [
        {"hash": "aaa111", "st": "Excluído", "nmarq": ["o00406-9625300490001.logjez", "o00406-9625300490001.bu"]},
        {"hash": "bbb222", "st": "Totalizado", "nmarq": ["o00406-9625300490001.logjez", "o00406-9625300490001.imgbu",
                                                       "o00406-9625300490001.bu", "o00406-9625300490001.rdv"]},
    ],
}


def test_find_bu_nao_quebra_com_textos_e_listas():
    assert _find_bu({"a": "x.json", "b": ["y.logjez", "z.bu"]}) == "z.bu"
    assert _find_bu({"a": "x.imgbu"}) is None


def test_bu_relativo_usa_pasta_do_hash_totalizado():
    assert bu_relativo(AUX) == "bbb222/o00406-9625300490001.bu"


def test_get_bu_file_monta_url_com_hash(monkeypatch, tmp_path):
    urls = []
    class R:
        content = FIXTURE.read_bytes()
        def raise_for_status(self): pass
        def json(self): return AUX
    def fake_get(url, timeout=30, headers=None):
        urls.append(url); return R()
    monkeypatch.setattr(tse_client.requests, 'get', fake_get)
    path, url, _ = tse_client.get_bu_file('go', '96253', '49', '2', dest_folder=tmp_path)
    assert url == ("https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna/003220/dados/go/96253/0049/0002/"
                   "bbb222/o00406-9625300490001.bu")
    assert path.read_bytes() == FIXTURE.read_bytes()


def test_extrair_secoes_formato_cs_json():
    cfg = {"abr": [{"cd": "GO", "mu": [
        {"cd": "96253", "zon": [{"cd": "0049", "sec": [{"ns": "0002"}, {"ns": "0001"}]},
                                {"cd": "0123", "sec": [{"ns": "0500"}]}]},
        {"cd": "93734", "zon": [{"cd": "0049", "sec": [{"ns": "0900"}]}]},
    ]}]}
    assert main._extrair_secoes(cfg, "96253", "49") == [1, 2]


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, 'DB_PATH', tmp_path / 'cache.sqlite3')
    downloads = []
    def fake_bu(uf, m, z, s):
        downloads.append(s); return FIXTURE, "TSE (teste)", {}
    monkeypatch.setattr(main, 'get_bu_file', fake_bu)
    return TestClient(main.app), downloads


def test_pesquisa_multiplas_soma_e_usa_cache(api):
    client, downloads = api
    params = {"secoes": "0001,0002,0003", "cargo": 6, "candidato": "1515"}
    d = client.get("/pesquisa-multiplas", params=params).json()
    assert [x["votos"] for x in d["secoes"]] == [48, 48, 48]
    assert d["total"] == 144
    assert downloads == ["0002", "0003"]  # a 0001 vem da fixture local

    d = client.get("/pesquisa-multiplas", params=params).json()
    assert all(x["cache"] for x in d["secoes"]) and downloads == ["0002", "0003"]

    # Trocar de cargo também não baixa de novo: o BU inteiro já foi salvo.
    d = client.get("/pesquisa-multiplas", params={**params, "cargo": 1, "candidato": "13"}).json()
    assert all(x["cache"] for x in d["secoes"]) and downloads == ["0002", "0003"]


def test_secao_sem_votos_no_candidato_fica_em_cache(api):
    client, downloads = api
    client.get("/votos", params={"secao": "0007", "cargo": 6, "candidato": "9999"})
    d = client.get("/votos", params={"secao": "0007", "cargo": 6, "candidato": "9999"}).json()
    assert d["cache"] is True and d["total"] == 0 and downloads == ["0007"]
