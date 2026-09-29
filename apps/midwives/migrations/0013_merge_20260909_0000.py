# Generated to join the two previously independent midwife migration branches.
# It has no database operations because each branch changes different fields.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("midwives", "0010_alter_midwifeprofile_license_number"),
        ("midwives", "0012_alter_is_accepting_bookings_default"),
    ]

    operations = []
