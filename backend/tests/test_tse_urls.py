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
    get_config_uf('go', '6259')
    assert captured['url'].endswith('/oficial/ele2026/arquivo-urna/003220/config/go/go-p003220-cs.json')
