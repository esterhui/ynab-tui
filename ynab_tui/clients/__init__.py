"""API clients for YNAB Categorizer."""

from .amazon_client import AmazonClient, AmazonClientError, MockAmazonClient
from .mock_ynab_client import MockYNABClient
from .protocols import AmazonClientProtocol, YNABClientProtocol
from .ynab_client import YNABClient, YNABClientError

__all__ = [
    # YNAB
    "YNABClient",
    "YNABClientError",
    "MockYNABClient",
    "YNABClientProtocol",
    # Amazon
    "AmazonClient",
    "AmazonClientError",
    "MockAmazonClient",
    "AmazonClientProtocol",
]
