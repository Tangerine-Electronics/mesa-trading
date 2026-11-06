import pytest

from mesa_trading.http_allow import AllowlistError, HttpClient


class Recorder:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, method, url, headers, body, timeout):
        self.calls += 1
        return 200, b"{}"


def test_a4_blocks_exchange_and_authorization():
    transport = Recorder()
    client = HttpClient(transport=transport)
    with pytest.raises(AllowlistError):
        client.request("POST", "https://api.hyperliquid.xyz/exchange", body={"type": "order"})
    with pytest.raises(AllowlistError):
        client.request(
            "GET",
            "https://api.exchange.coinbase.com/products/BTC-USD/book?level=1",
            headers={"Authorization": "Bearer nope"},
        )
    with pytest.raises(AllowlistError):
        client.request("GET", "https://api.binance.com/api/v3/ticker")
    with pytest.raises(AllowlistError):
        client.request("POST", "https://api.exchange.coinbase.com/orders", body={"size": "1"})
    with pytest.raises(AllowlistError):
        client.request("DELETE", "https://api.hyperliquid.xyz/info")
    client.request("POST", "https://api.hyperliquid.xyz/info", body={"type": "l2Book", "coin": "BTC"})
    client.request("GET", "https://api.geckoterminal.com/api/v2/networks")
    assert transport.calls == 2
