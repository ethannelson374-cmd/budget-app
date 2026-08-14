from __future__ import annotations

import json
from collections.abc import Iterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, get_settings_from_request, require_csrf, require_principal
from app.core.config import Settings
from app.core.errors import ApiError
from app.integrations.advisor import provider_for_settings
from app.models import User
from app.schemas.api import (
    AdvisorConversationCreate,
    AdvisorConversationDetailView,
    AdvisorConversationListView,
    AdvisorConversationView,
    AdvisorPrompt,
    AdvisorProposalView,
    AdvisorStatusView,
    OkView,
)
from app.services.advisor import (
    TOOL_DEFINITIONS,
    attached_insight,
    conversation_detail,
    conversation_view,
    create_conversation,
    delete_all_conversations,
    delete_conversation,
    discard_private_conversation,
    execute_tool,
    get_conversation,
    infer_mode,
    list_conversations,
    recent_history,
    reserve_advisor_request,
    sanitized_snapshot,
    save_message,
    trusted_facts,
)
from app.services.advisor_actions import (
    apply_proposal,
    create_proposal,
    get_proposal,
    proposal_view,
    reject_proposal,
    undo_proposal,
)
from app.services.auth import Principal, add_audit_event

router = APIRouter(prefix="/advisor", tags=["advisor"])


def _status(settings: Settings, principal: Principal) -> dict[str, object]:
    return {
        "available": settings.ai_configured,
        "enabled": principal.user.settings.advisor_enabled,
        "store_history": principal.user.settings.advisor_store_history,
        "provider": settings.ai_provider,
        "model": settings.advisor_model,
    }


