import requests
from pathlib import Path

BASE_URL = "https://resultados.tse.jus.br/oficial"
ELEICAO = "ele2026"
COD_PLEITO_2026 = "003220"
HEADERS = {"User-Agent": "UrnaFacil/2.0"}


def _get(url, timeout=30):
    r = requests.get(url, timeout=timeout, headers=HEADERS)
    r.raise_for_status()
    return r


def get_config_uf(uf="go", cod_pleito=COD_PLEITO_2026):
    # EA16 usa o CÓDIGO DO PLEITO (3220), não o código da eleição (6257/6259).
    url = f"{BASE_URL}/{ELEICAO}/arquivo-urna/{cod_pleito}/config/{uf.lower()}/{uf.lower()}-p{cod_pleito}-cs.json"
    return _get(url).json()


def get_urna_aux(uf, cod_municipio, zona, secao, cod_pleito=COD_PLEITO_2026):
    uf = uf.lower(); m = str(cod_municipio).zfill(5); z = str(zona).zfill(4); s = str(secao).zfill(4)
    # EA18 também usa o CÓDIGO DO PLEITO no nome e no diretório.
    url = f"{BASE_URL}/{ELEICAO}/arquivo-urna/{cod_pleito}/dados/{uf}/{m}/{z}/{s}/p{cod_pleito}-{uf}-m{m}-z{z}-s{s}-aux.json"
    return _get(url).json(), url


def _eh_bu(nome):
    return isinstance(nome, str) and nome.lower().split("?", 1)[0].endswith((".bu", ".busa"))


def _find_bu(value):
    """Procura recursivamente o nome de um arquivo de BU em qualquer estrutura JSON."""
    if _eh_bu(value):
        return value
    if isinstance(value, dict):
        for v in value.values():
            hit = _find_bu(v)
            if hit: return hit
    elif isinstance(value, list):
        for v in value:
            hit = _find_bu(v)
            if hit: return hit
    return None


def bu_relativo(aux):
    """Caminho do BU relativo à pasta do aux.json.

    Formato do aux.json do TSE: {"hashes": [{"hash": "...", "st": "Totalizado", "nmarq": ["...bu", ...]}]}.
    Os arquivos ficam numa subpasta com o nome do hash. Se houver mais de um hash
    (urna substituída), dá preferência ao que foi totalizado, e depois ao mais recente.
    """
    hashes = aux.get("hashes") if isinstance(aux, dict) else None
    if isinstance(hashes, list) and hashes:
        totalizados = [h for h in hashes if str(h.get("st", "")).lower().startswith("totalizad")]
        for h in reversed(totalizados or hashes):
            nome = next((n for n in h.get("nmarq", []) if _eh_bu(n)), None)
            if nome:
                return f"{h['hash']}/{nome}" if h.get("hash") else nome
    return _find_bu(aux)


def get_bu_file(uf, cod_municipio, zona, secao, dest_folder="/tmp/urna-facil-bus"):
    aux, aux_url = get_urna_aux(uf, cod_municipio, zona, secao)
    ref = bu_relativo(aux)
    if not ref: raise RuntimeError("O aux.json não informou um arquivo de BU (a seção pode ainda não ter sido totalizada)")
    url = ref if ref.startswith("http") else f"{aux_url.rsplit('/', 1)[0]}/{ref}"
    r = _get(url, 60)
    Path(dest_folder).mkdir(parents=True, exist_ok=True)
    path = Path(dest_folder) / url.rsplit('/', 1)[-1].split('?', 1)[0]
    path.write_bytes(r.content)
    return path, url, aux
