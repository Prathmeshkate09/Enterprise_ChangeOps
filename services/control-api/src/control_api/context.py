"""Request identity context resolved at the HTTP boundary."""

from typing import Annotated

from fastapi import Depends, Header

from control_api.errors import ActorRequiredError, TenantRequiredError


def _validated_identifier(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip()
    if not candidate or len(candidate) > 128:
        return None
    if not candidate[0].isalnum():
        return None
    if not all(character.isalnum() or character in "-_.:" for character in candidate):
        return None
    return candidate


async def require_tenant(
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
) -> str:
    tenant_id = _validated_identifier(x_tenant_id)
    if tenant_id is None:
        raise TenantRequiredError
    return tenant_id


async def require_actor(
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-ID")] = None,
) -> str:
    actor_id = _validated_identifier(x_actor_id)
    if actor_id is None:
        raise ActorRequiredError
    return actor_id


TenantId = Annotated[str, Depends(require_tenant)]
ActorId = Annotated[str, Depends(require_actor)]
