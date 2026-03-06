from decimal import Decimal
from rest_framework import serializers
from .models import Account, JournalEntry, JournalEntryLine, JournalEntrySource


class AccountSerializer(serializers.ModelSerializer):
    balance = serializers.SerializerMethodField()

    class Meta:
        model = Account
        fields = [
            "id", "code", "name", "account_type", "account_category",
            "description", "parent", "is_active", "created_at", "updated_at",
            "balance",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "balance"]

    def get_balance(self, obj):
        from .services import compute_account_balance
        return str(compute_account_balance(obj))

    def validate_code(self, value):
        if not value.isdigit():
            raise serializers.ValidationError("Account code must be numeric.")
        return value


class JournalEntryLineSerializer(serializers.ModelSerializer):
    account_code = serializers.ReadOnlyField(source="account.code")
    account_name = serializers.ReadOnlyField(source="account.name")
    account_type = serializers.ReadOnlyField(source="account.account_type")

    class Meta:
        model = JournalEntryLine
        fields = [
            "id", "account", "account_code", "account_name", "account_type",
            "description", "debit", "credit", "line_number",
        ]
        read_only_fields = ["id", "line_number", "account_code", "account_name", "account_type"]


class JournalEntrySerializer(serializers.ModelSerializer):
    lines = JournalEntryLineSerializer(many=True, read_only=True)
    total_debits = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)
    total_credits = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)
    posted_by_username = serializers.ReadOnlyField(source="posted_by.username")

    class Meta:
        model = JournalEntry
        fields = [
            "id", "reference_number", "date", "description", "source",
            "is_posted", "posted_at", "is_reversed", "reversal_of",
            "posted_by_username", "total_debits", "total_credits",
            "lines", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "reference_number", "is_posted", "posted_at",
            "is_reversed", "reversal_of", "posted_by_username",
            "total_debits", "total_credits", "lines",
            "created_at", "updated_at",
        ]


class JournalEntryLineInputSerializer(serializers.Serializer):
    account_id = serializers.UUIDField()
    description = serializers.CharField(required=False, default="", allow_blank=True)
    debit = serializers.DecimalField(
        max_digits=18, decimal_places=2, required=False, default=Decimal("0.00")
    )
    credit = serializers.DecimalField(
        max_digits=18, decimal_places=2, required=False, default=Decimal("0.00")
    )

    def validate(self, data):
        debit = data.get("debit", Decimal("0.00"))
        credit = data.get("credit", Decimal("0.00"))
        if debit > 0 and credit > 0:
            raise serializers.ValidationError(
                "A line cannot have both a debit and a credit amount."
            )
        if debit == Decimal("0.00") and credit == Decimal("0.00"):
            raise serializers.ValidationError(
                "A line must have either a debit or a credit amount."
            )
        return data


class CreateJournalEntrySerializer(serializers.Serializer):
    date = serializers.DateField()
    description = serializers.CharField(max_length=500)
    source = serializers.ChoiceField(
        choices=JournalEntrySource.choices,
        required=False,
        default=JournalEntrySource.MANUAL,
    )
    lines = JournalEntryLineInputSerializer(many=True)

    def validate_lines(self, value):
        if len(value) < 2:
            raise serializers.ValidationError("At least two lines are required.")
        total_debits = sum(line.get("debit", Decimal("0.00")) for line in value)
        total_credits = sum(line.get("credit", Decimal("0.00")) for line in value)
        if total_debits != total_credits:
            raise serializers.ValidationError(
                f"Lines are unbalanced: debits={total_debits}, credits={total_credits}."
            )
        return value


class ReverseJournalEntrySerializer(serializers.Serializer):
    reversal_date = serializers.DateField()
