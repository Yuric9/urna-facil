"""Nomes dos candidatos, a partir dos arquivos de resultado que o TSE publica por município.

O BU só traz o NÚMERO do candidato. O nome vem de outro arquivo do TSE, que lista os
candidatos de cada cargo com campos curtos: "n" (número), "nm" (nome) e "nmu" (nome na urna),
agrupados por partido ("sg" = sigla). Como o nome exato do arquivo pode mudar de uma
eleição para outra, tentamos os formatos conhecidos e lemos o JSON de forma flexível.
"""
import time

import requests

from cache import get_candidatos, save_candidatos
from tse_client import BASE_URL, ELEICAO, _get

# Na tela do TSE, a eleição federal (6257) aparece para todos os cargos; o BU separa em 6257/6259.
ELEICOES_2026 = ("6259", "6257")
# Lembra por 10 minutos quando o TSE não tinha a lista, para não repetir as tentativas a cada pesquisa.
_FALHAS = {}
ESPERA_APOS_FALHA = 600


def urls_candidatos(uf, municipio, cargo, eleicoes=ELEICOES_2026):
    uf = uf.lower(); m = str(municipio).zfill(5); c = str(cargo).zfill(4)
    urls = []
    for e in eleicoes:
        e6 = e.zfill(6)
        urls += [
            f"{BASE_URL}/{ELEICAO}/{e}/dados/{uf}/{uf}{m}-c{c}-e{e6}-u.json",  # resultado unificado do município
            f"{BASE_URL}/{ELEICAO}/{e}/dados/{uf}/{uf}{m}-c{c}-e{e6}-f.json",  # dados fixos do município
            f"{BASE_URL}/{ELEICAO}/{e}/dados/{uf}/{uf}-c{c}-e{e6}-u.json",     # resultado unificado do estado
            f"{BASE_URL}/{ELEICAO}/{e}/dados/{uf}/{uf}-c{c}-e{e6}-f.json",     # dados fixos do estado
        ]
    return urls


def extrair_candidatos(obj):
    """Procura em qualquer lugar do JSON objetos com número + nome. Devolve {numero: {nome, partido}}."""
    achados = {}

    def walk(x, sigla=None):
        if isinstance(x, dict):
            sg = x.get("sg") if isinstance(x.get("sg"), str) else sigla
            n = str(x.get("n", "")).strip()
            nome = x.get("nmu") or x.get("nm")
            if n.isdigit() and isinstance(nome, str) and nome.strip():
                achados[n] = {"nome": nome.strip(), "partido": sg}
            for v in x.values():
                walk(v, sg)
        elif isinstance(x, list):
            for v in x:
                walk(v, sigla)

    walk(obj)
    return achados


def nomes_candidatos(uf, municipio, cargo, force=False):
    """{numero: {nome, partido}} usando o cache; baixa do TSE só na primeira vez."""
    uf = uf.lower(); m = str(municipio).zfill(5)
    if not force:
        salvos = get_candidatos(uf, m, cargo)
        if salvos: return salvos, None
    chave = (uf, m, int(cargo))
    if not force and chave in _FALHAS and time.time() - _FALHAS[chave][0] < ESPERA_APOS_FALHA:
        raise RuntimeError(_FALHAS[chave][1])
    tentativas = []
    for url in urls_candidatos(uf, m, cargo):
        try:
            achados = extrair_candidatos(_get(url, 30).json())
        except (requests.RequestException, ValueError) as e:
            tentativas.append(f"{url} ({getattr(getattr(e, 'response', None), 'status_code', 'erro')})")
            continue
        if achados:
            save_candidatos(uf, m, cargo, achados, url)
            return achados, url
        tentativas.append(f"{url} (sem candidatos)")
    msg = "Não encontrei a lista de candidatos no TSE. Tentei: " + " | ".join(tentativas)
    _FALHAS[chave] = (time.time(), msg)
    raise RuntimeError(msg)
