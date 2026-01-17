"""
Zombies Services Module

Provides zombie resource detection and remediation:
- ZombieDetector: Scans for unused AWS resources
- RemediationService: Manages approval workflow
- ZombieDetectorFactory: Creates provider-specific detectors
"""

from .detector import ZombieDetector
from .remediation_service import RemediationService
from .service import ZombieService
from .factory import ZombieDetectorFactory

__all__ = ["ZombieDetector", "RemediationService", "ZombieService", "ZombieDetectorFactory"]
