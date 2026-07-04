"""The controlled vocabulary (Terminag) used to standardise form variables.

Terminag (https://github.com/controvoc/terminag) is a CSV-based agricultural
research vocabulary in two parts:

* **variables** — the canonical variable definitions (name, data type, unit, and
  for numeric variables an accepted min/max). A variable may point at a value
  list (its ``vocabulary``) for its accepted answers.
* **values** — the accepted values for a controlled character variable (e.g. the
  crop or country lists).

We mirror both into the DB (see ``importer``) so the form builder can offer
canonical field names + constraints, and the AI drafter can map a protocol's
variables to standard terms — reporting the ones with no match.
"""
from __future__ import annotations

from django.db import models

from apps.common.models import BaseModel


class VocabularyVariable(BaseModel):
    """One canonical variable from a Terminag ``variables_*.csv`` table."""

    class DataType(models.TextChoices):
        CHARACTER = "character", "Text"
        INTEGER = "integer", "Integer"
        NUMERIC = "numeric", "Decimal"
        DATE = "date", "Date"
        TIME = "time", "Time"
        LOGICAL = "logical", "Yes/No"

    name = models.CharField(max_length=128, unique=True)
    category = models.CharField(max_length=64)  # source table: soil, crop, weather, …
    data_type = models.CharField(max_length=16, blank=True)
    unit = models.CharField(max_length=64, blank=True)
    required = models.BooleanField(default=False)
    multiple_allowed = models.BooleanField(default=False)
    # The value list (a ``vocabulary`` key) an answer must come from, if controlled.
    value_list = models.CharField(max_length=64, blank=True)
    valid_min = models.FloatField(null=True, blank=True)
    valid_max = models.FloatField(null=True, blank=True)
    description = models.TextField(blank=True)
    obo = models.CharField(max_length=64, blank=True)  # ontology reference

    class Meta:
        ordering = ["category", "name"]

    def __str__(self) -> str:
        return self.name


class VocabularyValue(BaseModel):
    """One accepted value in a named value list (a Terminag ``values_*.csv``)."""

    list_name = models.CharField(max_length=64)  # e.g. "crop", "country"
    name = models.CharField(max_length=255)
    is_preferred = models.BooleanField(default=True)
    # Any extra columns from the source CSV (sciname, group, FAO_name, …).
    extra = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["list_name", "name"]
        constraints = [
            models.UniqueConstraint(fields=["list_name", "name"],
                                    name="uniq_vocab_value_per_list"),
        ]
        indexes = [models.Index(fields=["list_name"])]

    def __str__(self) -> str:
        return f"{self.list_name}:{self.name}"
