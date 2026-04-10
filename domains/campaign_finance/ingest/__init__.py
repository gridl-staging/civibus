"""Federal campaign finance ingest package."""

from domains.campaign_finance.ingest.federal_officeholder_loader import (
    load_federal_house_officeholders,
    load_federal_senate_officeholders,
)

__all__ = [
    "load_federal_house_officeholders",
    "load_federal_senate_officeholders",
]
