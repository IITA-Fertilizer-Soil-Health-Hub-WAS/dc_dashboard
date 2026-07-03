"""Export a use case's config from the database to YAML (stdout or file).

    python manage.py dump_usecase SNS-RWANDA
    python manage.py dump_usecase SNS-RWANDA --out config/usecases/sns-rwanda.yaml
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.config_admin.loader import dump_yaml
from apps.usecases.models import Project


class Command(BaseCommand):
    help = "Dump a use case's configuration to YAML."

    def add_arguments(self, parser):
        parser.add_argument("code", help="Use case code, e.g. SNS-RWANDA")
        parser.add_argument("--out", help="Write to this path instead of stdout")

    def handle(self, *args, **options):
        try:
            uc = Project.objects.get(code=options["code"])
        except Project.DoesNotExist as exc:
            raise CommandError(f"Unknown use case: {options['code']}") from exc

        text = dump_yaml(uc)
        if options["out"]:
            with open(options["out"], "w") as fh:
                fh.write(text)
            self.stdout.write(self.style.SUCCESS(f"Wrote {options['out']}"))
        else:
            self.stdout.write(text)
