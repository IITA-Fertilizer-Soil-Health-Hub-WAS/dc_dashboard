"""Plugin contract for per-use-case Python hooks.

Most use cases are fully declarative (YAML/DB config). A small number (e.g.
BioSSA's nested multi-crop repeat groups) need imperative logic that does not
fit a declarative mapping. Those provide a plugin implementing this Protocol;
the ingestion/validation engines call the hooks around the generic pipeline.

A use case opts in via ``UseCase.plugin_path`` (e.g. ``plugins.biossa:BioSSAPlugin``).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:  # avoid import cycles at runtime
    from apps.usecases.models import FormDefinition


@runtime_checkable
class UseCasePlugin(Protocol):
    """Optional per-use-case overrides around the generic pipeline."""

    def pre_ingest(
        self, form: FormDefinition, raw_records: list[dict]
    ) -> list[dict]:
        """Hook before mapping. Return the (possibly filtered/augmented) records."""
        ...

    def normalize(
        self, form: FormDefinition, raw_record: dict, mapped: dict
    ) -> list[dict]:
        """Turn one raw record + its config-mapped fields into >=1 normalized rows.

        Default behaviour (no plugin) is ``[mapped]``. Plugins may explode a
        single nested record into multiple rows (e.g. one per crop/season).
        """
        ...

    def post_validate(self, submission, flags: list) -> list:
        """Hook after the validation engine. Return the final list of flags."""
        ...


class BaseUseCasePlugin:
    """No-op default implementation; subclass and override what you need."""

    def pre_ingest(self, form, raw_records: list[dict]) -> list[dict]:
        return raw_records

    def normalize(self, form, raw_record: dict, mapped: dict) -> list[dict]:
        return [mapped]

    def post_validate(self, submission, flags: list) -> list:
        return flags
