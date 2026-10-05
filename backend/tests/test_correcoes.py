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


def test_formato_antigo_bu_na_pasta_do_hash(monkeypatch, tmp_path):
    urls = []
    class R:
        content = FIXTURE.read_bytes()
        def __init__(self, url): self.status_code = 200 if url.endswith(("aux.json", "bbb222/o00406-9625300490001.bu")) else 404
        def raise_for_status(self):
            if self.status_code == 404:
                import requests; raise requests.HTTPError(response=self)
        def json(self): return AUX
    def fake_get(url, timeout=30, headers=None):
        urls.append(url); return R(url)
    monkeypatch.setattr(tse_client.requests, 'get', fake_get)
    path, url, _ = tse_client.get_bu_file('go', '96253', '49', '2', dest_folder=tmp_path)
    assert url == ("https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna/3220/dados/go/96253/0049/0002/"
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


def test_reconhece_variacoes_de_nome_do_bu():
    assert tse_client._eh_bu("o03220-9625300490001.bu")
    assert tse_client._eh_bu("o03220-9625300490001-bu.dat")
    assert tse_client._eh_bu("x.bu.zip")
    assert not tse_client._eh_bu("o03220-9625300490001.imgbu")
    assert not tse_client._eh_bu("o03220-9625300490001.rdv")


def test_sem_bu_no_aux_tenta_nome_padrao_e_mostra_arquivos(monkeypatch, tmp_path):
    aux = {"st": "Totalizada", "hashes": [{"hash": "h1", "st": "Totalizado", "nmarq": ["a.logjez", "a.rdv"]}]}
    urls = []
    class R:
        def __init__(self, url): self.url = url; self.status_code = 200 if url.endswith("aux.json") else 404
        content = b""
        def raise_for_status(self):
            if self.status_code == 404:
                import requests; raise requests.HTTPError(response=self)
        def json(self): return aux
    def fake_get(url, timeout=30, headers=None):
        urls.append(url); return R(url)
    monkeypatch.setattr(tse_client.requests, 'get', fake_get)
    with pytest.raises(RuntimeError) as e:
        tse_client.get_bu_file('go', '96253', '49', '56', dest_folder=tmp_path)
    assert any(u.endswith("/0056/o03220go9625300490056-bu.dat") for u in urls)
    assert any(u.endswith("/0056/h1/o03220-9625300490056.bu") for u in urls)
    assert "a.logjez, a.rdv" in str(e.value) and "Totalizada" in str(e.value)


def test_formato_2026_bu_na_pasta_da_secao(monkeypatch, tmp_path):
    aux = {"st": "Totalizada", "hashes": [{"hash": "h1", "st": "Totalizado",
           "nmarq": ["o03220go9625300490002-rdv.dat", "o03220go9625300490002-bu.dat"]}]}
    class R:
        def __init__(self, url): self.status_code = 200 if url.endswith(("aux.json", "/0002/o03220go9625300490002-bu.dat")) else 404
        content = FIXTURE.read_bytes()
        def raise_for_status(self):
            if self.status_code == 404:
                import requests; raise requests.HTTPError(response=self)
        def json(self): return aux
    monkeypatch.setattr(tse_client.requests, 'get', lambda url, timeout=30, headers=None: R(url))
    path, url, _ = tse_client.get_bu_file('go', '96253', '49', '2', dest_folder=tmp_path)
    assert url.endswith("/0049/0002/o03220go9625300490002-bu.dat")


def test_sem_candidato_lista_todos(api):
    client, _ = api
    d = client.get("/pesquisa-multiplas", params={"secoes": "0001,0002", "cargo": 6}).json()
    cands = d["candidatos"]
    assert cands[0]["numero"] == "1515" and cands[0]["total"] == 96
    assert cands[0]["por_secao"] == {"0001": 48, "0002": 48}
    assert d["total"] == sum(c["total"] for c in cands) == 2 * 161
    assert [c["total"] for c in cands] == sorted((c["total"] for c in cands), reverse=True)


def test_formato_2026_confirmado_tenta_pasta_do_hash_primeiro():
    aux = {"hashes": [{"hash": "6f78", "st": "Totalizado", "nmarq": ["o03220go9625300490095-bu.dat"]}]}
    caminhos = tse_client.caminhos_candidatos(aux, "go", "96253", "49", "95")
    assert caminhos[0] == "6f78/o03220go9625300490095-bu.dat"
