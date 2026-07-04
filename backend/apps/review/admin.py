"""Review and its audit trail are project concerns, not system tables — they are
managed inside the app (per-project Review tab + Review log), so they are
intentionally NOT registered in the Django admin. See apps.dashboards for the
project-scoped review queue and the review-actions log.
"""
from __future__ import annotations
