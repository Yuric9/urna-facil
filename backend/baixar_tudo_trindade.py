
import requests
import pandas as pd
import time
import json
from tqdm import tqdm

# CONFIGURE AQUI
UF = "go"
COD_MUNICIPIO = "96253"  # Trindade - GO (código TSE)
CARGO = "0007"  # 0006 = Dep Federal, 0007 = Dep Estadual, 0001 = Presidente
ELEICAO_COD = "6259"  # 6257 = Federal, 6259 = Estadual
CANDIDATO_FILTRO = None  # Ex: "5555" para filtrar só um candidato, ou None para todos
ELEICAO_NOME = "ele2026"

BASE = "https://resultados.tse.jus.br/oficial"

def get_municipios():
    """Baixa lista de municípios e zonas"""
    urls = [
        f"{BASE}/{ELEICAO_NOME}/{ELEICAO_COD}/config/mun-e00{ELEICAO_COD}-cm.json",
        f"{BASE}/ele2026/6257/config/mun-e006257-cm.json",
        f"https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna/{ELEICAO_COD}/config/{UF}/{UF}-p000{ELEICAO_COD}-cs.json"
    ]
    for url in urls:
        try:
            print(f"Tentando {url}")
            r = requests.get(url, timeout=20)
            if r.status_code == 200:
                print(f"OK: {url}")
                return r.json(), url
        except Exception as e:
            print(f"Erro {url}: {e}")
    return None, None

def get_secoes_do_municipio():
    """
    Tenta pegar todas as seções de um município via arquivo de configuração de seções EA16
    ou via varredura do arquivo de totalização municipal
    """
    # Método 1: via totalização municipal -u.json que lista todas as seções no campo 'abr' ou 'sec'
    # Vamos tentar buscar o arquivo -u e extrair seções
    secoes = []
    
    # Fallback: varre zonas 1-200 e seções 1-500 (força bruta inteligente - TSE tem max 100 req/s)
    # Mas primeiro tenta pegar do config de seções
    try:
        # Arquivo de seções por UF - EA16
        url_cs = f"{BASE}/{ELEICAO_NOME}/arquivo-urna/{ELEICAO_COD}/config/{UF}/{UF}-p000{ELEICAO_COD}-cs.json"
        r = requests.get(url_cs, timeout=20)
        if r.status_code == 200:
            data = r.json()
            # estrutura varia, mas geralmente tem 'm' com municipios
            # Vamos procurar nosso município
            for mu in data.get('m', []):
                if str(mu.get('cd')) == COD_MUNICIPIO or str(mu.get('cd')).zfill(5) == COD_MUNICIPIO:
                    for zona in mu.get('z', []):
                        z_cd = str(zona.get('cd')).zfill(4)
                        for sec in zona.get('s', []):
                            s_cd = str(sec.get('cd')).zfill(4)
                            secoes.append((z_cd, s_cd))
            if secoes:
                print(f"Encontradas {len(secoes)} seções via CS.json")
                return secoes
    except Exception as e:
        print(f"Erro ao buscar CS.json: {e}")
    
    # Método 2: Se não achou, varre zona 49 que é a do seu link + zonas vizinhas 1-100
    # Para Trindade-GO normalmente são zonas 49, 123 etc - vamos varrer 49 e 123
    print("Usando varredura manual de zonas 49, 123, 72...")
    for zona in ["0049", "0123", "0072", "0001", "0002"]:
        for secao_num in range(1, 400):
            secoes.append((zona, str(secao_num).zfill(4)))
    return secoes[:500]  # limita

def get_votos_urna(zona, secao):
    """Pega votos daquela urna específica via arquivo -v.json ou -r.json de seção"""
    zona_4 = str(zona).zfill(4)
    secao_4 = str(secao).zfill(4)
    cod_5 = COD_MUNICIPIO.zfill(5)
    
    # Tentativa 1: arquivo de seção detalhado (boletim traduzido em JSON)
    # Estrutura 2024/2026: /dados/{uf}/{codmun}/{zona}/{secao}/...-v.json
    urls_tentar = [
        f"{BASE}/{ELEICAO_NOME}/{ELEICAO_COD}/dados/{UF}/{cod_5}/{zona_4}/{secao_4}/{UF}{cod_5}-c{CARGO}-e00{ELEICAO_COD}-v.json",
        f"{BASE}/ele2026/6259/dados/{UF}/{UF}{cod_5}-c{CARGO}-e006259-u.json",  # total municipal - tem todas as seções
    ]
    
    for url in urls_tentar:
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                return r.json(), url
        except:
            pass
    return None, None

def extrair_votos_cargo(dados_u_json):
    """Extrai lista de candidatos e votos do arquivo -u.json"""
    votos = []
    try:
        # EA20 formato: abr -> mu -> cand
        # Pode variar, vamos tentar genérico
        if 'abr' in dados_u_json:
            for abr in dados_u_json['abr']:
                for mu in abr.get('mu', []):
                    if str(mu.get('cd')).zfill(5) != COD_MUNICIPIO.zfill(5):
                        continue
                    for cand in mu.get('cand', []) + mu.get('c', []):
                        votos.append({
                            'numero': cand.get('n', cand.get('sqcand')),
                            'nome': cand.get('nm', cand.get('nome')),
                            'partido': cand.get('cc', cand.get('partido')),
                            'votos': int(cand.get('vap', cand.get('votos', 0))),
                            'zona': zona,
                            'secao': secao
                        })
        # Formato alternativo direto
        if 'cand' in dados_u_json:
            for cand in dados_u_json['cand']:
                votos.append(cand)
    except Exception as e:
        print(f"Erro parse: {e}")
    return votos

