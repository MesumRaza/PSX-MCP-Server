"""
PSX API Client for fetching market data
"""

import csv
from io import StringIO

import httpx
from typing import List, Dict, Any
from bs4 import BeautifulSoup
import re
from .models import TimeSeriesData

SECTOR_MAP = {
    "0819": "MODARABAS",
    "0803": "CABLE & ELECTRICAL GOODS",
    "0820": "OIL & GAS EXPLORATION COMPANIES",
    "0826": "SUGAR & ALLIED INDUSTRIES",
    "0829": "TEXTILE COMPOSITE",
    "0808": "ENGINEERING",
    "0825": "REFINERY",
    "0831": "TEXTILE WEAVING",
    "0806": "CLOSE - END MUTUAL FUND",
    "0813": "INV. BANKS / INV. COS. / SECURITIES COS.",
    "0821": "OIL & GAS MARKETING COMPANIES",
    "0811": "GLASS & CERAMICS",
    "0835": "WOOLLEN",
    "0824": "POWER GENERATION & DISTRIBUTION",
    "0804": "CEMENT",
    "0832": "TOBACCO",
    "0827": "SYNTHETIC & RAYON",
    "0816": "LEATHER & TANNERIES",
    "0828": "TECHNOLOGY & COMMUNICATION",
    "0823": "PHARMACEUTICALS",
    "0801": "AUTOMOBILE ASSEMBLER",
    "0833": "TRANSPORT",
    "0807": "COMMERCIAL BANKS",
    "0814": "JUTE",
    "0838": "PROPERTY",
    "0805": "CHEMICAL",
    "0834": "VANASPATI & ALLIED INDUSTRIES",
    "0818": "MISCELLANEOUS",
    "0836": "REAL ESTATE INVESTMENT TRUST",
    "0837": "EXCHANGE TRADED FUNDS",
    "0830": "TEXTILE SPINNING",
    "0815": "LEASING COMPANIES",
    "0810": "FOOD & PERSONAL CARE PRODUCTS",
    "0802": "AUTOMOBILE PARTS & ACCESSORIES",
    "0812": "INSURANCE",
    "0822": "PAPER & BOARD",
    "0809": "FERTILIZER",
}

def extract_symbol(cell):
    anchor = cell.select_one('a.tbl__symbol strong')
    if anchor:
        return anchor.text.strip()

    return cell.select_one('a.tbl__symbol').text.strip()

class PSXClient:
    """Client for fetching data from PSX website"""

    def __init__(self):
        self.sheet_url = (
            "https://docs.google.com/spreadsheets/d/"
            "1ByvO8hbeqSH8FQLbv_LDt98HRe2o-e28jOLx8KKRjXw"
            "/export?format=csv&gid=2105131278"
        )

        self.client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
        )

        self.headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/154.0.0.0 Safari/537.36"
            ),
            "X-Requested-With": "XMLHttpRequest",
            "X-Req-Id": "cMsMszi5JC581pgLE27dRLlqM5TgwTo7pTuLaVVED_o",
        }

    async def get_market_watch_data(self) -> List[Dict[str, Any]]:
        """Fetch market watch data from Google Sheets CSV."""

        try:
            response = await self.client.get(self.sheet_url)
            response.raise_for_status()

            reader = csv.DictReader(StringIO(response.text))

            # Fetch PSX symbol names using PSX headers
            symbols_response = await self.client.get(
                "https://dps.psx.com.pk/symbols",
                headers=self.headers,
            )
            symbols_response.raise_for_status()

            symbols_data = symbols_response.json()

            # Create symbol -> name mapping
            symbol_names = {
                item["symbol"].strip().upper(): item["name"].strip()
                for item in symbols_data
                if isinstance(item, dict)
                and item.get("symbol")
                and item.get("name")
            }

            stocks = []

            for row in reader:
                try:
                    symbol = (row.get("Symbol") or "").strip()

                    if not symbol:
                        continue

                    stock_data = {
                        "symbol": symbol,
                        "name": symbol_names.get(symbol.upper()),

                        "sector": SECTOR_MAP.get(
                            (row.get("Sector") or "").strip(),
                            (row.get("Sector") or "").strip()
                        ),
                        "listed_in": (row.get("ListedIn") or "").strip(),

                        "ldcp": self._parse_float(row.get("LDCP")),
                        "open_price": self._parse_float(row.get("Open")),
                        "high_price": self._parse_float(row.get("High")),
                        "low_price": self._parse_float(row.get("Low")),
                        "current_price": self._parse_float(row.get("Current")),
                        "change": self._parse_float(row.get("Change")),
                        "change_percent": 0.0,
                        "volume": self._parse_int(row.get("Volume")),

                        "last_updated": (row.get("LastUpdated") or "").strip(),
                        "source": (row.get("Source") or "").strip(),
                    }

                    stocks.append(stock_data)

                except (ValueError, TypeError, IndexError):
                    continue

            return stocks

        except httpx.HTTPError as e:
            raise Exception(
                f"Failed to fetch market watch CSV: {str(e)}"
            ) from e

        except Exception as e:
            raise Exception(
                f"Failed to parse market watch data: {str(e)}"
            ) from e

    @staticmethod
    def _parse_float(value: Any) -> float:
        if value is None:
            return 0.0

        value = str(value).strip().replace(",", "")

        if not value or value in {"-", "N/A", "NA", "null"}:
            return 0.0

        try:
            return float(value)
        except (ValueError, TypeError):
            return 0.0


    @staticmethod
    def _parse_int(value: Any) -> int:
        if value is None:
            return 0

        value = str(value).strip().replace(",", "")

        if not value or value in {"-", "N/A", "NA", "null"}:
            return 0

        try:
            return int(float(value))
        except (ValueError, TypeError):
            return 0

    async def get_intraday_data(self, symbol: str) -> List[Dict[str, Any]]:
        """Fetch intraday time series data for a specific stock"""
        try:
            response = await self.client.get(f"{self.base_url}/timeseries/int/{symbol}")
            response.raise_for_status()

            data = response.json()

            # PSX returns {"status": 1, "message": "", "data": [...]}
            if isinstance(data, dict) and data.get("status") == 1 and "data" in data:
                raw_data = data["data"]
            else:
                raw_data = data

            # Convert to our format
            intraday_data = []
            for item in raw_data:
                if len(item) >= 3:
                    time_point = TimeSeriesData(
                        timestamp=item[0], price=float(item[1]), volume=int(item[2])
                    )
                    intraday_data.append(time_point.model_dump())

            return intraday_data

        except Exception as e:
            raise Exception(f"Failed to fetch intraday data for {symbol}: {str(e)}")

    async def get_eod_data(self, symbol: str) -> List[Dict[str, Any]]:
        """Fetch end-of-day time series data for a specific stock"""
        try:
            response = await self.client.get(f"{self.base_url}/timeseries/eod/{symbol}")
            response.raise_for_status()

            data = response.json()

            # PSX returns {"status": 1, "message": "", "data": [...]}
            if isinstance(data, dict) and data.get("status") == 1 and "data" in data:
                raw_data = data["data"]
            else:
                raw_data = data

            # Convert to our format
            eod_data = []
            for item in raw_data:
                if len(item) >= 4:
                    time_point = TimeSeriesData(
                        timestamp=item[0],
                        price=float(item[1]),
                        volume=int(item[2]),
                        open_price=float(item[3]),
                    )
                    eod_data.append(time_point.model_dump())

            return eod_data

        except Exception as e:
            raise Exception(f"Failed to fetch EOD data for {symbol}: {str(e)}")

    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()
