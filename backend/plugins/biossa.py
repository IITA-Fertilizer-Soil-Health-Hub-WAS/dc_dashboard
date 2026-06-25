"""BioSSA plugin — the proving case for the optional Python hook.

In the R app, BioSSA was the worst offender: 4 crops (banana, cassava, legumes,
yam) x 2 seasons, each with deeply nested `repeat/group` measurement groups and
~200 lines of bespoke unnest/mutate/pivot per crop. That does not fit a flat
declarative field-mapping, so BioSSA opts into a plugin.

This plugin's `normalize` explodes one raw record whose nested `plots` repeat
contains several plots into one normalized row per plot — something the generic
engine cannot express declaratively. Everything else (ID patterns, schedule,
validation rules) still comes from the use case's YAML/DB config.

Enable by setting `plugin: plugins.biossa:BioSSAPlugin` in the use case config.
"""
from __future__ import annotations

from apps.common.plugins import BaseUseCasePlugin

# Key of the nested repeat group in the raw ONA record.
PLOTS_REPEAT_KEY = "group/plots"


class BioSSAPlugin(BaseUseCasePlugin):
    def normalize(self, form, raw_record: dict, mapped: dict) -> list[dict]:
        plots = raw_record.get(PLOTS_REPEAT_KEY)
        if not isinstance(plots, list) or not plots:
            # No nested repeat — behave like the generic engine.
            return [mapped]

        rows: list[dict] = []
        for plot in plots:
            row = dict(mapped)  # inherit the record-level mapped fields
            # Per-plot overrides explode the record into one row per plot.
            if "plot/HHID" in plot:
                row["HHID"] = plot["plot/HHID"]
            if "plot/crop" in plot:
                row["Crop"] = plot["plot/crop"]
            if "plot/event" in plot:
                row["event_key"] = plot["plot/event"]
            if "plot/date" in plot:
                row["today"] = plot["plot/date"]
            # Give each exploded row a distinct uuid so submissions don't collide.
            base_uuid = raw_record.get("_uuid", "")
            row["_explode_suffix"] = plot.get("plot/HHID", str(len(rows)))
            row["_uuid"] = f"{base_uuid}:{row['_explode_suffix']}"
            rows.append(row)
        return rows
