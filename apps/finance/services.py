"""
Core accounting services.

All business logic for the Chart of Accounts, Journal Entries,
and Account Balance computation lives here. Views are thin wrappers
that delegate to these service functions.
"""
import logging
from decimal import Decimal
from datetime import date
from typing import Optional

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import (
    Account,
    AccountType,
    AccountCategory,
    JournalEntry,
    JournalEntryLine,
    JournalEntrySource,
    BalanceSnapshot,
)

logger = logging.getLogger("amss.finance")


# ---------------------------------------------------------------------------
# Default Chart of Accounts — Nigerian SME
# ---------------------------------------------------------------------------

DEFAULT_ACCOUNTS = [
    # Assets (1xxx) — debit-normal
    ("1000", "Cash and Cash Equivalents",            AccountType.ASSET,     AccountCategory.CURRENT_ASSET),
    ("1100", "Accounts Receivable",                  AccountType.ASSET,     AccountCategory.CURRENT_ASSET),
    ("1200", "Inventory",                            AccountType.ASSET,     AccountCategory.CURRENT_ASSET),
    ("1300", "Prepaid Expenses",                     AccountType.ASSET,     AccountCategory.CURRENT_ASSET),
    ("1500", "Equipment",                            AccountType.ASSET,     AccountCategory.FIXED_ASSET),
    ("1510", "Accumulated Depreciation - Equipment", AccountType.ASSET,     AccountCategory.FIXED_ASSET),
    ("1600", "Motor Vehicles",                       AccountType.ASSET,     AccountCategory.FIXED_ASSET),
    ("1610", "Accumulated Depreciation - Vehicles",  AccountType.ASSET,     AccountCategory.FIXED_ASSET),
    ("1700", "Land and Buildings",                   AccountType.ASSET,     AccountCategory.FIXED_ASSET),
    ("1710", "Accumulated Depreciation - Buildings", AccountType.ASSET,     AccountCategory.FIXED_ASSET),
    # Liabilities (2xxx) — credit-normal
    ("2000", "Accounts Payable",                     AccountType.LIABILITY,  AccountCategory.CURRENT_LIABILITY),
    ("2100", "VAT Payable",                          AccountType.LIABILITY,  AccountCategory.CURRENT_LIABILITY),
    ("2200", "Withholding Tax Payable",              AccountType.LIABILITY,  AccountCategory.CURRENT_LIABILITY),
    ("2300", "PAYE Payable",                         AccountType.LIABILITY,  AccountCategory.CURRENT_LIABILITY),
    ("2400", "Short-term Loans",                     AccountType.LIABILITY,  AccountCategory.CURRENT_LIABILITY),
    ("2500", "Long-term Loans",                      AccountType.LIABILITY,  AccountCategory.LONG_TERM_LIABILITY),
    ("2600", "Accrued Liabilities",                  AccountType.LIABILITY,  AccountCategory.CURRENT_LIABILITY),
    # Equity (3xxx) — credit-normal
    ("3000", "Owner's Capital",                      AccountType.EQUITY,    AccountCategory.EQUITY),
    ("3100", "Retained Earnings",                    AccountType.EQUITY,    AccountCategory.EQUITY),
    ("3200", "Current Year Profit / Loss",           AccountType.EQUITY,    AccountCategory.EQUITY),
    # Income (4xxx) — credit-normal
    ("4000", "Sales Revenue",                        AccountType.INCOME,    AccountCategory.OPERATING_INCOME),
    ("4100", "Service Revenue",                      AccountType.INCOME,    AccountCategory.OPERATING_INCOME),
    ("4900", "Other Income",                         AccountType.INCOME,    AccountCategory.OTHER_INCOME),
    # Expenses (5xxx) — debit-normal
    ("5000", "Cost of Goods Sold",                   AccountType.EXPENSE,   AccountCategory.OPERATING_EXPENSE),
    ("5100", "Salaries and Wages",                   AccountType.EXPENSE,   AccountCategory.OPERATING_EXPENSE),
    ("5200", "Rent Expense",                         AccountType.EXPENSE,   AccountCategory.OPERATING_EXPENSE),
    ("5300", "Utilities Expense",                    AccountType.EXPENSE,   AccountCategory.OPERATING_EXPENSE),
    ("5400", "Insurance Expense",                    AccountType.EXPENSE,   AccountCategory.OPERATING_EXPENSE),
    ("5500", "Depreciation Expense",                 AccountType.EXPENSE,   AccountCategory.OPERATING_EXPENSE),
    ("5600", "Bank Charges",                         AccountType.EXPENSE,   AccountCategory.OPERATING_EXPENSE),
    ("5700", "Tax Expense",                          AccountType.EXPENSE,   AccountCategory.OPERATING_EXPENSE),
    ("5800", "Repairs and Maintenance",              AccountType.EXPENSE,   AccountCategory.OPERATING_EXPENSE),
    ("5900", "Miscellaneous Expense",                AccountType.EXPENSE,   AccountCategory.OTHER_EXPENSE),
]


