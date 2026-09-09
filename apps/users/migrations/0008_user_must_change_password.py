# Generated for temporary passwords issued by administrator provisioning.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("users", "0007_alter_user_managers")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="must_change_password",
            field=models.BooleanField(default=False),
        ),
    ]
