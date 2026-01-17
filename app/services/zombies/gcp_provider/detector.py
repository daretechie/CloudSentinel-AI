from typing import List, Dict, Any, Optional
import structlog
from google.cloud import compute_v1
# Note: google.oauth2.service_account is needed for custom creds if not using default
from google.oauth2 import service_account
from app.services.zombies.base import BaseZombieDetector
from app.services.zombies.zombie_plugin import ZombiePlugin

# Import GCP Plugins
from app.services.zombies.gcp_provider.plugins.unattached_disks import GCPUnattachedDisksPlugin
from app.services.zombies.gcp_provider.plugins.unused_ips import GCPUnusedStaticIpsPlugin
from app.services.zombies.gcp_provider.plugins.machine_images import GCPMachineImagesPlugin

logger = structlog.get_logger()
class GCPZombieDetector(BaseZombieDetector):
    """
    Concrete implementation of ZombieDetector for GCP.
    Manages GCP SDK clients and plugin execution.
    """

    def __init__(self, region: str = "us-central1-a", credentials: Optional[Dict[str, Any]] = None, db: Optional[Any] = None):
        # region for GCP is usually a zone like 'us-central1-a'
        super().__init__(region, credentials, db)
        self.project_id = credentials.get("project_id") if credentials else None
        
        self._credentials_obj = None
        if credentials and credentials.get("service_account_json"):
            import json
            info = json.loads(credentials["service_account_json"])
            self._credentials_obj = service_account.Credentials.from_service_account_info(info)
            if not self.project_id:
                self.project_id = info.get("project_id")

        self._disks_client = None
        self._address_client = None
        self._images_client = None

    @property
    def provider_name(self) -> str:
        return "gcp"

    def _initialize_plugins(self):
        """Register the standard suite of GCP detections."""
        self.plugins = [
            GCPUnattachedDisksPlugin(),
            GCPUnusedStaticIpsPlugin(),
            GCPMachineImagesPlugin(),
        ]

    async def _execute_plugin_scan(self, plugin: ZombiePlugin) -> List[Dict[str, Any]]:
        """
        Execute GCP plugin scan.
        """
        if not self.project_id:
            logger.error("gcp_detector_missing_project_id")
            return []

        if plugin.category_key == "unattached_disks":
            if not self._disks_client:
                if self._credentials_obj:
                    self._disks_client = compute_v1.DisksClient(credentials=self._credentials_obj)
                else:
                    self._disks_client = compute_v1.DisksClient()
            return await plugin.scan(self._disks_client, project_id=self.project_id, zone=self.region)
            
        elif plugin.category_key == "orphaned_ips":
            # Extract region from zone (e.g., 'us-central1-a' -> 'us-central1')
            gcp_region = "-".join(self.region.split("-")[:2])
            
            if not self._address_client:
                if self._credentials_obj:
                    self._address_client = compute_v1.AddressesClient(credentials=self._credentials_obj)
                else:
                    self._address_client = compute_v1.AddressesClient()
            return await plugin.scan(self._address_client, project_id=self.project_id, region=gcp_region)
            
        elif plugin.category_key == "orphaned_images":
            if not self._images_client:
                if self._credentials_obj:
                    self._images_client = compute_v1.MachineImagesClient(credentials=self._credentials_obj)
                else:
                    self._images_client = compute_v1.MachineImagesClient()
            return await plugin.scan(self._images_client, project_id=self.project_id)

        return []
