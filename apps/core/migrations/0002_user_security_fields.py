import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        # Add MiddlewareTestModel (used in test_core.py)
        migrations.CreateModel(
            name="MiddlewareTestModel",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tenant_id", models.UUIDField(db_index=True, default=uuid.uuid4)),
                ("name", models.CharField(max_length=100)),
            ],
            options={
                "db_table": "core_middlewaretestmodel",
            },
        ),
        # Add Dummy model (used in test_tenant_isolation.py)
        migrations.CreateModel(
            name="Dummy",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tenant_id", models.UUIDField(db_index=True, default=uuid.uuid4)),
                ("name", models.CharField(max_length=100)),
            ],
            options={
                "db_table": "core_dummy",
            },
        ),
        # Add email verification field to User
        migrations.AddField(
            model_name="user",
            name="is_email_verified",
            field=models.BooleanField(default=False),
        ),
        # Add TOTP fields to User
        migrations.AddField(
            model_name="user",
            name="totp_secret",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="user",
            name="totp_enabled",
            field=models.BooleanField(default=False),
        ),
        # Add LoginAttempt model
        migrations.CreateModel(
            name="LoginAttempt",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("username", models.CharField(db_index=True, max_length=150)),
                ("ip_address", models.GenericIPAddressField(blank=True, db_index=True, null=True)),
                ("timestamp", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("success", models.BooleanField(default=False)),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="login_attempts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "login_attempts",
                "ordering": ["-timestamp"],
            },
        ),
    ]
