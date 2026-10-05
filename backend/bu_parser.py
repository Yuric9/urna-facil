from bu_decoder import decode_bu_file, extract_candidate_votes


def parse_bu_file(filepath):
    env, bu = decode_bu_file(filepath)
    return {"envelope": {k:v for k,v in env.items() if k != "conteudo"}, "bu": bu}


def votos_por_candidato(filepath, cargo=6, eleicao=6259):
    _, bu = decode_bu_file(filepath)
    return extract_candidate_votes(bu, election_id=eleicao, cargo_code=cargo)


def votos_por_candidato_mock(*args, **kwargs):
    raise RuntimeError("Dados fictícios foram removidos do UrnaFácil. Use votos_por_candidato().")
