# Generated manually — adds organization and contact_number to AccessRequest;
# also removes blank=True from message.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0005_accessrequest'),
    ]

    operations = [
        migrations.AddField(
            model_name='accessrequest',
            name='organization',
            field=models.CharField(default='', max_length=255, help_text="User's organisation"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='accessrequest',
            name='contact_number',
            field=models.CharField(default='', max_length=20, help_text='Contact phone number'),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='accessrequest',
            name='message',
            field=models.TextField(help_text='Why does the user need full-tier access?'),
        ),
    ]