@router.get("/status", response_model=AdvisorStatusView)
def get_advisor_status(
    principal: Principal = Depends(require_principal),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    return _status(settings, principal)


@router.get("/conversations", response_model=AdvisorConversationListView)
def get_advisor_conversations(
    principal: Principal = Depends(require_principal), db: Session = Depends(get_db)
) -> dict[str, object]:
    return {"conversations": [conversation_view(row) for row in list_conversations(db, principal.user)]}


@router.post("/conversations", response_model=AdvisorConversationView, status_code=201)
def post_advisor_conversation(
    payload: AdvisorConversationCreate,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    if not principal.user.settings.advisor_enabled:
        raise ApiError(403, "advisor_disabled", "Ask Budget is disabled in Settings")
    if not settings.ai_configured:
        raise ApiError(503, "advisor_unavailable", "Ask Budget is not configured on this server")
    row = create_conversation(db, principal.user, payload.title)
    add_audit_event(db, settings, action="advisor.conversation.create", outcome="success", request_id=getattr(request.state, "request_id", None), user_id=principal.user.id, detail="history" if principal.user.settings.advisor_store_history else "private")
    db.commit()
    return conversation_view(row)


@router.get("/conversations/{conversation_id}", response_model=AdvisorConversationDetailView)
def get_advisor_conversation(
    conversation_id: int,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return conversation_detail(db, principal.user, conversation_id)


@router.delete("/conversations/{conversation_id}", response_model=OkView)
def remove_advisor_conversation(
    conversation_id: int,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, bool]:
    delete_conversation(db, principal.user, conversation_id)
    add_audit_event(db, settings, action="advisor.conversation.delete", outcome="success", request_id=getattr(request.state, "request_id", None), user_id=principal.user.id, detail=str(conversation_id))
    db.commit()
    return {"ok": True}


@router.delete("/conversations", response_model=OkView)
def remove_all_advisor_conversations(
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, bool]:
    delete_all_conversations(db, principal.user)
    add_audit_event(db, settings, action="advisor.history.delete", outcome="success", request_id=getattr(request.state, "request_id", None), user_id=principal.user.id, detail="all")
    db.commit()
    return {"ok": True}



@router.get("/proposals/{proposal_id}", response_model=AdvisorProposalView)
def get_advisor_proposal(
    proposal_id: int,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return proposal_view(db, principal.user, get_proposal(db, principal.user, proposal_id))


@router.post("/proposals/{proposal_id}/apply", response_model=AdvisorProposalView)
def post_advisor_proposal_apply(
    proposal_id: int,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    proposal = apply_proposal(db, principal.user, proposal_id)
    add_audit_event(
        db, settings, action="advisor.proposal.apply", outcome="success",
        request_id=getattr(request.state, "request_id", None), user_id=principal.user.id, detail=str(proposal_id),
    )
    db.commit()
    return proposal_view(db, principal.user, proposal)


@router.post("/proposals/{proposal_id}/reject", response_model=AdvisorProposalView)
def post_advisor_proposal_reject(
    proposal_id: int,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    proposal = reject_proposal(db, principal.user, proposal_id)
    add_audit_event(
        db, settings, action="advisor.proposal.reject", outcome="success",
        request_id=getattr(request.state, "request_id", None), user_id=principal.user.id, detail=str(proposal_id),
    )
    db.commit()
    return proposal_view(db, principal.user, proposal)


@router.post("/proposals/{proposal_id}/undo", response_model=AdvisorProposalView)
def post_advisor_proposal_undo(
    proposal_id: int,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    proposal = undo_proposal(db, principal.user, proposal_id)
    add_audit_event(
        db, settings, action="advisor.proposal.undo", outcome="success",
        request_id=getattr(request.state, "request_id", None), user_id=principal.user.id, detail=str(proposal_id),
    )
    db.commit()
    return proposal_view(db, principal.user, proposal)

def _sse(event: str, payload: object) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, separators=(',', ':'), default=str)}\n\n"


@router.post("/conversations/{conversation_id}/messages/stream")
def stream_advisor_message(
    conversation_id: int,
    payload: AdvisorPrompt,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> StreamingResponse:
    if not principal.user.settings.advisor_enabled:
        raise ApiError(403, "advisor_disabled", "Ask Budget is disabled in Settings")
    if not settings.ai_configured:
        raise ApiError(503, "advisor_unavailable", "Ask Budget is not configured on this server")
    retry_after = reserve_advisor_request(principal.user.id, settings.ai_requests_per_minute)
    if retry_after is not None:
        raise ApiError(429, "advisor_rate_limited", "Ask Budget is receiving too many requests", headers={"Retry-After": str(retry_after)})

    conversation = get_conversation(db, principal.user, conversation_id)
    store_history = principal.user.settings.advisor_store_history
    mode = infer_mode(payload.message)
    request_id = getattr(request.state, "request_id", None)
    try:
        snapshot = sanitized_snapshot(db, principal.user)
        insight = attached_insight(db, principal.user, payload.insight_id)
        history = recent_history(db, principal.user, conversation.id)
        provider = provider_for_settings(settings)
        calls = provider.plan(message=payload.message, mode=mode, snapshot=snapshot, history=history, attached_insight=insight, tools=TOOL_DEFINITIONS, max_tool_calls=settings.ai_max_tool_calls)
        allowed = {str(tool["name"]) for tool in TOOL_DEFINITIONS}
        tool_results: list[dict[str, object]] = []
        for call in calls[: settings.ai_max_tool_calls]:
            name = str(call.get("name") or "")
            if name not in allowed:
                continue
            arguments = call.get("arguments")
            if not isinstance(arguments, dict):
                arguments = {}
            try:
                result = execute_tool(db, principal.user, name, arguments)
            except ApiError as exc:
                result = {"error": exc.code, "message": exc.message}
            tool_results.append({"name": name, "result": result})
        facts = trusted_facts(snapshot, tool_results)
    except Exception as exc:
        # A private session creates a transient conversation row only to keep the
        # streaming route owner-scoped. If planning fails before streaming begins,
        # remove that shell immediately so private mode truly retains no history.
        db.rollback()
        if not store_history:
            discard_private_conversation(db, principal.user.id, conversation_id)
        add_audit_event(
            db, settings, action="advisor.answer", outcome="failure",
            request_id=request_id, user_id=principal.user.id,
            detail=exc.code if isinstance(exc, ApiError) else "advisor_planning_failed",
        )
        db.commit()
        raise

    if store_history:
        save_message(db, principal.user, conversation, role="user", content=payload.message, context={"mode": mode, "insight_id": payload.insight_id})
    # Deterministic planning helpers may materialize default settings. Commit before
    # streaming so the request-scoped connection holds no write lock while the
    # stream uses a short-lived session for outcome/history persistence.
    db.commit()

    user_id = principal.user.id
    session_factory = request.app.state.database.session_factory

    def persist_proposal(reply: dict[str, object]) -> None:
        suggestions = reply.pop("proposed_actions", [])
        title = str(reply.pop("action_plan_title", "") or "")
        summary = str(reply.pop("action_plan_summary", "") or "")
        reply["proposal_id"] = None
        if not store_history or not isinstance(suggestions, list) or not suggestions:
            return
        safe_suggestions = [item for item in suggestions if isinstance(item, dict)]
        if not safe_suggestions:
            return
        try:
            with session_factory() as proposal_db:
                proposal_user = proposal_db.get(User, user_id)
                if proposal_user is None:
                    return
                proposal = create_proposal(
                    proposal_db, proposal_user, conversation_id=conversation_id,
                    title=title, summary=summary, suggestions=safe_suggestions,
                )
                if proposal is None:
                    return
                add_audit_event(
                    proposal_db, settings, action="advisor.proposal.create", outcome="success",
                    request_id=request_id, user_id=user_id, detail=f"{proposal.id}:actions={len(safe_suggestions)}",
                )
                proposal_db.commit()
                reply["proposal_id"] = proposal.id
        except ApiError:
            warnings = reply.get("warnings")
            if isinstance(warnings, list) and len(warnings) < 5:
                warnings.append("Budget could not validate the suggested action plan, so no changes were made.")

    def save_outcome(*, success: bool, reply: dict[str, object] | None = None, error_code: str | None = None) -> None:
        with session_factory() as save_db:
            user = save_db.get(User, user_id)
            if user is None:
                return
            if success and reply is not None and store_history:
                conv = get_conversation(save_db, user, conversation_id)
                save_message(save_db, user, conv, role="assistant", content=str(reply.get("answer", "")), response=reply, context={"mode": mode, "tool_count": len(tool_results)})
            add_audit_event(save_db, settings, action="advisor.answer", outcome="success" if success else "failure", request_id=request_id, user_id=user_id, detail=f"{mode}:tools={len(tool_results)}" if success else (error_code or "stream_error"))
            if not store_history:
                discard_private_conversation(save_db, user_id, conversation_id)
            save_db.commit()

    def generate() -> Iterator[str]:
        reply: dict[str, object] | None = None
        try:
            yield _sse("meta", {"mode": mode, "facts": facts})
            for event, value in provider.stream_answer(message=payload.message, mode=mode, snapshot=snapshot, history=history, attached_insight=insight, tool_results=tool_results, facts=facts):
                if event == "delta":
                    yield _sse("delta", {"text": str(value)})
                elif event == "done" and isinstance(value, dict):
                    reply = dict(value)
                    reply["facts"] = facts
                    persist_proposal(reply)
                    yield _sse("done", reply)
            if reply is None:
                raise ApiError(503, "advisor_invalid_response", "Ask Budget did not return a complete response")
            save_outcome(success=True, reply=reply)
        except ApiError as exc:
            save_outcome(success=False, error_code=exc.code)
            yield _sse("error", {"code": exc.code, "message": exc.message})
        except Exception:
            save_outcome(success=False, error_code="advisor_stream_failed")
            yield _sse("error", {"code": "advisor_stream_failed", "message": "Ask Budget could not complete the response"})

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
