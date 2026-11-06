import importlib
import pkgutil

import pytest
from pydantic import ValidationError

from mesa_trading import config as config_module
from mesa_trading.broker.base import Broker
from mesa_trading.broker.factory import ShadowGate, make_broker
from mesa_trading.broker.sim import SimBroker
from mesa_trading.cli.tick import main
from mesa_trading.config import DeskConfig, load_yaml, repo_root


def test_a1_only_simbroker_implements_broker():
    import mesa_trading

    for module in pkgutil.walk_packages(mesa_trading.__path__, mesa_trading.__name__ + "."):
        importlib.import_module(module.name)
    found = set()

    def walk(cls):
        for sub in cls.__subclasses__():
            found.add(sub)
            walk(sub)

    walk(Broker)
    assert found == {SimBroker}
    assert not issubclass(ShadowGate, Broker)


def test_a2_make_broker_rejects_live_and_real():
    with pytest.raises(ValueError):
        make_broker("live")
    with pytest.raises(ValueError):
        make_broker("real")
    with pytest.raises(ValueError):
        make_broker("paper")
    assert isinstance(make_broker("shadow"), ShadowGate)
    assert isinstance(make_broker("simulated"), SimBroker)


def test_a2_job_exits_before_network(tmp_path):
    source = (repo_root() / "config" / "desk.yaml").read_text(encoding="utf-8")
    broken = source.replace("mode: shadow", "mode: live", 1)
    path = tmp_path / "desk.yaml"
    path.write_text(broken, encoding="utf-8")
    code = main(["--config", str(path), "--data-dir", str(tmp_path / "data")])
    assert code != 0
    assert not (tmp_path / "data" / "logs").exists()


def test_a6_schema_rejects_secret_fields():
    raw = load_yaml(repo_root() / "config" / "desk.yaml")
    for field in ("exchange_key", "api_secret", "wallet", "private_key"):
        tainted = dict(raw)
        tainted[field] = "no-va"
        with pytest.raises(ValidationError):
            DeskConfig.model_validate(tainted)
    assert "live" not in config_module.MODES if hasattr(config_module, "MODES") else True
