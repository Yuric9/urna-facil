# UrnaFácil - Frontend

Este é o app que simplifica o link do TSE.

Para conectar com o backend:
1. Rode o backend: uvicorn main:app --reload --port 8000
2. No frontend, altere a URL de fetch para http://localhost:8000/votos?uf=go&municipio=96253&zona=0049&secao=0330&candidato=5555

O index.html atual já é funcional standalone com mock.
