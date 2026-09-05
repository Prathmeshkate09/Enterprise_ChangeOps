"""Private backend routes for identity verification and central admission."""

from functools import partial
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from control_api.admission.identity import IdentityProvider
from control_api.admission.models import (
    AccessView,
    Identity,
    InvitationCreate,
    InvitationRedeem,
    Organization,
    OrganizationCreate,
    SessionCreate,
    StatusUpdate,
    Workspace,
)
from control_api.admission.service import AdmissionService
from control_api.admission.store import Document
from control_api.errors import ControlApiError


def build_admission_router(service: AdmissionService, provider: IdentityProvider) -> APIRouter:
    router = APIRouter(prefix="/v1/access", tags=["enterprise access"])

    async def identity(
        request: Request, authorization: Annotated[str | None, Header()] = None
    ) -> Identity:
        if not authorization or not authorization.startswith("Bearer "):
            raise ControlApiError("session_required", "Sign in to continue.", 401)
        session = authorization.removeprefix("Bearer ")
        if not session or len(session) > 16384:
            raise ControlApiError("session_invalid", "Sign in again to continue.", 401)
        actor = await run_in_threadpool(provider.verify, session)
        request.state.admission_actor = actor.subject
        return actor

    @router.post("/session")
    async def create_session(request: SessionCreate) -> dict[str, str]:
        cookie = await run_in_threadpool(provider.create_session, request.id_token)
        return {"session_cookie": cookie}

    @router.post("/logout", status_code=204)
    async def logout(actor: Annotated[Identity, Depends(identity)]) -> Response:
        await run_in_threadpool(provider.revoke, actor.subject)
        return Response(status_code=204)

    @router.get("/me", response_model=AccessView)
    async def me(actor: Annotated[Identity, Depends(identity)]) -> AccessView:
        return await run_in_threadpool(service.access, actor)

    @router.get("/organizations/{organization_id}", response_model=Workspace)
    async def workspace(
        organization_id: str, actor: Annotated[Identity, Depends(identity)]
    ) -> Workspace:
        return await run_in_threadpool(service.workspace, actor, organization_id)

    @router.post("/invitations/redeem", response_model=AccessView)
    async def redeem(
        request: InvitationRedeem, actor: Annotated[Identity, Depends(identity)]
    ) -> AccessView:
        return await run_in_threadpool(service.redeem, actor, request.token)

    @router.post("/admin/organizations", response_model=Organization, status_code=201)
    async def create_organization(
        request: OrganizationCreate, actor: Annotated[Identity, Depends(identity)]
    ) -> Organization:
        return await run_in_threadpool(service.create_organization, actor, request.name)

    @router.post("/admin/invitations", status_code=201)
    async def invite(
        request: InvitationCreate, actor: Annotated[Identity, Depends(identity)]
    ) -> Document:
        invitation, token = await run_in_threadpool(service.invite, actor, request)
        # Secret is returned once to the authenticated admin; never persisted in plaintext.
        return {
            "invitation_id": invitation.invitation_id,
            "token": token,
            "expires_at": invitation.expires_at.isoformat(),
        }

    @router.get("/admin/{kind}")
    async def list_records(
        kind: str,
        actor: Annotated[Identity, Depends(identity)],
        after: Annotated[str, Query(pattern=r"^[A-Za-z0-9_-]{0,128}$")] = "",
    ) -> Document:
        items = await run_in_threadpool(partial(service.list_records, actor, kind, after=after))
        return {"items": items, "next_cursor": items[-1]["record_id"] if len(items) == 50 else None}

    @router.patch("/admin/{kind}/{identifier}", status_code=204)
    async def set_status(
        kind: str,
        identifier: str,
        request: StatusUpdate,
        actor: Annotated[Identity, Depends(identity)],
    ) -> Response:
        if (
            not identifier
            or len(identifier) > 128
            or not all(char.isascii() and (char.isalnum() or char in "_-") for char in identifier)
        ):
            raise ControlApiError("invalid_identifier", "Invalid access record.", 422)
        if kind == "administrators":
            await run_in_threadpool(service.set_administrator, actor, identifier, request)
        else:
            await run_in_threadpool(service.set_status, actor, kind, identifier, request)
        return Response(status_code=204)

    return router
