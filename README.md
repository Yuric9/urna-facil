# UrnaFácil v2 — TSE + BU real + cache

O projeto consulta dados oficiais disponibilizados pelo TSE e armazena no SQLite os votos já processados por seção. A pesquisa por várias seções soma apenas os dados encontrados para cada seção.

## Fluxo
1. Primeira consulta: obtém o BU oficial da seção no TSE e decodifica o formato ASN.1/BER v2.
2. Salva os votos por candidato no cache SQLite.
3. Consultas seguintes usam o cache e não repetem o download da mesma seção.
4. `/pesquisa-multiplas` aceita várias seções (`001,002,003`) e soma os votos do número informado.

## Exemplo
`GET /pesquisa-multiplas?uf=go&municipio=96253&zona=0049&secoes=0001,0002,0003&cargo=6&candidato=13`

**Não há mais votos mockados.** Se o TSE não fornecer o BU, a API retorna erro; ela não inventa valores.

## Teste
`pytest -q`

A fixture `backend/tests/fixtures/boletim_trindade_0049_0001.dat` é o BU real fornecido para validar o parser.

## Pesquisa por múltiplas seções

A API agora possui `GET /secoes/{uf}/{municipio}/{zona}?cargo=6` para carregar as seções disponíveis no arquivo oficial de configuração do TSE. O frontend permite selecionar várias seções ou todas e consulta `GET /pesquisa-multiplas`.

Os resultados de cada seção são persistidos em SQLite. Pesquisas posteriores reutilizam o cache local e não precisam repetir o download/processamento daquela seção, salvo quando `force=true` for usado.

A fonte primária é o TSE. O arquivo BU real de Trindade incluído em `backend/tests/fixtures/` é somente uma fixture de teste automatizado e não deve ser tratado como fonte de produção.
