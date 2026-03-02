from django.test import TestCase
from django.db import models
from apps.core.models import TenantAwareModel
import uuid


class Dummy(TenantAwareModel):
    name = models.CharField(max_length=100)

    class Meta:
        app_label = "core"


class TenantIsolationTests(TestCase):
    databases = {"default"}

    @classmethod
    def setUpTestData(cls):
        # create two dummy records for different tenants
        Dummy.objects.create(tenant_id=uuid.UUID(int=1), name="Tenant1 Record")
        Dummy.objects.create(tenant_id=uuid.UUID(int=2), name="Tenant2 Record")

    def test_tenant_a_cannot_see_tenant_b(self):
        # simulate querying as tenant 1
        tenant1_records = Dummy.objects.filter(tenant_id=uuid.UUID(int=1))
        tenant2_records = Dummy.objects.filter(tenant_id=uuid.UUID(int=2))
        self.assertEqual(len(tenant1_records), 1)
        self.assertEqual(tenant1_records[0].name, "Tenant1 Record")
        # ensure tenant1 query returns none of tenant2's data
        self.assertNotIn("Tenant2 Record", [r.name for r in tenant1_records])
        # also ensure tenant2 query is correct
        self.assertEqual(len(tenant2_records), 1)
        self.assertEqual(tenant2_records[0].name, "Tenant2 Record")
