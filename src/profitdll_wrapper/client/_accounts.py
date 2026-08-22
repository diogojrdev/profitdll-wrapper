"""Trading account, position, and broker/agent query mixin."""

from __future__ import annotations

import logging

from profitdll_wrapper._bindings.errors import NLCode, ProfitAPIError
from profitdll_wrapper._bindings.structures import (
    TConnectorAccountIdentifierOut,
    TConnectorTradingAccountOut,
    TConnectorTradingAccountPosition,
)
from profitdll_wrapper._types.accounts import Account, Position
from profitdll_wrapper._types.core import AssetId
from profitdll_wrapper.client._base import _ClientBase
from profitdll_wrapper.client._helpers import build_account_id, build_asset_id, validate_exchange

logger = logging.getLogger("profitdll_wrapper.client")


class _ClientAccountsMixin(_ClientBase):
    """Mixin providing position, account, and broker query methods."""

    def get_position(
        self,
        ticker: str,
        *,
        exchange: str,
        account: str,
        broker_id: int | None = None,
    ) -> Position:
        """Queries custody position for a given asset (thread-safe)."""
        validate_exchange(exchange)

        resolved_broker_id = self._resolve_broker_id(broker_id, account=account)

        acc_id = build_account_id(account, resolved_broker_id)
        asset_id = build_asset_id(ticker, exchange)
        out_pos = TConnectorTradingAccountPosition()
        out_pos.Version = 0
        out_pos.AccountID = acc_id
        out_pos.AssetID = asset_id

        asset_model = AssetId(ticker=ticker, exchange=exchange)

        try:
            code = self._backend.get_position_v2(out_pos)
            self._check_code(code)
        except ProfitAPIError as exc:
            if getattr(exc, "code", None) in (
                NLCode.NO_POSITION,
                NLCode.NOT_FOUND,
                NLCode.MARKET_ONLY,
                NLCode.INTERNAL_ERROR,
            ):
                return Position(
                    asset=asset_model,
                    account_id=account,
                    quantity=0,
                    average_price=0.0,
                )
            raise

        return Position(
            asset=asset_model,
            account_id=account,
            quantity=int(out_pos.DailyQuantity),
            average_price=float(out_pos.OpenAveragePrice),
            buy_quantity=int(out_pos.DailyBuyQuantity),
            sell_quantity=int(out_pos.DailySellQuantity),
            buy_average_price=float(out_pos.DailyAverageBuyPrice),
            sell_average_price=float(out_pos.DailyAverageSellPrice),
            realized_profit=0.0,
        )

    def get_agent_name(self, agent_id: int, *, short_name: bool = True) -> str:
        """Retrieves broker/agent name by numeric ID."""
        short_flag = 1 if short_name else 0
        length = int(self._backend.get_agent_name_length(agent_id, short_flag))
        if length <= 0:
            return ""

        from ctypes import create_unicode_buffer

        buffer = create_unicode_buffer(length + 1)
        res = self._backend.get_agent_name(length + 1, agent_id, buffer, short_flag)
        if res <= 0:
            return ""
        return str(buffer.value)

    def get_accounts(self, include_subaccounts: bool = True) -> list[Account]:
        """Lists available trading accounts and sub-accounts."""
        count = int(self._backend.get_account_count())
        if count <= 0:
            return []

        accounts_arr = (TConnectorAccountIdentifierOut * count)()
        res_count = int(self._backend.get_accounts(0, 0, count, accounts_arr))
        if res_count <= 0:
            return []

        result: list[Account] = []
        for i in range(res_count):
            item = accounts_arr[i]
            acc_id = str(item.AccountID or "").strip()
            broker_id = int(item.BrokerID)
            if not acc_id:
                continue

            details = self.get_account_details(acc_id, broker_id=broker_id)
            if details is not None:
                result.append(details)
            else:
                result.append(Account(account_id=acc_id, broker_id=broker_id))

            if include_subaccounts:
                acc_ident = build_account_id(acc_id, broker_id)
                sub_count = int(self._backend.get_sub_account_count(acc_ident))
                if sub_count > 0:
                    sub_arr = (TConnectorAccountIdentifierOut * sub_count)()
                    res_sub = int(
                        self._backend.get_sub_accounts(acc_ident, 0, 0, sub_count, sub_arr)
                    )
                    for j in range(res_sub):
                        sub_item = sub_arr[j]
                        sub_id = str(sub_item.SubAccountID or "").strip()
                        if sub_id:
                            sub_details = self.get_account_details(
                                acc_id, broker_id=broker_id, sub_account_id=sub_id
                            )
                            if sub_details is not None:
                                result.append(sub_details)
                            else:
                                result.append(
                                    Account(
                                        account_id=acc_id,
                                        broker_id=broker_id,
                                        sub_account_id=sub_id,
                                    )
                                )

        return result

    def get_account_details(
        self,
        account_id: str,
        *,
        broker_id: int | None = None,
        sub_account_id: str = "",
    ) -> Account | None:
        """Retrieves complete details of a trading account or sub-account."""
        # No account-list fallback here: get_accounts() calls this method while
        # iterating the list, so a lookup would recurse.
        if broker_id is None:
            broker_id = getattr(self, "_broker_id", None)
        if broker_id is None:
            raise ValueError(
                "broker_id is required for get_account_details: pass it explicitly, "
                "set it in the ProfitClient(broker_id=...) constructor, or define "
                "BROKER in the .env file."
            )
        acc_ident = build_account_id(account_id, broker_id)
        if sub_account_id:
            acc_ident.SubAccountID = sub_account_id

        out_acc = TConnectorTradingAccountOut()
        out_acc.Version = 1
        out_acc.AccountID = acc_ident

        code1 = self._backend.get_account_details(out_acc)
        if code1 != int(NLCode.OK):
            return None

        b_len = max(int(out_acc.BrokerNameLength), 0)
        o_len = max(int(out_acc.OwnerNameLength), 0)
        so_len = max(int(out_acc.SubOwnerNameLength), 0)

        out_acc.BrokerName = " " * b_len if b_len > 0 else ""
        out_acc.OwnerName = " " * o_len if o_len > 0 else ""
        out_acc.SubOwnerName = " " * so_len if so_len > 0 else ""

        code2 = self._backend.get_account_details(out_acc)
        if code2 != int(NLCode.OK):
            return None

        return Account(
            account_id=account_id,
            broker_id=broker_id,
            sub_account_id=sub_account_id,
            broker_name=str(out_acc.BrokerName or "").strip(),
            owner_name=str(out_acc.OwnerName or "").strip(),
            sub_owner_name=str(out_acc.SubOwnerName or "").strip(),
            account_flags=int(out_acc.AccountFlags),
            account_type=int(out_acc.AccountType),
        )
