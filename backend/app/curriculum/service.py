"""Hour allocation and scenario estimates from measured topic mastery."""

from fastapi import HTTPException

from app.contracts import (
    HourAllocation,
    OptimizeOut,
    OptimizeRequest,
    SimulateOut,
    SimulateRequest,
    TopicProjection,
    TopicsOut,
)


def _validate_topics(names: set[str], topics: TopicsOut) -> dict[str, float]:
    mastery = {item.topic: item.mastery for item in topics.topics}
    missing = sorted(names - mastery.keys())
    if missing:
        raise HTTPException(status_code=422, detail=f"Unknown topics: {', '.join(missing)}")
    return mastery


def _validate_hours(hours: dict[str, int], label: str) -> None:
    if not hours:
        raise HTTPException(status_code=422, detail=f"{label} must contain at least one topic")
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in hours.values()):
        raise HTTPException(status_code=422, detail=f"{label} must contain nonnegative integer hours")


def optimize(request: OptimizeRequest, topics: TopicsOut) -> OptimizeOut:
    """Transfer hours toward lower mastery while preserving total and limits."""
    current = request.current_hours
    _validate_hours(current, "current_hours")
    mastery = _validate_topics(set(current), topics)
    total = sum(current.values())
    minimum = request.minimum_hours
    limit = request.max_change_per_topic
    if total < minimum * len(current):
        raise HTTPException(status_code=422, detail="Total hours cannot satisfy minimum_hours for every topic")

    lower = {name: max(minimum, hours - limit) for name, hours in current.items()}
    upper = {name: hours + limit for name, hours in current.items()}
    if any(lower[name] > upper[name] for name in current):
        raise HTTPException(status_code=422, detail="minimum_hours conflicts with max_change_per_topic")
    if sum(lower.values()) > total:
        raise HTTPException(status_code=422, detail="Minimum hours cannot be met within max_change_per_topic")

    # First meet mandatory minimums using hours from the least needy eligible topics.
    allocation = current.copy()
    for recipient in sorted(current):
        while allocation[recipient] < lower[recipient]:
            donors = [name for name in current if name != recipient and allocation[name] > lower[name]]
            if not donors:
                raise HTTPException(status_code=422, detail="No feasible allocation satisfies the constraints")
            donor = min(donors, key=lambda name: (1 - mastery[name], name))
            allocation[donor] -= 1
            allocation[recipient] += 1

    # Each improving transfer increases the linear priority objective.
    recipients = sorted(current, key=lambda name: (mastery[name], name))
    donors = sorted(current, key=lambda name: (-mastery[name], name))
    for recipient in recipients:
        for donor in donors:
            if mastery[recipient] >= mastery[donor]:
                continue
            amount = min(upper[recipient] - allocation[recipient], allocation[donor] - lower[donor])
            if amount > 0:
                allocation[recipient] += amount
                allocation[donor] -= amount

    rows = [
        HourAllocation(
            topic=name,
            current_hours=current[name],
            recommended_hours=allocation[name],
            change=allocation[name] - current[name],
            mastery=mastery[name],
            priority=1 - mastery[name],
        )
        for name in sorted(current, key=lambda name: (mastery[name], name))
    ]
    return OptimizeOut(
        dataset_id=topics.dataset_id,
        total_hours=total,
        allocations=rows,
        method="Deterministic priority-weighted hour transfer; priority = 1 - mastery",
    )


def simulate(request: SimulateRequest, topics: TopicsOut) -> SimulateOut:
    """Estimate topic mastery from relative changes in teaching hours."""
    current = request.current_hours
    proposed = request.proposed_hours
    _validate_hours(current, "current_hours")
    _validate_hours(proposed, "proposed_hours")
    if current.keys() != proposed.keys():
        raise HTTPException(status_code=422, detail="current_hours and proposed_hours must have identical topics")
    if sum(current.values()) <= 0:
        raise HTTPException(status_code=422, detail="Total current hours must be positive")
    mastery = _validate_topics(set(current), topics)
    projections = []
    for name in sorted(current):
        before = mastery[name]
        change = request.sensitivity * (proposed[name] - current[name]) / max(current[name], 1)
        after = min(1.0, max(0.0, before + change))
        projections.append(
            TopicProjection(
                topic=name,
                current_hours=current[name],
                proposed_hours=proposed[name],
                mastery_before=before,
                mastery_after=after,
                delta=after - before,
            )
        )
    count = len(projections)
    return SimulateOut(
        dataset_id=topics.dataset_id,
        projections=projections,
        overall_before=sum(row.mastery_before for row in projections) / count,
        overall_after=sum(row.mastery_after for row in projections) / count,
        assumption="Each topic changes by sensitivity × (proposed_hours - current_hours) / max(current_hours, 1); mastery is capped to [0, 1]. Overall is the unweighted mean across selected topics. This is a scenario estimate, not a causal prediction.",
    )
