import uuid
from decimal import Decimal
import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ---------------------------------------------------------------
        # Account (Chart of Accounts)
        # ---------------------------------------------------------------
        migrations.CreateModel(
            name="Account",
            fields=[
                ("tenant_id", models.UUIDField(default=uuid.uuid4, db_index=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("code", models.CharField(db_index=True, max_length=20)),
                ("name", models.CharField(max_length=255)),
                ("account_type", models.CharField(
                    choices=[
                        ("ASSET", "Asset"),
                        ("LIABILITY", "Liability"),
                        ("EQUITY", "Equity"),
                        ("INCOME", "Income"),
                        ("EXPENSE", "Expense"),
                    ],
                    max_length=20,
                )),
                ("account_category", models.CharField(
                    choices=[
                        ("CURRENT_ASSET", "Current Asset"),
                        ("FIXED_ASSET", "Fixed Asset"),
                        ("CURRENT_LIABILITY", "Current Liability"),
                        ("LONG_TERM_LIABILITY", "Long-term Liability"),
                        ("EQUITY", "Equity"),
                        ("OPERATING_INCOME", "Operating Income"),
                        ("OTHER_INCOME", "Other Income"),
                        ("OPERATING_EXPENSE", "Operating Expense"),
                        ("OTHER_EXPENSE", "Other Expense"),
                    ],
                    max_length=30,
                )),
                ("description", models.TextField(blank=True, default="")),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("parent", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="children",
                    to="finance.account",
                )),
            ],
            options={
                "db_table": "finance_accounts",
                "ordering": ["code"],
            },
        ),
        migrations.AddConstraint(
            model_name="account",
            constraint=models.UniqueConstraint(
                fields=["tenant_id", "code"],
                name="finance_account_tenant_code_uniq",
            ),
        ),

        # ---------------------------------------------------------------
        # JournalEntry
        # ---------------------------------------------------------------
        migrations.CreateModel(
            name="JournalEntry",
            fields=[
                ("tenant_id", models.UUIDField(default=uuid.uuid4, db_index=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("reference_number", models.CharField(db_index=True, max_length=50)),
                ("date", models.DateField()),
                ("description", models.TextField()),
                ("source", models.CharField(
                    choices=[
                        ("MANUAL", "Manual Entry"),
                        ("INVOICE", "Invoice Posting"),
                        ("PAYMENT", "Payment Received"),
                        ("EXPENSE", "Expense Payment"),
                        ("DEPRECIATION", "Depreciation"),
                        ("INSURANCE", "Insurance Premium"),
                        ("TAX", "Tax Payment"),
                        ("REVERSAL", "Reversal Entry"),
                    ],
                    default="MANUAL",
                    max_length=20,
                )),
                ("is_posted", models.BooleanField(default=False)),
                ("posted_at", models.DateTimeField(blank=True, null=True)),
                ("is_reversed", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("posted_by", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="journal_entries",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("reversal_of", models.OneToOneField(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="reversed_by",
                    to="finance.journalentry",
                )),
            ],
            options={
                "db_table": "finance_journal_entries",
                "ordering": ["-date", "-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="journalentry",
            constraint=models.UniqueConstraint(
                fields=["tenant_id", "reference_number"],
                name="finance_je_tenant_ref_uniq",
            ),
        ),

        # ---------------------------------------------------------------
        # JournalEntryLine
        # ---------------------------------------------------------------
        migrations.CreateModel(
            name="JournalEntryLine",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("description", models.TextField(blank=True, default="")),
                ("debit", models.DecimalField(
                    decimal_places=2,
                    default=Decimal("0.00"),
                    max_digits=18,
                    validators=[django.core.validators.MinValueValidator(Decimal("0.00"))],
                )),
                ("credit", models.DecimalField(
                    decimal_places=2,
                    default=Decimal("0.00"),
                    max_digits=18,
                    validators=[django.core.validators.MinValueValidator(Decimal("0.00"))],
                )),
                ("line_number", models.PositiveIntegerField()),
                ("account", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="journal_lines",
                    to="finance.account",
                )),
                ("journal_entry", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="lines",
                    to="finance.journalentry",
                )),
            ],
            options={
                "db_table": "finance_journal_entry_lines",
                "ordering": ["line_number"],
            },
        ),
        migrations.AddConstraint(
            model_name="journalentryline",
            constraint=models.UniqueConstraint(
                fields=["journal_entry", "line_number"],
                name="finance_jel_entry_line_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="journalentryline",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(debit__gt=0, credit=Decimal("0.00")) |
                    models.Q(credit__gt=0, debit=Decimal("0.00"))
                ),
                name="chk_line_debit_xor_credit",
            ),
        ),

        # ---------------------------------------------------------------
        # BalanceSnapshot
        # ---------------------------------------------------------------
        migrations.CreateModel(
            name="BalanceSnapshot",
            fields=[
                ("tenant_id", models.UUIDField(default=uuid.uuid4, db_index=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("year", models.PositiveIntegerField()),
                ("month", models.PositiveIntegerField()),
                ("closing_balance", models.DecimalField(
                    decimal_places=2,
                    default=Decimal("0.00"),
                    max_digits=18,
                )),
                ("computed_at", models.DateTimeField(auto_now=True)),
                ("account", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="snapshots",
                    to="finance.account",
                )),
            ],
            options={
                "db_table": "finance_balance_snapshots",
                "ordering": ["-year", "-month"],
            },
        ),
        migrations.AddConstraint(
            model_name="balancesnapshot",
            constraint=models.UniqueConstraint(
                fields=["tenant_id", "account", "year", "month"],
                name="finance_snap_tenant_acct_period_uniq",
            ),
        ),
    ]
