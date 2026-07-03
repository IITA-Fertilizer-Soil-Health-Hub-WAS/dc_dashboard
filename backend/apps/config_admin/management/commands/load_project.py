"""Import use-case config from YAML into the database.

    python manage.py load_project config/projects/sns-rwanda.yaml
    python manage.py load_project --all          # load every file in config/projects/
"""
from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.config_admin.loader import (
    ConfigError,
    import_config,
    load_yaml,
    validate_config,
)


class Command(BaseCommand):
    help = "Load use-case configuration from YAML file(s)."

    def add_arguments(self, parser):
        parser.add_argument("paths", nargs="*", help="YAML config file paths")
        parser.add_argument("--all", action="store_true", help="Load all files in PROJECT_CONFIG_DIR")
        parser.add_argument("--check", action="store_true", help="Validate only; do not write")

    def handle(self, *args, **options):
        paths: list[Path] = [Path(p) for p in options["paths"]]
        if options["all"]:
            paths += sorted(Path(settings.PROJECT_CONFIG_DIR).glob("*.y*ml"))
        if not paths:
            raise CommandError("Provide config file path(s) or --all")

        for path in paths:
            try:
                data = load_yaml(path)
                problems = validate_config(data)
                if problems:
                    for p in problems:
                        self.stderr.write(self.style.WARNING(f"  ! {path.name}: {p}"))
                if options["check"]:
                    if not problems:
                        self.stdout.write(self.style.SUCCESS(f"{path.name}: config OK"))
                    continue
                uc = import_config(data)
            except (ConfigError, FileNotFoundError) as exc:
                raise CommandError(f"{path}: {exc}") from exc
            self.stdout.write(self.style.SUCCESS(
                f"Loaded {uc.code} (v{uc.config_version}): "
                f"{uc.forms.count()} forms, {uc.schedule.count()} events, "
                f"{uc.rules.count()} rules"
            ))
