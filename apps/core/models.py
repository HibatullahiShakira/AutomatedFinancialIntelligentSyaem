from django.db import models
import uuid


from django.db import models
import uuid


class TenantAwareModel(models.Model):  # type: ignore[misc]
    """
    Base model for all business entities. See CODE_LEARNING_GUIDE.md for design rationale.
    """
    tenant_id = models.UUIDField(default=uuid.uuid4, db_index=True)

    class Meta:
        abstract = True
