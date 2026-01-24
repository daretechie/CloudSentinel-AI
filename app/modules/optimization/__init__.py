"""
Zombies Services Module

Provides zombie resource detection and remediation:
- ZombieDetector: Scans for unused AWS resources
- RemediationService: Manages approval workflow
- ZombieDetectorFactory: Creates provider-specific detectors
"""

from .domain.remediation import RemediationService
from .domain.service import ZombieService
from .domain.factory import ZombieDetectorFactory

__all__ = ["RemediationService", "ZombieService", "ZombieDetectorFactory"]
