import re
import requests
from pathlib import Path

BASE_URL = "https://resultados.tse.jus.br/oficial"
ELEICAO = "ele2026"
COD_PLEITO_2026 = "3220"  # confirmado no cabeçalho do BU real de Trindade
HEADERS = {"User-Agent": "UrnaFacil/2.0"}


def _get(url, timeout=30):
    r = requests.get(url, timeout=timeout, headers=HEADERS)
    r.raise_for_status()
    return r


def _pastas_pleito(cod_pleito):
    """Nome da pasta do pleito no site do TSE.

    O nome do ARQUIVO sempre usa 6 dígitos (p003220), mas a PASTA usa o número
    sem zeros à esquerda (.../arquivo-urna/3220/...), como em 2022 (406) e 2024.
    A versão com zeros fica como reserva caso o TSE mude o padrão.
    """
    sem_zeros = str(int(cod_pleito))
    return [sem_zeros, str(cod_pleito).zfill(6)] if sem_zeros != str(cod_pleito).zfill(6) else [sem_zeros]


def _get_primeira(caminhos, timeout=30):
    """Tenta cada URL até uma responder; devolve (resposta, url)."""
    erros = []
    for url in caminhos:
        try:
            return _get(url, timeout), url
        except requests.HTTPError as e:
            if e.response is None or e.response.status_code != 404: raise
            erros.append(url)
    raise RuntimeError("O TSE respondeu 404 (não encontrado) para: " + " | ".join(erros))


def get_config_uf(uf="go", cod_pleito=COD_PLEITO_2026):
    # EA16 usa o CÓDIGO DO PLEITO (3220), não o código da eleição (6257/6259).
    uf = uf.lower(); p6 = str(cod_pleito).zfill(6)
    r, _ = _get_primeira([f"{BASE_URL}/{ELEICAO}/arquivo-urna/{pasta}/config/{uf}/{uf}-p{p6}-cs.json"
                          for pasta in _pastas_pleito(cod_pleito)])
    return r.json()


def get_urna_aux(uf, cod_municipio, zona, secao, cod_pleito=COD_PLEITO_2026):
    uf = uf.lower(); m = str(cod_municipio).zfill(5); z = str(zona).zfill(4); s = str(secao).zfill(4); p6 = str(cod_pleito).zfill(6)
    # EA18 também usa o CÓDIGO DO PLEITO no nome e no diretório.
    r, url = _get_primeira([f"{BASE_URL}/{ELEICAO}/arquivo-urna/{pasta}/dados/{uf}/{m}/{z}/{s}/p{p6}-{uf}-m{m}-z{z}-s{s}-aux.json"
                            for pasta in _pastas_pleito(cod_pleito)])
    return r.json(), url


def _eh_bu(nome):
    """Reconhece arquivos de BU: "x.bu", "x.busa", "x-bu.dat", "x.bu.zip"... mas não "x.imgbu" (imagem do BU)."""
    if not isinstance(nome, str): return False
    base = nome.lower().split("?", 1)[0].rsplit("/", 1)[-1]
    return re.search(r"(^|[.\-_])bu(sa)?([.\-_]|$)", base) is not None


def _nomes_de_arquivo(value, out=None):
    """Lista todos os textos com cara de nome de arquivo dentro do aux.json (para diagnóstico)."""
    out = [] if out is None else out
    if isinstance(value, str) and re.search(r"\.[a-z0-9]{2,6}$", value.lower()): out.append(value)
    elif isinstance(value, dict): [_nomes_de_arquivo(v, out) for v in value.values()]
    elif isinstance(value, list): [_nomes_de_arquivo(v, out) for v in value]
    return out


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


def _hashes_preferidos(aux):
    hashes = aux.get("hashes") if isinstance(aux, dict) else None
    if not isinstance(hashes, list): return []
    totalizados = [h for h in hashes if isinstance(h, dict) and str(h.get("st", "")).lower().startswith("totalizad")]
    return [h.get("hash") for h in reversed(totalizados or hashes) if isinstance(h, dict) and h.get("hash")]


def _nomes_bu(aux):
    """Todos os nomes de BU citados no aux.json, preferindo os do hash totalizado."""
    nomes = []
    hashes = aux.get("hashes") if isinstance(aux, dict) else None
    if isinstance(hashes, list):
        totalizados = [h for h in hashes if isinstance(h, dict) and str(h.get("st", "")).lower().startswith("totalizad")]
        for h in reversed(totalizados or hashes):
            if isinstance(h, dict): nomes += [n for n in h.get("nmarq", []) if _eh_bu(n)]
    nomes += [n for n in _nomes_de_arquivo(aux) if _eh_bu(n)]
    return list(dict.fromkeys(nomes))


def caminhos_candidatos(aux, uf, cod_municipio, zona, secao, cod_pleito=COD_PLEITO_2026):
    """Caminhos possíveis do BU, do mais provável ao menos provável.

    2026 (confirmado): ".../0049/0095/<hash>/o03220go9625300490095-bu.dat", ou seja,
    o BU fica numa subpasta com o hash da urna. Sem hash fica só como reserva.
    """
    m, z, s = str(cod_municipio).zfill(5), str(zona).zfill(4), str(secao).zfill(4)
    p5 = str(int(cod_pleito)).zfill(5)
    nomes = _nomes_bu(aux) + [f"o{p5}{uf.lower()}{m}{z}{s}-bu.dat", f"o{p5}-{m}{z}{s}.bu"]
    caminhos = []
    for nome in dict.fromkeys(nomes):
        if nome.startswith("http") or "/" in nome: caminhos.append(nome); continue
        caminhos += [f"{h}/{nome}" for h in _hashes_preferidos(aux)]
        caminhos.append(nome)
    return list(dict.fromkeys(caminhos))


def get_bu_file(uf, cod_municipio, zona, secao, dest_folder="/tmp/urna-facil-bus"):
    aux, aux_url = get_urna_aux(uf, cod_municipio, zona, secao)
    pasta = aux_url.rsplit('/', 1)[0]
    urls = [c if c.startswith("http") else f"{pasta}/{c}" for c in caminhos_candidatos(aux, uf, cod_municipio, zona, secao)]
    try:
        r, url = _get_primeira(urls, 60)
    except RuntimeError as e:
        status = aux.get("st") if isinstance(aux, dict) else None
        arquivos = ", ".join(_nomes_de_arquivo(aux)) or "nenhum"
        raise RuntimeError(f"BU não encontrado. Situação no TSE: {status or 'não informada'}. "
                           f"Arquivos listados no aux.json: {arquivos}. {e}")
    Path(dest_folder).mkdir(parents=True, exist_ok=True)
    path = Path(dest_folder) / url.rsplit('/', 1)[-1].split('?', 1)[0]
    path.write_bytes(r.content)
    return path, url, aux
