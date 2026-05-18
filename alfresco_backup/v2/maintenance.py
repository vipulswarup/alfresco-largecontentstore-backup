"""Per-destination restic forget/prune maintenance."""

import logging
from datetime import datetime

from .app_config import AppConfig
from .models import BackupPolicy, MaintenanceResult
from .restic import ResticRepository

logger = logging.getLogger(__name__)


class MaintenanceTask:
    def __init__(self, config: AppConfig, policy: BackupPolicy):
        self.config = config
        self.policy = policy
        profile = config.get_profile(policy.credential_profile) if policy.credential_profile else None
        self.repo = ResticRepository(policy, config, profile)

    def run(self) -> MaintenanceResult:
        result = MaintenanceResult(policy_name=self.policy.name, success=False)
        try:
            r = self.repo.forget_prune(self.policy.retention_days)
            if r['success']:
                result.success = True
                logger.info(
                    f"Maintenance {self.policy.name}: forget/prune "
                    f"(retention {self.policy.retention_days}d) OK"
                )
            else:
                result.error = r.get('error', 'forget/prune failed')
                result.lock_contention = r.get('lock_contention', False)
                logger.error(f"Maintenance {self.policy.name}: {result.error}")
        except Exception as e:
            result.error = str(e)
            logger.exception(f"Maintenance {self.policy.name} failed: {e}")
        return result
