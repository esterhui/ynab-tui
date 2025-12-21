"""Tests for utility modules."""

from datetime import date, datetime

import pytest

from ynab_tui.utils import (
    fuzzy_match,
    get_match_fn,
    is_amazon_payee,
    parse_date,
    parse_to_datetime,
    substring_match,
    truncate_list_display,
    word_boundary_match,
)
from ynab_tui.utils.string_utils import normalize_string


class TestParseDate:
    """Tests for parse_date function."""

    def test_parse_date_from_string(self):
        """Test parsing ISO date string."""
        result = parse_date("2024-01-15")
        assert result == date(2024, 1, 15)

    def test_parse_date_from_iso_datetime_string(self):
        """Test parsing ISO datetime string extracts date."""
        result = parse_date("2024-01-15T10:30:00")
        assert result == date(2024, 1, 15)

    def test_parse_date_from_datetime(self):
        """Test parsing datetime object extracts date."""
        dt = datetime(2024, 1, 15, 10, 30, 0)
        result = parse_date(dt)
        assert result == date(2024, 1, 15)

    def test_parse_date_from_date(self):
        """Test parsing date object returns same date."""
        d = date(2024, 1, 15)
        result = parse_date(d)
        assert result == d

    def test_parse_date_none_raises(self):
        """Test parsing None raises ValueError."""
        with pytest.raises(ValueError, match="Cannot parse None"):
            parse_date(None)

    def test_parse_date_invalid_type_raises(self):
        """Test parsing invalid type raises ValueError."""
        with pytest.raises(ValueError, match="Cannot parse"):
            parse_date(12345)

    def test_parse_date_truncates_time(self):
        """Test date string with extra characters is truncated."""
        result = parse_date("2024-01-15 extra stuff")
        assert result == date(2024, 1, 15)


class TestParseToDatetime:
    """Tests for parse_to_datetime function."""

    def test_parse_to_datetime_from_datetime(self):
        """Test parsing datetime returns same datetime."""
        dt = datetime(2024, 1, 15, 10, 30, 0)
        result = parse_to_datetime(dt)
        assert result == dt

    def test_parse_to_datetime_from_date(self):
        """Test parsing date returns datetime at midnight."""
        d = date(2024, 1, 15)
        result = parse_to_datetime(d)
        assert result == datetime(2024, 1, 15, 0, 0, 0)

    def test_parse_to_datetime_from_iso_string(self):
        """Test parsing ISO datetime string."""
        result = parse_to_datetime("2024-01-15T10:30:00")
        assert result == datetime(2024, 1, 15, 10, 30, 0)

    def test_parse_to_datetime_from_date_string(self):
        """Test parsing date-only string returns datetime at midnight."""
        result = parse_to_datetime("2024-01-15")
        assert result == datetime(2024, 1, 15, 0, 0, 0)

    def test_parse_to_datetime_none_raises(self):
        """Test parsing None raises ValueError."""
        with pytest.raises(ValueError, match="Cannot parse None"):
            parse_to_datetime(None)

    def test_parse_to_datetime_invalid_type_raises(self):
        """Test parsing invalid type raises ValueError."""
        with pytest.raises(ValueError, match="Cannot parse"):
            parse_to_datetime(12345)


class TestFuzzyMatch:
    """Tests for fuzzy_match function."""

    def test_fuzzy_match_exact(self):
        """Test exact match returns True."""
        assert fuzzy_match("abc", "abc") is True

    def test_fuzzy_match_subsequence(self):
        """Test subsequence match returns True."""
        assert fuzzy_match("abc", "aXbXcX") is True
        assert fuzzy_match("Gro", "Groceries") is True  # Case-sensitive match

    def test_fuzzy_match_in_order(self):
        """Test characters must be in order."""
        assert fuzzy_match("abc", "cba") is False

    def test_fuzzy_match_no_match(self):
        """Test no match returns False."""
        assert fuzzy_match("xyz", "abc") is False

    def test_fuzzy_match_empty_query(self):
        """Test empty query matches everything."""
        assert fuzzy_match("", "anything") is True

    def test_fuzzy_match_empty_text(self):
        """Test empty text matches empty query only."""
        assert fuzzy_match("", "") is True
        assert fuzzy_match("a", "") is False

    def test_fuzzy_match_case_sensitive(self):
        """Test fuzzy match is case sensitive."""
        assert fuzzy_match("A", "a") is False
        assert fuzzy_match("a", "A") is False


class TestSubstringMatch:
    """Tests for substring_match function."""

    def test_substring_match_exact(self):
        """Test exact match returns True."""
        assert substring_match("misc", "misc") is True

    def test_substring_match_contained(self):
        """Test substring contained in text returns True."""
        # Note: actual usage lowercases both query and text before matching
        assert substring_match("misc", "miscellaneous") is True
        assert substring_match("misc", "some misc item") is True

    def test_substring_match_not_contained(self):
        """Test substring not in text returns False."""
        assert substring_match("misc", "Groceries") is False
        # Importantly, this should NOT match fzf-style
        assert substring_match("misc", "Mortgage Insurance Company") is False

    def test_substring_match_empty_query(self):
        """Test empty query matches everything."""
        assert substring_match("", "anything") is True

    def test_substring_match_empty_text(self):
        """Test empty text only matches empty query."""
        assert substring_match("", "") is True
        assert substring_match("a", "") is False

    def test_substring_match_case_sensitive(self):
        """Test substring match is case sensitive."""
        assert substring_match("MISC", "misc") is False
        assert substring_match("misc", "MISC") is False

    def test_substring_match_real_world_example(self):
        """Test real-world case: 'misc' should NOT match 'Investments Spire Stock'."""
        # This was the original bug - fuzzy match was too permissive
        assert substring_match("misc", "investments spire stock") is False
        assert substring_match("misc", "credit card payments visa-chase") is False


