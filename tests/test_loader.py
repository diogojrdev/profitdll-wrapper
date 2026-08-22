"""Unit tests for native DLL loader (_bindings/loader.py)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from profitdll_wrapper._bindings.errors import PlatformNotSupportedError
from profitdll_wrapper._bindings.loader import (
    PROFITDLL_PATH_ENV,
    _bits,
    _candidate_filenames,
    _load_dll,
    _resolve_dll_path,
)


class TestLoaderArchitectureAndFilenames:
    def test_bits_returns_int(self) -> None:
        assert _bits() in (32, 64)

    def test_candidate_filenames_64bit(self) -> None:
        cands = _candidate_filenames(64)
        assert cands == ["ProfitDLL64.dll", "ProfitDLL.dll"]

    def test_candidate_filenames_32bit(self) -> None:
        cands = _candidate_filenames(32)
        assert cands == ["ProfitDLL.dll"]


class TestResolveDllPath:
    def test_resolve_explicit_path_found(self, tmp_path: Path) -> None:
        dll_file = tmp_path / "MyProfit.dll"
        dll_file.touch()
        resolved = _resolve_dll_path(dll_file)
        assert resolved == dll_file.resolve()

    def test_resolve_env_var_found(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        dll_file = tmp_path / "EnvProfit.dll"
        dll_file.touch()
        monkeypatch.setenv(PROFITDLL_PATH_ENV, str(dll_file))
        resolved = _resolve_dll_path()
        assert resolved == dll_file.resolve()

    def test_resolve_not_found_raises_file_not_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(PROFITDLL_PATH_ENV, raising=False)
        with pytest.raises(FileNotFoundError) as exc_info:
            _resolve_dll_path()
        assert "ProfitDLL not found" in str(exc_info.value)


class TestLoadDll:
    def test_load_dll_non_windows_raises_platform_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("platform.system", lambda: "Linux")
        with pytest.raises(PlatformNotSupportedError) as exc_info:
            _load_dll()
        assert "Windows-only" in str(exc_info.value)

    def test_load_dll_success_calls_windll(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dll_file = tmp_path / "MockProfit.dll"
        dll_file.touch()

        monkeypatch.setattr("platform.system", lambda: "Windows")
        mock_win_dll = MagicMock()
        # raising=False: ctypes.WinDLL does not exist on non-Windows runners,
        # where this test simulates Windows to exercise the load path.
        monkeypatch.setattr("ctypes.WinDLL", mock_win_dll, raising=False)

        _load_dll(explicit=dll_file)
        mock_win_dll.assert_called_once_with(str(dll_file.resolve()))
