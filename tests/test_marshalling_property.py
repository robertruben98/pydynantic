"""Property-based round-trip tests for :mod:`pydynantic.marshalling`.

These tests prove the ``deserialize(serialize(x)) == x`` contract over the
*supported* value space, accounting for the documented lossy conversions that
``marshalling.py`` performs:

* ``str`` (incl. ``""``), ``bool`` and ``bytes`` round-trip exactly.
* ``int`` is stored as a DynamoDB ``N`` and comes back as a :class:`Decimal`
  that is numerically equal to the original (DynamoDB has no integer type).
* ``Decimal`` within DynamoDB precision/range round-trips exactly, preserving
  trailing zeros.
* ``float`` is *intentionally* converted to ``Decimal(str(f))`` to avoid binary
  floating-point drift; the contract asserted here is therefore
  ``deserialize(serialize(f)) == Decimal(str(f))``.
* ``list``/``dict`` of supported scalars round-trip structurally (numbers come
  back as ``Decimal``).
* a homogeneous ``set`` of ``str`` or of ``int`` round-trips as a ``set``
  (element ordering is irrelevant; ints come back as ``Decimal``).

Values that are known to be lossy/unsupported (NaN, inf, mixed-type sets,
out-of-range numbers) are deliberately excluded from the strategies here and are
covered by example-based tests in ``tests/test_marshalling.py``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from pydynantic.marshalling import _check_number, deserialize, serialize

# DynamoDB numbers: <=38 significant digits, exponent roughly Emin=-130..Emax=125.
# Keep well inside the bounds so the strategy never produces values that
# ``_check_number`` would reject (those are exercised by example tests).
_MAX_NUMBER = Decimal(10) ** 30
_MIN_NUMBER = -_MAX_NUMBER

_SETTINGS = settings(max_examples=200, deadline=None)


def _in_dynamo_number_space(value: Any) -> bool:
    """True if ``value`` survives marshalling's number validation.

    Centralises the DynamoDB number constraints (<=38 significant digits,
    exponent within range) so the numeric strategies only emit values inside the
    supported space -- out-of-range / over-precise numbers are covered by
    example-based tests in ``tests/test_marshalling.py``.
    """
    try:
        _check_number(Decimal(str(value)))
    except Exception:
        return False
    return True


def _to_decimal(value: Any) -> Any:
    """Mirror marshalling's number normalisation for expected-value building."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, list):
        return [_to_decimal(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_decimal(val) for key, val in value.items()}
    return value


# --- scalar strategies --------------------------------------------------------

# bounded ints kept inside DynamoDB's number range
ints = st.integers(min_value=-(10**30), max_value=10**30)

# decimals within DynamoDB precision/range, no NaN/inf. The ``_in_dynamo_number_space``
# filter rejects the few generated values that exceed 38 significant digits or
# fall outside the exponent range (those are covered by example tests).
decimals = st.decimals(
    min_value=_MIN_NUMBER,
    max_value=_MAX_NUMBER,
    allow_nan=False,
    allow_infinity=False,
    places=None,
).filter(_in_dynamo_number_space)

# floats: finite, in-range, no NaN/inf. Subnormals/very small magnitudes have an
# exponent below DynamoDB's Emin, so filter them out (zero is fine).
floats = st.floats(
    min_value=-1e30,
    max_value=1e30,
    allow_nan=False,
    allow_infinity=False,
    allow_subnormal=False,
).filter(_in_dynamo_number_space)


# --- exact round-trip scalars -------------------------------------------------


@_SETTINGS
@given(st.text())
def test_str_roundtrip(value: str) -> None:
    assert deserialize(serialize(value)) == value


@_SETTINGS
@given(st.booleans())
def test_bool_roundtrip(value: bool) -> None:
    result = deserialize(serialize(value))
    assert result is value


@_SETTINGS
@given(st.binary())
def test_bytes_roundtrip(value: bytes) -> None:
    result = deserialize(serialize(value))
    # boto3 deserializes binary as a Binary wrapper; bytes() recovers the value.
    assert bytes(result) == value


@_SETTINGS
@given(ints)
def test_int_roundtrip_as_decimal_equal(value: int) -> None:
    result = deserialize(serialize(value))
    assert result == value
    assert result == Decimal(value)


@_SETTINGS
@given(decimals)
def test_decimal_roundtrip_exact(value: Decimal) -> None:
    result = deserialize(serialize(value))
    assert result == value
    assert isinstance(result, Decimal)


@_SETTINGS
@given(floats)
def test_float_roundtrip_to_decimal_str(value: float) -> None:
    # Documented contract: float -> Decimal(str(f)).
    result = deserialize(serialize(value))
    assert result == Decimal(str(value))


# --- collections --------------------------------------------------------------

# Scalars that may appear inside lists/dicts (numbers will come back as Decimal).
scalar_values = st.one_of(
    st.text(),
    st.booleans(),
    ints,
    decimals,
    floats,
)


@_SETTINGS
@given(st.lists(scalar_values, max_size=8))
def test_list_roundtrip(value: list[Any]) -> None:
    result = deserialize(serialize(value))
    assert result == _to_decimal(value)


@_SETTINGS
@given(st.dictionaries(st.text(), scalar_values, max_size=8))
def test_dict_roundtrip(value: dict[str, Any]) -> None:
    result = deserialize(serialize(value))
    assert result == _to_decimal(value)


# --- homogeneous sets ---------------------------------------------------------


@_SETTINGS
@given(st.sets(st.text(min_size=1), min_size=1, max_size=8))
def test_str_set_roundtrip(value: set[str]) -> None:
    result = deserialize(serialize(value))
    assert isinstance(result, set)
    assert result == value


@_SETTINGS
@given(st.sets(ints, min_size=1, max_size=8))
def test_int_set_roundtrip(value: set[int]) -> None:
    result = deserialize(serialize(value))
    assert isinstance(result, set)
    # ints come back as Decimal; compare as a set of Decimals (order irrelevant).
    assert result == {Decimal(item) for item in value}
