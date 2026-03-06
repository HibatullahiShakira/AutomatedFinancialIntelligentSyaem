import uuid
from decimal import Decimal
from django.db import models
from django.core.validators import MinValueValidator
from apps.core.models import TenantAwareModel


class AccountType(models.TextChoices):
    ASSET = "ASSET", "Asset"
    LIABILITY = "LIABILITY", "Liability"
    EQUITY = "EQUITY", "Equity"
    INCOME = "INCOME", "Income"
    EXPENSE = "EXPENSE", "Expense"


class AccountCategory(models.TextChoices):
    CURRENT_ASSET = "CURRENT_ASSET", "Current Asset"
    FIXED_ASSET = "FIXED_ASSET", "Fixed Asset"
    CURRENT_LIABILITY = "CURRENT_LIABILITY", "Current Liability"
    LONG_TERM_LIABILITY = "LONG_TERM_LIABILITY", "Long-term Liability"
    EQUITY = "EQUITY", "Equity"
    OPERATING_INCOME = "OPERATING_INCOME", "Operating Income"
    OTHER_INCOME = "OTHER_INCOME", "Other Income"
    OPERATING_EXPENSE = "OPERATING_EXPENSE", "Operating Expense"
    OTHER_EXPENSE = "OTHER_EXPENSE", "Other Expense"


class Account(TenantAwareModel):
    """
    Chart of accounts entry. The vocabulary of all financial transactions.

    Code numbering scheme (enforced by convention, not DB constraint):
        1xxx = Assets
        2xxx = Liabilities
        3xxx = Equity
        4xxx = Income
        5xxx = Expenses

    Accounts can be deactivated but never deleted if they have posted journal entries.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=20, db_index=True)
    name = models.CharField(max_length=255)
    account_type = models.CharField(max_length=20, choices=AccountType.choices)
    account_category = models.CharField(max_length=30, choices=AccountCategory.choices)
    description = models.TextField(blank=True, default="")
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "finance_accounts"
        unique_together = [["tenant_id", "code"]]
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} - {self.name}"

    @property
    def is_debit_normal(self):
        """Assets and Expenses increase with debits (debit-normal accounts)."""
        return self.account_type in (AccountType.ASSET, AccountType.EXPENSE)


class JournalEntrySource(models.TextChoices):
    MANUAL = "MANUAL", "Manual Entry"
    INVOICE = "INVOICE", "Invoice Posting"
    PAYMENT = "PAYMENT", "Payment Received"
    EXPENSE = "EXPENSE", "Expense Payment"
    DEPRECIATION = "DEPRECIATION", "Depreciation"
    INSURANCE = "INSURANCE", "Insurance Premium"
    TAX = "TAX", "Tax Payment"
    REVERSAL = "REVERSAL", "Reversal Entry"


class JournalEntry(TenantAwareModel):
    """
    Double-entry journal entry header. Once posted, it is immutable.
    Errors are corrected by reversal entries — never by editing or deletion.

    Rules:
    - Must have at least 2 lines
    - Total debits must equal total credits
    - Cannot be edited once posted
    - Can only be corrected via a reversal entry
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference_number = models.CharField(max_length=50, db_index=True)
    date = models.DateField()
    description = models.TextField()
    source = models.CharField(
        max_length=20,
        choices=JournalEntrySource.choices,
        default=JournalEntrySource.MANUAL,
    )
    posted_by = models.ForeignKey(
        "core.User",
        on_delete=models.PROTECT,
        related_name="journal_entries",
        null=True,
        blank=True,
    )
    is_posted = models.BooleanField(default=False)
    posted_at = models.DateTimeField(null=True, blank=True)
    is_reversed = models.BooleanField(default=False)
    reversal_of = models.OneToOneField(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reversed_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "finance_journal_entries"
        unique_together = [["tenant_id", "reference_number"]]
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.reference_number}: {self.description[:60]}"

    @property
    def total_debits(self):
        return self.lines.aggregate(
            total=models.Sum("debit", default=Decimal("0.00"))
        )["total"]

    @property
    def total_credits(self):
        return self.lines.aggregate(
            total=models.Sum("credit", default=Decimal("0.00"))
        )["total"]

    @property
    def is_balanced(self):
        return self.total_debits == self.total_credits


class JournalEntryLine(models.Model):
    """
    Individual debit or credit line within a journal entry.

    Each line has either a debit OR a credit amount (not both).
    Lines are immutable once the parent entry is posted.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="journal_lines",
    )
    description = models.TextField(blank=True, default="")
    debit = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    credit = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    line_number = models.PositiveIntegerField()

    class Meta:
        db_table = "finance_journal_entry_lines"
        ordering = ["line_number"]
        unique_together = [["journal_entry", "line_number"]]
        constraints = [
            # Each line must carry exactly one side: debit XOR credit > 0
            models.CheckConstraint(
                condition=(
                    models.Q(debit__gt=0, credit=Decimal("0.00")) |
                    models.Q(credit__gt=0, debit=Decimal("0.00"))
                ),
                name="chk_line_debit_xor_credit",
            )
        ]

    def __str__(self):
        side = f"DR {self.debit}" if self.debit else f"CR {self.credit}"
        return f"Line {self.line_number}: {self.account} {side}"


class BalanceSnapshot(TenantAwareModel):
    """
    Monthly closing balance snapshot per account.

    Performance optimisation: instead of replaying all history on every balance
    query, queries only replay entries since the last snapshot.
    Snapshots are computed by a scheduled job at month-end.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name="snapshots",
    )
    year = models.PositiveIntegerField()
    month = models.PositiveIntegerField()
    # Natural balance: positive = account's normal side has a balance
    closing_balance = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "finance_balance_snapshots"
        unique_together = [["tenant_id", "account", "year", "month"]]
        ordering = ["-year", "-month"]

    def __str__(self):
        return f"{self.account.code} @ {self.year}/{self.month:02d}: {self.closing_balance}"
