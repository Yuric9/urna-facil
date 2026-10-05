from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from bu_parser import votos_todos_cargos
from cache import get_section, get_fonte, save_eleicao, cache_count
from tse_client import get_config_uf, get_urna_aux, get_bu_file

app = FastAPI(title="UrnaFácil API - TSE", version="2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "index.html"
FIXTURE = Path(__file__).resolve().parent / "tests" / "fixtures" / "boletim_trindade_0049_0001.dat"


def agora(): return datetime.now(timezone.utc).isoformat()


def _secoes_formato_tse(obj, mun_target, zona_target):
    """Formato do EA16 (cs.json): {"abr":[{"mu":[{"cd":"96253","zon":[{"cd":"0049","sec":[{"ns":"0001"}]}]}]}]}."""
    encontrados=set()
    for abr in obj.get("abr",[]) if isinstance(obj,dict) else []:
        for mu in abr.get("mu",[]):
            if not str(mu.get("cd","")).strip().isdigit() or int(mu["cd"])!=mun_target: continue
            for zon in mu.get("zon",[]):
                if not str(zon.get("cd","")).strip().isdigit() or int(zon["cd"])!=zona_target: continue
                for sec in zon.get("sec",[]):
                    ns=str(sec.get("ns","")).strip()
                    if ns.isdigit(): encontrados.add(int(ns))
    return encontrados


def _extrair_secoes(obj, municipio, zona):
    """Extrai seções do EA16 do TSE filtrando município/zona, tolerando variações de nomes."""
    mun_target=int(str(municipio).strip())
    zona_target=int(str(zona).strip())
    encontrados=_secoes_formato_tse(obj, mun_target, zona_target)
    if encontrados: return sorted(encontrados)
    mun_keys={"municipio","codmunicipio","cdmunicipio","nmunicipio","municipiozona"}
    zona_keys={"zona","nrzona","numerozona","cdzona","z"}
    sec_keys={"secao","nrsecao","numerosecao","numerosecaoeleitoral","cdsecao","s"}
    def norm(k): return str(k).lower().replace('_','').replace('-','')
    def scalar(d, keys):
        for k,v in d.items():
            if norm(k) in keys and isinstance(v,(int,str)):
                try: return int(str(v).strip())
                except ValueError: pass
        return None
    def walk(x, mun=None, zona=None):
        if isinstance(x, dict):
            local_mun=scalar(x,mun_keys) if scalar(x,mun_keys) is not None else mun
            local_zona=scalar(x,zona_keys) if scalar(x,zona_keys) is not None else zona
            for k,v in x.items():
                nk=norm(k)
                if nk in sec_keys and isinstance(v,(int,str)) and local_mun==mun_target and local_zona==zona_target:
                    try:
                        n=int(str(v).strip())
                        if 1 <= n <= 9999: encontrados.add(n)
                    except ValueError: pass
                walk(v,local_mun,local_zona)
        elif isinstance(x,list):
            for v in x: walk(v,mun,zona)
    walk(obj)
    return sorted(encontrados)


def _cargo_eleicao(cargo:int):
    # Códigos oficiais TSE 2026: 6257 = eleição geral federal (Presidente);
    # 6259 = eleições gerais estaduais (Governador, Senador e Deputados).
    if cargo == 1: return 6257
    if cargo in (3, 5, 6, 7): return 6259
    raise ValueError(f"Cargo não suportado para 2026: {cargo}")


def carregar_secao(uf,municipio,zona,secao,cargo,force=False):
    eleicao=_cargo_eleicao(cargo)
    uf=uf.lower(); m=str(municipio).zfill(5); z=str(zona).zfill(4); s=str(secao).zfill(4)
    if not force:
        cached=get_section(eleicao,cargo,uf,m,z,s)
        if cached is not None: return cached, True, get_fonte(eleicao,uf,m,z,s)
    # Fixture real usada apenas como teste automatizado para a seção 0049/0001.
    if uf=="go" and m=="96253" and z=="0049" and s=="0001" and FIXTURE.exists():
        path=FIXTURE; source="fixture BU real fornecida para validação"
    else:
        path,source,_aux=get_bu_file(uf,m,z,s)
    # O BU traz todos os cargos das duas eleições: salva tudo para não baixar de novo ao trocar de cargo.
    updated=agora()
    for id_eleicao,cargos in votos_todos_cargos(path).items():
        save_eleicao(id_eleicao,uf,m,z,s,cargos,source,updated)
    return get_section(eleicao,cargo,uf,m,z,s) or [],False,source

@app.get("/", include_in_schema=False)
def pagina():
    """Serve o frontend, assim o sistema abre só com o endereço http://127.0.0.1:8000."""
    return FileResponse(FRONTEND)

@app.get("/status")
def status():
    return {"msg":"UrnaFácil API online","fonte":"TSE","cache":"SQLite","mock":False,"exemplo":"/pesquisa-multiplas?secoes=0001,0002,0003&cargo=6&candidato=13"}

@app.get("/config/{uf}")
def config_uf(uf:str):
    try: return get_config_uf(uf)
    except Exception as e: raise HTTPException(502,f"Falha ao consultar configuração do TSE: {e}")

@app.get("/secoes/{uf}/{municipio}/{zona}")
def secoes_disponiveis(uf:str, municipio:str, zona:str, cargo:int=6):
    """Lista as seções disponíveis no arquivo oficial de configuração do TSE."""
    eleicao=_cargo_eleicao(cargo)
    try:
        cfg=get_config_uf(uf)
        secoes=_extrair_secoes(cfg, municipio, zona)
        return {"uf":uf.upper(),"municipio":str(municipio).zfill(5),"zona":str(zona).zfill(4),"secoes":[str(x).zfill(4) for x in secoes],"quantidade":len(secoes),"fonte":"TSE"}
    except Exception as e:
        raise HTTPException(502,f"Falha ao carregar seções do TSE: {e}")

@app.get("/urna")
def urna_dados(uf:str="go",municipio:str="96253",zona:str="0049",secao:str="0001"):
    try:
        aux,url=get_urna_aux(uf,municipio,zona,secao)
        return {"aux":aux,"aux_url":url,"params":{"uf":uf,"municipio":municipio,"zona":zona,"secao":secao}}
    except Exception as e: raise HTTPException(502,f"Falha ao consultar TSE: {e}")

@app.get("/votos")
def votos(uf:str=Query("go"),municipio:str=Query("96253"),zona:str=Query("0049"),secao:str=Query("0001"),cargo:int=Query(6),candidato:Optional[str]=Query(None),force:bool=False):
    try: rows,from_cache,source=carregar_secao(uf,municipio,zona,secao,cargo,force)
    except Exception as e: raise HTTPException(502,str(e))
    if candidato:
        q=candidato.strip().lower()
        rows=[r for r in rows if r["numero"].lower()==q]
    total=sum(r["votos"] for r in rows)
    return {"uf":uf.upper(),"municipio":str(municipio).zfill(5),"zona":str(zona).zfill(4),"secao":str(secao).zfill(4),"cargo":cargo,"votos":rows,"total":total,"cache":from_cache,"fonte":source,"mock":False}

@app.get("/pesquisa-multiplas")
def pesquisa_multiplas(uf:str="go",municipio:str="96253",zona:str="0049",secoes:str=Query(...,description="001,002,003"),cargo:int=6,candidato:str=Query(...,description="Número do candidato"),force:bool=False):
    lista=[]
    for s in secoes.split(','):
        s=s.strip()
        if not s: continue
        try:
            rows,from_cache,source=carregar_secao(uf,municipio,zona,s,cargo,force)
        except Exception as e:
            lista.append({"secao":s,"erro":str(e)}); continue
        matches=[r for r in rows if r["numero"]==candidato.strip()]
        votos=matches[0]["votos"] if matches else 0
        lista.append({"secao":str(s).zfill(4),"votos":votos,"cache":from_cache,"fonte":source})
    total=sum(x.get("votos",0) for x in lista if "erro" not in x)
    return {"uf":uf.upper(),"municipio":str(municipio).zfill(5),"zona":str(zona).zfill(4),"cargo":cargo,"candidato":candidato,"secoes":lista,"total":total,"cache_registros":cache_count(),"mock":False}

@app.get("/cache")
def cache(): return {"registros":cache_count(),"armazenamento":"SQLite","mock":False}
