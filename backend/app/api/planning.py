from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, get_settings_from_request, require_csrf, require_principal
from app.core.config import Settings
from app.schemas.api import (
    DebtCreate,
    DebtPatch,
    DebtStrategyWrite,
    DebtsView,
    FinancialGoalCreate,
    FinancialGoalPatch,
    FinancialGoalsView,
    ForecastAssumptionsWrite,
    ForecastScenarioView,
    ForecastScenarioWrite,
    ForecastView,
    GoalContributionCreate,
    OkView,
)
from app.services.auth import Principal, add_audit_event
from app.services.financial_planning import (
    add_goal_contribution,
    create_debt,
    create_goal,
    delete_debt,
    delete_goal,
    forecast_view,
    list_debts,
    list_goals,
    scenario_view,
    update_debt,
    update_debt_strategy,
    update_forecast_assumptions,
    update_goal,
)

router = APIRouter(prefix="/planning", tags=["planning"])


def _audit(
    db: Session,
    settings: Settings,
    request: Request,
    principal: Principal,
    action: str,
    detail: str,
) -> None:
    add_audit_event(
        db,
        settings,
        action=action,
        outcome="success",
        request_id=getattr(request.state, "request_id", None),
        user_id=principal.user.id,
        detail=detail,
    )


@router.get("/goals", response_model=FinancialGoalsView)
def get_goals(
    principal: Principal = Depends(require_principal), db: Session = Depends(get_db)
) -> dict[str, object]:
    return list_goals(db, principal.user)


@router.post("/goals", response_model=FinancialGoalsView, status_code=201)
def post_goal(
    payload: FinancialGoalCreate,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    goal = create_goal(db, principal.user, payload.model_dump())
    _audit(db, settings, request, principal, "planning.goal.create", str(goal.id))
    db.commit()
    return list_goals(db, principal.user)


@router.patch("/goals/{goal_id}", response_model=FinancialGoalsView)
def patch_goal(
    goal_id: int,
    payload: FinancialGoalPatch,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    update_goal(db, principal.user, goal_id, payload.model_dump(exclude_unset=True))
    _audit(db, settings, request, principal, "planning.goal.update", str(goal_id))
    db.commit()
    return list_goals(db, principal.user)


@router.post("/goals/{goal_id}/contributions", response_model=FinancialGoalsView)
def post_goal_contribution(
    goal_id: int,
    payload: GoalContributionCreate,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    add_goal_contribution(
        db,
        principal.user,
        goal_id,
        payload.amount,
        payload.contribution_date,
        payload.notes,
    )
    _audit(db, settings, request, principal, "planning.goal.contribution", str(goal_id))
    db.commit()
    return list_goals(db, principal.user)


@router.delete("/goals/{goal_id}", response_model=OkView)
def remove_goal(
    goal_id: int,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, bool]:
    delete_goal(db, principal.user, goal_id)
    _audit(db, settings, request, principal, "planning.goal.delete", str(goal_id))
    db.commit()
    return {"ok": True}


@router.get("/debts", response_model=DebtsView)
def get_debts(
    principal: Principal = Depends(require_principal), db: Session = Depends(get_db)
) -> dict[str, object]:
    result = list_debts(db, principal.user)
    db.commit()
    return result


@router.post("/debts", response_model=DebtsView, status_code=201)
def post_debt(
    payload: DebtCreate,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    debt = create_debt(db, principal.user, payload.model_dump())
    _audit(db, settings, request, principal, "planning.debt.create", str(debt.id))
    db.commit()
    return list_debts(db, principal.user)


@router.patch("/debts/{debt_id}", response_model=DebtsView)
def patch_debt(
    debt_id: int,
    payload: DebtPatch,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    update_debt(db, principal.user, debt_id, payload.model_dump(exclude_unset=True))
    _audit(db, settings, request, principal, "planning.debt.update", str(debt_id))
    db.commit()
    return list_debts(db, principal.user)


@router.delete("/debts/{debt_id}", response_model=OkView)
def remove_debt(
    debt_id: int,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, bool]:
    delete_debt(db, principal.user, debt_id)
    _audit(db, settings, request, principal, "planning.debt.delete", str(debt_id))
    db.commit()
    return {"ok": True}


@router.put("/debts/strategy", response_model=DebtsView)
def put_strategy(
    payload: DebtStrategyWrite,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    update_debt_strategy(db, principal.user, payload.strategy, payload.monthly_extra_budget)
    _audit(db, settings, request, principal, "planning.debt.strategy", payload.strategy)
    db.commit()
    return list_debts(db, principal.user)


@router.get("/forecast", response_model=ForecastView)
def get_forecast(
    principal: Principal = Depends(require_principal), db: Session = Depends(get_db)
) -> dict[str, object]:
    result = forecast_view(db, principal.user)
    db.commit()
    return result


@router.put("/forecast/assumptions", response_model=ForecastView)
def put_forecast_assumptions(
    payload: ForecastAssumptionsWrite,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    update_forecast_assumptions(
        db, principal.user, payload.reserve_balance, payload.include_budget_reserve
    )
    _audit(db, settings, request, principal, "planning.forecast.assumptions", "updated")
    db.commit()
    return forecast_view(db, principal.user)


@router.post("/forecast/scenario", response_model=ForecastScenarioView)
def post_scenario(
    payload: ForecastScenarioWrite,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    result = scenario_view(db, principal.user, payload.model_dump())
    db.rollback()
    return result
