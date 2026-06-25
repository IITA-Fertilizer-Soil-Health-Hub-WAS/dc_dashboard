"""DRF endpoints for review actions.

A single POST endpoint dispatches to the review service layer. The same state
machine + permission checks back the HTMX dashboard buttons (Phase 7), so web
and API stay consistent.
"""
from __future__ import annotations

from rest_framework import serializers, status
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.review import services
from apps.review.models import Review, ReviewAction
from apps.review.state_machine import ReviewPermissionDenied, TransitionError
from apps.submissions.models import Submission

_SERVICE = {
    ReviewAction.OPEN_REVIEW: services.open_review,
    ReviewAction.REQUEST_EDIT: services.request_edit,
    ReviewAction.DECLINE: services.decline,
    ReviewAction.QC_APPROVE: services.qc_approve,
    ReviewAction.REOPEN: services.reopen,
    ReviewAction.COMMENT: services.comment,
}


class ReviewActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=[a.value for a in ReviewAction])
    note = serializers.CharField(required=False, allow_blank=True, default="")
    field_key = serializers.CharField(required=False, allow_blank=True, default="")
    new_value = serializers.JSONField(required=False, default=None)


class ReviewActionView(APIView):
    """POST /api/review/<submission_id>/action/"""

    def post(self, request, submission_id):
        submission = get_object_or_404(Submission, pk=submission_id)
        serializer = ReviewActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        action = data["action"]

        try:
            if action == ReviewAction.EDIT_VALUE:
                if not data["field_key"]:
                    return Response(
                        {"detail": "field_key is required for EDIT_VALUE"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                review = services.edit_value(
                    request.user,
                    submission,
                    field_key=data["field_key"],
                    new_value=data["new_value"],
                    note=data["note"],
                )
            else:
                review = _SERVICE[action](request.user, submission, note=data["note"])
        except ReviewPermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except TransitionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)

        return Response(
            {"submission": str(submission.id), "state": review.state}, status=status.HTTP_200_OK
        )


class ReviewDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = ["submission", "state", "assigned_to", "qc_signed_by", "qc_signed_at"]