def seed_chart_of_accounts(tenant_id) -> list:
    """
    Seed the default chart of accounts for a new Nigerian SME tenant.
    Safe to call multiple times — uses get_or_create.

    Returns:
        List of Account objects (created or existing).
    """
    result = []
    for code, name, acct_type, category in DEFAULT_ACCOUNTS:
        account, created = Account.objects.get_or_create(
            tenant_id=tenant_id,
            code=code,
            defaults={
                "name": name,
                "account_type": acct_type,
                "account_category": category,
            },
        )
        result.append(account)
    logger.info("Seeded %d accounts for tenant %s", len(result), tenant_id)
    return result


# ---------------------------------------------------------------------------
# Reference Number Generation
# ---------------------------------------------------------------------------

def _generate_reference_number(tenant_id, posting_date: date) -> str:
    """Generate a unique, sequential journal entry reference number."""
    prefix = f"JNL-{posting_date.year}{posting_date.month:02d}"
    count = JournalEntry.objects.filter(
        tenant_id=tenant_id,
        reference_number__startswith=prefix,
    ).count()
    return f"{prefix}-{count + 1:04d}"


# ---------------------------------------------------------------------------
# Balance Computation
# ---------------------------------------------------------------------------

def compute_account_balance(
    account: Account,
    as_of_date: Optional[date] = None,
    since_date: Optional[date] = None,
) -> Decimal:
    """
    Derive the natural balance of an account from posted journal lines.

    Normal balance convention:
    - Debit-normal (Assets, Expenses): balance = sum(debits) - sum(credits)
    - Credit-normal (Liabilities, Equity, Income): balance = sum(credits) - sum(debits)

    Args:
        account:     The account to compute a balance for.
        as_of_date:  Include only entries on or before this date.
        since_date:  Include only entries on or after this date.

    Returns:
        Natural balance as Decimal.
        Positive = balance on the normal side.
        Negative = contra balance (unusual, e.g. overdraft on a cash account).
    """
    qs = JournalEntryLine.objects.filter(
        account=account,
        journal_entry__is_posted=True,
        journal_entry__tenant_id=account.tenant_id,
    )
    if as_of_date:
        qs = qs.filter(journal_entry__date__lte=as_of_date)
    if since_date:
        qs = qs.filter(journal_entry__date__gte=since_date)

    totals = qs.aggregate(
        total_debits=Sum("debit", default=Decimal("0.00")),
        total_credits=Sum("credit", default=Decimal("0.00")),
    )
    total_debits = totals["total_debits"] or Decimal("0.00")
    total_credits = totals["total_credits"] or Decimal("0.00")

    if account.is_debit_normal:
        return total_debits - total_credits
    return total_credits - total_debits


def generate_trial_balance(tenant_id, as_of_date: Optional[date] = None) -> dict:
    """
    Generate a trial balance for the tenant as of a given date.

    Returns a dict with:
    - as_of_date
    - rows: list of account rows with debit_balance / credit_balance
    - total_debits, total_credits
    - is_balanced (should always be True for a correct ledger)
    """
    accounts = Account.objects.filter(
        tenant_id=tenant_id,
        is_active=True,
    ).order_by("code")

    rows = []
    total_debits = Decimal("0.00")
    total_credits = Decimal("0.00")

    for account in accounts:
        balance = compute_account_balance(account, as_of_date=as_of_date)
        if balance == Decimal("0.00"):
            continue

        if account.is_debit_normal:
            debit_col = balance if balance > 0 else Decimal("0.00")
            credit_col = abs(balance) if balance < 0 else Decimal("0.00")
        else:
            credit_col = balance if balance > 0 else Decimal("0.00")
            debit_col = abs(balance) if balance < 0 else Decimal("0.00")

        rows.append({
            "account_id": str(account.id),
            "code": account.code,
            "name": account.name,
            "account_type": account.account_type,
            "debit_balance": debit_col,
            "credit_balance": credit_col,
        })
        total_debits += debit_col
        total_credits += credit_col

    return {
        "as_of_date": (as_of_date or date.today()).isoformat(),
        "rows": rows,
        "total_debits": total_debits,
        "total_credits": total_credits,
        "is_balanced": total_debits == total_credits,
    }


# ---------------------------------------------------------------------------
# Journal Entry Operations
# ---------------------------------------------------------------------------

