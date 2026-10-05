from tse_client import get_config_uf
import tse_client


def test_ea16_url_usa_pleito_2026(monkeypatch):
    captured = {}
    class R:
        def raise_for_status(self): pass
        def json(self): return {}
    def fake_get(url, timeout=30, headers=None):
        captured['url'] = url
        return R()
    monkeypatch.setattr(tse_client.requests, 'get', fake_get)
    get_config_uf('go')
    assert captured['url'].endswith('/oficial/ele2026/arquivo-urna/3220/config/go/go-p003220-cs.json')


def test_tenta_pasta_com_zeros_se_a_primeira_der_404(monkeypatch):
    import requests
    urls = []
    class R:
        def __init__(self, code): self.status_code = code
        def raise_for_status(self):
            if self.status_code == 404: raise requests.HTTPError(response=self)
        def json(self): return {"ok": True}
    def fake_get(url, timeout=30, headers=None):
        urls.append(url); return R(404 if "/3220/" in url else 200)
    monkeypatch.setattr(tse_client.requests, 'get', fake_get)
    assert get_config_uf('go') == {"ok": True}
    assert [u.split('arquivo-urna/')[1].split('/')[0] for u in urls] == ["3220", "003220"]
