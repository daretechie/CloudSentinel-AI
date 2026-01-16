from datetime import datetime, timedelta, timezone
from enum import Enum
from functools import wraps
from typing import Optional, Callable, Set, Dict

from fastapi import HTTPException, status

import structlog

logger = structlog.get_logger()


class PricingTier(str, Enum):
    """Available subscription tiers."""
    TRIAL = "trial"
    STARTER = "starter"
    GROWTH = "growth"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class FeatureFlag(str, Enum):
    """Feature flags for tier gating."""
    DASHBOARDS = "dashboards"
    ALERTS = "alerts"
    ZOMBIE_DETECTION = "zombie_detection"
    LLM_ANALYSIS = "llm_analysis"
    MULTI_CLOUD = "multi_cloud"
    GREENOPS = "greenops"
    AUTO_REMEDIATION = "auto_remediation"
    API_ACCESS = "api_access"
    FORECASTING = "forecasting"
    SSO = "sso"
    DEDICATED_SUPPORT = "dedicated_support"
    AUDIT_LOGS = "audit_logs"


# Tier configuration - USD pricing
TIER_CONFIG: Dict[PricingTier, Dict] = {
    PricingTier.TRIAL: {
        "name": "Trial",
        "price_usd": 0,
        "features": {
            FeatureFlag.DASHBOARDS,
            FeatureFlag.ALERTS,
            FeatureFlag.ZOMBIE_DETECTION,
            FeatureFlag.LLM_ANALYSIS,
            FeatureFlag.MULTI_CLOUD,
            FeatureFlag.GREENOPS,
        },
        "limits": {
            "zombie_scans_per_day": 10,
            "llm_analyses_per_day": 5,
        }
    },
    PricingTier.STARTER: {
        "name": "Starter",
        "price_usd": 29,
        "features": {
            FeatureFlag.DASHBOARDS,
            FeatureFlag.ALERTS,
            FeatureFlag.ZOMBIE_DETECTION,
        },
        "limits": {
            "zombie_scans_per_day": 20,
            "llm_analyses_per_day": 0,
        }
    },
    PricingTier.GROWTH: {
        "name": "Growth",
        "price_usd": 79,
        "features": {
            FeatureFlag.DASHBOARDS,
            FeatureFlag.ALERTS,
            FeatureFlag.ZOMBIE_DETECTION,
            FeatureFlag.LLM_ANALYSIS,
            FeatureFlag.MULTI_CLOUD,
            FeatureFlag.GREENOPS,
            FeatureFlag.FORECASTING,
        },
        "limits": {
            "zombie_scans_per_day": 50,
            "llm_analyses_per_day": 20,
        }
    },
    PricingTier.PRO: {
        "name": "Pro",
        "price_usd": 199,
        "features": {
            FeatureFlag.DASHBOARDS,
            FeatureFlag.ALERTS,
            FeatureFlag.ZOMBIE_DETECTION,
            FeatureFlag.LLM_ANALYSIS,
            FeatureFlag.MULTI_CLOUD,
            FeatureFlag.GREENOPS,
            FeatureFlag.FORECASTING,
            FeatureFlag.AUTO_REMEDIATION,
            FeatureFlag.API_ACCESS,
            FeatureFlag.AUDIT_LOGS,
        },
        "limits": {
            "zombie_scans_per_day": 100,
            "llm_analyses_per_day": 100,
        }
    },
    PricingTier.ENTERPRISE: {
        "name": "Enterprise",
        "price_usd": None,
        "features": set(FeatureFlag),
        "limits": {
            "zombie_scans_per_day": None,
            "llm_analyses_per_day": None,
        }
    },
}


def get_tier_config(tier: PricingTier) -> dict:
    """Get configuration for a tier."""
    return TIER_CONFIG.get(tier, TIER_CONFIG[PricingTier.STARTER])


def is_feature_enabled(tier: PricingTier, feature: str | FeatureFlag) -> bool:
    """Check if a feature is enabled for a tier."""
    if isinstance(feature, str):
        try:
            feature = FeatureFlag(feature)
        except ValueError:
            return False
            
    config = get_tier_config(tier)
    return feature in config.get("features", set())


def get_tier_limit(tier: PricingTier, limit_name: str) -> Optional[int]:
    """Get a limit value for a tier (None = unlimited)."""
    config = get_tier_config(tier)
    return config.get("limits", {}).get(limit_name)


def requires_tier(*allowed_tiers: PricingTier):
    """
    Decorator to require specific tiers for an endpoint.
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            user = kwargs.get("user")
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required"
                )
            
            user_tier = getattr(user, "tier", PricingTier.STARTER)
            if isinstance(user_tier, str):
                try:
                    user_tier = PricingTier(user_tier)
                except ValueError:
                    user_tier = PricingTier.STARTER
            
            if user_tier not in allowed_tiers:
                tier_names = [t.value for t in allowed_tiers]
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"This feature requires {' or '.join(tier_names)} tier. Please upgrade."
                )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def requires_feature(feature_name: str | FeatureFlag):
    """
    Decorator to require a specific feature for an endpoint.
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            user = kwargs.get("user")
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required"
                )
            
            user_tier = getattr(user, "tier", PricingTier.STARTER)
            if isinstance(user_tier, str):
                try:
                    user_tier = PricingTier(user_tier)
                except ValueError:
                    user_tier = PricingTier.STARTER
            
            if not is_feature_enabled(user_tier, feature_name):
                fn = feature_name.value if isinstance(feature_name, FeatureFlag) else feature_name
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Feature '{fn}' is not available on your current plan. Please upgrade."
                )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator
