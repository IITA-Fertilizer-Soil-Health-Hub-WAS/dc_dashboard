"""Use-case configuration models.

These tables hold everything the R app hardcoded across okapi.R / dataprocessing.R
/ support_fun.R / app.R. A use case is fully described by data: its ONA forms,
how each form's fields map to canonical names, its event schedule (day offsets),
its crops/trials/stages, and its ID patterns. Adding a use case = inserting rows
(via YAML import or the Admin UI), not editing code.
"""
from __future__ import annotations

from django.db import models

from apps.common.models import BaseModel

# Small list-of-strings fields use JSONField(default=list) rather than Postgres
# ArrayField so the same models run on SQLite (fast unit tests) and Postgres
# (prod, where JSONField is jsonb). These lists are read whole, not queried.


class Region(BaseModel):
    """A geographic region grouping countries (e.g. West Africa). Drives the
    coordinator hierarchy: a Regional Coordinator oversees all its countries."""

    code = models.SlugField(max_length=32, unique=True)
    name = models.CharField(max_length=128)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Country(BaseModel):
    """A country within a region. A Country Coordinator oversees its use cases."""

    region = models.ForeignKey(Region, on_delete=models.CASCADE, related_name="countries")
    code = models.CharField(max_length=8)  # ISO-ish
    name = models.CharField(max_length=128)

    class Meta:
        ordering = ["name"]
        unique_together = ("region", "code")
        verbose_name_plural = "countries"

    def __str__(self) -> str:
        return self.name


class UseCase(BaseModel):
    """An independent project implementation (e.g. SNS-RWANDA, KALRO, BioSSA)."""

    code = models.SlugField(max_length=64, unique=True)  # "SNS-RWANDA"
    country = models.ForeignKey(
        "Country", null=True, blank=True, on_delete=models.SET_NULL, related_name="use_cases"
    )
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)  # replaces active_use_case_list
    countries = models.JSONField(default=list, blank=True)

    # ID validation patterns (was patternissues / patternissuesE in app.R).
    enid_patterns = models.JSONField(default=list, blank=True)
    hhid_patterns = models.JSONField(default=list, blank=True)

    # Optional per-use-case Python plugin, e.g. "plugins.biossa:BioSSAPlugin".
    plugin_path = models.CharField(max_length=255, blank=True)

    # Bumped on every published config edit (Admin UI / YAML import).
    config_version = models.PositiveIntegerField(default=1)
    timezone = models.CharField(max_length=64, default="UTC")

    # Label shown for the household/plot id column (BioSSA uses "Plot Number").
    household_label = models.CharField(max_length=64, default="Household")

    # Enumerator IDs registered only for testing/monitoring; excluded from data
    # (R: filter(ENID != "RSENRW000001")).
    test_ids = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return self.code

    def bump_version(self) -> None:
        self.config_version = models.F("config_version") + 1
        self.save(update_fields=["config_version", "updated_at"])


class DataSource(BaseModel):
    """The data-collection server a use case is pulled from (and written back to).

    Makes the engine generic: ONA is one backend; KoboToolbox, ODK Central,
    SurveyCTO, a REST/CSV endpoint, etc. are added by registering more backends
    (see apps.ingestion.backends). One source per use case.
    """

    use_case = models.OneToOneField(UseCase, on_delete=models.CASCADE, related_name="data_source")
    backend = models.CharField(max_length=32, default="ONA")  # matches a registered backend type
    base_url = models.CharField(max_length=255, blank=True)
    token = models.CharField(max_length=512, blank=True)  # API token / key
    # Extra per-backend connection settings (project id, username, namespace…).
    config = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["use_case"]

    def __str__(self) -> str:
        return f"{self.use_case.code} via {self.backend}"


class Stage(BaseModel):
    """Research / Validation / Piloting."""

    use_case = models.ForeignKey(UseCase, on_delete=models.CASCADE, related_name="stages")
    name = models.CharField(max_length=64)

    class Meta:
        unique_together = ("use_case", "name")
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Crop(BaseModel):
    """maize, potato, rice, banana, cassava, legumes, yam, soy. Aliases handle
    inconsistent ONA values (e.g. 'potatoIrish' == potato)."""

    use_case = models.ForeignKey(UseCase, on_delete=models.CASCADE, related_name="crops")
    name = models.CharField(max_length=64)
    aliases = models.JSONField(default=list, blank=True)

    class Meta:
        unique_together = ("use_case", "name")
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Trial(BaseModel):
    """Fertilizer Recommendation, Variety Selection, Planting Date, Intercropping, NOT."""

    use_case = models.ForeignKey(UseCase, on_delete=models.CASCADE, related_name="trials")
    name = models.CharField(max_length=128)
    code = models.CharField(max_length=32, blank=True)

    class Meta:
        unique_together = ("use_case", "name")
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class FormDefinition(BaseModel):
    """One ONA form belonging to a use case (was the form_id inventory in okapi.R)."""

    class Role(models.TextChoices):
        ENUM_REG = "ENUM_REG", "Enumerator registration"
        HH_REG = "HH_REG", "Household registration"
        VALIDATION = "VALIDATION", "Validation data"
        NOT = "NOT", "Nutrient-omission trial"
        INTERCROP = "INTERCROP", "Intercropping"
        EXTRA = "EXTRA", "Extra"

    use_case = models.ForeignKey(UseCase, on_delete=models.CASCADE, related_name="forms")
    ona_form_id = models.BigIntegerField()
    role = models.CharField(max_length=16, choices=Role.choices)
    crop = models.ForeignKey(Crop, null=True, blank=True, on_delete=models.SET_NULL)
    season = models.CharField(max_length=16, blank=True)  # "S1"/"S2" (BioSSA)
    # ONA system columns to drop (the R `system_var` strip list); per-form override.
    system_vars_drop = models.JSONField(default=list, blank=True)

    class Meta:
        unique_together = ("use_case", "ona_form_id")
        ordering = ["use_case", "role", "ona_form_id"]

    def __str__(self) -> str:
        return f"{self.use_case.code}:{self.role}:{self.ona_form_id}"


class FieldMapping(BaseModel):
    """Maps raw ONA field path(s) -> a canonical field. Replaces the per-use-case
    rename()/coalesce()/separate() spaghetti in dataprocessing.R."""

    class Transform(models.TextChoices):
        DIRECT = "DIRECT", "Direct copy"
        COALESCE = "COALESCE", "First non-null of sources"
        SPLIT_GEOPOINT = "SPLIT_GEOPOINT", "Split 'lat lon alt err' geopoint"
        REGEX_SUB = "REGEX_SUB", "Regex substitution"
        DATE_PARSE = "DATE_PARSE", "Parse to date"
        CONST = "CONST", "Constant value"
        LOOKUP = "LOOKUP", "Resolve via crop/alias lookup"

    form = models.ForeignKey(FormDefinition, on_delete=models.CASCADE, related_name="mappings")
    target_field = models.CharField(max_length=64)  # ENID, HHID, LAT, LON, Crop, Trial, today...
    source_paths = models.JSONField(default=list, blank=True)
    transform = models.CharField(max_length=20, choices=Transform.choices, default=Transform.DIRECT)
    transform_args = models.JSONField(default=dict, blank=True)
    required = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["form", "order", "target_field"]

    def __str__(self) -> str:
        return f"{self.form} -> {self.target_field}"


class EventScheduleItem(BaseModel):
    """One event in a use case's timeline. Replaces the hardcoded day offsets in
    support_fun.R dynamic_colorcodeS (Event1 = SiteSelection+14, Event2=+29, ...,
    potato +57 / rice +64, etc.). Drives the green/amber/red/purple status."""

    class Anchor(models.TextChoices):
        SITE_SELECTION = "SITE_SELECTION", "Site selection date"
        EVENT1 = "EVENT1", "Event 1 date"
        PREV_EVENT = "PREV_EVENT", "Previous event date"

    use_case = models.ForeignKey(UseCase, on_delete=models.CASCADE, related_name="schedule")
    event_key = models.CharField(max_length=32)  # "Event1", "Event1R", "Event2"...
    sequence = models.IntegerField()  # ordering; drives out-of-sequence checks
    anchor = models.CharField(max_length=20, choices=Anchor.choices, default=Anchor.EVENT1)
    offset_days = models.IntegerField(default=0)
    # Per-crop offset overrides, e.g. {"potato": 57, "rice": 64}.
    crop_overrides = models.JSONField(default=dict, blank=True)
    grace_days = models.PositiveIntegerField(default=0)  # window before "overdue"

    class Meta:
        unique_together = ("use_case", "event_key")
        ordering = ["use_case", "sequence"]

    def __str__(self) -> str:
        return f"{self.use_case.code}:{self.event_key}(+{self.offset_days})"

    def target_offset_for_crop(self, crop_name: str | None) -> int:
        """Resolve the offset for a crop, honouring crop_overrides."""
        if crop_name and crop_name in self.crop_overrides:
            return int(self.crop_overrides[crop_name])
        return self.offset_days
