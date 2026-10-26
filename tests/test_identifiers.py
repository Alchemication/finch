"""The owner's own IBAN and BIC: validation, derived parts and storage.

The IBAN used is the published sample from the IBAN registry, not anyone's
account.
"""

from __future__ import annotations

import sqlite3

import pytest

from identifiers import AccountIdentifiers, domestic_parts, normalise_iban
from models import Account
from store import get_account_identifiers, set_account_identifiers

SAMPLE_IBAN = "IE29 AIBK 9311 5212 3456 78"


class TestAccountIdentifiers:
    def test_normalises_spacing_and_case(self) -> None:
        ids = AccountIdentifiers(iban="ie29aibk93115212345678", bic="aibkie2d")
        assert ids.iban == "IE29AIBK93115212345678"
        assert ids.bic == "AIBKIE2D"
        assert ids.grouped_iban == SAMPLE_IBAN
        assert ids.last4 == "5678"

    def test_mistyped_digit_fails_the_checksum(self) -> None:
        with pytest.raises(ValueError, match="check digits"):
            AccountIdentifiers(iban="IE29 AIBK 9311 5212 3456 79")

    def test_error_does_not_repeat_the_iban(self) -> None:
        with pytest.raises(ValueError) as caught:
            AccountIdentifiers(iban="IE29 AIBK 9311 5212 3456 79")
        assert "3456" not in str(caught.value)

    def test_wrong_length_for_ireland(self) -> None:
        with pytest.raises(ValueError, match="22 characters"):
            AccountIdentifiers(iban="IE29AIBK931152123456")

    def test_not_an_iban(self) -> None:
        with pytest.raises(ValueError, match="not an IBAN"):
            AccountIdentifiers(iban="12345678")

    @pytest.mark.parametrize("bic", ["AIBK", "AIBKIE2DX", "AIBK1E2D"])
    def test_malformed_bic(self, bic: str) -> None:
        with pytest.raises(ValueError, match="BIC"):
            AccountIdentifiers(iban=SAMPLE_IBAN, bic=bic)

    def test_eleven_character_bic(self) -> None:
        assert AccountIdentifiers(iban=SAMPLE_IBAN, bic="AIBKIE2DXXX").bic


class TestDomesticParts:
    def test_irish_sort_code_and_account_number(self) -> None:
        assert domestic_parts(normalise_iban(SAMPLE_IBAN)) == ("931152", "12345678")

    def test_other_countries_have_none(self) -> None:
        assert domestic_parts("DE89370400440532013000") is None


class TestStore:
    def test_round_trip_and_replace(
        self, conn: sqlite3.Connection, account: Account
    ) -> None:
        assert account.id is not None
        assert get_account_identifiers(conn, account.id) is None
        set_account_identifiers(conn, account.id, AccountIdentifiers(iban=SAMPLE_IBAN))
        set_account_identifiers(
            conn, account.id, AccountIdentifiers(iban=SAMPLE_IBAN, bic="AIBKIE2D")
        )
        stored = get_account_identifiers(conn, account.id)
        assert stored == AccountIdentifiers(iban=SAMPLE_IBAN, bic="AIBKIE2D")
        count = conn.execute("SELECT COUNT(*) FROM account_identifiers").fetchone()[0]
        assert count == 1
