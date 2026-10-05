import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]))
from bu_decoder import decode_bu_file, extract_candidate_votes

FIXTURE=Path(__file__).parent/'fixtures'/'boletim_trindade_0049_0001.dat'

def test_bu_real_identificacao():
    env,bu=decode_bu_file(FIXTURE)
    assert bu['identificacaoSecao']['municipioZona']['municipio']==96253
    assert bu['identificacaoSecao']['municipioZona']['zona']==49
    assert bu['identificacaoSecao']['secao']==1
    assert [e['idEleicao'] for e in bu['resultadosVotacaoPorEleicao']]==[6257,6259]

def test_bu_real_tem_votos():
    _,bu=decode_bu_file(FIXTURE)
    votos=extract_candidate_votes(bu,6259,6)
    assert votos
    assert all(v['votos']>=0 for v in votos)
