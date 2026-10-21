import json
from django.core.management.base import BaseCommand
from apps.common.models import TranslationKey, TranslationValue, TranslationVersion
from apps.common.views import SUPPORTED_LANGUAGES


class Command(BaseCommand):
    help = "Validate translation completeness, identify missing translations, and audit translation health."

    def add_arguments(self, parser):
        parser.add_argument(
            "--lang",
            type=str,
            default="",
            help="Validate a specific language code (e.g. 'am', 'en')",
        )
        parser.add_argument(
            "--fail-on-missing",
            action="store_true",
            help="Exit with non-zero status code if any translation is missing or unpublished.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Output report in JSON format.",
        )

    def handle(self, *args, **options):
        target_lang = options["lang"].strip().lower()
        fail_on_missing = options["fail_on_missing"]
        output_json = options["json"]

        all_keys = list(TranslationKey.objects.all().order_by("category", "key"))
        total_keys = len(all_keys)

        supported_codes = [l["code"] for l in SUPPORTED_LANGUAGES]
        if target_lang:
            if target_lang not in supported_codes:
                self.stderr.write(self.style.ERROR(f"Unsupported language code '{target_lang}'. Supported: {supported_codes}"))
                return
            languages_to_check = [target_lang]
        else:
            languages_to_check = supported_codes

        report = {
            "total_keys": total_keys,
            "languages": {},
            "has_missing": False,
        }

        for lang in languages_to_check:
            values_qs = TranslationValue.objects.filter(language=lang)
            value_map = {tv.key_id: tv for tv in values_qs}

            missing_keys = []
            unpublished_keys = []
            empty_keys = []
            published_count = 0

            for tk in all_keys:
                tv = value_map.get(tk.id)
                if not tv:
                    missing_keys.append(tk.key)
                elif not tv.value or not tv.value.strip():
                    empty_keys.append(tk.key)
                elif tv.status != TranslationValue.Status.PUBLISHED:
                    unpublished_keys.append({"key": tk.key, "status": tv.status})
                else:
                    published_count += 1

            coverage_pct = round((published_count / total_keys * 100), 2) if total_keys > 0 else 0.0
            version = TranslationVersion.get_version(lang)

            if missing_keys or unpublished_keys or empty_keys:
                report["has_missing"] = True

            report["languages"][lang] = {
                "version": version,
                "published_count": published_count,
                "missing_count": len(missing_keys),
                "unpublished_count": len(unpublished_keys),
                "empty_count": len(empty_keys),
                "coverage_pct": coverage_pct,
                "missing_keys": missing_keys,
                "unpublished_keys": unpublished_keys,
                "empty_keys": empty_keys,
            }

        if output_json:
            self.stdout.write(json.dumps(report, indent=2))
            if fail_on_missing and report["has_missing"]:
                raise SystemExit(1)
            return

        self.stdout.write(self.style.MIGRATE_HEADING(f"=== Translation Health & Completeness Audit ==="))
        self.stdout.write(f"Total Translation Keys in Database: {total_keys}\n")

        for lang, data in report["languages"].items():
            lang_label = lang.upper()
            self.stdout.write(
                f"[{lang_label}] Version: v{data['version']} | Published: {data['published_count']}/{total_keys} ({data['coverage_pct']}%)"
            )

            if data["missing_keys"]:
                self.stdout.write(self.style.WARNING(f"  Missing ({len(data['missing_keys'])}): {', '.join(data['missing_keys'][:10])}"))
            if data["unpublished_keys"]:
                self.stdout.write(self.style.WARNING(f"  Unpublished / Drafts: {len(data['unpublished_keys'])}"))
            if data["empty_keys"]:
                self.stdout.write(self.style.ERROR(f"  Empty values: {len(data['empty_keys'])}"))

            if not data["missing_keys"] and not data["unpublished_keys"] and not data["empty_keys"]:
                self.stdout.write(self.style.SUCCESS(f"  Status: 100% COMPLETE & PUBLISHED"))
            self.stdout.write("")

        if fail_on_missing and report["has_missing"]:
            self.stderr.write(self.style.ERROR("Audit failed: Incomplete translations detected."))
            raise SystemExit(1)
