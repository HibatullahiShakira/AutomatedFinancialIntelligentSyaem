from django.db import models
import uuid


class TenantAwareModel(models.Model):
    tenant_id = models.UUIDField(default=uuid.uuid4, db_index=True)

    class Meta:
        abstract = True
