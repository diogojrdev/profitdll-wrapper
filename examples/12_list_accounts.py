"""List every trading account linked to the DLL login (Routing Mode).

Demonstrates enumerating all accounts (and sub-accounts) the DLL reports for
the logged user via `client.get_accounts()`. One login may carry accounts at
several brokers; each entry is enriched with owner, broker, type and flags
from `GetAccountDetails`.

Prerequisites:
  * Windows 64-bit OS with Python 64-bit;
  * ProfitDLL binary available (defined via PROFITDLL_PATH env var or inside `dll/`);
  * Credentials set in `.env` file or environment variables — including
    `ROUTING_KEY`, the routing password (distinct from the login password),
    since the account roster is delivered by the routing server.

Execution:

    uv run python examples/12_list_accounts.py
"""

from __future__ import annotations

import sys
import time

from _common import load_credentials, setup_dll_path

from profitdll_wrapper import Account, AccountType, ProfitClient

# TConnectorAccountFlags bits (see docs/profitdll.md, GetAccountDetails).
CA_IS_SUB_ACCOUNT = 0x1
CA_IS_ENABLED = 0x2

# The roster is downloaded asynchronously from the routing server after
# login, so an immediate query right after connecting may come back empty.
ROSTER_ATTEMPTS = 10
ROSTER_RETRY_INTERVAL_S = 0.5


def account_type_name(code: int) -> str:
    """Best-effort name for a TConnectorAccountType value."""
    try:
        return AccountType(code).name
    except ValueError:
        return f"UNKNOWN ({code})"


def describe_flags(flags: int) -> str:
    """Decodes the account flags bitmask into readable parts."""
    parts: list[str] = []
    if flags & CA_IS_SUB_ACCOUNT:
        parts.append("SUB_ACCOUNT")
    if flags & CA_IS_ENABLED:
        parts.append("ENABLED")
    return " | ".join(parts) if parts else "none"


def fetch_roster(client: ProfitClient) -> list[Account]:
    """Polls the account roster, retrying briefly while the DLL loads it."""
    for attempt in range(1, ROSTER_ATTEMPTS + 1):
        roster = client.get_accounts()
        if roster:
            return roster
        print(
            f"Account roster still empty (attempt {attempt}/{ROSTER_ATTEMPTS}); "
            f"waiting {ROSTER_RETRY_INTERVAL_S:.1f}s for the routing server..."
        )
        time.sleep(ROSTER_RETRY_INTERVAL_S)
    return []


def print_roster(roster: list[Account]) -> None:
    """Prints the full details of every linked account, grouped by broker."""
    masters = [acc for acc in roster if not acc.sub_account_id]
    sub_accounts = [acc for acc in roster if acc.sub_account_id]
    brokers = {acc.broker_id: acc.broker_name for acc in roster}

    print(
        f"\n=== Accounts linked to this DLL login: {len(roster)} "
        f"({len(masters)} master, {len(sub_accounts)} sub-accounts) ==="
    )
    print(f"Brokers involved: {len(brokers)}")
    for broker_id, broker_name in sorted(brokers.items()):
        print(f"  -> broker_id={broker_id} ({broker_name or 'name unavailable'})")

    for acc in roster:
        label = f"{acc.account_id}" + (f" / sub {acc.sub_account_id}" if acc.sub_account_id else "")
        owner = acc.owner_name or acc.sub_owner_name or "owner unavailable"
        if acc.sub_owner_name and acc.owner_name:
            owner = f"{owner} ({acc.sub_owner_name})"
        print(
            f"  {label}\n"
            f"      Broker: {acc.broker_name or 'name unavailable'} (id={acc.broker_id})\n"
            f"      Owner:  {owner}\n"
            f"      Type:   {account_type_name(acc.account_type)}\n"
            f"      Flags:  {describe_flags(acc.account_flags)}"
        )


def main() -> int:
    setup_dll_path()
    activation_key, user, password, account, routing_key = load_credentials()

    if not (activation_key and user and password):
        print(
            "Missing credentials. Please define PROFITDLL_ACTIVATION_KEY, PROFITDLL_USER, "
            "and PROFITDLL_PASSWORD in your .env file or environment.",
            file=sys.stderr,
        )
        return 2
    if not routing_key:
        print(
            "Missing ROUTING_KEY: the routing password is required to receive the "
            "account roster and differs from the login password.",
            file=sys.stderr,
        )
        return 2

    try:
        with ProfitClient(
            activation_key=activation_key,
            user=user,
            password=password,
            routing_password=routing_key,
            mode="routing",
        ) as client:
            print("Connected. Querying the account roster...")

            roster = fetch_roster(client)
            if not roster:
                print(
                    "WARNING: no accounts reported by the DLL after "
                    f"{ROSTER_ATTEMPTS * ROSTER_RETRY_INTERVAL_S:.0f}s — "
                    "check your credentials/login.",
                    file=sys.stderr,
                )
                return 1

            print_roster(roster)

            if account and not any(acc.account_id == account for acc in roster):
                print(
                    f"WARNING: account {account!r} from .env is not in the DLL roster "
                    "shown above; check your PROFITDLL_ACCOUNT configuration.",
                    file=sys.stderr,
                )
    except KeyboardInterrupt:
        print("\nDisconnecting and exiting.")
    except Exception as exc:
        print(f"Error listing accounts: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
