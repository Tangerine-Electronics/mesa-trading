"""Copia ``config/*.yaml`` dentro del paquete al construir el wheel.

Tras ``pip install .``, ``__file__`` queda en site-packages y no ve el ``config/`` del repo.
"""

from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py


class BuildPy(build_py):
    def run(self) -> None:
        super().run()
        config_dir = Path(__file__).resolve().parent / "config"
        desk = config_dir / "desk.yaml"
        if not desk.is_file():
            raise FileNotFoundError(f"falta {desk} al construir el paquete")
        dest = Path(self.build_lib) / "mesa_trading" / "bundled_config"
        dest.mkdir(parents=True, exist_ok=True)
        init = dest / "__init__.py"
        if not init.exists():
            init.write_text(
                '"""YAML de la mesa empaquetados con el wheel. La fuente es config/."""\n',
                encoding="utf-8",
            )
        for path in sorted(config_dir.glob("*.yaml")):
            (dest / path.name).write_bytes(path.read_bytes())


setup(cmdclass={"build_py": BuildPy})
