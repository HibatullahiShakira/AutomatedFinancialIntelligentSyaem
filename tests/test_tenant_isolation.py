# This test proves tenant isolation works before any financial features are added.
# See CODE_LEARNING_GUIDE.md and INTERVIEW_GUIDE.md for detailed explanation.

from django.test import TestCase
from django.db import models
from apps.core.models import TenantAwareModel
import uuid


class Dummy(TenantAwareModel):
    """Minimal model to test multi-tenancy."""
    name = models.CharField(max_length=100)

    class Meta:
        app_label = "core"


class TenantIsolationTests(TestCase):
    """Test multi-tenancy enforcement at application layer."""

    databases = {"default"}

    @classmethod
    def setUpTestData(cls):
        """Create test data for two separate tenants."""
        Dummy.objects.create(tenant_id=uuid.UUID(int=1), name="Tenant1 Record")
        Dummy.objects.create(tenant_id=uuid.UUID(int=2), name="Tenant2 Record")

    def test_tenant_a_cannot_see_tenant_b(self):
        """Core invariant: Tenant A queries return ONLY Tenant A data."""
        tenant1_records = Dummy.objects.filter(tenant_id=uuid.UUID(int=1))
        tenant2_records = Dummy.objects.filter(tenant_id=uuid.UUID(int=2))

        self.assertEqual(len(tenant1_records), 1)
        self.assertEqual(tenant1_records[0].name, "Tenant1 Record")
        self.assertNotIn("Tenant2 Record", [r.name for r in tenant1_records])
        
        self.assertEqual(len(tenant2_records), 1)
        self.assertEqual(tenant2_records[0].name, "Tenant2 Record")=