@transaction.atomic
def create_journal_entry(
    tenant_id,
    posting_date: date,
    description: str,
    lines: list,
    source: str = JournalEntrySource.MANUAL,
    posted_by=None,
    reference_number: Optional[str] = None,
) -> JournalEntry:
    """
    Create a draft journal entry with its lines.

    Lines must be balanced (total debits == total credits) and contain
    at least two entries. The entry is saved as draft (is_posted=False).
    Call post_journal_entry() to commit it to the ledger.

    Args:
        tenant_id:        Tenant UUID.
        posting_date:     Date of the transaction.
        description:      Narrative description.
        lines:            List of dicts: {account_id, debit, credit, description}.
        source:           JournalEntrySource value.
        posted_by:        User creating the entry.
        reference_number: Optional custom reference (auto-generated if omitted).

    Returns:
        JournalEntry in draft state.

    Raises:
        ValueError: If lines are unbalanced, fewer than 2, or all-zero.
        Account.DoesNotExist: If any account_id is invalid for this tenant.
    """
    if len(lines) < 2:
        raise ValueError("A journal entry must have at least two lines.")

    total_debits = sum(Decimal(str(line.get("debit", 0))) for line in lines)
    total_credits = sum(Decimal(str(line.get("credit", 0))) for line in lines)

    if total_debits != total_credits:
        raise ValueError(
            f"Journal entry is unbalanced: debits={total_debits}, credits={total_credits}. "
            "Total debits must equal total credits."
        )

    if total_debits == Decimal("0.00"):
        raise ValueError("Journal entry amounts cannot all be zero.")

    ref = reference_number or _generate_reference_number(tenant_id, posting_date)

    entry = JournalEntry.objects.create(
        tenant_id=tenant_id,
        reference_number=ref,
        date=posting_date,
        description=description,
        source=source,
        posted_by=posted_by,
        is_posted=False,
    )

    for i, line_data in enumerate(lines, start=1):
        account = Account.objects.get(
            id=line_data["account_id"],
            tenant_id=tenant_id,
            is_active=True,
        )
        JournalEntryLine.objects.create(
            journal_entry=entry,
            account=account,
            description=line_data.get("description", ""),
            debit=Decimal(str(line_data.get("debit", "0.00"))),
            credit=Decimal(str(line_data.get("credit", "0.00"))),
            line_number=i,
        )

    logger.info(
        "Created draft journal entry %s for tenant %s (amount: %s)",
        entry.reference_number, tenant_id, total_debits,
    )
    return entry


@transaction.atomic
def post_journal_entry(entry: JournalEntry, posted_by=None) -> JournalEntry:
    """
    Post a draft journal entry, making it immutable and part of the ledger.
    Publishes a JOURNAL_ENTRY_POSTED event after posting.

    Raises:
        ValueError: If already posted, unbalanced, or has fewer than 2 lines.
    """
    if entry.is_posted:
        raise ValueError(f"Journal entry {entry.reference_number} is already posted.")

    if entry.lines.count() < 2:
        raise ValueError("Cannot post a journal entry with fewer than 2 lines.")

    if not entry.is_balanced:
        raise ValueError(
            f"Cannot post unbalanced entry {entry.reference_number}: "
            f"debits={entry.total_debits}, credits={entry.total_credits}."
        )

    if posted_by:
        entry.posted_by = posted_by
    entry.is_posted = True
    entry.posted_at = timezone.now()
    entry.save(update_fields=["is_posted", "posted_at", "posted_by"])

    logger.info(
        "Posted journal entry %s for tenant %s",
        entry.reference_number, entry.tenant_id,
    )

    # Publish event — best-effort; a publish failure does NOT roll back posting
    try:
        from .events import publish_journal_entry_posted
        publish_journal_entry_posted(entry)
    except Exception as exc:
        logger.warning("Failed to publish JOURNAL_ENTRY_POSTED event: %s", exc)

    return entry


@transaction.atomic
def reverse_journal_entry(
    entry: JournalEntry,
    reversal_date: date,
    reversed_by=None,
) -> JournalEntry:
    """
    Create and immediately post a reversal of the given entry.

    The reversal swaps debits and credits on every line.
    The original entry is marked is_reversed=True.

    Returns:
        The newly posted reversal JournalEntry.

    Raises:
        ValueError: If the entry is not posted or has already been reversed.
    """
    if not entry.is_posted:
        raise ValueError("Only posted entries can be reversed.")

    if entry.is_reversed:
        raise ValueError(
            f"Journal entry {entry.reference_number} has already been reversed."
        )

    original_lines = list(entry.lines.all())
    reversal_lines = [
        {
            "account_id": str(line.account_id),
            "debit": str(line.credit),    # swap sides
            "credit": str(line.debit),    # swap sides
            "description": f"Reversal: {line.description}",
        }
        for line in original_lines
    ]

    reversal_ref = f"REV-{entry.reference_number}"
    reversal = create_journal_entry(
        tenant_id=entry.tenant_id,
        posting_date=reversal_date,
        description=f"Reversal of {entry.reference_number}: {entry.description}",
        lines=reversal_lines,
        source=JournalEntrySource.REVERSAL,
        posted_by=reversed_by,
        reference_number=reversal_ref,
    )
    reversal.reversal_of = entry
    reversal.save(update_fields=["reversal_of"])

    post_journal_entry(reversal, posted_by=reversed_by)

    entry.is_reversed = True
    entry.save(update_fields=["is_reversed"])

    logger.info(
        "Reversed journal entry %s → %s for tenant %s",
        entry.reference_number, reversal.reference_number, entry.tenant_id,
    )
    return reversal
