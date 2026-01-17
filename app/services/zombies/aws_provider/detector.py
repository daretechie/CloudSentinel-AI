from typing import List, Dict, Any
import aioboto3
import structlog
from app.services.zombies.base import BaseZombieDetector
from app.services.zombies.zombie_plugin import ZombiePlugin

from app.services.zombies.registry import registry
# Import plugins to trigger registration (Audit Fix: Decoupling)
import app.services.zombies.aws_provider.plugins  # noqa

logger = structlog.get_logger()

class AWSZombieDetector(BaseZombieDetector):
    """
    Concrete implementation of ZombieDetector for AWS.
    Manages aioboto3 session and AWS-specific plugin execution.
    """

    from sqlalchemy.ext.asyncio import AsyncSession
    def __init__(self, region: str = "us-east-1", credentials: Dict[str, str] = None, db: AsyncSession = None):
        super().__init__(region, credentials, db)
        self.session = aioboto3.Session()

    @property
    def provider_name(self) -> str:
        return "aws"

    def _initialize_plugins(self):
        """Register the standard suite of AWS detections."""
        self.plugins = registry.get_plugins_for_provider("aws")

    async def _execute_plugin_scan(self, plugin: ZombiePlugin) -> List[Dict[str, Any]]:
        """
        Execute AWS plugin scan, passing the aioboto3 session.
        Matches the signature expected by existing AWS plugins:
        plugin.scan(session, region, credentials)
        """
        return await plugin.scan(self.session, self.region, self.credentials)
