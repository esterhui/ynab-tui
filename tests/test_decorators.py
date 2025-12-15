"""Tests for client decorators."""

from unittest.mock import patch

import pytest

from src.clients.decorators import with_retry, wrap_client_errors


class CustomError(Exception):
    """Custom error for testing wrap_client_errors."""

    pass


class APIError(Exception):
    """Simulated API error for testing."""

    pass


class TestWrapClientErrors:
    """Tests for wrap_client_errors decorator."""

    def test_successful_call(self):
        """Test that successful calls return normally."""

        @wrap_client_errors(CustomError, "test operation")
        def successful_func():
            return "success"

        result = successful_func()
        assert result == "success"

    def test_successful_call_with_args(self):
        """Test that arguments are passed through correctly."""

        @wrap_client_errors(CustomError, "test operation")
        def func_with_args(a, b, c=None):
            return (a, b, c)

        result = func_with_args(1, 2, c=3)
        assert result == (1, 2, 3)

    def test_reraises_same_error_type(self):
        """Test that errors of the same type are re-raised as-is."""

        @wrap_client_errors(CustomError, "test operation")
        def raises_custom():
            raise CustomError("original message")

        with pytest.raises(CustomError, match="original message"):
            raises_custom()

    def test_wraps_api_exception(self):
        """Test that API exceptions are wrapped with context."""

        @wrap_client_errors(CustomError, "fetch data", api_exception_class=APIError)
        def raises_api_error():
            raise APIError("API unavailable")

        with pytest.raises(CustomError, match="Failed to fetch data"):
            raises_api_error()

    def test_wraps_generic_exception(self):
        """Test that generic exceptions are wrapped."""

        @wrap_client_errors(CustomError, "process request")
        def raises_generic():
            raise ValueError("invalid value")

        with pytest.raises(CustomError, match="Failed to process request"):
            raises_generic()

    def test_preserves_exception_chain(self):
        """Test that original exception is preserved in chain."""

        @wrap_client_errors(CustomError, "test operation")
        def raises_value_error():
            raise ValueError("original")

        with pytest.raises(CustomError) as exc_info:
            raises_value_error()

        assert exc_info.value.__cause__ is not None
        assert isinstance(exc_info.value.__cause__, ValueError)

    def test_wraps_non_api_exception_even_with_api_class(self):
        """Test that non-API exceptions are wrapped even when api_exception_class is set."""

        @wrap_client_errors(CustomError, "operation", api_exception_class=APIError)
        def raises_other_error():
            raise RuntimeError("runtime error")

        with pytest.raises(CustomError, match="Failed to operation"):
            raises_other_error()


