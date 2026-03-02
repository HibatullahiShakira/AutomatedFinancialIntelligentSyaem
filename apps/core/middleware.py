import uuid
from django.utils.deprecation import MiddlewareMixin
from typing import Any


class CorrelationIdMiddleware(MiddlewareMixin):
    def process_request(self, request: Any) -> None:
        request.correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))


class TenantContextMiddleware(MiddlewareMixin):
    def process_request(self, request: Any) -> None:
        request.tenant_id = None  # set by authentication middleware later
