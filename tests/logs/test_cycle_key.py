from mesa_trading.gcs import cycle_log_key


def test_cycle_log_key_is_one_object():
    assert cycle_log_key("20261109T171500Z") == "logs/dt=2026-11-09/20261109T171500Z.jsonl"
    assert cycle_log_key("20261109T171500Z-01") == "logs/dt=2026-11-09/20261109T171500Z-01.jsonl"
    assert cycle_log_key("ancho") is None
