"""Unit tests for the pure state machine."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.litter_box_monitor.state_machine import (
    CycleOutcome,
    DoorState,
    EventType,
    LitterBoxStateMachine,
    MachineConfig,
    MaintenanceSource,
    OperationalState,
    StartSource,
)

OPEN = DoorState.OPEN
CLOSED = DoorState.CLOSED
TZ = ZoneInfo("America/Chicago")
T0 = datetime(2026, 10, 13, 15, 0, tzinfo=UTC)  # 10:00 local


def local_date(value: datetime) -> date:
    return value.astimezone(TZ).date()


def make(**overrides) -> LitterBoxStateMachine:
    config = MachineConfig(cleaning_timeout=timedelta(minutes=5), **overrides)
    return LitterBoxStateMachine(config, local_date)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def types(events) -> list[EventType]:
    return [e.type for e in events]


def ready(machine: LitterBoxStateMachine) -> LitterBoxStateMachine:
    machine.handle_main_door(OPEN, T0, T0)
    return machine


def restart(machine: LitterBoxStateMachine, saved_at: datetime, **overrides):
    """Simulate persisting at ``saved_at`` and loading into a new machine."""
    data = machine.as_dict(saved_at)
    fresh = make(**overrides)
    fresh.load(data)
    return fresh


def test_open_is_ready() -> None:
    machine = make()
    assert machine.status is OperationalState.UNAVAILABLE
    assert machine.handle_main_door(OPEN, T0, T0) == []
    assert machine.status is OperationalState.READY


def test_close_starts_cleaning() -> None:
    machine = ready(make())
    assert machine.handle_main_door(CLOSED, at(10), at(10)) == []
    assert machine.status is OperationalState.CLEANING
    assert machine.cycle.started_at == at(10)
    assert machine.cycle.start_source is StartSource.OBSERVED
    assert machine.timeout_deadline == at(310)
    assert machine.consume_critical_change()


def test_complete_cycle_counts() -> None:
    machine = ready(make())
    machine.handle_main_door(CLOSED, at(10), at(10))
    events = machine.handle_main_door(OPEN, at(130), at(130))
    assert types(events) == [EventType.CLEANING_COMPLETED]
    assert events[0].data["duration_seconds"] == 120
    assert events[0].data["cleans_today"] == 1
    assert machine.status is OperationalState.READY
    assert machine.last_cleaning_at == at(130)
    assert machine.last_cleaning_duration == 120
    assert machine.total_cleans == 1
    assert machine.cleans_on(date(2026, 10, 13)) == 1
    assert machine.history[0].outcome is CycleOutcome.COMPLETED
    assert machine.average_duration(date(2026, 10, 13), 30) == 120


def test_timeout_raises_fault_once_and_opening_clears() -> None:
    machine = ready(make())
    machine.handle_main_door(CLOSED, at(0), at(0))
    assert machine.check_timeout(at(299)) == []
    events = machine.check_timeout(at(300))
    assert types(events) == [EventType.FAULT_DETECTED]
    assert events[0].data == {
        "fault_type": "main_door_stuck_closed",
        "reason": "Main door stuck closed",
        "detected_at": at(300).isoformat(),
        "cleaning_started_at": at(0).isoformat(),
        "elapsed_seconds": 300,
    }
    assert machine.status is OperationalState.ERROR
    assert machine.timeout_deadline is None
    # Re-evaluation and duplicate deliveries never re-raise.
    assert machine.check_timeout(at(400)) == []
    assert machine.handle_main_door(CLOSED, at(401), at(0)) == []

    events = machine.handle_main_door(OPEN, at(500), at(500))
    assert types(events) == [EventType.FAULT_CLEARED]
    assert events[0].data["resolution"] == "main_door_opened"
    assert machine.status is OperationalState.READY
    # Faulted cycle is recorded but not counted.
    assert machine.total_cleans == 0
    assert machine.history[-1].outcome is CycleOutcome.OVERTIME


def test_fault_monitoring_disabled() -> None:
    machine = ready(make(fault_monitoring=False))
    machine.handle_main_door(CLOSED, at(0), at(0))
    assert machine.timeout_deadline is None
    assert machine.check_timeout(at(10_000)) == []
    events = machine.handle_main_door(OPEN, at(10_000), at(10_000))
    assert types(events) == [EventType.CLEANING_COMPLETED]


def test_disabling_monitoring_clears_active_fault() -> None:
    machine = ready(make())
    machine.handle_main_door(CLOSED, at(0), at(0))
    machine.check_timeout(at(301))
    restored = restart(machine, at(302), fault_monitoring=False)
    events = restored.apply_config(at(303))
    assert types(events) == [EventType.FAULT_CLEARED]
    assert events[0].data["resolution"] == "monitoring_disabled"


def test_duplicate_events_are_ignored() -> None:
    machine = ready(make())
    machine.handle_main_door(CLOSED, at(0), at(0))
    machine.handle_main_door(CLOSED, at(1), at(0))
    assert machine.cycle.started_at == at(0)
    assert types(machine.handle_main_door(OPEN, at(60), at(60))) == [
        EventType.CLEANING_COMPLETED
    ]
    assert machine.handle_main_door(OPEN, at(61), at(60)) == []
    assert machine.total_cleans == 1


def test_unavailable_never_counts_as_transition() -> None:
    machine = ready(make())
    assert machine.handle_main_door(None, at(10)) == []
    assert machine.status is OperationalState.UNAVAILABLE
    assert machine.cycle is None
    # Back to the same state after a long outage: still ready, nothing counted.
    assert machine.handle_main_door(OPEN, at(1000), at(1000)) == []
    assert machine.status is OperationalState.READY
    assert machine.total_cleans == 0


def test_short_outage_during_cycle_keeps_timer_and_counts() -> None:
    machine = ready(make())
    machine.handle_main_door(CLOSED, at(0), at(0))
    machine.handle_main_door(None, at(60))
    assert machine.timeout_deadline is None  # no confirmation while offline
    assert machine.check_timeout(at(400)) == []
    machine.handle_main_door(CLOSED, at(90), at(90))
    assert machine.cycle.started_at == at(0)
    assert machine.cycle.continuity_verified
    assert machine.timeout_deadline == at(300)
    events = machine.handle_main_door(OPEN, at(120), at(120))
    assert types(events) == [EventType.CLEANING_COMPLETED]


def test_short_outage_cycle_finishes_while_offline() -> None:
    machine = ready(make())
    machine.handle_main_door(CLOSED, at(0), at(0))
    machine.handle_main_door(None, at(100))
    events = machine.handle_main_door(OPEN, at(140), at(140))
    assert types(events) == [EventType.CLEANING_COMPLETED]
    assert events[0].data["observation_gap_seconds"] == 40
    assert machine.history[-1].observation_gap_seconds == 40


def test_long_outage_discards_cycle() -> None:
    machine = ready(make())
    machine.handle_main_door(CLOSED, at(0), at(0))
    machine.handle_main_door(None, at(30))
    assert machine.handle_main_door(OPEN, at(600), at(600)) == []
    assert machine.cycle is None
    assert machine.total_cleans == 0
    assert machine.history == []
    assert machine.transitions[-1]["event"] == "cycle_discarded"


def test_long_outage_still_closed_marks_unverified_but_keeps_start() -> None:
    machine = ready(make())
    machine.handle_main_door(CLOSED, at(0), at(0))
    machine.handle_main_door(None, at(30))
    events = machine.handle_main_door(CLOSED, at(400), at(400))
    # Timeout already exceeded relative to the original start.
    assert types(events) == [EventType.FAULT_DETECTED]
    assert machine.cycle.started_at == at(0)
    assert not machine.cycle.continuity_verified


def test_long_outage_unverified_cycle_not_counted() -> None:
    machine = ready(make(fault_monitoring=False))
    machine.handle_main_door(CLOSED, at(0), at(0))
    machine.handle_main_door(None, at(30))
    machine.handle_main_door(CLOSED, at(200), at(200))
    assert machine.handle_main_door(OPEN, at(250), at(250)) == []
    assert machine.history[-1].outcome is CycleOutcome.UNVERIFIED
    assert machine.total_cleans == 0


def test_fault_survives_unavailability() -> None:
    machine = ready(make())
    machine.handle_main_door(CLOSED, at(0), at(0))
    machine.check_timeout(at(300))
    machine.handle_main_door(None, at(310))
    assert machine.status is OperationalState.ERROR
    assert machine.fault is not None
    assert machine.handle_main_door(CLOSED, at(5000), at(5000)) == []
    assert machine.fault is not None


def test_fault_cleared_by_open_after_long_outage() -> None:
    machine = ready(make())
    machine.handle_main_door(CLOSED, at(0), at(0))
    machine.check_timeout(at(300))
    machine.handle_main_door(None, at(310))
    events = machine.handle_main_door(OPEN, at(5000), at(5000))
    assert types(events) == [EventType.FAULT_CLEARED]
    assert machine.cycle is None


def test_unavailable_does_not_raise_fault() -> None:
    machine = ready(make())
    machine.handle_main_door(CLOSED, at(0), at(0))
    machine.handle_main_door(None, at(10))
    assert machine.check_timeout(at(10_000)) == []
    assert machine.fault is None


# --- startup / restart -------------------------------------------------


def test_first_startup_door_open() -> None:
    machine = make()
    assert machine.handle_main_door(OPEN, T0, T0 - timedelta(days=3)) == []
    assert machine.status is OperationalState.READY


def test_first_startup_door_closed_uses_last_changed_as_lower_bound() -> None:
    machine = make()
    machine.handle_main_door(CLOSED, at(100), at(0))
    assert machine.cycle.start_source is StartSource.ESTIMATED
    assert machine.cycle.started_at == at(0)
    assert machine.timeout_deadline == at(300)
    # Never counted.
    assert machine.handle_main_door(OPEN, at(150), at(150)) == []
    assert machine.history[-1].outcome is CycleOutcome.UNVERIFIED
    assert machine.total_cleans == 0


def test_restart_during_cleaning_resumes_original_start() -> None:
    machine = ready(make())
    machine.handle_main_door(CLOSED, at(0), at(0))
    restored = restart(machine, at(60))
    assert restored.status is OperationalState.UNAVAILABLE
    # HA restored state: last_changed reset to startup time.
    assert restored.handle_main_door(CLOSED, at(90), at(85)) == []
    assert restored.cycle.started_at == at(0)
    assert restored.cycle.continuity_verified
    assert restored.timeout_deadline == at(300)
    events = restored.handle_main_door(OPEN, at(150), at(150))
    assert types(events) == [EventType.CLEANING_COMPLETED]
    assert events[0].data["duration_seconds"] == 150


def test_restart_after_timeout_reports_fault_promptly() -> None:
    machine = ready(make())
    machine.handle_main_door(CLOSED, at(0), at(0))
    restored = restart(machine, at(100))
    events = restored.handle_main_door(CLOSED, at(400), at(400))
    assert types(events) == [EventType.FAULT_DETECTED]
    assert events[0].data["elapsed_seconds"] == 400


def test_restart_with_active_fault_does_not_duplicate() -> None:
    machine = ready(make())
    machine.handle_main_door(CLOSED, at(0), at(0))
    machine.check_timeout(at(300))
    restored = restart(machine, at(310))
    assert restored.status is OperationalState.ERROR
    assert restored.handle_main_door(CLOSED, at(330), at(330)) == []
    assert restored.fault.detected_at == at(300)


def test_cycle_finished_while_ha_down_is_discarded() -> None:
    machine = ready(make())
    machine.handle_main_door(CLOSED, at(0), at(0))
    restored = restart(machine, at(30))
    assert restored.handle_main_door(OPEN, at(600), at(600)) == []
    assert restored.cycle is None
    assert restored.total_cleans == 0


def test_door_closed_during_quick_restart_is_observed() -> None:
    machine = ready(make())
    restored = restart(machine, at(0))
    restored.handle_main_door(CLOSED, at(20), at(15))
    assert restored.cycle.start_source is StartSource.OBSERVED
    assert restored.cycle.started_at == at(15)


def test_malformed_storage_is_ignored() -> None:
    machine = make()
    machine.load(
        {
            "cycle": {"started_at": "garbage"},
            "fault": {"fault_type": "nope"},
            "statistics": {
                "total_cleans": -3,
                "daily_counts": {"2026-10-13": "x", "2026-10-12": 2},
                "history": [{"started_at": "bad"}, 7],
                "last_cleaning_duration": "12",
            },
            "maintenance": {"bag_door_opened_at": 5},
        }
    )
    assert machine.cycle is None
    assert machine.fault is None
    assert machine.total_cleans == 0
    assert machine.daily_counts == {"2026-10-12": 2}
    assert machine.history == []
    assert machine.last_cleaning_duration is None
    assert machine.bag_door_opened_at is None


def test_round_trip_persistence() -> None:
    machine = ready(make())
    machine.handle_main_door(CLOSED, at(0), at(0))
    machine.handle_main_door(OPEN, at(100), at(100))
    machine.handle_bag_door(CLOSED, at(0), at(0))
    machine.handle_bag_door(OPEN, at(200), at(200))
    restored = restart(machine, at(300))
    assert restored.total_cleans == 1
    assert restored.last_cleaning_at == at(100)
    assert restored.daily_counts == machine.daily_counts
    assert [r.as_dict() for r in restored.history] == [
        r.as_dict() for r in machine.history
    ]
    assert restored.bag_door_opened_at == at(200)
    assert restored.bag_door_source is MaintenanceSource.OBSERVED


# --- calendar ------------------------------------------------------------


def test_cycle_spanning_midnight_counts_on_completion_date() -> None:
    machine = make()
    before_midnight = datetime(2026, 10, 13, 23, 58, tzinfo=TZ)
    machine.handle_main_door(OPEN, before_midnight, before_midnight)
    machine.handle_main_door(CLOSED, before_midnight, before_midnight)
    after = before_midnight + timedelta(minutes=3)
    machine.handle_main_door(OPEN, after, after)
    assert machine.cleans_on(date(2026, 10, 14)) == 1
    assert machine.cleans_on(date(2026, 10, 13)) == 0


def test_rolling_counts_and_prune() -> None:
    machine = make(retention_days=30)
    machine.daily_counts = {
        "2026-10-13": 2,
        "2026-10-12": 3,
        "2026-10-07": 1,
        "2026-10-06": 10,
        "2026-09-13": 4,
        "2026-09-12": 4,
    }
    today = date(2026, 10, 13)
    assert machine.cleans_in_last_days(today, 7) == 6
    machine.prune(today)
    assert "2026-09-13" not in machine.daily_counts
    assert set(machine.daily_counts) == {
        "2026-10-13",
        "2026-10-12",
        "2026-10-07",
        "2026-10-06",
    }


@pytest.mark.parametrize(
    ("opened_local", "now_local", "expected"),
    [
        (datetime(2026, 10, 13, 23, 59), datetime(2026, 10, 14, 0, 1), 1),
        (datetime(2026, 10, 13, 0, 1), datetime(2026, 10, 13, 23, 59), 0),
        # Spans the November DST change (25-hour day).
        (datetime(2026, 10, 31, 12, 0), datetime(2026, 11, 2, 0, 30), 2),
        # Spans the March DST change (23-hour day).
        (datetime(2026, 3, 7, 23, 30), datetime(2026, 3, 9, 0, 10), 2),
    ],
)
def test_days_since_uses_calendar_days(opened_local, now_local, expected) -> None:
    machine = make()
    machine.set_bag_door_opened(
        opened_local.replace(tzinfo=TZ), MaintenanceSource.MANUAL
    )
    today = now_local.replace(tzinfo=TZ).date()
    assert machine.days_since_bag_door_opened(today) == expected


# --- bag door --------------------------------------------------------------


def test_bag_door_transition_records_opening() -> None:
    machine = make()
    machine.handle_bag_door(CLOSED, at(0), at(0))
    events = machine.handle_bag_door(OPEN, at(10), at(10))
    assert types(events) == [EventType.BAG_DOOR_OPENED]
    assert machine.bag_door_opened_at == at(10)
    assert machine.handle_bag_door(OPEN, at(11), at(10)) == []
    machine.handle_bag_door(CLOSED, at(20), at(20))
    assert types(machine.handle_bag_door(OPEN, at(30), at(30))) == [
        EventType.BAG_DOOR_OPENED
    ]


def test_bag_door_already_open_at_startup_not_recorded() -> None:
    machine = make()
    assert machine.handle_bag_door(OPEN, at(0), at(0)) == []
    assert machine.bag_door_opened_at is None


def test_bag_door_opened_during_long_gap_not_recorded() -> None:
    machine = make()
    machine.handle_bag_door(CLOSED, at(0), at(0))
    restored = restart(machine, at(0))
    assert restored.handle_bag_door(OPEN, at(3600), at(3600)) == []
    assert restored.bag_door_opened_at is None


def test_bag_door_opened_during_short_gap_recorded() -> None:
    machine = make()
    machine.handle_bag_door(CLOSED, at(0), at(0))
    machine.handle_bag_door(None, at(5))
    assert types(machine.handle_bag_door(OPEN, at(20), at(20))) == [
        EventType.BAG_DOOR_OPENED
    ]


def test_bag_door_ignored_when_maintenance_disabled() -> None:
    machine = make(maintenance_tracking=False)
    machine.handle_bag_door(CLOSED, at(0), at(0))
    assert machine.handle_bag_door(OPEN, at(10), at(10)) == []
    assert machine.bag_door_opened_at is None


def test_statistics_disabled_records_nothing() -> None:
    machine = ready(make(statistics=False))
    machine.handle_main_door(CLOSED, at(0), at(0))
    events = machine.handle_main_door(OPEN, at(60), at(60))
    assert types(events) == [EventType.CLEANING_COMPLETED]
    assert machine.total_cleans == 0
    assert machine.history == []