# ============== FLUXO PRINCIPAL ==============
print(f"=== UrnaFácil - Baixando todas as urnas de {COD_MUNICIPIO} ===")

# 1. Pega o arquivo de totalização do município - ele já tem TODOS os candidatos e total de votos
#    mas não por seção. Para por seção precisamos do dadosabertos ou do -v.json
url_total = f"{BASE}/{ELEICAO_NOME}/{ELEICAO_COD}/dados/{UF}/{UF}{COD_MUNICIPIO}-c{CARGO}-e00{ELEICAO_COD}-u.json"
print(f"Baixando total municipal: {url_total}")
try:
    r = requests.get(url_total, timeout=20)
    if r.status_code == 200:
        total_mun = r.json()
        print("Total municipal baixado - contém lista de candidatos")
        # salva
        with open(f"total_mun_{COD_MUNICIPIO}.json","w", encoding="utf-8") as f:
            json.dump(total_mun, f, ensure_ascii=False, indent=2)
    else:
        print(f"Total municipal retornou {r.status_code}")
        total_mun = None
except Exception as e:
    print(f"Erro total municipal: {e}")
    total_mun = None

# 2. Método mais confiável para votos por seção: Dados Abertos TSE
# https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_secao/votacao_secao_2022_GO.zip
# Para 2026 ainda não está no dados abertos no dia da eleição, então usamos o oficial + varredura

print("\n--- Varredura de seções (isso pode levar 2-3 minutos) ---")
secoes = get_secoes_do_municipio()
print(f"Varrendo {len(secoes)} seções...")

todos_votos = []
for zona, secao in tqdm(secoes[:100]):  # testa 100 primeiras para não tomar block
    aux_url = f"{BASE}/{ELEICAO_NOME}/arquivo-urna/{ELEICAO_COD}/dados/{UF}/{COD_MUNICIPIO.zfill(5)}/{zona}/{secao}/p000{ELEICAO_COD}-{UF}-m{COD_MUNICIPIO.zfill(5)}-z{zona}-s{secao}-aux.json"
    try:
        r = requests.get(aux_url, timeout=5)
        if r.status_code == 200:
            # Se aux existe, a seção existe
            # Agora tenta pegar votos dessa seção via -v.json
            # Na prática, o -v.json de seção individual nem sempre existe, então usamos o -u municipal e depois dados abertos
            todos_votos.append({"zona": zona, "secao": secao, "status": "existe", "aux_url": aux_url})
    except:
        pass
    time.sleep(0.05)  # respeita rate limit 100 req/s

print(f"Seções existentes encontradas: {len(todos_votos)}")

# 3. Gera Excel com o que achou
if todos_votos:
    df = pd.DataFrame(todos_votos)
    # Aqui você integraria o parser real do BU para pegar votos por candidato
    # Para demonstração, criamos colunas extras
    df['link_tse'] = df.apply(lambda x: f"https://resultados.tse.jus.br/oficial/app/index.html#/eleicao/{ELEICAO_COD}/uf/{UF}/mu/{COD_MUNICIPIO}/zn/{x['zona']}/cargo/7/vis/nominal/se/{x['secao']}/dados-de-urna/boletim-de-urna", axis=1)
    
    # Se filtrar candidato, duplica linhas com votos
    if CANDIDATO_FILTRO:
        df['candidato_filtro'] = CANDIDATO_FILTRO
        df['votos'] = 0  # preencher após parser BU
    
    df.to_excel(f"urnas_{COD_MUNICIPIO}_zona_{zona}.xlsx", index=False)
    print(f"Excel gerado: urnas_{COD_MUNICIPIO}_zona_{zona}.xlsx")
else:
    print("Nenhuma seção encontrada - verifique COD_MUNICIPIO e tente zona 0049 manualmente")
    # Cria Excel de exemplo
    exemplo = [
        {"zona": "0049", "secao": "0330", "municipio": COD_MUNICIPIO, "candidato_numero": "5555", "candidato_nome": "EXEMPLO", "partido": "PSD", "votos": 45, "link": f"https://resultados.tse.jus.br/oficial/app/index.html#/eleicao/{ELEICAO_COD}/uf/{UF}/mu/{COD_MUNICIPIO}/zn/0049/cargo/7/vis/nominal/se/0330/dados-de-urna/boletim-de-urna"},
        {"zona": "0049", "secao": "0331", "municipio": COD_MUNICIPIO, "candidato_numero": "5555", "candidato_nome": "EXEMPLO", "partido": "PSD", "votos": 38, "link": "..."},
    ]
    pd.DataFrame(exemplo).to_excel(f"exemplo_urnas_{COD_MUNICIPIO}.xlsx", index=False)
    print("Gerado exemplo_urnas.xlsx com dados fictícios - rode com internet para dados reais")

print("\nDICA: O jeito mais fácil e estável para votos por urna é usar votacao_secao do Dados Abertos:")
print("https://dadosabertos.tse.jus.br/dataset/resultados-2024 -> votacao_secao_2024_GO.csv")
print("Lá tem: ANO_ELEICAO, SG_UF, CD_MUNICIPIO, NR_ZONA, NR_SECAO, NR_VOTAVEL, QT_VOTOS")
