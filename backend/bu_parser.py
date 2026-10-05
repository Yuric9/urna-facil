from bu_decoder import decode_bu_file, extract_candidate_votes


def parse_bu_file(filepath):
    env, bu = decode_bu_file(filepath)
    return {"envelope": {k:v for k,v in env.items() if k != "conteudo"}, "bu": bu}


def votos_por_candidato(filepath, cargo=6, eleicao=6259):
    _, bu = decode_bu_file(filepath)
    return extract_candidate_votes(bu, election_id=eleicao, cargo_code=cargo)


def votos_todos_cargos(filepath):
    """Decodifica o BU uma vez e devolve {idEleicao: {cargo: [votos...]}} com todos os cargos."""
    _, bu = decode_bu_file(filepath)
    out = {}
    for e in bu['resultadosVotacaoPorEleicao']:
        cargos = out.setdefault(e['idEleicao'], {})
        for rv in e['resultadosVotacao']:
            for c in rv['totaisVotosCargo']:
                cod = c['codigoCargo']['valor']
                cargos[cod] = extract_candidate_votes(bu, election_id=e['idEleicao'], cargo_code=cod)
    return out
