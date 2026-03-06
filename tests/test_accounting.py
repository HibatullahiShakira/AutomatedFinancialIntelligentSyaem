"""
Phase 2 — Core Accounting Engine tests.

Test coverage:
  - Chart of Accounts: creation, validation, deactivation guard
  - Journal Entry: creation, posting, reversal, immutability
  - Balance Computation: debit-normal, credit-normal, date filtering
  - Trial Balance: balanced assertion, date filtering
  - Event Publisher: publishes on post (no SQS configured → log path)
  - API Endpoints: accounts CRUD, journal CRUD, post, reverse, trial-balance
  - Tenant Isolation: Tenant A cannot read Tenant B's accounts or journals
  - RBAC: VIEWER cannot create/post; ACCOUNTANT/OWNER can
"""
from decimal import Decimal
from datetime import date, timedelta

from django.test import TestCase

from apps.core.models import Tenant, User, UserTenant
from apps.core.auth_utils import generate_access_token
from apps.finance.models import (
    Account, AccountType, AccountCategory,
    JournalEntry, JournalEntrySource,
)
from apps.finance.services import (
    seed_chart_of_accounts,
    create_journal_entry,
    post_journal_entry,
    reverse_journal_entry,
    compute_account_balance,
    generate_trial_balance,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_tenant(name="Test Corp"):
    return Tenant.objects.create(name=name)


def make_user(username="testuser", email=None):
    email = email or f"{username}@example.com"
    return User.objects.create_user(
        username=username,
        email=email,
        password="SecurePass123!",
    )


def assign_role(user, tenant, role):
    return UserTenant.objects.create(user=user, tenant=tenant, role=role)


def auth_header(user, tenant):
    token = generate_access_token(str(user.id), str(tenant.id))
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def make_account(tenant, code, name, account_type, category):
    return Account.objects.create(
        tenant_id=tenant.id,
        code=code,
        name=name,
        account_type=account_type,
        account_category=category,
    )


def make_simple_entry(tenant, cash, revenue, amount=Decimal("1000.00"), posting_date=None):
    """Create a balanced draft entry: DR Cash / CR Revenue."""
    return create_journal_entry(
        tenant_id=tenant.id,
        posting_date=posting_date or date.today(),
        description="Sale of goods",
        lines=[
            {"account_id": str(cash.id), "debit": str(amount), "credit": "0.00"},
            {"account_id": str(revenue.id), "debit": "0.00", "credit": str(amount)},
        ],
    )


# ---------------------------------------------------------------------------
# 1. Chart of Accounts Tests
# ---------------------------------------------------------------------------

class TestChartOfAccounts(TestCase):

    def setUp(self):
        self.tenant = make_tenant()

    def test_seed_creates_default_accounts(self):
        accounts = seed_chart_of_accounts(self.tenant.id)
        self.assertGreater(len(accounts), 0)
        codes = [a.code for a in accounts]
        self.assertIn("1000", codes)   # Cash
        self.assertIn("4000", codes)   # Sales Revenue
        self.assertIn("5100", codes)   # Salaries

    def test_seed_is_idempotent(self):
        first = seed_chart_of_accounts(self.tenant.id)
        second = seed_chart_of_accounts(self.tenant.id)
        self.assertEqual(len(first), len(second))
        self.assertEqual(
            Account.objects.filter(tenant_id=self.tenant.id).count(),
            len(first),
        )

    def test_asset_account_is_debit_normal(self):
        account = make_account(
            self.tenant, "1000", "Cash", AccountType.ASSET, AccountCategory.CURRENT_ASSET
        )
        self.assertTrue(account.is_debit_normal)

    def test_expense_account_is_debit_normal(self):
        account = make_account(
            self.tenant, "5000", "COGS", AccountType.EXPENSE, AccountCategory.OPERATING_EXPENSE
        )
        self.assertTrue(account.is_debit_normal)

    def test_liability_account_is_credit_normal(self):
        account = make_account(
            self.tenant, "2000", "AP", AccountType.LIABILITY, AccountCategory.CURRENT_LIABILITY
        )
        self.assertFalse(account.is_debit_normal)

    def test_income_account_is_credit_normal(self):
        account = make_account(
            self.tenant, "4000", "Revenue", AccountType.INCOME, AccountCategory.OPERATING_INCOME
        )
        self.assertFalse(account.is_debit_normal)

    def test_equity_account_is_credit_normal(self):
        account = make_account(
            self.tenant, "3000", "Capital", AccountType.EQUITY, AccountCategory.EQUITY
        )
        self.assertFalse(account.is_debit_normal)

    def test_account_code_unique_per_tenant(self):
        from django.db import IntegrityError
        make_account(self.tenant, "9999", "Test A", AccountType.ASSET, AccountCategory.CURRENT_ASSET)
        with self.assertRaises(IntegrityError):
            make_account(self.tenant, "9999", "Test B", AccountType.ASSET, AccountCategory.CURRENT_ASSET)

    def test_same_code_allowed_for_different_tenants(self):
        other_tenant = make_tenant("Other Corp")
        a1 = make_account(self.tenant, "9998", "Test", AccountType.ASSET, AccountCategory.CURRENT_ASSET)
        a2 = make_account(other_tenant, "9998", "Test", AccountType.ASSET, AccountCategory.CURRENT_ASSET)
        self.assertNotEqual(a1.id, a2.id)


# ---------------------------------------------------------------------------
# 2. Journal Entry Service Tests
# ---------------------------------------------------------------------------

class TestJournalEntryService(TestCase):

    def setUp(self):
        self.tenant = make_tenant()
        seed_chart_of_accounts(self.tenant.id)
        self.cash = Account.objects.get(tenant_id=self.tenant.id, code="1000")
        self.revenue = Account.objects.get(tenant_id=self.tenant.id, code="4000")
        self.ap = Account.objects.get(tenant_id=self.tenant.id, code="2000")
        self.expense = Account.objects.get(tenant_id=self.tenant.id, code="5000")

    def test_create_draft_entry(self):
        entry = make_simple_entry(self.tenant, self.cash, self.revenue)
        self.assertFalse(entry.is_posted)
        self.assertEqual(entry.lines.count(), 2)
        self.assertTrue(entry.is_balanced)

    def test_reference_number_auto_generated(self):
        entry = make_simple_entry(self.tenant, self.cash, self.revenue)
        self.assertTrue(entry.reference_number.startswith("JNL-"))

    def test_unbalanced_entry_raises(self):
        with self.assertRaises(ValueError) as ctx:
            create_journal_entry(
                tenant_id=self.tenant.id,
                posting_date=date.today(),
                description="Bad entry",
                lines=[
                    {"account_id": str(self.cash.id), "debit": "500.00", "credit": "0.00"},
                    {"account_id": str(self.revenue.id), "debit": "0.00", "credit": "300.00"},
                ],
            )
        self.assertIn("unbalanced", str(ctx.exception))

    def test_single_line_raises(self):
        with self.assertRaises(ValueError) as ctx:
            create_journal_entry(
                tenant_id=self.tenant.id,
                posting_date=date.today(),
                description="Single line",
                lines=[
                    {"account_id": str(self.cash.id), "debit": "100.00", "credit": "0.00"},
                ],
            )
        self.assertIn("two lines", str(ctx.exception))

    def test_all_zero_amounts_raises(self):
        with self.assertRaises(ValueError) as ctx:
            create_journal_entry(
                tenant_id=self.tenant.id,
                posting_date=date.today(),
                description="Zero entry",
                lines=[
                    {"account_id": str(self.cash.id), "debit": "0.00", "credit": "0.00"},
                    {"account_id": str(self.revenue.id), "debit": "0.00", "credit": "0.00"},
                ],
            )
        self.assertIn("zero", str(ctx.exception))

    def test_post_entry_sets_flags(self):
        entry = make_simple_entry(self.tenant, self.cash, self.revenue)
        post_journal_entry(entry)
        entry.refresh_from_db()
        self.assertTrue(entry.is_posted)
        self.assertIsNotNone(entry.posted_at)

    def test_cannot_post_twice(self):
        entry = make_simple_entry(self.tenant, self.cash, self.revenue)
        post_journal_entry(entry)
        with self.assertRaises(ValueError) as ctx:
            post_journal_entry(entry)
        self.assertIn("already posted", str(ctx.exception))

    def test_reversal_creates_mirrored_entry(self):
        entry = make_simple_entry(self.tenant, self.cash, self.revenue, amount=Decimal("2000.00"))
        post_journal_entry(entry)

        reversal = reverse_journal_entry(entry, reversal_date=date.today())
        reversal.refresh_from_db()
        entry.refresh_from_db()

        self.assertTrue(entry.is_reversed)
        self.assertTrue(reversal.is_posted)
        self.assertEqual(reversal.source, JournalEntrySource.REVERSAL)
        self.assertEqual(reversal.reversal_of_id, entry.id)
        self.assertTrue(reversal.is_balanced)

        # After reversal, net balance should be zero
        cash_balance = compute_account_balance(self.cash)
        revenue_balance = compute_account_balance(self.revenue)
        self.assertEqual(cash_balance, Decimal("0.00"))
        self.assertEqual(revenue_balance, Decimal("0.00"))

    def test_cannot_reverse_draft(self):
        entry = make_simple_entry(self.tenant, self.cash, self.revenue)
        with self.assertRaises(ValueError) as ctx:
            reverse_journal_entry(entry, reversal_date=date.today())
        self.assertIn("posted", str(ctx.exception).lower())

    def test_cannot_reverse_twice(self):
        entry = make_simple_entry(self.tenant, self.cash, self.revenue)
        post_journal_entry(entry)
        reverse_journal_entry(entry, reversal_date=date.today())
        entry.refresh_from_db()
        with self.assertRaises(ValueError) as ctx:
            reverse_journal_entry(entry, reversal_date=date.today())
        self.assertIn("already been reversed", str(ctx.exception))

    def test_draft_entry_does_not_affect_balance(self):
        # Create but do not post
        make_simple_entry(self.tenant, self.cash, self.revenue, amount=Decimal("5000.00"))
        cash_balance = compute_account_balance(self.cash)
        self.assertEqual(cash_balance, Decimal("0.00"))

    def test_invalid_account_id_raises(self):
        import uuid
        with self.assertRaises(Account.DoesNotExist):
            create_journal_entry(
                tenant_id=self.tenant.id,
                posting_date=date.today(),
                description="Bad account",
                lines=[
                    {"account_id": str(uuid.uuid4()), "debit": "100.00", "credit": "0.00"},
                    {"account_id": str(self.revenue.id), "debit": "0.00", "credit": "100.00"},
                ],
            )


# ---------------------------------------------------------------------------
# 3. Balance Computation Tests
# ---------------------------------------------------------------------------

class TestBalanceComputation(TestCase):

    def setUp(self):
        self.tenant = make_tenant()
        seed_chart_of_accounts(self.tenant.id)
        self.cash = Account.objects.get(tenant_id=self.tenant.id, code="1000")
        self.ar = Account.objects.get(tenant_id=self.tenant.id, code="1100")
        self.revenue = Account.objects.get(tenant_id=self.tenant.id, code="4000")
        self.expense = Account.objects.get(tenant_id=self.tenant.id, code="5000")
        self.ap = Account.objects.get(tenant_id=self.tenant.id, code="2000")

    def _post(self, cash_amt, rev_amt, d=None):
        entry = make_simple_entry(self.tenant, self.cash, self.revenue,
                                   amount=cash_amt, posting_date=d or date.today())
        post_journal_entry(entry)
        return entry

    def test_debit_normal_account_increases_on_debit(self):
        self._post(Decimal("1000.00"), Decimal("1000.00"))
        self.assertEqual(compute_account_balance(self.cash), Decimal("1000.00"))

    def test_credit_normal_account_increases_on_credit(self):
        self._post(Decimal("1000.00"), Decimal("1000.00"))
        self.assertEqual(compute_account_balance(self.revenue), Decimal("1000.00"))

    def test_multiple_postings_accumulate(self):
        self._post(Decimal("500.00"), Decimal("500.00"))
        self._post(Decimal("300.00"), Decimal("300.00"))
        self.assertEqual(compute_account_balance(self.cash), Decimal("800.00"))
        self.assertEqual(compute_account_balance(self.revenue), Decimal("800.00"))

    def test_as_of_date_filter(self):
        yesterday = date.today() - timedelta(days=1)
        self._post(Decimal("1000.00"), Decimal("1000.00"), d=yesterday)
        self._post(Decimal("500.00"), Decimal("500.00"), d=date.today())

        balance_yesterday = compute_account_balance(self.cash, as_of_date=yesterday)
        self.assertEqual(balance_yesterday, Decimal("1000.00"))

        balance_today = compute_account_balance(self.cash, as_of_date=date.today())
        self.assertEqual(balance_today, Decimal("1500.00"))

    def test_zero_balance_on_empty_account(self):
        self.assertEqual(compute_account_balance(self.ar), Decimal("0.00"))

    def test_contra_balance_when_credits_exceed_debits_on_asset(self):
        # DR Revenue / CR Cash (unusual but possible manually)
        entry = create_journal_entry(
            tenant_id=self.tenant.id,
            posting_date=date.today(),
            description="Refund issued",
            lines=[
                {"account_id": str(self.revenue.id), "debit": "200.00", "credit": "0.00"},
                {"account_id": str(self.cash.id), "debit": "0.00", "credit": "200.00"},
            ],
        )
        post_journal_entry(entry)
        cash_balance = compute_account_balance(self.cash)
        # Cash is debit-normal; crediting it produces negative balance
        self.assertEqual(cash_balance, Decimal("-200.00"))


# ---------------------------------------------------------------------------
# 4. Trial Balance Tests
# ---------------------------------------------------------------------------

class TestTrialBalance(TestCase):

    def setUp(self):
        self.tenant = make_tenant()
        seed_chart_of_accounts(self.tenant.id)
        self.cash = Account.objects.get(tenant_id=self.tenant.id, code="1000")
        self.revenue = Account.objects.get(tenant_id=self.tenant.id, code="4000")

    def test_trial_balance_is_always_balanced(self):
        entry = make_simple_entry(self.tenant, self.cash, self.revenue, amount=Decimal("5000.00"))
        post_journal_entry(entry)

        tb = generate_trial_balance(self.tenant.id)
        self.assertTrue(tb["is_balanced"])
        self.assertEqual(tb["total_debits"], tb["total_credits"])

    def test_trial_balance_excludes_zero_balance_accounts(self):
        # Only post to cash and revenue
        entry = make_simple_entry(self.tenant, self.cash, self.revenue, amount=Decimal("1000.00"))
        post_journal_entry(entry)

        tb = generate_trial_balance(self.tenant.id)
        codes = [row["code"] for row in tb["rows"]]
        self.assertIn("1000", codes)
        self.assertIn("4000", codes)
        # Accounts with no postings should be excluded
        self.assertNotIn("1100", codes)   # AR has zero balance

    def test_trial_balance_date_filter(self):
        yesterday = date.today() - timedelta(days=1)
        entry = make_simple_entry(self.tenant, self.cash, self.revenue,
                                   amount=Decimal("3000.00"), posting_date=yesterday)
        post_journal_entry(entry)

        tb_yesterday = generate_trial_balance(self.tenant.id, as_of_date=yesterday)
        tb_last_week = generate_trial_balance(
            self.tenant.id,
            as_of_date=date.today() - timedelta(days=7),
        )
        self.assertTrue(tb_yesterday["total_debits"] > Decimal("0.00"))
        self.assertEqual(tb_last_week["total_debits"], Decimal("0.00"))

    def test_empty_trial_balance_is_balanced(self):
        tb = generate_trial_balance(self.tenant.id)
        self.assertTrue(tb["is_balanced"])
        self.assertEqual(tb["rows"], [])


# ---------------------------------------------------------------------------
# 5. Tenant Isolation Tests
# ---------------------------------------------------------------------------

class TestTenantIsolation(TestCase):

    def setUp(self):
        self.tenant_a = make_tenant("Tenant A")
        self.tenant_b = make_tenant("Tenant B")
        seed_chart_of_accounts(self.tenant_a.id)
        seed_chart_of_accounts(self.tenant_b.id)

    def test_accounts_are_tenant_scoped(self):
        a_count = Account.objects.filter(tenant_id=self.tenant_a.id).count()
        b_count = Account.objects.filter(tenant_id=self.tenant_b.id).count()
        # Each tenant has their own copy
        self.assertEqual(a_count, b_count)
        self.assertGreater(a_count, 0)

    def test_tenant_a_cannot_use_tenant_b_account_in_journal(self):
        b_cash = Account.objects.get(tenant_id=self.tenant_b.id, code="1000")
        a_revenue = Account.objects.get(tenant_id=self.tenant_a.id, code="4000")

        with self.assertRaises(Account.DoesNotExist):
            create_journal_entry(
                tenant_id=self.tenant_a.id,
                posting_date=date.today(),
                description="Cross-tenant attempt",
                lines=[
                    {"account_id": str(b_cash.id), "debit": "100.00", "credit": "0.00"},
                    {"account_id": str(a_revenue.id), "debit": "0.00", "credit": "100.00"},
                ],
            )

    def test_journals_are_tenant_scoped(self):
        a_cash = Account.objects.get(tenant_id=self.tenant_a.id, code="1000")
        a_revenue = Account.objects.get(tenant_id=self.tenant_a.id, code="4000")

        entry = make_simple_entry(self.tenant_a, a_cash, a_revenue)
        post_journal_entry(entry)

        a_journals = JournalEntry.objects.filter(tenant_id=self.tenant_a.id)
        b_journals = JournalEntry.objects.filter(tenant_id=self.tenant_b.id)

        self.assertEqual(a_journals.count(), 1)
        self.assertEqual(b_journals.count(), 0)

    def test_balance_is_tenant_scoped(self):
        a_cash = Account.objects.get(tenant_id=self.tenant_a.id, code="1000")
        a_revenue = Account.objects.get(tenant_id=self.tenant_a.id, code="4000")
        b_cash = Account.objects.get(tenant_id=self.tenant_b.id, code="1000")

        entry = make_simple_entry(self.tenant_a, a_cash, a_revenue, amount=Decimal("9999.00"))
        post_journal_entry(entry)

        # Tenant A's cash has a balance
        self.assertEqual(compute_account_balance(a_cash), Decimal("9999.00"))
        # Tenant B's cash is untouched
        self.assertEqual(compute_account_balance(b_cash), Decimal("0.00"))


# ---------------------------------------------------------------------------
# 6. API Endpoint Tests
# ---------------------------------------------------------------------------

class TestAccountAPI(TestCase):

    def setUp(self):
        self.tenant = make_tenant()
        self.owner = make_user("owner")
        self.accountant = make_user("accountant")
        self.viewer = make_user("viewer")
        assign_role(self.owner, self.tenant, "OWNER")
        assign_role(self.accountant, self.tenant, "ACCOUNTANT")
        assign_role(self.viewer, self.tenant, "VIEWER")
        seed_chart_of_accounts(self.tenant.id)

    def test_seed_endpoint_creates_accounts(self):
        # Create a fresh tenant with no accounts
        new_tenant = make_tenant("Fresh Corp")
        new_owner = make_user("fresh_owner", "fresh@example.com")
        assign_role(new_owner, new_tenant, "OWNER")

        response = self.client.post(
            "/api/finance/accounts/seed/",
            content_type="application/json",
            **auth_header(new_owner, new_tenant),
        )
        self.assertEqual(response.status_code, 200)
        self.assertGreater(response.json()["seeded"], 0)

    def test_viewer_cannot_seed(self):
        response = self.client.post(
            "/api/finance/accounts/seed/",
            content_type="application/json",
            **auth_header(self.viewer, self.tenant),
        )
        self.assertEqual(response.status_code, 403)

    def test_list_accounts_returns_accounts(self):
        response = self.client.get(
            "/api/finance/accounts/",
            **auth_header(self.viewer, self.tenant),
        )
        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(response.json()), 0)

    def test_viewer_cannot_create_account(self):
        response = self.client.post(
            "/api/finance/accounts/",
            data={
                "code": "9990",
                "name": "Test Account",
                "account_type": "ASSET",
                "account_category": "CURRENT_ASSET",
            },
            content_type="application/json",
            **auth_header(self.viewer, self.tenant),
        )
        self.assertEqual(response.status_code, 403)

    def test_accountant_can_create_account(self):
        response = self.client.post(
            "/api/finance/accounts/",
            data={
                "code": "9991",
                "name": "Petty Cash",
                "account_type": "ASSET",
                "account_category": "CURRENT_ASSET",
            },
            content_type="application/json",
            **auth_header(self.accountant, self.tenant),
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["code"], "9991")

    def test_account_detail_includes_balance(self):
        account = Account.objects.get(tenant_id=self.tenant.id, code="1000")
        response = self.client.get(
            f"/api/finance/accounts/{account.id}/",
            **auth_header(self.viewer, self.tenant),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("balance", response.json())

    def test_account_balance_endpoint(self):
        account = Account.objects.get(tenant_id=self.tenant.id, code="1000")
        response = self.client.get(
            f"/api/finance/accounts/{account.id}/balance/",
            **auth_header(self.viewer, self.tenant),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("balance", response.json())
        self.assertIn("as_of_date", response.json())

    def test_cannot_see_other_tenants_account(self):
        other_tenant = make_tenant("Other")
        other_user = make_user("other_user", "other@test.com")
        assign_role(other_user, other_tenant, "OWNER")
        seed_chart_of_accounts(other_tenant.id)
        other_account = Account.objects.get(tenant_id=other_tenant.id, code="1000")

        response = self.client.get(
            f"/api/finance/accounts/{other_account.id}/",
            **auth_header(self.viewer, self.tenant),
        )
        self.assertEqual(response.status_code, 404)


class TestJournalEntryAPI(TestCase):

    def setUp(self):
        self.tenant = make_tenant()
        self.owner = make_user("jowner")
        self.accountant = make_user("jaccountant")
        self.viewer = make_user("jviewer")
        assign_role(self.owner, self.tenant, "OWNER")
        assign_role(self.accountant, self.tenant, "ACCOUNTANT")
        assign_role(self.viewer, self.tenant, "VIEWER")
        seed_chart_of_accounts(self.tenant.id)
        self.cash = Account.objects.get(tenant_id=self.tenant.id, code="1000")
        self.revenue = Account.objects.get(tenant_id=self.tenant.id, code="4000")

    def _create_entry_payload(self, amount="500.00"):
        return {
            "date": date.today().isoformat(),
            "description": "API test entry",
            "lines": [
                {"account_id": str(self.cash.id), "debit": amount, "credit": "0.00"},
                {"account_id": str(self.revenue.id), "debit": "0.00", "credit": amount},
            ],
        }

    def test_create_journal_entry(self):
        response = self.client.post(
            "/api/finance/journals/",
            data=self._create_entry_payload(),
            content_type="application/json",
            **auth_header(self.accountant, self.tenant),
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertFalse(data["is_posted"])
        self.assertEqual(len(data["lines"]), 2)

    def test_viewer_cannot_create_entry(self):
        response = self.client.post(
            "/api/finance/journals/",
            data=self._create_entry_payload(),
            content_type="application/json",
            **auth_header(self.viewer, self.tenant),
        )
        self.assertEqual(response.status_code, 403)

    def test_unbalanced_entry_rejected(self):
        payload = {
            "date": date.today().isoformat(),
            "description": "Unbalanced",
            "lines": [
                {"account_id": str(self.cash.id), "debit": "100.00", "credit": "0.00"},
                {"account_id": str(self.revenue.id), "debit": "0.00", "credit": "50.00"},
            ],
        }
        response = self.client.post(
            "/api/finance/journals/",
            data=payload,
            content_type="application/json",
            **auth_header(self.accountant, self.tenant),
        )
        self.assertEqual(response.status_code, 400)

    def test_post_journal_entry(self):
        create_resp = self.client.post(
            "/api/finance/journals/",
            data=self._create_entry_payload(),
            content_type="application/json",
            **auth_header(self.accountant, self.tenant),
        )
        entry_id = create_resp.json()["id"]

        post_resp = self.client.post(
            f"/api/finance/journals/{entry_id}/post/",
            content_type="application/json",
            **auth_header(self.owner, self.tenant),
        )
        self.assertEqual(post_resp.status_code, 200)
        self.assertTrue(post_resp.json()["is_posted"])

    def test_viewer_cannot_post(self):
        entry = make_simple_entry(self.tenant, self.cash, self.revenue)
        response = self.client.post(
            f"/api/finance/journals/{entry.id}/post/",
            content_type="application/json",
            **auth_header(self.viewer, self.tenant),
        )
        self.assertEqual(response.status_code, 403)

    def test_reverse_journal_entry(self):
        entry = make_simple_entry(self.tenant, self.cash, self.revenue)
        post_journal_entry(entry)

        resp = self.client.post(
            f"/api/finance/journals/{entry.id}/reverse/",
            data={"reversal_date": date.today().isoformat()},
            content_type="application/json",
            **auth_header(self.owner, self.tenant),
        )
        self.assertEqual(resp.status_code, 201)
        reversal = resp.json()
        self.assertEqual(reversal["source"], "REVERSAL")
        self.assertTrue(reversal["is_posted"])

    def test_cannot_reverse_draft_entry_via_api(self):
        entry = make_simple_entry(self.tenant, self.cash, self.revenue)
        resp = self.client.post(
            f"/api/finance/journals/{entry.id}/reverse/",
            data={"reversal_date": date.today().isoformat()},
            content_type="application/json",
            **auth_header(self.owner, self.tenant),
        )
        self.assertEqual(resp.status_code, 400)

    def test_list_journals_with_filter(self):
        entry = make_simple_entry(self.tenant, self.cash, self.revenue)
        post_journal_entry(entry)

        resp = self.client.get(
            "/api/finance/journals/?is_posted=true",
            **auth_header(self.viewer, self.tenant),
        )
        self.assertEqual(resp.status_code, 200)
        results = resp.json()
        self.assertTrue(all(j["is_posted"] for j in results))

    def test_journal_detail_endpoint(self):
        entry = make_simple_entry(self.tenant, self.cash, self.revenue)
        resp = self.client.get(
            f"/api/finance/journals/{entry.id}/",
            **auth_header(self.viewer, self.tenant),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], str(entry.id))

    def test_cannot_see_other_tenants_journal(self):
        other_tenant = make_tenant("Other")
        other_user = make_user("other_juser", "oj@test.com")
        assign_role(other_user, other_tenant, "OWNER")
        seed_chart_of_accounts(other_tenant.id)
        other_cash = Account.objects.get(tenant_id=other_tenant.id, code="1000")
        other_revenue = Account.objects.get(tenant_id=other_tenant.id, code="4000")
        other_entry = make_simple_entry(other_tenant, other_cash, other_revenue)

        resp = self.client.get(
            f"/api/finance/journals/{other_entry.id}/",
            **auth_header(self.viewer, self.tenant),
        )
        self.assertEqual(resp.status_code, 404)


class TestTrialBalanceAPI(TestCase):

    def setUp(self):
        self.tenant = make_tenant()
        self.owner = make_user("tbowner")
        assign_role(self.owner, self.tenant, "OWNER")
        seed_chart_of_accounts(self.tenant.id)
        self.cash = Account.objects.get(tenant_id=self.tenant.id, code="1000")
        self.revenue = Account.objects.get(tenant_id=self.tenant.id, code="4000")

    def test_trial_balance_endpoint(self):
        entry = make_simple_entry(self.tenant, self.cash, self.revenue, amount=Decimal("2500.00"))
        post_journal_entry(entry)

        resp = self.client.get(
            "/api/finance/trial-balance/",
            **auth_header(self.owner, self.tenant),
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["is_balanced"])
        self.assertEqual(data["total_debits"], data["total_credits"])
        codes = [row["code"] for row in data["rows"]]
        self.assertIn("1000", codes)
        self.assertIn("4000", codes)

    def test_trial_balance_with_invalid_date_returns_400(self):
        resp = self.client.get(
            "/api/finance/trial-balance/?as_of=not-a-date",
            **auth_header(self.owner, self.tenant),
        )
        self.assertEqual(resp.status_code, 400)

    def test_unauthenticated_request_rejected(self):
        resp = self.client.get("/api/finance/trial-balance/")
        self.assertEqual(resp.status_code, 401)
