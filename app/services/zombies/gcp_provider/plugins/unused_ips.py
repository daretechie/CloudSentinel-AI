from typing import List, Dict, Any
import structlog
from google.cloud import compute_v1
from app.services.zombies.zombie_plugin import ZombiePlugin
from app.services.zombies.registry import registry
from decimal import Decimal

logger = structlog.get_logger()

@registry.register("gcp")
class GCPUnusedStaticIpsPlugin(ZombiePlugin):
    """
    Detects unused static external IP addresses in GCP.
    These addresses are charged even when not in use.
    """

    @property
    def category_key(self) -> str:
        return "orphaned_ips"

    async def scan(self, client: compute_v1.AddressesClient, project_id: str = None, region: str = None) -> List[Dict[str, Any]]:
        """
        Scans for addresses with status 'RESERVED' (not in use).
        """
        zombies = []
        try:
            # List all addresses in the project and region
            request = compute_v1.ListAddressesRequest(
                project=project_id,
                region=region,
            )
            
            import asyncio
            addresses = await asyncio.to_thread(client.list, request=request)
            
            for address in addresses:
                # 'RESERVED' means it's allocated but not attached to a resource
                if address.status == "RESERVED":
                    # Static IP monthly cost is ~$7.30 (standard rate for redundant IPs)
                    # Or ~$0.01 per hour = $7.2 per 30 days
                    monthly_waste = Decimal("7.20")
                    
                    zombies.append({
                        "id": str(address.id),
                        "name": address.name,
                        "region": region,
                        "ip_address": address.address,
                        "monthly_waste": float(monthly_waste),
                        "tags": dict(address.labels) if address.labels else {},
                        "created_at": address.creation_timestamp
                    })
                    
            return zombies
        except Exception as e:
            logger.error("gcp_unused_ips_scan_failed", error=str(e), project_id=project_id)
            return []
