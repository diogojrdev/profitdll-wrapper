"""Smoke tests — validam o mínimo viável do scaffold.

Garantem que o pacote é instalável/importável e expõe a versão. Sem eles, um
erro de empacotamento (ex.: layout src/) só apareceria no CI de PR.
"""

from __future__ import annotations

import profitdll_wrapper


def test_importable() -> None:
    """O pacote deve ser importável sem carregar a DLL nativa."""
    assert profitdll_wrapper is not None


def test_version_string() -> None:
    """``__version__`` deve ser uma string não vazia (PEP 440)."""
    assert isinstance(profitdll_wrapper.__version__, str)
    assert profitdll_wrapper.__version__


def test_layers_are_submodules() -> None:
    """As três camadas internas devem estar registradas como submódulos."""
    import importlib

    for submodule in ("_bindings", "_types", "_events"):
        mod = importlib.import_module(f"profitdll_wrapper.{submodule}")
        assert mod is not None
