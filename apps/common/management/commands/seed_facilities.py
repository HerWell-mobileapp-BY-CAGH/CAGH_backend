from django.core.management.base import BaseCommand
from apps.common.models import Facility


class Command(BaseCommand):
    help = "Seed accurate and detailed healthcare facilities in Ethiopia (Addis Ababa area)"

    def handle(self, *args, **kwargs):
        self.stdout.write("Seeding accurate Ethiopian healthcare facilities data...")

        facilities_data = [
            {
                "name": "Tikur Anbessa (Black Lion) Specialized Hospital",
                "facility_type": "HOSPITAL",
                "address": "Zambia St, Lideta Sub-City",
                "city": "Addis Ababa",
                "region": "Addis Ababa",
                "phone_number": "+251115511211",
                "operating_hours": "24/7 Emergency & Inpatient Care",
                "available_services": [
                    "Maternal & Fetal Medicine",
                    "High-Risk Pregnancy Unit",
                    "Obstetrics & Gynecology",
                    "Emergency Care",
                    "Pediatric Surgery",
                    "ICU & NICU",
                ],
                "latitude": 9.015100,
                "longitude": 38.751200,
                "rating_average": 4.50,
                "is_active": True,
            },
            {
                "name": "St. Paul's Hospital Millennium Medical College",
                "facility_type": "HOSPITAL",
                "address": "Swaziland St, Gulele Sub-City",
                "city": "Addis Ababa",
                "region": "Addis Ababa",
                "phone_number": "+251112750125",
                "operating_hours": "24/7 Emergency",
                "available_services": [
                    "Maternal Health & ANC",
                    "Delivery & Childbirth",
                    "Neonatal Intensive Care (NICU)",
                    "Reproductive Surgery",
                    "Emergency Medicine",
                ],
                "latitude": 9.055800,
                "longitude": 38.727500,
                "rating_average": 4.60,
                "is_active": True,
            },
            {
                "name": "Gandhi Memorial Hospital",
                "facility_type": "HOSPITAL",
                "address": "Ras Desta Damtew St, Kirkos Sub-City (Near Stadium)",
                "city": "Addis Ababa",
                "region": "Addis Ababa",
                "phone_number": "+251115518225",
                "operating_hours": "24/7 Maternity & Neonatal Emergency",
                "available_services": [
                    "Specialized Maternity Care",
                    "Obstetrics & Delivery",
                    "Gynecology",
                    "Postnatal Care (PNC)",
                    "Family Planning & ANC",
                ],
                "latitude": 9.011200,
                "longitude": 38.754800,
                "rating_average": 4.40,
                "is_active": True,
            },
            {
                "name": "Zewditu Memorial Hospital",
                "facility_type": "HOSPITAL",
                "address": "Dejazmach Belay Zeleke St, Kirkos Sub-City",
                "city": "Addis Ababa",
                "region": "Addis Ababa",
                "phone_number": "+251115518085",
                "operating_hours": "24/7 Emergency",
                "available_services": [
                    "Antenatal Care (ANC)",
                    "Delivery & Obstetric Care",
                    "PMTCT & HIV Care",
                    "Pediatrics",
                    "Outpatient Clinics",
                ],
                "latitude": 9.014200,
                "longitude": 38.761800,
                "rating_average": 4.30,
                "is_active": True,
            },
            {
                "name": "Yekatit 12 Hospital Medical College",
                "facility_type": "HOSPITAL",
                "address": "Ethiopia St, Arada Sub-City (Sidist Kilo)",
                "city": "Addis Ababa",
                "region": "Addis Ababa",
                "phone_number": "+251111234344",
                "operating_hours": "24/7 Emergency",
                "available_services": [
                    "Maternal & Child Health",
                    "Plastic & Burn Reconstructive Surgery",
                    "General Surgery",
                    "Pediatric Care",
                    "Immunization",
                ],
                "latitude": 9.043500,
                "longitude": 38.762200,
                "rating_average": 4.20,
                "is_active": True,
            },
            {
                "name": "Bethzatha Maternal & Children Specialty Hospital",
                "facility_type": "HOSPITAL",
                "address": "Stadium Area, Kirkos Sub-City",
                "city": "Addis Ababa",
                "region": "Addis Ababa",
                "phone_number": "+251115514141",
                "operating_hours": "24/7 Emergency & Maternity",
                "available_services": [
                    "Private Maternity Wards",
                    "Ultrasound Diagnostics",
                    "Painless Delivery",
                    "Comprehensive ANC/PNC",
                    "Pediatrics",
                ],
                "latitude": 9.012500,
                "longitude": 38.753800,
                "rating_average": 4.70,
                "is_active": True,
            },
            {
                "name": "MCM Comprehensive Specialized Hospital (Korean Hospital)",
                "facility_type": "HOSPITAL",
                "address": "Gerji, Bole Sub-City",
                "city": "Addis Ababa",
                "region": "Addis Ababa",
                "phone_number": "+251116292963",
                "operating_hours": "24/7 Emergency",
                "available_services": [
                    "Advanced Obstetric Care",
                    "Neonatal Intensive Care",
                    "3D/4D Ultrasound Diagnostics",
                    "Specialist Consultations",
                ],
                "latitude": 9.006500,
                "longitude": 38.802100,
                "rating_average": 4.70,
                "is_active": True,
            },
            {
                "name": "Teklehaimanot Health Center",
                "facility_type": "HEALTH_CENTER",
                "address": "Woreda 01, Addis Ketema Sub-City",
                "city": "Addis Ababa",
                "region": "Addis Ababa",
                "phone_number": "+251112753311",
                "operating_hours": "Mon-Fri: 8:00 AM - 5:30 PM, Sat: 8:00 AM - 12:30 PM",
                "available_services": [
                    "Routine ANC Checkups",
                    "Childhood Vaccination",
                    "Nutritional Counseling",
                    "Family Planning",
                    "Outpatient Care",
                ],
                "latitude": 9.028000,
                "longitude": 38.741000,
                "rating_average": 4.10,
                "is_active": True,
            },
            {
                "name": "Bole Bulbula Health Center",
                "facility_type": "HEALTH_CENTER",
                "address": "Woreda 12, Bole Sub-City",
                "city": "Addis Ababa",
                "region": "Addis Ababa",
                "phone_number": "+251116632200",
                "operating_hours": "Mon-Sat: 8:00 AM - 6:00 PM",
                "available_services": [
                    "Maternal Health Checkups",
                    "PMTCT Program",
                    "Family Planning",
                    "Basic Emergency Obstetric Care (BEmOC)",
                ],
                "latitude": 8.975000,
                "longitude": 38.778000,
                "rating_average": 4.00,
                "is_active": True,
            },
            {
                "name": "Lion Pharmacy (Piazza Branch)",
                "facility_type": "PHARMACY",
                "address": "Piazza, Arada Sub-City",
                "city": "Addis Ababa",
                "region": "Addis Ababa",
                "phone_number": "+251111223344",
                "operating_hours": "Mon-Sun: 8:00 AM - 10:00 PM",
                "available_services": [
                    "Maternal & Folic Acid Supplements",
                    "Prenatal Vitamins",
                    "Contraceptives & Family Planning",
                    "Prescription Dispensing",
                    "Medical Supplies",
                ],
                "latitude": 9.035000,
                "longitude": 38.752000,
                "rating_average": 4.70,
                "is_active": True,
            },
            {
                "name": "Kenema Pharmacy No. 1 (Mexico)",
                "facility_type": "PHARMACY",
                "address": "Mexico Square, Kirkos Sub-City",
                "city": "Addis Ababa",
                "region": "Addis Ababa",
                "phone_number": "+251115521199",
                "operating_hours": "24/7 Open",
                "available_services": [
                    "Essential Maternal Medicines",
                    "Iron & Calcium Supplements",
                    "Infant Formula & Baby Care",
                    "Emergency Prescriptions",
                ],
                "latitude": 9.010500,
                "longitude": 38.745500,
                "rating_average": 4.50,
                "is_active": True,
            },
            {
                "name": "International Clinical Laboratories (ICL)",
                "facility_type": "LABORATORY",
                "address": "Sarbet, Nifas Silk-Lafto Sub-City",
                "city": "Addis Ababa",
                "region": "Addis Ababa",
                "phone_number": "+251113723322",
                "operating_hours": "Mon-Sat: 7:30 AM - 7:30 PM",
                "available_services": [
                    "Prenatal Genetic Screening",
                    "Hormonal Assays (HCG, Progesterone)",
                    "Routine Blood & Urine Labs",
                    "Torch Panel Testing",
                ],
                "latitude": 9.001800,
                "longitude": 38.736200,
                "rating_average": 4.80,
                "is_active": True,
            },
        ]

        count = 0
        updated = 0
        for item in facilities_data:
            facility, created = Facility.objects.update_or_create(
                name=item["name"],
                defaults=item
            )
            if created:
                count += 1
            else:
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully seeded healthcare facilities! (New created: {count}, Updated: {updated}, Total in DB: {Facility.objects.count()})"
            )
        )
