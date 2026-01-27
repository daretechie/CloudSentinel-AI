"""
Currency Service - Multi-Currency Support for Valdrix

Provides exchange rate fetching and conversion.
Prioritizes Paystack for NGN rates to ensure alignment with user billing.
"""

import time
import httpx
from decimal import Decimal
from typing import Dict, Optional, List
import structlog
from app.shared.core.config import get_settings

logger = structlog.get_logger()

# In-memory cache for exchange rates
# key: currency_code, value: (rate_vs_usd, last_updated_timestamp)
_RATES_CACHE: Dict[str, tuple[Decimal, float]] = {
    "USD": (Decimal("1.0"), time.time())
}

# Fallback rates (Hardcoded as a last resort)
FALLBACK_RATES = {
    "NGN": Decimal("1550.0"),  # Approximate market rate Jan 2026
    "EUR": Decimal("0.92"),
    "GBP": Decimal("0.78"),
}

async def fetch_paystack_ngn_rate() -> Optional[Decimal]:
    """
    Attempts to fetch the current NGN exchange rate from Paystack.
    Paystack uses these rates for international settlement.
    """
    settings = get_settings()
    if not settings.PAYSTACK_SECRET_KEY:
        return None
        
    try:
        async with httpx.AsyncClient() as client:
            # Paystack undocumented (but used by SDKs) rate endpoint
            # Fallback: We can check their balance or recent transfers if needed
            # For now, we'll try a common approach: simulating a conversion or using the decision API
            response = await client.get(
                "https://api.paystack.co/transfer/rate?from=USD&to=NGN",
                headers={"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"},
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("status") and "data" in data:
                    rate = data["data"].get("rate")
                    if rate:
                        return Decimal(str(rate))
            
            logger.warning("paystack_rate_fetch_failed", status=response.status_code)
    except Exception as e:
        logger.error("paystack_rate_fetch_error", error=str(e))
        
    return None

async def fetch_fallback_rates() -> Dict[str, Decimal]:
    """
    Fetches exchange rates from a public API if possible.
    For MVP, we use hardcoded defaults if Paystack/Specific providers fail.
    """
    # Future: Integrate with Open Exchange Rates or similar
    return FALLBACK_RATES

async def get_exchange_rate(to_currency: str) -> Decimal:
    """
    Returns the exchange rate for USD to to_currency.
    Uses cached value if sync interval hasn't passed.
    """
    settings = get_settings()
    to_currency = to_currency.upper()
    
    if to_currency == "USD":
        return Decimal("1.0")
        
    now = time.time()
    cached_rate, last_updated = _RATES_CACHE.get(to_currency, (None, 0))
    
    # Check if cache is fresh (Sync interval in hours)
    sync_interval_sec = settings.EXCHANGE_RATE_SYNC_INTERVAL_HOURS * 3600
    if cached_rate and (now - last_updated < sync_interval_sec):
        return cached_rate
        
    # Cache expired or missing: Fetch new rate
    logger.info("syncing_exchange_rate", currency=to_currency)
    
    rate = None
    if to_currency == "NGN":
        rate = await fetch_paystack_ngn_rate()
        
    if not rate:
        # Fallback to other providers or hardcoded defaults
        all_fallbacks = await fetch_fallback_rates()
        rate = all_fallbacks.get(to_currency, FALLBACK_RATES.get(to_currency))
        
    if rate:
        _RATES_CACHE[to_currency] = (rate, now)
        return rate
        
    return Decimal("1.0") # Final fallback

async def convert_usd(amount_usd: float | Decimal, to_currency: str) -> Decimal:
    """
    Converts a USD amount to the target currency.
    """
    if to_currency.upper() == "USD":
        return Decimal(str(amount_usd))
        
    rate = await get_exchange_rate(to_currency)
    return Decimal(str(amount_usd)) * rate

async def format_currency(amount_usd: float | Decimal, to_currency: str) -> str:
    """
    Formats a USD amount for display in the target currency.
    """
    converted = await convert_usd(amount_usd, to_currency)
    
    symbols = {
        "NGN": "₦",
        "USD": "$",
        "EUR": "€",
        "GBP": "£"
    }
    symbol = symbols.get(to_currency.upper(), f"{to_currency.upper()} ")
    
    return f"{symbol}{float(converted):,.2f}"
