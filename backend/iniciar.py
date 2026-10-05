"""Liga o servidor do UrnaFácil e abre o navegador. Usado pelo "Iniciar UrnaFacil.bat"."""
import json, os, sys, threading, time, urllib.request, webbrowser

PORTA = 8000
URL = f"http://127.0.0.1:{PORTA}"


def ja_esta_rodando():
    try:
        with urllib.request.urlopen(f"{URL}/status", timeout=1) as r:
            return "UrnaFácil" in json.load(r).get("msg", "")
    except Exception:
        return False


def abrir_quando_pronto():
    for _ in range(60):
        if ja_esta_rodando():
            webbrowser.open(URL); return
        time.sleep(0.5)


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.getcwd())
    if ja_esta_rodando():
        # Já existe uma janela do UrnaFácil aberta: só abre o navegador de novo.
        webbrowser.open(URL); sys.exit(0)
    import uvicorn
    print(f"UrnaFácil rodando em {URL}")
    print("Para encerrar o sistema, feche esta janela.\n")
    threading.Thread(target=abrir_quando_pronto, daemon=True).start()
    uvicorn.run("main:app", host="127.0.0.1", port=PORTA, log_level="warning")
