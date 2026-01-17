import asyncio
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import structlog
from datetime import datetime, timezone
from decimal import Decimal

from app.core.config import get_settings
from app.services.zombies.zombie_plugin import ZombiePlugin

logger = structlog.get_logger()
settings = get_settings()

class BaseZombieDetector(ABC):
    """
    Abstract Base Class for multi-cloud zombie resource detection.
    
    Responsibilities:
    - Orchestrate scans across multiple plugins (Strategy Pattern).
    - Aggregate results and calculate total waste.
    - Handle timeouts and region-specific context.
    - Provide a bridge between generic plugins and provider-specific clients.
    """

    from sqlalchemy.ext.asyncio import AsyncSession
    def __init__(self, region: str = "global", credentials: Optional[Dict[str, str]] = None, db: Optional[AsyncSession] = None):
        """
        Initializes the detector for a specific region.
        
        Args:
            region: Cloud region (e.g., 'us-east-1').
            credentials: Optional provider-specific credentials override.
            db: Optional database session for persistence.
        """
        self.region = region
        self.credentials = credentials
        self.db = db
        self.plugins: List[ZombiePlugin] = [] 

    @abstractmethod
    def _initialize_plugins(self):
        """Register provider-specific plugins for the cloud service."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """The cloud provider identifier (e.g., 'aws')."""

    async def scan_all(self, on_category_complete=None) -> Dict[str, Any]:
        """
        Orchestrates the scan across all registered plugins in parallel.
        
        Args:
            on_category_complete: Optional async callback triggered after each plugin finishing.
            
        Returns:
            A dictionary containing scan results, waste metrics, and metadata.
        """
        self._initialize_plugins()
        
        results = {
            "provider": self.provider_name,
            "region": self.region,
            "scanned_at": datetime.now(timezone.utc).isoformat(),
            "total_monthly_waste": Decimal("0"),
        }

        # Initialize results keys for all plugins
        for plugin in self.plugins:
            results[plugin.category_key] = []

        try:
            # Run plugins in parallel with timeout protection
            tasks = [self._run_plugin_with_timeout(plugin) for plugin in self.plugins]
            
            async def run_and_checkpoint(task):
                cat_key, items = await task
                if on_category_complete:
                    await on_category_complete(cat_key, items)
                return cat_key, items

            checkpoint_tasks = [run_and_checkpoint(t) for t in tasks]
            plugin_results = await asyncio.gather(*checkpoint_tasks)

            # Aggregate individual plugin results
            for category_key, items in plugin_results:
                results[category_key] = items

            # Calculate the total monthly waste across all items
            total = Decimal("0")
            for items in results.values():
                if isinstance(items, list):
                    for item in items:
                        total += Decimal(str(item.get("monthly_cost", 0)))
            
            results["total_monthly_waste"] = float(round(total, 2))

            logger.info(
                "zombie_scan_complete",
                provider=self.provider_name,
                waste=results["total_monthly_waste"],
                plugins_run=len(self.plugins)
            )

        except Exception as e:
            logger.error("zombie_scan_failed", provider=self.provider_name, error=str(e))
            results["error"] = str(e)

        return results

    async def _run_plugin_with_timeout(self, plugin: ZombiePlugin) -> tuple[str, List[Dict]]:
        """Wraps plugin execution with a generic timeout."""
        try:
            scan_coro = self._execute_plugin_scan(plugin)
            
            # Use global timeout from settings
            timeout = settings.ZOMBIE_PLUGIN_TIMEOUT_SECONDS
            items = await asyncio.wait_for(scan_coro, timeout=timeout)
            return plugin.category_key, items
            
        except asyncio.TimeoutError:
            logger.error("plugin_timeout", plugin=plugin.category_key)
            return plugin.category_key, []
        except Exception as e:
            logger.error("plugin_scan_failed", plugin=plugin.category_key, error=str(e))
            return plugin.category_key, []

    @abstractmethod
    async def _execute_plugin_scan(self, plugin: ZombiePlugin) -> List[Dict[str, Any]]:
        """
        Performs the actual API call to the cloud provider.
        Must be implemented by concrete subclasses to bridge to boto3, etc.
        """
        pass
