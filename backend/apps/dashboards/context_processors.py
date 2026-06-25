"""Template context shared across all pages (the app shell needs it everywhere)."""
from __future__ import annotations

from apps.rbac.permissions import visible_use_cases


def navigation(request):
    """Expose nav data for the single green app rail:

    * the user's accessible use cases (monitoring mode), and
    * the management console sections (Manage mode, staff only).
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"nav_use_cases": [], "console_groups": []}

    from apps.review.models import ReviewState
    from apps.submissions.models import Submission

    my_queue_count = (
        Submission.objects.filter(review__assigned_to=user)
        .exclude(review__state__in=[ReviewState.APPROVED, ReviewState.DECLINED])
        .count()
    )

    console_groups = []
    active_group = None
    if user.is_staff:
        from apps.console.registry import REGISTRY, grouped

        console_groups = grouped()
        match = getattr(request, "resolver_match", None)
        if match is not None and match.app_name == "console":
            current = REGISTRY.get(match.kwargs.get("key"))
            active_group = current.group if current else None
    return {
        "nav_use_cases": visible_use_cases(user),
        "console_groups": console_groups,
        "console_active_group": active_group,
        "my_queue_count": my_queue_count,
    }
