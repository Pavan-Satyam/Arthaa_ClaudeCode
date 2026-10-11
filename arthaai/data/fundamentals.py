"""SEC EDGAR fundamentals and insider-trade extraction."""

from __future__ import annotations

import os
from typing import Any

import pandas as pd


class SECDataProcessor:
    """Read SEC company filings through the optional ``edgartools`` package."""

    def __init__(self, identity: str | None = None, company_factory: Any | None = None) -> None:
        self._identity = identity or os.environ.get("ARTHAAI_SEC_IDENTITY", "").strip()
        self._company_factory = company_factory

    def _company(self, ticker: str):
        if self._company_factory is not None:
            return self._company_factory(ticker.upper())
        try:
            import edgar
        except ImportError as exc:
            raise RuntimeError(
                "SEC filing support requires `pip install -e '.[fundamentals]'`."
            ) from exc
        if not self._identity:
            raise RuntimeError(
                "Set ARTHAAI_SEC_IDENTITY to an organization and contact email "
                "before making SEC EDGAR requests."
            )
        edgar.set_identity(self._identity)
        return edgar.Company(ticker.upper())

    @staticmethod
    def _latest(filings):
        if hasattr(filings, "latest"):
            return filings.latest()
        return filings[0] if filings else None

    @staticmethod
    def _to_frame(value: Any) -> pd.DataFrame:
        if isinstance(value, pd.DataFrame):
            return value.copy()
        for method_name in ("to_dataframe", "to_pandas"):
            method = getattr(value, method_name, None)
            if callable(method):
                converted = method()
                if isinstance(converted, pd.DataFrame):
                    return converted
        if isinstance(value, (list, tuple)):
            return pd.DataFrame(value)
        if isinstance(value, dict):
            return pd.DataFrame(value)
        raise TypeError("edgartools result cannot be converted to a Pandas DataFrame")

    def get_10k_financials(self, ticker: str) -> pd.DataFrame:
        """Download the latest 10-K income statement as a Pandas DataFrame."""
        company = self._company(ticker)
        filing = self._latest(company.get_filings(form="10-K"))
        if filing is None:
            return pd.DataFrame()
        xbrl = filing.xbrl()
        statement = xbrl.statements.income_statement()
        return self._to_frame(statement)

    @staticmethod
    def _field(value: Any, *names: str):
        for name in names:
            if isinstance(value, dict) and name in value:
                return value[name]
            if hasattr(value, name):
                return getattr(value, name)
        return None

    def get_insider_trades(self, ticker: str, *, limit: int = 100) -> pd.DataFrame:
        """Return transactions parsed from recent Form 4 filings.

        Edgar filing object APIs evolve; transaction objects are converted using
        their documented fields and unknown fields are left null, never guessed.
        """
        if limit < 1:
            raise ValueError("limit must be at least 1")
        company = self._company(ticker)
        filings = company.get_filings(form="4")
        if hasattr(filings, "head"):
            filings = filings.head(limit)
        rows = []
        for filing in filings[:limit]:
            obj = filing.obj() if callable(getattr(filing, "obj", None)) else filing
            transactions = self._field(obj, "transactions")
            if isinstance(transactions, pd.DataFrame):
                transactions = transactions.to_dict(orient="records")
            elif transactions is None:
                transactions = []
            for transaction in transactions:
                rows.append(
                    {
                        "ticker": ticker.upper(),
                        "filing_date": self._field(filing, "filing_date", "filingDate"),
                        "insider": self._field(obj, "reporting_owner", "owner_name", "ownerName"),
                        "transaction_date": self._field(transaction, "transaction_date", "date"),
                        "security": self._field(transaction, "security_title", "securityTitle"),
                        "transaction_code": self._field(transaction, "transaction_code", "code"),
                        "shares": self._field(transaction, "transaction_shares", "shares"),
                        "price": self._field(transaction, "transaction_price", "price"),
                        "acquired_disposed": self._field(
                            transaction, "acquired_disposed", "acquiredDisposed"
                        ),
                    }
                )
        columns = [
            "ticker", "filing_date", "insider", "transaction_date", "security",
            "transaction_code", "shares", "price", "acquired_disposed",
        ]
        return pd.DataFrame(rows, columns=columns)