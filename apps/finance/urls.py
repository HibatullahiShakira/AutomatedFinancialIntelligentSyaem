from django.urls import path
from . import views

urlpatterns = [
    # Chart of Accounts
    path("accounts/", views.account_list, name="finance-account-list"),
    path("accounts/seed/", views.seed_accounts_view, name="finance-account-seed"),
    path("accounts/<uuid:account_id>/", views.account_detail, name="finance-account-detail"),
    path("accounts/<uuid:account_id>/balance/", views.account_balance_view, name="finance-account-balance"),

    # Journal Entries
    path("journals/", views.journal_entry_list, name="finance-journal-list"),
    path("journals/<uuid:entry_id>/", views.journal_entry_detail, name="finance-journal-detail"),
    path("journals/<uuid:entry_id>/post/", views.post_entry_view, name="finance-journal-post"),
    path("journals/<uuid:entry_id>/reverse/", views.reverse_entry_view, name="finance-journal-reverse"),

    # Trial Balance
    path("trial-balance/", views.trial_balance_view, name="finance-trial-balance"),
]
