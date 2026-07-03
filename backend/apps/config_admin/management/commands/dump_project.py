"""Export a project's config from the database to YAML (stdout or file).

    python manage.py dump_project SNS-RWANDA
    python manage.py dump_project SNS-RWANDA --out config/projects/sns-rwanda.yaml
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.config_admin.loader import dump_yaml
from apps.projects.models import Project


class Command(BaseCommand):
    help = "Dump a project's configuration to YAML."

    def add_arguments(self, parser):
        parser.add_argument("code", help="Project code, e.g. SNS-RWANDA")
        parser.add_argument("--out", help="Write to this path instead of stdout")

    def handle(self, *args, **options):
        try:
            uc = Project.objects.get(code=options["code"])
        except Project.DoesNotExist as exc:
            raise CommandError(f"Unknown project: {options['code']}") from exc

        text = dump_yaml(uc)
        if options["out"]:
            with open(options["out"], "w") as fh:
                fh.write(text)
            self.stdout.write(self.style.SUCCESS(f"Wrote {options['out']}"))
        else:
            self.stdout.write(text)
