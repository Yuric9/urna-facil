
import pandas as pd

# JEITO MAIS FÁCIL - RECOMENDADO
# 1. Baixe https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_secao/votacao_secao_2022_GO.zip
# 2. Descompacte
# 3. Rode este script

CSV_PATH = "votacao_secao_2022_GO.csv"  # ou 2024
CANDIDATO_NUM = "5555"  # troque
MUNICIPIO_FILTRO = 96253  # Trindade

print("Lendo CSV...")
df = pd.read_csv(CSV_PATH, encoding='latin1', sep=';')

# Filtra
filtro = df[(df['NR_VOTAVEL'] == int(CANDIDATO_NUM)) & (df['CD_MUNICIPIO'] == MUNICIPIO_FILTRO)]

# Agrupa por urna
resultado = filtro[['SG_UF','CD_MUNICIPIO','NM_MUNICIPIO','NR_ZONA','NR_SECAO','NR_VOTAVEL','NM_VOTAVEL','SG_PARTIDO','QT_VOTOS']].copy()
resultado = resultado.sort_values(by='QT_VOTOS', ascending=False)

print(resultado.head(20))
print(f"\nTotal votos candidato {CANDIDATO_NUM} em Trindade: {resultado['QT_VOTOS'].sum()}")

resultado.to_excel(f"votos_{CANDIDATO_NUM}_trindade_por_urna.xlsx", index=False)
print("Excel gerado!")
