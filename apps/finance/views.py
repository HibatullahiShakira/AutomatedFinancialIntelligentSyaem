import logging
from datetime import date

from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from apps.core.models import UserTenant
from apps.core.permissions import require_accountant_or_owner, require_any_role, require_owner

from .models import Account, JournalEntry
from .serializers import (
    AccountSerializer,
    CreateJournalEntrySerializer,
    JournalEntrySerializer,
    ReverseJournalEntrySerializer,
)
from .services import (
    create_journal_entry,
    post_journal_entry,
    reverse_journal_entry,
    generate_trial_balance,
    seed_chart_of_accounts,
    compute_account_balance,
)

logger = logging.getLogger("amss.finance")


def _get_user_role(request) -> str | None:
    """Fetch the current user's role within the request tenant."""
    try:
        return UserTenant.objects.get(
            user=request.user,
            tenant_id=request.tenant_id,
            is_active=True,
        ).role
    except UserTenant.DoesNotExist:
        return None


# ---------------------------------------------------------------------------
# Chart of Accounts
# ---------------------------------------------------------------------------

@api_view(["GET", "POST"])
@require_any_role
def account_list(request):
    """
    GET  — List all active accounts for the tenant. Any authenticated role.
    POST — Create a new account. OWNER or ACCOUNTANT only.
    """
    tenant_id = request.tenant_id

    if request.method == "GET":
        accounts = Account.objects.filter(tenant_id=tenant_id)
        account_type = request.query_params.get("account_type")
        if account_type:
            accounts = accounts.filter(account_type=account_type)
        is_active = request.query_params.get("is_active")
        if is_active is not None:
            accounts = accounts.filter(is_active=is_active.lower() == "true")
        return Response(AccountSerializer(accounts, many=True).data)

    # POST
    role = _get_user_role(request)
    if role not in ("OWNER", "ACCOUNTANT"):
        return Response(
            {"error": "Insufficient permissions. Required role(s): OWNER, ACCOUNTANT"},
            status=status.HTTP_403_FORBIDDEN,
        )

    serializer = AccountSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # Enforce tenant scoping — tenant_id comes from the JWT, not the request body
    account = serializer.save(tenant_id=tenant_id)
    return Response(AccountSerializer(account).data, status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH"])
@require_any_role
def account_detail(request, account_id):
    """
    GET   — Retrieve a single account with its current balance.
    PATCH — Update account fields. OWNER or ACCOUNTANT only.
            Cannot deactivate an account that has posted journal entries.
    """
    tenant_id = request.tenant_id
    account = get_object_or_404(Account, id=account_id, tenant_id=tenant_id)

    if request.method == "GET":
        return Response(AccountSerializer(account).data)

    # PATCH
    role = _get_user_role(request)
    if role not in ("OWNER", "ACCOUNTANT"):
        return Response(
            {"error": "Insufficient permissions. Required role(s): OWNER, ACCOUNTANT"},
            status=status.HTTP_403_FORBIDDEN,
        )

    # Guard: cannot deactivate accounts with posted history
    if request.data.get("is_active") is False or request.data.get("is_active") == "false":
        if account.journal_lines.filter(journal_entry__is_posted=True).exists():
            return Response(
                {"error": "Cannot deactivate an account that has posted journal entries."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    serializer = AccountSerializer(account, data=request.data, partial=True)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    serializer.save()
    return Response(serializer.data)


@api_view(["GET"])
@require_any_role
def account_balance_view(request, account_id):
    """
    Return the current balance of a single account.
    Optional query param: ?as_of=YYYY-MM-DD
    """
    tenant_id = request.tenant_id
    account = get_object_or_404(Account, id=account_id, tenant_id=tenant_id)

    as_of_str = request.query_params.get("as_of")
    as_of = None
    if as_of_str:
        try:
            as_of = date.fromisoformat(as_of_str)
        except ValueError:
            return Response(
                {"error": "Invalid date format. Use YYYY-MM-DD."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    balance = compute_account_balance(account, as_of_date=as_of)
    return Response({
        "account_id": str(account.id),
        "code": account.code,
        "name": account.name,
        "account_type": account.account_type,
        "balance": str(balance),
        "as_of_date": (as_of or date.today()).isoformat(),
    })


@api_view(["POST"])
@require_owner
def seed_accounts_view(request):
    """
    Seed the default Nigerian SME chart of accounts for this tenant.
    OWNER only. Safe to call multiple times (idempotent).
    """
    accounts = seed_chart_of_accounts(request.tenant_id)
    return Response(
        {"seeded": len(accounts), "message": "Default chart of accounts applied."},
        status=status.HTTP_200_OK,
    )


# ---------------------------------------------------------------------------
# Journal Entries
# ---------------------------------------------------------------------------

@api_view(["GET", "POST"])
@require_any_role
def journal_entry_list(request):
    """
    GET  — List journal entries. Optional filters: ?source=&is_posted=&date_from=&date_to=
    POST — Create a draft journal entry. OWNER or ACCOUNTANT only.
    """
    tenant_id = request.tenant_id

    if request.method == "GET":
        qs = JournalEntry.objects.filter(tenant_id=tenant_id).prefetch_related(
            "lines__account"
        )
        source = request.query_params.get("source")
        if source:
            qs = qs.filter(source=source)
        is_posted = request.query_params.get("is_posted")
        if is_posted is not None:
            qs = qs.filter(is_posted=is_posted.lower() == "true")
        date_from = request.query_params.get("date_from")
        if date_from:
            qs = qs.filter(date__gte=date_from)
        date_to = request.query_params.get("date_to")
        if date_to:
            qs = qs.filter(date__lte=date_to)
        return Response(JournalEntrySerializer(qs, many=True).data)

    # POST
    role = _get_user_role(request)
    if role not in ("OWNER", "ACCOUNTANT"):
        return Response(
            {"error": "Insufficient permissions. Required role(s): OWNER, ACCOUNTANT"},
            status=status.HTTP_403_FORBIDDEN,
        )

    serializer = CreateJournalEntrySerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data
    try:
        entry = create_journal_entry(
            tenant_id=tenant_id,
            posting_date=data["date"],
            description=data["description"],
            lines=[dict(line) for line in data["lines"]],
            source=data.get("source", "MANUAL"),
            posted_by=request.user,
        )
    except (ValueError, Account.DoesNotExist) as exc:
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    entry.refresh_from_db()
    return Response(
        JournalEntrySerializer(entry).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET"])
@require_any_role
def journal_entry_detail(request, entry_id):
    """Retrieve a single journal entry with all its lines."""
    entry = get_object_or_404(
        JournalEntry.objects.prefetch_related("lines__account"),
        id=entry_id,
        tenant_id=request.tenant_id,
    )
    return Response(JournalEntrySerializer(entry).data)


@api_view(["POST"])
@require_accountant_or_owner
def post_entry_view(request, entry_id):
    """
    Post a draft journal entry, making it part of the ledger.
    Once posted an entry is immutable — use the reverse endpoint to correct it.
    """
    entry = get_object_or_404(JournalEntry, id=entry_id, tenant_id=request.tenant_id)
    try:
        entry = post_journal_entry(entry, posted_by=request.user)
    except ValueError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    entry.refresh_from_db()
    return Response(JournalEntrySerializer(entry).data)


@api_view(["POST"])
@require_accountant_or_owner
def reverse_entry_view(request, entry_id):
    """
    Create and post a reversal of the given journal entry.
    Requires body: { "reversal_date": "YYYY-MM-DD" }
    Returns the new reversal entry.
    """
    entry = get_object_or_404(JournalEntry, id=entry_id, tenant_id=request.tenant_id)

    serializer = ReverseJournalEntrySerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    try:
        reversal = reverse_journal_entry(
            entry,
            reversal_date=serializer.validated_data["reversal_date"],
            reversed_by=request.user,
        )
    except ValueError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    reversal.refresh_from_db()
    return Response(JournalEntrySerializer(reversal).data, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# Trial Balance
# ---------------------------------------------------------------------------

@api_view(["GET"])
@require_any_role
def trial_balance_view(request):
    """
    Generate the trial balance for this tenant.
    Optional query param: ?as_of=YYYY-MM-DD (defaults to today).
    """
    as_of_str = request.query_params.get("as_of")
    as_of = None
    if as_of_str:
        try:
            as_of = date.fromisoformat(as_of_str)
        except ValueError:
            return Response(
                {"error": "Invalid date format. Use YYYY-MM-DD."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    result = generate_trial_balance(request.tenant_id, as_of_date=as_of)

    # Coerce Decimal to str for JSON serialization
    result["total_debits"] = str(result["total_debits"])
    result["total_credits"] = str(result["total_credits"])
    for row in result["rows"]:
        row["debit_balance"] = str(row["debit_balance"])
        row["credit_balance"] = str(row["credit_balance"])

    return Response(result)
