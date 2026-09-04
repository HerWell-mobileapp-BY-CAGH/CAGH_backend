from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('midwives', '0010_add_rejection_reason'),
    ]

    operations = [
        migrations.AddField(
            model_name='midwifeprofile',
            name='suspension_reason',
            field=models.TextField(
                blank=True,
                default='',
                help_text='Admin-provided reason when an approved midwife account is suspended.',
            ),
        ),
    ]
