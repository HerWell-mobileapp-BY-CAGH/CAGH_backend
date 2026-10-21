import json
from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings
from apps.common.models import TranslationKey, TranslationValue, TranslationVersion


class Command(BaseCommand):
    help = "Populate or sync initial translation keys and values from Flutter ARB files into the database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--arb-dir",
            type=str,
            default="",
            help="Path to directory containing app_en.arb and app_am.arb",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Overwrite existing translation values in the database",
        )

    def handle(self, *args, **options):
        arb_dir_arg = options["arb_dir"]
        overwrite = options["overwrite"]

        if arb_dir_arg:
            arb_dir = Path(arb_dir_arg)
        else:
            # Default to adjacent frontend repository
            arb_dir = settings.BASE_DIR.parent / "cagh_frontend" / "lib" / "l10n"

        en_path = arb_dir / "app_en.arb"
        am_path = arb_dir / "app_am.arb"

        if not en_path.exists():
            self.stderr.write(self.style.ERROR(f"English ARB file not found at: {en_path}"))
            return

        with open(en_path, "r", encoding="utf-8") as f:
            en_data = json.load(f)

        am_data = {}
        if am_path.exists():
            with open(am_path, "r", encoding="utf-8") as f:
                am_data = json.load(f)

        keys_created = 0
        translations_created = 0
        translations_updated = 0

        for key, en_text in en_data.items():
            if key.startswith("@"):
                continue  # Skip metadata
            if not isinstance(en_text, str):
                continue

            # Infer logical category from key name prefix or module convention
            category = "general"
            for prefix in ("val", "auth", "login", "register", "home", "chat", "consult", "midwife", "profile", "appointment", "review"):
                if key.lower().startswith(prefix):
                    category = prefix
                    break

            tk, created = TranslationKey.objects.get_or_create(
                key=key,
                defaults={"default_text": en_text, "category": category},
            )
            if created:
                keys_created += 1
            elif overwrite:
                tk.default_text = en_text
                tk.save()

            # Process English translation value
            en_clean = en_text.strip()
            if en_clean:
                en_tv, en_created = TranslationValue.objects.get_or_create(
                    key=tk,
                    language="en",
                    defaults={
                        "value": en_clean,
                        "status": TranslationValue.Status.PUBLISHED,
                    },
                )
                if en_created:
                    translations_created += 1
                elif overwrite:
                    en_tv.value = en_clean
                    en_tv.status = TranslationValue.Status.PUBLISHED
                    en_tv.save()
                    translations_updated += 1

            # Process Amharic translation
            if key in am_data and isinstance(am_data[key], str):
                am_text = am_data[key].strip()
                if am_text:
                    tv, v_created = TranslationValue.objects.get_or_create(
                        key=tk,
                        language="am",
                        defaults={
                            "value": am_text,
                            "status": TranslationValue.Status.PUBLISHED,
                        },
                    )
                    if v_created:
                        translations_created += 1
                    elif overwrite:
                        tv.value = am_text
                        tv.status = TranslationValue.Status.PUBLISHED
                        tv.save()
                        translations_updated += 1

        # Additional default keys for newly created screens
        additional_screen_keys = {
            "pendingRequests": ("Pending Requests", "የሚጠባበቁ ጥያቄዎች", "home"),
            "topicCategory": ("Topic Category", "የይዘት ምድብ", "home"),
            "browseAllGuides": ("Browse All Published Guides", "ሁሉንም የታተሙ መመሪያዎች ይመልከቱ", "home"),
            "openFullLearningCenter": ("Open Full Learning & Protocols Center", "ሙሉውን የመማሪያ እና የፕሮቶኮሎች ማዕከል ይክፈቱ", "home"),
            "bookVisit": ("Book Visit", "ቀጠሮ ይያዙ", "consult"),
            "ethiopianCalendar": ("Ethiopian Calendar", "የኢትዮጵያ ዘመን አቆጣጠር", "calendar"),
            "monthMeskerem": ("Meskerem", "መስከረም", "calendar"),
            "monthTikimt": ("Tikimt", "ጥቅምት", "calendar"),
            "monthHidar": ("Hidar", "ኅዳር", "calendar"),
            "monthTahsas": ("Tahsas", "ታኅሣሥ", "calendar"),
            "monthTir": ("Tir", "ጥር", "calendar"),
            "monthYakatit": ("Yakatit", "የካቲት", "calendar"),
            "monthMegabit": ("Megabit", "መጋቢት", "calendar"),
            "monthMiazia": ("Miazia", "ሚያዝያ", "calendar"),
            "monthGinbot": ("Ginbot", "ግንቦት", "calendar"),
            "monthSene": ("Sene", "ሰኔ", "calendar"),
            "monthHamle": ("Hamle", "ሐምሌ", "calendar"),
            "monthNehase": ("Nehase", "ነሐሴ", "calendar"),
            "monthPagume": ("Pagume", "ጳጉሜ", "calendar"),
            "dayEhud": ("Sun", "እሑድ", "calendar"),
            "daySegno": ("Mon", "ሰኞ", "calendar"),
            "dayMaksegno": ("Tue", "ማክሰኞ", "calendar"),
            "dayErob": ("Wed", "ረቡዕ", "calendar"),
            "dayHamus": ("Thu", "ሐሙስ", "calendar"),
            "dayArb": ("Fri", "ዓርብ", "calendar"),
            "dayKidame": ("Sat", "ቅዳሜ", "calendar"),
        }

        for extra_key, (extra_en, extra_am, extra_cat) in additional_screen_keys.items():
            tk, created = TranslationKey.objects.get_or_create(
                key=extra_key,
                defaults={"default_text": extra_en, "category": extra_cat},
            )
            if created:
                keys_created += 1

            for lang_code, text_val in [("en", extra_en), ("am", extra_am)]:
                val_obj, val_created = TranslationValue.objects.get_or_create(
                    key=tk,
                    language=lang_code,
                    defaults={
                        "value": text_val,
                        "status": TranslationValue.Status.PUBLISHED,
                    },
                )
                if val_created:
                    translations_created += 1
                elif overwrite:
                    val_obj.value = text_val
                    val_obj.status = TranslationValue.Status.PUBLISHED
                    val_obj.save()
                    translations_updated += 1

        TranslationVersion.bump("am")
        TranslationVersion.bump("en")

        self.stdout.write(
            self.style.SUCCESS(
                f"Sync complete! Created {keys_created} keys, {translations_created} translations created/updated."
            )
        )
