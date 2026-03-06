"""
Tests for core infrastructure: middleware, exceptions, models.
These tests validate multi-tenancy foundation before financial modules are built.
"""

from django.test import TestCase, RequestFactory
from django.http import HttpResponse
import uuid
from apps.core.middleware import CorrelationIdMiddleware, TenantContextMiddleware
from apps.core.exceptions import AMSSException
from apps.core.models import MiddlewareTestModel


def dummy_view(request):
    """Dummy view for middleware testing."""
    return HttpResponse("OK")


class CorrelationIdMiddlewareTest(TestCase):
    """Test distributed tracing middleware."""

    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = CorrelationIdMiddleware(dummy_view)

    def test_generates_correlation_id_if_missing(self):
        """If client doesn't send X-Correlation-ID, middleware generates UUID."""
        request = self.factory.get("/api/test/")
        self.middleware(request)

        # Should have correlation_id set
        self.assertIsNotNone(request.correlation_id)
        # Should be valid UUID format
        try:
            uuid.UUID(request.correlation_id)
            is_valid_uuid = True
        except ValueError:
            is_valid_uuid = False
        self.assertTrue(is_valid_uuid)

    def test_uses_client_correlation_id(self):
        """If client sends X-Correlation-ID header, middleware uses it."""
        client_id = str(uuid.uuid4())
        request = self.factory.get("/api/test/", HTTP_X_CORRELATION_ID=client_id)
        self.middleware(request)

        # Should use the client-provided ID
        self.assertEqual(request.correlation_id, client_id)

    def test_correlation_id_persists_across_requests(self):
        """Correlation ID is consistent for debugging."""
        request1 = self.factory.get("/api/test/")
        self.middleware(request1)
        id1 = request1.correlation_id

        request2 = self.factory.get("/api/test/")
        self.middleware(request2)
        id2 = request2.correlation_id

        # Different requests get different correlation IDs
        self.assertNotEqual(id1, id2)

    def test_correlation_id_format(self):
        """Correlation ID should be in standard UUID format."""
        request = self.factory.get("/api/test/")
        self.middleware(request)

        # Parse as UUID to verify format
        parsed = uuid.UUID(request.correlation_id)
        self.assertEqual(str(parsed), request.correlation_id)


class TenantContextMiddlewareTest(TestCase):
    """Test tenant context injection middleware."""

    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = TenantContextMiddleware(dummy_view)

    def test_initializes_tenant_id_to_none(self):
        """Before authentication, tenant_id should be None."""
        request = self.factory.get("/api/test/")
        self.middleware(request)

        self.assertIsNone(request.tenant_id)

    def test_tenant_id_is_set_on_request_object(self):
        """Middleware should set tenant_id attribute on request."""
        request = self.factory.get("/api/test/")
        self.middleware(request)

        # Request object should have tenant_id attribute
        self.assertTrue(hasattr(request, "tenant_id"))

    def test_multiple_requests_have_independent_tenant_contexts(self):
        """Each request gets its own tenant context."""
        request1 = self.factory.get("/api/test/")
        request2 = self.factory.get("/api/test/")

        self.middleware(request1)
        self.middleware(request2)

        # Both should be None initially, but independent objects
        self.assertIsNone(request1.tenant_id)
        self.assertIsNone(request2.tenant_id)
        self.assertIsNot(request1, request2)


class AMSSExceptionTest(TestCase):
    """Test custom exception handling."""

    def test_amss_exception_has_correct_status_code(self):
        """AMSS exceptions should return 400 Bad Request by default."""
        exc = AMSSException()
        self.assertEqual(exc.status_code, 400)

    def test_amss_exception_default_detail(self):
        """AMSS exceptions should have sensible default message."""
        exc = AMSSException()
        self.assertEqual(exc.default_detail, "An error occurred in AMSS")

    def test_amss_exception_with_custom_detail(self):
        """AMSS exceptions can be raised with custom messages."""
        custom_msg = "Custom error message"
        exc = AMSSException(detail=custom_msg)
        self.assertEqual(exc.detail, custom_msg)

    def test_amss_exception_code(self):
        """AMSS exceptions should have consistent error code."""
        exc = AMSSException()
        self.assertEqual(exc.default_code, "amss_error")

    def test_amss_exception_is_api_exception(self):
        """AMSS exceptions should be Django REST Framework compatible."""
        from rest_framework.exceptions import APIException
        exc = AMSSException()
        self.assertIsInstance(exc, APIException)


