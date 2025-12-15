"""Decorators for client error handling."""

import functools
import logging
import random
import time
from typing import Callable, Type, TypeVar

F = TypeVar("F", bound=Callable)

logger = logging.getLogger(__name__)


def wrap_client_errors(
    error_class: Type[Exception],
    operation: str,
    api_exception_class: Type[Exception] | None = None,
) -> Callable[[F], F]:
    """Decorator to wrap client method errors in a consistent error type.

    Args:
        error_class: The exception class to wrap errors in (e.g., YNABClientError).
        operation: Description of the operation for error messages (e.g., "fetch categories").
        api_exception_class: Optional specific API exception class to catch first.

    Returns:
        Decorated function that catches and wraps exceptions.

    Example:
        @wrap_client_errors(YNABClientError, "fetch categories", ynab.ApiException)
        def get_categories(self) -> CategoryList:
            ...
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                # If it's already our error type, re-raise
                if isinstance(e, error_class):
                    raise
                # If we have a specific API exception class and this is it, wrap it
                if api_exception_class and isinstance(e, api_exception_class):
                    raise error_class(f"Failed to {operation}: {e}") from e
                # Wrap any other exception
                raise error_class(f"Failed to {operation}: {e}") from e

        return wrapper  # type: ignore

    return decorator


def with_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: tuple[Type[Exception], ...] = (Exception,),
) -> Callable[[F], F]:
    """Decorator to retry a function with exponential backoff.

    Retries on transient failures (network errors, rate limits, server errors).
    Does NOT retry on client errors (invalid data, auth failures).

    Args:
        max_retries: Maximum number of retry attempts (default: 3).
        base_delay: Initial delay between retries in seconds (default: 1.0).
        max_delay: Maximum delay between retries in seconds (default: 30.0).
        exponential_base: Base for exponential backoff (default: 2.0).
        jitter: Whether to add random jitter to delays (default: True).
        retryable_exceptions: Tuple of exception types to retry on.

    Returns:
        Decorated function that retries on failure.

    Example:
        @with_retry(max_retries=3, base_delay=1.0)
        def make_api_call():
            ...
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e

                    # Check if this is a non-retryable error (4xx client errors)
                    error_str = str(e).lower()
                    if any(code in error_str for code in ["400", "401", "403", "404", "422"]):
                        # Client error - don't retry
                        raise

                    # If we've exhausted retries, raise the exception
                    if attempt >= max_retries:
                        logger.warning(
                            "All %d retry attempts exhausted for %s",
                            max_retries,
                            func.__name__,
                        )
                        raise

                    # Calculate delay with exponential backoff
                    delay = min(
                        base_delay * (exponential_base**attempt),
                        max_delay,
                    )

                    # Add jitter (±25% randomization)
                    if jitter:
                        delay = delay * (0.75 + random.random() * 0.5)

                    logger.info(
                        "Retry attempt %d/%d for %s after %.1fs delay (error: %s)",
                        attempt + 1,
                        max_retries,
                        func.__name__,
                        delay,
                        str(e)[:100],
                    )
                    time.sleep(delay)

            # Should not reach here, but just in case
            if last_exception:
                raise last_exception

        return wrapper  # type: ignore

    return decorator
