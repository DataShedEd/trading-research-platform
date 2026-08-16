import pytest

from trp.domain.identifier_validation import validate_cusip, validate_isin, validate_sedol


class TestIsin:
    def test_known_valid(self) -> None:
        validate_isin("US0378331005")  # Apple
        validate_isin("GB0002374006")  # Diageo

    def test_bad_check_digit(self) -> None:
        with pytest.raises(ValueError, match="check digit"):
            validate_isin("US0378331004")

    @pytest.mark.parametrize("bad", ["us0378331005", "US03783310", "0378331005US", ""])
    def test_malformed(self, bad: str) -> None:
        with pytest.raises(ValueError, match="malformed"):
            validate_isin(bad)


class TestSedol:
    def test_known_valid(self) -> None:
        validate_sedol("0263494")  # Barclays

    def test_bad_checksum(self) -> None:
        with pytest.raises(ValueError, match="checksum"):
            validate_sedol("0263495")

    def test_vowels_rejected(self) -> None:
        with pytest.raises(ValueError, match="malformed"):
            validate_sedol("A263494")


class TestCusip:
    def test_known_valid(self) -> None:
        validate_cusip("037833100")  # Apple

    def test_bad_check_digit(self) -> None:
        with pytest.raises(ValueError, match="check digit"):
            validate_cusip("037833101")