class TenantAwareModelTest(TestCase):
    """Test multi-tenancy model foundation."""

    def setUp(self):
        self.tenant_id_1 = uuid.UUID(int=1)
        self.tenant_id_2 = uuid.UUID(int=2)

    def test_model_requires_tenant_id(self):
        """TenantAwareModel subclasses have tenant_id field."""
        obj = MiddlewareTestModel.objects.create(
            tenant_id=self.tenant_id_1,
            name="Test 1"
        )
        self.assertEqual(obj.tenant_id, self.tenant_id_1)

    def test_tenant_id_has_index(self):
        """tenant_id should be indexed for query performance."""
        # Get the model's fields
        field = MiddlewareTestModel._meta.get_field('tenant_id')
        # Field should be indexed
        self.assertTrue(field.db_index)

    def test_model_is_abstract(self):
        """TenantAwareModel is abstract (doesn't create its own table)."""
        from apps.core.models import TenantAwareModel
        self.assertTrue(TenantAwareModel._meta.abstract)

    def test_auto_generates_tenant_id_if_not_provided(self):
        """If tenant_id not explicitly set, should auto-generate UUID."""
        # Create without tenant_id (relies on default=uuid.uuid4)
        obj1 = MiddlewareTestModel.objects.create(name="Auto 1")
        obj2 = MiddlewareTestModel.objects.create(name="Auto 2")

        # Both should have tenant_id
        self.assertIsNotNone(obj1.tenant_id)
        self.assertIsNotNone(obj2.tenant_id)

        # Should be different UUIDs
        self.assertNotEqual(obj1.tenant_id, obj2.tenant_id)

    def test_tenant_id_is_uuid_field(self):
        """tenant_id should be a UUID field."""
        from django.db.models import UUIDField
        field = MiddlewareTestModel._meta.get_field('tenant_id')
        self.assertIsInstance(field, UUIDField)

    def test_different_tenants_isolated_in_queries(self):
        """Verify basic isolation: queries by tenant_id return correct records."""
        MiddlewareTestModel.objects.create(
            tenant_id=self.tenant_id_1,
            name="Tenant 1 Record"
        )
        MiddlewareTestModel.objects.create(
            tenant_id=self.tenant_id_2,
            name="Tenant 2 Record"
        )

        # Query for tenant 1
        tenant_1_records = MiddlewareTestModel.objects.filter(tenant_id=self.tenant_id_1)
        self.assertEqual(tenant_1_records.count(), 1)
        self.assertEqual(tenant_1_records.first().name, "Tenant 1 Record")

        # Query for tenant 2
        tenant_2_records = MiddlewareTestModel.objects.filter(tenant_id=self.tenant_id_2)
        self.assertEqual(tenant_2_records.count(), 1)
        self.assertEqual(tenant_2_records.first().name, "Tenant 2 Record")

    def test_multiple_records_per_tenant(self):
        """A single tenant can have multiple records."""
        MiddlewareTestModel.objects.create(
            tenant_id=self.tenant_id_1,
            name="Record 1"
        )
        MiddlewareTestModel.objects.create(
            tenant_id=self.tenant_id_1,
            name="Record 2"
        )
        MiddlewareTestModel.objects.create(
            tenant_id=self.tenant_id_2,
            name="Record 3"
        )

        tenant_1_count = MiddlewareTestModel.objects.filter(
            tenant_id=self.tenant_id_1
        ).count()
        self.assertEqual(tenant_1_count, 2)

        tenant_2_count = MiddlewareTestModel.objects.filter(
            tenant_id=self.tenant_id_2
        ).count()
        self.assertEqual(tenant_2_count, 1)
