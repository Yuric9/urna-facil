from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from bu_parser import votos_todos_cargos
from cache import get_section, get_fonte, save_eleicao, cache_count
import dados_abertos
from candidatos import nomes_candidatos
from tse_client import get_config_uf, get_urna_aux, get_bu_file, SecaoSemBU

app = FastAPI(title="UrnaFácil API - TSE", version="2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

ANO_ATUAL = 2026  # eleição lida ao vivo dos Boletins de Urna; anos anteriores vêm dos Dados Abertos
FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "index.html"
FIXTURE = Path(__file__).resolve().parent / "tests" / "fixtures" / "boletim_trindade_0049_0001.dat"


def agora(): return datetime.now(timezone.utc).isoformat()


def _secoes_formato_tse(obj, mun_target, zona_target):
    """Formato do EA16 (cs.json): {"abr":[{"mu":[{"cd":"96253","zon":[{"cd":"0049","sec":[{"ns":"0001","nsp":"0001"}]}]}]}]}.

    "nsp" é a seção principal: quando é diferente de "ns", a seção foi agregada a outra
    e não tem BU próprio. Devolve (todas as seções, {agregada: principal}).
    """
    encontrados=set(); agregadas={}
    for abr in obj.get("abr",[]) if isinstance(obj,dict) else []:
        for mu in abr.get("mu",[]):
            if not str(mu.get("cd","")).strip().isdigit() or int(mu["cd"])!=mun_target: continue
            for zon in mu.get("zon",[]):
                if not str(zon.get("cd","")).strip().isdigit() or int(zon["cd"])!=zona_target: continue
                for sec in zon.get("sec",[]):
                    ns=str(sec.get("ns","")).strip(); nsp=str(sec.get("nsp","")).strip()
                    if not ns.isdigit(): continue
                    encontrados.add(int(ns))
                    if nsp.isdigit() and int(nsp)!=int(ns): agregadas[int(ns)]=int(nsp)
    return encontrados, agregadas


def secoes_agregadas(cfg, municipio, zona):
    return _secoes_formato_tse(cfg, int(str(municipio).strip()), int(str(zona).strip()))[1]


def _extrair_secoes(obj, municipio, zona):
    """Extrai seções do EA16 do TSE filtrando município/zona, tolerando variações de nomes."""
    mun_target=int(str(municipio).strip())
    zona_target=int(str(zona).strip())
    encontrados,_=_secoes_formato_tse(obj, mun_target, zona_target)
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
        agregadas={str(a).zfill(4):str(p).zfill(4) for a,p in secoes_agregadas(cfg, municipio, zona).items()}
        return {"uf":uf.upper(),"municipio":str(municipio).zfill(5),"zona":str(zona).zfill(4),"secoes":[str(x).zfill(4) for x in secoes],"quantidade":len(secoes),"agregadas":agregadas,"fonte":"TSE"}
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
def pesquisa_multiplas(uf:str="go",municipio:str="96253",zona:str="0049",secoes:str=Query(...,description="001,002,003"),cargo:int=6,candidato:Optional[str]=Query(None,description="Número do candidato; vazio = todos"),force:bool=False,ano:int=ANO_ATUAL,turno:int=1):
    cand=(candidato or "").strip()
    historico=ano!=ANO_ATUAL
    if historico and not dados_abertos.ja_importado(ano,uf,municipio):
        raise HTTPException(409,f"Os dados de {ano} de {uf.upper()}/{str(municipio).zfill(5)} ainda não foram importados.")
    lista=[]; por_candidato={}; nomes_historico={}
    for s in secoes.split(','):
        s=s.strip()
        if not s: continue
        try:
            if historico:
                rows=dados_abertos.votos_secao(ano,turno,uf,municipio,zona,s,cargo); from_cache=True; source=f"Dados Abertos TSE {ano}"
                nomes_historico.update({r["numero"]:{"nome":r["nome"],"partido":None} for r in rows if r.get("nome")})
            else:
                rows,from_cache,source=carregar_secao(uf,municipio,zona,s,cargo,force)
        except SecaoSemBU as e:
            lista.append({"secao":str(s).zfill(4),"votos":0,"aviso":str(e)}); continue
        except Exception as e:
            lista.append({"secao":str(s).zfill(4),"erro":str(e)}); continue
        sec=str(s).zfill(4)
        for r in rows:
            c=por_candidato.setdefault(r["numero"],{"numero":r["numero"],"partido":r.get("partido"),"total":0,"por_secao":{}})
            c["por_secao"][sec]=r["votos"]; c["total"]+=r["votos"]
        votos=por_candidato.get(cand,{}).get("por_secao",{}).get(sec,0) if cand else sum(r["votos"] for r in rows)
        lista.append({"secao":sec,"votos":votos,"cache":from_cache,"fonte":source})
    total=sum(x.get("votos",0) for x in lista if "erro" not in x)
    resp={"uf":uf.upper(),"municipio":str(municipio).zfill(5),"zona":str(zona).zfill(4),"cargo":cargo,"ano":ano,"turno":turno,"candidato":cand or None,"secoes":lista,"total":total,"cache_registros":cache_count(),"mock":False}
    if historico:
        nomes=nomes_historico  # o CSV dos Dados Abertos já traz o nome de cada candidato
    else:
        # Nomes vêm de outro arquivo do TSE; se ele falhar, a pesquisa segue só com os números.
        try: nomes,_=nomes_candidatos(uf,municipio,cargo)
        except Exception as e: nomes={}; resp["aviso_nomes"]=str(e)
    if cand:
        resp["nome"]=nomes.get(cand,{}).get("nome"); resp["sigla"]=nomes.get(cand,{}).get("partido")
    else:
        # Sem número: devolve o ranking de todos os candidatos nas seções consultadas.
        for c in por_candidato.values():
            c["nome"]=nomes.get(c["numero"],{}).get("nome"); c["sigla"]=nomes.get(c["numero"],{}).get("partido")
        resp["candidatos"]=sorted(por_candidato.values(),key=lambda c:(-c["total"],c["numero"]))
    return resp

@app.get("/candidatos/{uf}/{municipio}")
def lista_candidatos(uf:str, municipio:str, cargo:int=6, force:bool=False):
    """Lista de candidatos com nome (útil para conferir de onde os nomes vieram)."""
    try: nomes,fonte=nomes_candidatos(uf,municipio,cargo,force)
    except Exception as e: raise HTTPException(502,str(e))
    return {"uf":uf.upper(),"municipio":str(municipio).zfill(5),"cargo":cargo,"quantidade":len(nomes),"fonte":fonte or "cache","candidatos":nomes}

@app.get("/anos")
def anos():
    """Eleições disponíveis: a atual vem dos BUs ao vivo; as anteriores, dos Dados Abertos."""
    atual={"ano":ANO_ATUAL,"fonte":"bu","turnos":[1],"cargos":{1:"Presidente",3:"Governador",5:"Senador",6:"Deputado Federal",7:"Deputado Estadual"}}
    return {"anos":[atual]+[{"ano":a,"fonte":"dados_abertos","turnos":[1,2],"cargos":c} for a,c in dados_abertos.ANOS.items()]}

@app.post("/historico/importar")
def historico_importar(ano:int, uf:str, municipio:str):
    if ano not in dados_abertos.ANOS: raise HTTPException(400,f"Ano não suportado: {ano}")
    dados_abertos.iniciar_importacao(ano,uf,municipio)
    return dados_abertos.status(ano,uf,municipio)

@app.get("/historico/status")
def historico_status(ano:int, uf:str, municipio:str):
    return dados_abertos.status(ano,uf,municipio)

@app.get("/historico/secoes/{uf}/{municipio}/{zona}")
def historico_secoes(uf:str, municipio:str, zona:str, ano:int, turno:int=1, cargo:int=13):
    if not dados_abertos.ja_importado(ano,uf,municipio):
        raise HTTPException(409,f"Os dados de {ano} de {uf.upper()}/{str(municipio).zfill(5)} ainda não foram importados.")
    secoes=dados_abertos.secoes(ano,turno,uf,municipio,zona,cargo)
    return {"uf":uf.upper(),"municipio":str(municipio).zfill(5),"zona":str(zona).zfill(4),"ano":ano,"turno":turno,"secoes":secoes,"quantidade":len(secoes),"agregadas":{},"fonte":f"Dados Abertos TSE {ano}"}

@app.get("/cache")
def cache(): return {"registros":cache_count(),"armazenamento":"SQLite","mock":False}
