import os, requests
from pathlib import Path

BASE_URL = "https://resultados.tse.jus.br/oficial"
ELEICAO = "ele2026"
COD_ELEICAO_FEDERAL = "6257"
COD_ELEICAO_ESTADUAL = "6259"
COD_PLEITO_2026 = "003220"


def _get(url, timeout=30):
    r=requests.get(url,timeout=timeout,headers={"User-Agent":"UrnaFacil/2.0"})
    r.raise_for_status()
    return r


def get_config_uf(uf="go", cod_eleicao=COD_ELEICAO_FEDERAL, cod_pleito=COD_PLEITO_2026):
    # EA16 usa o CÓDIGO DO PLEITO (3220), não o código da eleição (6257/6259).
    url=f"{BASE_URL}/{ELEICAO}/arquivo-urna/{cod_pleito}/config/{uf.lower()}/{uf.lower()}-p{cod_pleito}-cs.json"
    return _get(url).json()


def get_urna_aux(uf,cod_municipio,zona,secao,cod_eleicao=COD_ELEICAO_FEDERAL, cod_pleito=COD_PLEITO_2026):
    uf=uf.lower(); m=str(cod_municipio).zfill(5); z=str(zona).zfill(4); s=str(secao).zfill(4)
    # EA18 também usa o CÓDIGO DO PLEITO no nome e no diretório.
    url=f"{BASE_URL}/{ELEICAO}/arquivo-urna/{cod_pleito}/dados/{uf}/{m}/{z}/{s}/p{cod_pleito}-{uf}-m{m}-z{z}-s{s}-aux.json"
    r=requests.get(url,timeout=30,headers={"User-Agent":"UrnaFacil/2.0"})
    r.raise_for_status(); return r.json(),url


def _find_bu(value):
    if isinstance(value,str):
        v=value
        if any(x in v.lower() for x in [".dat",".bu","boletimdeurna"]): return v
    if isinstance(dict(value),dict):
        for k,v in value.items():
            hit=_find_bu(v)
            if hit: return hit
    elif isinstance(value,list):
        for v in value:
            hit=_find_bu(v)
            if hit: return hit
    return None


def get_bu_file(uf,cod_municipio,zona,secao,cod_eleicao=COD_ELEICAO_FEDERAL,dest_folder="/tmp/urna-facil-bus"):
    aux,aux_url=get_urna_aux(uf,cod_municipio,zona,secao,cod_eleicao)
    ref=_find_bu(aux)
    if not ref: raise RuntimeError("O aux.json não informou um arquivo de BU reconhecível")
    if ref.startswith("http"):
        url=ref
    else:
        base=aux_url.rsplit('/',1)[0]
        url=f"{base}/{ref}"
    r=_get(url,60)
    Path(dest_folder).mkdir(parents=True,exist_ok=True)
    name=url.rsplit('/',1)[-1].split('?',1)[0]
    path=Path(dest_folder)/name
    path.write_bytes(r.content)
    return path,url,aux
