# Generated manually for AccessRequest model

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('discharge_prediction', '0023_remove_google_sheets_fields'),
        ('users', '0004_account_tier'),
    ]

    operations = [
        migrations.CreateModel(
            name='AccessRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('message', models.TextField(blank=True, help_text='Why does the user need full-tier access?')),
                ('status', models.CharField(
                    choices=[('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')],
                    default='pending',
                    max_length=10,
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('reviewed_at', models.DateTimeField(null=True, blank=True)),
                ('admin_note', models.TextField(blank=True, help_text='Internal note visible only to admins.')),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='access_requests',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('station', models.ForeignKey(
                    blank=True,
                    help_text='Station the user is interested in (optional).',
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to='discharge_prediction.dischargestation',
                )),
                ('reviewed_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='reviewed_access_requests',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Access Request',
                'verbose_name_plural': 'Access Requests',
                'ordering': ['-created_at'],
            },
        ),
    ]