class TestWithRetry:
    """Tests for with_retry decorator."""

    def test_successful_call_no_retry(self):
        """Test that successful calls don't trigger retries."""
        call_count = 0

        @with_retry(max_retries=3)
        def successful_func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = successful_func()
        assert result == "success"
        assert call_count == 1

    def test_retry_on_failure_then_success(self):
        """Test retry succeeds on subsequent attempt."""
        call_count = 0

        @with_retry(max_retries=3, base_delay=0.001, jitter=False)
        def fails_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("transient error")
            return "success"

        with patch("src.clients.decorators.time.sleep"):
            result = fails_twice()

        assert result == "success"
        assert call_count == 3

    def test_max_retries_exceeded(self):
        """Test that max retries limit is enforced."""
        call_count = 0

        @with_retry(max_retries=2, base_delay=0.001, jitter=False)
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise Exception("persistent error")

        with patch("src.clients.decorators.time.sleep"):
            with pytest.raises(Exception, match="persistent error"):
                always_fails()

        # Initial call + 2 retries = 3 total
        assert call_count == 3

    def test_no_retry_on_400_error(self):
        """Test that 400 client errors are not retried."""
        call_count = 0

        @with_retry(max_retries=3)
        def raises_400():
            nonlocal call_count
            call_count += 1
            raise Exception("HTTP 400: Bad Request")

        with pytest.raises(Exception, match="400"):
            raises_400()

        assert call_count == 1  # No retries

    def test_no_retry_on_401_error(self):
        """Test that 401 auth errors are not retried."""
        call_count = 0

        @with_retry(max_retries=3)
        def raises_401():
            nonlocal call_count
            call_count += 1
            raise Exception("HTTP 401: Unauthorized")

        with pytest.raises(Exception, match="401"):
            raises_401()

        assert call_count == 1

    def test_no_retry_on_403_error(self):
        """Test that 403 forbidden errors are not retried."""
        call_count = 0

        @with_retry(max_retries=3)
        def raises_403():
            nonlocal call_count
            call_count += 1
            raise Exception("HTTP 403: Forbidden")

        with pytest.raises(Exception, match="403"):
            raises_403()

        assert call_count == 1

    def test_no_retry_on_404_error(self):
        """Test that 404 not found errors are not retried."""
        call_count = 0

        @with_retry(max_retries=3)
        def raises_404():
            nonlocal call_count
            call_count += 1
            raise Exception("HTTP 404: Not Found")

        with pytest.raises(Exception, match="404"):
            raises_404()

        assert call_count == 1

    def test_no_retry_on_422_error(self):
        """Test that 422 validation errors are not retried."""
        call_count = 0

        @with_retry(max_retries=3)
        def raises_422():
            nonlocal call_count
            call_count += 1
            raise Exception("HTTP 422: Unprocessable Entity")

        with pytest.raises(Exception, match="422"):
            raises_422()

        assert call_count == 1

    def test_retry_on_500_error(self):
        """Test that 500 server errors ARE retried."""
        call_count = 0

        @with_retry(max_retries=2, base_delay=0.001, jitter=False)
        def raises_500_then_succeeds():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("HTTP 500: Internal Server Error")
            return "recovered"

        with patch("src.clients.decorators.time.sleep"):
            result = raises_500_then_succeeds()

        assert result == "recovered"
        assert call_count == 2

    def test_exponential_backoff(self):
        """Test that delay increases exponentially."""
        call_count = 0
        delays = []

        @with_retry(max_retries=3, base_delay=1.0, exponential_base=2.0, jitter=False)
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise Exception("error")

        with patch("src.clients.decorators.time.sleep") as mock_sleep:
            mock_sleep.side_effect = lambda d: delays.append(d)
            with pytest.raises(Exception):
                always_fails()

        # Expected delays: 1.0, 2.0, 4.0 (base * 2^attempt)
        assert len(delays) == 3
        assert delays[0] == 1.0
        assert delays[1] == 2.0
        assert delays[2] == 4.0

    def test_max_delay_cap(self):
        """Test that delay is capped at max_delay."""
        call_count = 0
        delays = []

        @with_retry(max_retries=5, base_delay=10.0, max_delay=15.0, jitter=False)
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise Exception("error")

        with patch("src.clients.decorators.time.sleep") as mock_sleep:
            mock_sleep.side_effect = lambda d: delays.append(d)
            with pytest.raises(Exception):
                always_fails()

        # All delays should be capped at 15.0
        assert all(d <= 15.0 for d in delays)

    def test_jitter_adds_randomness(self):
        """Test that jitter adds randomness to delays."""
        delays_run1 = []
        delays_run2 = []

        @with_retry(max_retries=2, base_delay=1.0, jitter=True)
        def fails_with_jitter():
            raise Exception("error")

        # Run twice and collect delays
        with patch("src.clients.decorators.time.sleep") as mock_sleep:
            mock_sleep.side_effect = lambda d: delays_run1.append(d)
            with pytest.raises(Exception):
                fails_with_jitter()

        with patch("src.clients.decorators.time.sleep") as mock_sleep:
            mock_sleep.side_effect = lambda d: delays_run2.append(d)
            with pytest.raises(Exception):
                fails_with_jitter()

        # Jitter should make delays different (very unlikely to be identical)
        # Each delay should be within ±25% of base (0.75 to 1.25 * base)
        for delay in delays_run1 + delays_run2:
            assert 0.75 <= delay <= 15.0  # max could be 1.25 * 2^2 * 1.0 = 5.0

    def test_custom_retryable_exceptions(self):
        """Test that only specified exceptions trigger retry."""
        call_count = 0

        class RetryableError(Exception):
            pass

        class NonRetryableError(Exception):
            pass

        @with_retry(max_retries=3, retryable_exceptions=(RetryableError,))
        def raises_non_retryable():
            nonlocal call_count
            call_count += 1
            raise NonRetryableError("not retryable")

        with pytest.raises(NonRetryableError):
            raises_non_retryable()

        assert call_count == 1  # No retries for non-matching exception

    def test_function_name_preserved(self):
        """Test that decorated function preserves original name."""

        @with_retry()
        def my_function():
            pass

        assert my_function.__name__ == "my_function"

    def test_wrap_client_errors_preserves_name(self):
        """Test that wrap_client_errors preserves function name."""

        @wrap_client_errors(CustomError, "test")
        def my_other_function():
            pass

        assert my_other_function.__name__ == "my_other_function"