class TestWordBoundaryMatch:
    """Tests for word_boundary_match function."""

    def test_word_boundary_match_at_starts(self):
        """Test matching at word boundaries."""
        assert word_boundary_match("mr", "misc rental") is True  # M-isc R-ental
        assert word_boundary_match("hi", "home improvement") is True  # H-ome I-mprovement

    def test_word_boundary_match_exact(self):
        """Test exact match returns True."""
        assert word_boundary_match("misc", "misc") is True

    def test_word_boundary_match_fallback_to_fuzzy(self):
        """Test falls back to fuzzy if word boundary fails."""
        # "gro" can match "Groceries" via fuzzy (g-r-o in order)
        assert word_boundary_match("gro", "groceries") is True

    def test_word_boundary_match_empty_query(self):
        """Test empty query matches everything."""
        assert word_boundary_match("", "anything") is True

    def test_word_boundary_match_empty_text(self):
        """Test empty text only matches empty query."""
        assert word_boundary_match("", "") is True
        assert word_boundary_match("a", "") is False

    def test_word_boundary_match_no_match(self):
        """Test no match returns False."""
        assert word_boundary_match("xyz", "abc def") is False


class TestGetMatchFn:
    """Tests for get_match_fn function."""

    def test_get_match_fn_substring(self):
        """Test getting substring match function."""
        fn = get_match_fn("substring")
        assert fn == substring_match
        # Note: actual usage lowercases both query and text before matching
        assert fn("misc", "miscellaneous") is True
        assert fn("misc", "investments spire stock") is False

    def test_get_match_fn_fuzzy(self):
        """Test getting fuzzy match function."""
        fn = get_match_fn("fuzzy")
        assert fn == fuzzy_match
        # Note: actual usage lowercases both query and text before matching
        assert fn("misc", "miscellaneous") is True
        # fzf-style: m-i-s-c in order
        assert fn("misc", "mortgage insurance company") is True

    def test_get_match_fn_word_boundary(self):
        """Test getting word boundary match function."""
        fn = get_match_fn("word_boundary")
        assert fn == word_boundary_match
        assert fn("mr", "misc rental") is True

    def test_get_match_fn_invalid_defaults_to_substring(self):
        """Test invalid style defaults to substring."""
        fn = get_match_fn("invalid_style")  # type: ignore[arg-type]
        assert fn == substring_match


class TestTruncateListDisplay:
    """Tests for truncate_list_display function."""

    def test_truncate_list_empty(self):
        """Test empty list returns '(no items)'."""
        assert truncate_list_display([]) == "(no items)"

    def test_truncate_list_under_limit(self):
        """Test list under limit shows all items."""
        result = truncate_list_display(["a", "b"])
        assert result == "a, b"

    def test_truncate_list_at_limit(self):
        """Test list at limit shows all items."""
        result = truncate_list_display(["a", "b", "c"])
        assert result == "a, b, c"

    def test_truncate_list_over_limit(self):
        """Test list over limit shows truncated with count."""
        result = truncate_list_display(["a", "b", "c", "d", "e"])
        assert result == "a, b, c (+2 more)"

    def test_truncate_list_custom_max(self):
        """Test custom max_items parameter."""
        result = truncate_list_display(["a", "b", "c", "d"], max_items=2)
        assert result == "a, b (+2 more)"

    def test_truncate_list_custom_separator(self):
        """Test custom separator parameter."""
        result = truncate_list_display(["a", "b"], separator=" | ")
        assert result == "a | b"


class TestIsAmazonPayee:
    """Tests for is_amazon_payee function."""

    def test_is_amazon_payee_exact_match(self):
        """Test exact match."""
        patterns = ["AMAZON", "AMZN"]
        assert is_amazon_payee("AMAZON", patterns) is True

    def test_is_amazon_payee_contains(self):
        """Test pattern contained in payee."""
        patterns = ["AMAZON", "AMZN"]
        assert is_amazon_payee("AMAZON.COM", patterns) is True
        assert is_amazon_payee("AMZN MKTPLACE", patterns) is True

    def test_is_amazon_payee_case_insensitive(self):
        """Test case insensitive matching."""
        patterns = ["amazon", "amzn"]
        assert is_amazon_payee("AMAZON.COM", patterns) is True
        assert is_amazon_payee("amazon.com", patterns) is True

    def test_is_amazon_payee_no_match(self):
        """Test no pattern match."""
        patterns = ["AMAZON", "AMZN"]
        assert is_amazon_payee("COSTCO", patterns) is False

    def test_is_amazon_payee_empty_name(self):
        """Test empty payee name returns False."""
        patterns = ["AMAZON"]
        assert is_amazon_payee("", patterns) is False

    def test_is_amazon_payee_none_name(self):
        """Test None payee name returns False."""
        patterns = ["AMAZON"]
        assert is_amazon_payee(None, patterns) is False

    def test_is_amazon_payee_empty_patterns(self):
        """Test empty patterns list returns False."""
        assert is_amazon_payee("AMAZON", []) is False


class TestNormalizeString:
    """Tests for normalize_string function."""

    def test_normalize_lowercase(self):
        """Test converts to lowercase."""
        assert normalize_string("ABC") == "abc"

    def test_normalize_strip_whitespace(self):
        """Test strips leading/trailing whitespace."""
        assert normalize_string("  abc  ") == "abc"

    def test_normalize_combined(self):
        """Test lowercase and strip combined."""
        assert normalize_string("  HELLO WORLD  ") == "hello world"

    def test_normalize_already_normalized(self):
        """Test already normalized string unchanged."""
        assert normalize_string("hello") == "hello"
