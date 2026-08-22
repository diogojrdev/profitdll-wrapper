"""Testes de contas, detalhes e consultas de agentes do ProfitClient."""

from __future__ import annotations

from profitdll_wrapper import Account, ProfitClient
from tests.fakes.backend import FakeProfitBackend


def _client(backend: FakeProfitBackend, **kwargs: object) -> ProfitClient:
    defaults: dict[str, object] = {
        "activation_key": "key",
        "user": "user",
        "password": "pass",
        "mode": "market_data",
        "backend": backend,
    }
    defaults.update(kwargs)
    return ProfitClient(**defaults)  # type: ignore[arg-type]


class TestAgentName:
    def test_get_agent_name_short_and_full(self, fake_backend: FakeProfitBackend) -> None:
        client = _client(fake_backend)
        assert client.get_agent_name(120, short_name=True) == "XP"
        assert client.get_agent_name(120, short_name=False) == "XP Investimentos"
        assert client.get_agent_name(8, short_name=True) == "UBS"

    def test_get_agent_name_not_found(self, fake_backend: FakeProfitBackend) -> None:
        client = _client(fake_backend)
        assert client.get_agent_name(99999) == ""


class TestAccounts:
    def test_get_accounts_empty(self, fake_backend: FakeProfitBackend) -> None:
        client = _client(fake_backend)
        assert client.get_accounts() == []

    def test_get_accounts_and_details(self, fake_backend: FakeProfitBackend) -> None:
        acc1 = Account(
            account_id="12345",
            broker_id=120,
            broker_name="XP",
            owner_name="JOAO SILVA",
            account_type=0,
        )
        acc1_sub = Account(
            account_id="12345",
            broker_id=120,
            sub_account_id="SUB01",
            broker_name="XP",
            owner_name="JOAO SILVA",
            sub_owner_name="SUB JOAO",
            account_type=3,
        )
        acc2 = Account(
            account_id="67890",
            broker_id=8,
            broker_name="UBS",
            owner_name="MARIA SOUZA",
            account_type=0,
        )

        fake_backend.set_mock_accounts([acc1, acc1_sub, acc2])

        client = _client(fake_backend)

        masters = client.get_accounts(include_subaccounts=False)
        assert len(masters) == 2
        assert masters[0].account_id == "12345"
        assert masters[0].broker_name == "XP"
        assert masters[0].owner_name == "JOAO SILVA"
        assert masters[1].account_id == "67890"

        all_accs = client.get_accounts(include_subaccounts=True)
        assert len(all_accs) == 3
        assert all_accs[1].sub_account_id == "SUB01"
        assert all_accs[1].sub_owner_name == "SUB JOAO"

    def test_get_account_details_not_found(self, fake_backend: FakeProfitBackend) -> None:
        client = _client(fake_backend)
        assert client.get_account_details("99999", broker_id=3) is None


class TestPositionInAccounts:
    def test_get_position_autodetect_broker(self, fake_backend: FakeProfitBackend) -> None:
        acc = Account(account_id="1380116", broker_id=120, owner_name="TESTE")
        fake_backend.set_mock_accounts([acc])
        client = _client(fake_backend)

        pos = client.get_position("PETR4", exchange="B", account="1380116")
        assert pos.asset.ticker == "PETR4"
        assert pos.account_id == "1380116"
        assert pos.quantity == 0

    def test_get_position_internal_error_handled(self, fake_backend: FakeProfitBackend) -> None:
        fake_backend.position_error_code = 0x80000001
        client = _client(fake_backend)

        pos = client.get_position("VALE3", exchange="B", account="12345", broker_id=3)
        assert pos.asset.ticker == "VALE3"
        assert pos.quantity == 0
