"""Operational state machine for a litter box.

This module is deliberately free of Home Assistant imports. It consumes door
observations with timestamps and produces domain events plus a timeout
deadline, which the coordinator turns into Home Assistant timers, bus events
and entity updates. Everything here is synchronous and deterministic so it can
be tested exhaustively.

Policy summary (also documented in the README):

* A valid door observation following a period in which the door state was not
  known (startup, sensor unavailable, Home Assistant restart) is *reconciled*
  rather than treated as a live transition.
* An observation gap no longer than ``observation_grace`` is a temporary
  disconnection: the cycle is considered continuous and a change seen
  afterwards is attributed to the moment the sensor reconnected.
* A longer gap makes the outcome unknown. A cycle that is found finished after
  a long gap is discarded; a cycle that is still running keeps its recorded
  start time (so the stuck-door timeout is not restarted) but is marked
  unverified and will not be counted.
* A cycle whose start was not observed (door already closed with no stored
  cycle) uses the sensor's ``last_changed`` as a lower bound for the timeout
  and is never counted.
* Only cycles that were observed from closing to opening and finished within
  the timeout (when fault monitoring is enabled) count towards statistics.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)


class DoorState(StrEnum):
    """Valid physical door states."""

    OPEN = "open"
    CLOSED = "closed"


class OperationalState(StrEnum):
    """Operational state of the virtual appliance."""

    READY = "ready"
    CLEANING = "cleaning"
    ERROR = "error"
    # Not "unavailable": that string is reserved by Home Assistant.
    UNAVAILABLE = "sensor_unavailable"


class FaultType(StrEnum):
    """Machine readable fault identifiers."""

    MAIN_DOOR_STUCK_CLOSED = "main_door_stuck_closed"


FAULT_REASONS: dict[FaultType, str] = {
    FaultType.MAIN_DOOR_STUCK_CLOSED: "Main door stuck closed",
}


class StartSource(StrEnum):
    """How the start of a cleaning cycle was established."""

    OBSERVED = "observed"
    ESTIMATED = "estimated"


class CycleOutcome(StrEnum):
    """Classification of a finished cleaning cycle."""

    COMPLETED = "completed"  # counted
    OVERTIME = "overtime"  # exceeded the timeout / raised a fault
    UNVERIFIED = "unverified"  # start or continuity not observed


class MaintenanceSource(StrEnum):
    """Origin of the bag door timestamp."""

    OBSERVED = "observed"
    MANUAL = "manual"
    INITIALIZED = "initialized"


class EventType(StrEnum):
    """Domain events produced by the state machine."""

    CLEANING_COMPLETED = "cleaning_completed"
    FAULT_DETECTED = "fault_detected"
    FAULT_CLEARED = "fault_cleared"
    BAG_DOOR_OPENED = "bag_door_opened"


@dataclass(frozen=True, slots=True)
class MachineEvent:
    """An event emitted by the state machine."""

    type: EventType
    data: dict[str, Any]


@dataclass(slots=True)
class MachineConfig:
    """Behavioural configuration."""

    cleaning_timeout: timedelta
    fault_monitoring: bool = True
    statistics: bool = True
    maintenance_tracking: bool = True
    retention_days: int = 90
    observation_grace: timedelta = timedelta(seconds=60)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _seconds(delta: timedelta) -> int:
    return max(0, round(delta.total_seconds()))


@dataclass(slots=True)
class Fault:
    """An active fault."""

    fault_type: FaultType
    detected_at: datetime
    cleaning_started_at: datetime | None
    elapsed_seconds: int

    @property
    def reason(self) -> str:
        """Human readable reason."""
        return FAULT_REASONS[self.fault_type]

    def as_dict(self) -> dict[str, Any]:
        """Serialize (also used as event payload)."""
        return {
            "fault_type": self.fault_type.value,
            "reason": self.reason,
            "detected_at": _iso(self.detected_at),
            "cleaning_started_at": _iso(self.cleaning_started_at),
            "elapsed_seconds": self.elapsed_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Fault | None:
        """Deserialize, returning None for unusable data."""
        try:
            fault_type = FaultType(data["fault_type"])
        except KeyError, ValueError, TypeError:
            return None
        detected_at = _parse_dt(data.get("detected_at"))
        if detected_at is None:
            return None
        return cls(
            fault_type=fault_type,
            detected_at=detected_at,
            cleaning_started_at=_parse_dt(data.get("cleaning_started_at")),
            elapsed_seconds=int(data.get("elapsed_seconds") or 0),
        )


@dataclass(slots=True)
class ActiveCycle:
    """A cleaning cycle in progress."""

    started_at: datetime
    start_source: StartSource
    continuity_verified: bool = True

    def as_dict(self) -> dict[str, Any]:
        """Serialize."""
        return {
            "started_at": _iso(self.started_at),
            "start_source": self.start_source.value,
            "continuity_verified": self.continuity_verified,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ActiveCycle | None:
        """Deserialize, returning None for unusable data."""
        started_at = _parse_dt(data.get("started_at"))
        if started_at is None:
            return None
        try:
            source = StartSource(data.get("start_source"))
        except ValueError:
            source = StartSource.ESTIMATED
        return cls(started_at, source, bool(data.get("continuity_verified", False)))


@dataclass(slots=True)
class CycleRecord:
    """A finished cleaning cycle kept in the bounded history."""

    started_at: datetime
    completed_at: datetime
    duration_seconds: int
    date: str  # local ISO date of completion
    outcome: CycleOutcome
    start_source: StartSource
    observation_gap_seconds: int | None = None

    def as_dict(self) -> dict[str, Any]:
        """Serialize."""
        return {
            "started_at": _iso(self.started_at),
            "completed_at": _iso(self.completed_at),
            "duration_seconds": self.duration_seconds,
            "date": self.date,
            "outcome": self.outcome.value,
            "start_source": self.start_source.value,
            "observation_gap_seconds": self.observation_gap_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CycleRecord | None:
        """Deserialize, returning None for unusable data."""
        started = _parse_dt(data.get("started_at"))
        completed = _parse_dt(data.get("completed_at"))
        if (
            started is None
            or completed is None
            or not isinstance(data.get("date"), str)
        ):
            return None
        try:
            return cls(
                started_at=started,
                completed_at=completed,
                duration_seconds=int(data["duration_seconds"]),
                date=data["date"],
                outcome=CycleOutcome(data["outcome"]),
                start_source=StartSource(data.get("start_source", "observed")),
                observation_gap_seconds=data.get("observation_gap_seconds"),
            )
        except KeyError, ValueError, TypeError:
            return None


@dataclass(slots=True)
class InputTracker:
    """Observation bookkeeping for one input sensor."""

    # Runtime only: the state currently reported (None = unknown/unavailable).
    current: DoorState | None = None
    # Persisted: last valid state and the last moment it was known to hold.
    last_valid: DoorState | None = None
    observed_until: datetime | None = None

    def gap(self, now: datetime) -> timedelta | None:
        """Length of the observation gap ending now, if it can be measured."""
        if self.last_valid is None or self.observed_until is None:
            return None
        return max(timedelta(0), now - self.observed_until)

    def as_dict(self, now: datetime) -> dict[str, Any]:
        """Serialize; a currently valid state is known to hold until now."""
        until = now if self.current is not None else self.observed_until
        return {"last_valid": self.last_valid, "observed_until": _iso(until)}

    def load(self, data: dict[str, Any]) -> None:
        """Restore persisted fields."""
        try:
            self.last_valid = DoorState(data.get("last_valid"))
        except ValueError:
            self.last_valid = None
        self.observed_until = _parse_dt(data.get("observed_until"))


class LitterBoxStateMachine:
    """Central controller holding all operational and statistical state."""

    def __init__(
        self,
        config: MachineConfig,
        local_date: Callable[[datetime], date],
        transition_log_size: int = 50,
    ) -> None:
        """Initialize."""
        self.config = config
        self._local_date = local_date
        self.main = InputTracker()
        self.bag = InputTracker()
        self.cycle: ActiveCycle | None = None
        self.fault: Fault | None = None
        self.last_cleaning_at: datetime | None = None
        self.last_cleaning_duration: int | None = None
        self.total_cleans = 0
        self.daily_counts: dict[str, int] = {}
        self.history: list[CycleRecord] = []
        self.bag_door_opened_at: datetime | None = None
        self.bag_door_source: MaintenanceSource | None = None
        self.transitions: deque[dict[str, Any]] = deque(maxlen=transition_log_size)
        self._critical_change = False

    # ------------------------------------------------------------------
    # Derived values
    # ------------------------------------------------------------------

    @property
    def status(self) -> OperationalState:
        """Return the operational state."""
        if self.fault is not None:
            return OperationalState.ERROR
        if self.main.current is None:
            return OperationalState.UNAVAILABLE
        if self.cycle is not None:
            return OperationalState.CLEANING
        return OperationalState.READY

    @property
    def timeout_deadline(self) -> datetime | None:
        """Moment at which the stuck-door fault should be raised, if any."""
        if (
            not self.config.fault_monitoring
            or self.fault is not None
            or self.cycle is None
            or self.main.current is not DoorState.CLOSED
        ):
            return None
        return self.cycle.started_at + self.config.cleaning_timeout

    def cleans_on(self, day: date) -> int:
        """Completed cleans on a local date."""
        return self.daily_counts.get(day.isoformat(), 0)

    def cleans_in_last_days(self, today: date, days: int) -> int:
        """Completed cleans over ``days`` local dates ending today (inclusive)."""
        return sum(self.cleans_on(today - timedelta(days=i)) for i in range(days))

    def average_duration(self, today: date, days: int) -> float | None:
        """Mean duration of counted cycles completed in the last ``days`` dates."""
        cutoff = (today - timedelta(days=days - 1)).isoformat()
        durations = [
            r.duration_seconds
            for r in self.history
            if r.outcome is CycleOutcome.COMPLETED and r.date >= cutoff
        ]
        if not durations:
            return None
        return round(sum(durations) / len(durations), 1)

    def current_cycle_seconds(self, now: datetime) -> int | None:
        """Elapsed seconds of the running cycle, 0 when idle."""
        if self.cycle is None:
            return 0
        return _seconds(now - self.cycle.started_at)

    def days_since_bag_door_opened(self, today: date) -> int | None:
        """Local calendar days since the bag door was last opened."""
        if self.bag_door_opened_at is None:
            return None
        return max(0, (today - self._local_date(self.bag_door_opened_at)).days)

    def consume_critical_change(self) -> bool:
        """Return and reset whether state that must be saved promptly changed."""
        changed, self._critical_change = self._critical_change, False
        return changed

    # ------------------------------------------------------------------
    # Inputs
    # ------------------------------------------------------------------

    def handle_main_door(
        self,
        state: DoorState | None,
        now: datetime,
        changed_at: datetime | None = None,
    ) -> list[MachineEvent]:
        """Process a main door observation (None = unknown/unavailable)."""
        tracker = self.main
        if state is None:
            if tracker.current is not None:
                tracker.observed_until = now
                tracker.current = None
                self._log(now, "main_door_unavailable")
            return []

        changed_at = self._bound(changed_at, tracker.observed_until, now)
        prev = tracker.current
        events: list[MachineEvent] = []
        if prev is None:
            events += self._reconcile_main(state, now, changed_at)
        elif prev is not state:
            tracker.current = state
            if state is DoorState.CLOSED:
                self._start_cycle(changed_at, StartSource.OBSERVED, now)
            else:
                events += self._finish_cycle(changed_at, now, gap=None)
        # prev is state: duplicate delivery, nothing to do.

        tracker.current = state
        tracker.last_valid = state
        tracker.observed_until = now
        events += self.check_timeout(now)
        return events

    def handle_bag_door(
        self,
        state: DoorState | None,
        now: datetime,
        changed_at: datetime | None = None,
    ) -> list[MachineEvent]:
        """Process a bag door observation (None = unknown/unavailable)."""
        tracker = self.bag
        if state is None:
            if tracker.current is not None:
                tracker.observed_until = now
                tracker.current = None
                self._log(now, "bag_door_unavailable")
            return []

        changed_at = self._bound(changed_at, tracker.observed_until, now)
        prev = tracker.current
        opened_at: datetime | None = None
        if prev is None:
            gap = tracker.gap(now)
            if state is DoorState.OPEN and tracker.last_valid is DoorState.CLOSED:
                if gap is not None and gap <= self.config.observation_grace:
                    opened_at = changed_at
                else:
                    self._log(
                        now,
                        "bag_door_opened_unobserved",
                        gap_seconds=_seconds(gap) if gap is not None else None,
                    )
        elif prev is DoorState.CLOSED and state is DoorState.OPEN:
            opened_at = changed_at

        tracker.current = state
        tracker.last_valid = state
        tracker.observed_until = now

        if opened_at is None or not self.config.maintenance_tracking:
            return []
        previous = self.bag_door_opened_at
        self.bag_door_opened_at = opened_at
        self.bag_door_source = MaintenanceSource.OBSERVED
        self._critical_change = True
        self._log(now, "bag_door_opened", opened_at=_iso(opened_at))
        return [
            MachineEvent(
                EventType.BAG_DOOR_OPENED,
                {
                    "opened_at": _iso(opened_at),
                    "previous_opened_at": _iso(previous),
                },
            )
        ]

    def check_timeout(self, now: datetime) -> list[MachineEvent]:
        """Raise the stuck-door fault if the deadline has passed."""
        deadline = self.timeout_deadline
        if deadline is None or now < deadline:
            return []
        assert self.cycle is not None
        self.fault = Fault(
            fault_type=FaultType.MAIN_DOOR_STUCK_CLOSED,
            detected_at=now,
            cleaning_started_at=self.cycle.started_at,
            elapsed_seconds=_seconds(now - self.cycle.started_at),
        )
        self._critical_change = True
        self._log(now, "fault_detected", fault_type=self.fault.fault_type.value)
        return [MachineEvent(EventType.FAULT_DETECTED, self.fault.as_dict())]

    def apply_config(self, now: datetime) -> list[MachineEvent]:
        """Reconcile state with the current configuration (after load/options)."""
        if not self.config.fault_monitoring and self.fault is not None:
            return self._clear_fault(now, "monitoring_disabled")
        return []

    def set_bag_door_opened(self, at: datetime, source: MaintenanceSource) -> None:
        """Set the maintenance timestamp from a non-observed source."""
        self.bag_door_opened_at = at
        self.bag_door_source = source
        self._critical_change = True
        self._log(at, "bag_door_timestamp_set", source=source.value)

    def prune(self, today: date) -> None:
        """Drop history older than the retention period."""
        cutoff = (today - timedelta(days=self.config.retention_days)).isoformat()
        self.daily_counts = {d: c for d, c in self.daily_counts.items() if d > cutoff}
        self.history = [r for r in self.history if r.date > cutoff]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _bound(
        value: datetime | None, lower: datetime | None, upper: datetime
    ) -> datetime:
        """Clamp a reported change time into the window it can belong to."""
        if value is None or value > upper:
            return upper
        if lower is not None and value < lower:
            return lower
        return value

    def _reconcile_main(
        self, state: DoorState, now: datetime, changed_at: datetime
    ) -> list[MachineEvent]:
        """Interpret the first valid observation after a gap."""
        gap = self.main.gap(now)
        within_grace = gap is not None and gap <= self.config.observation_grace
        gap_s = _seconds(gap) if gap is not None else None
        events: list[MachineEvent] = []
        self._log(
            now,
            "main_door_reconcile",
            state=state.value,
            gap_seconds=gap_s,
            cycle_active=self.cycle is not None,
            fault_active=self.fault is not None,
        )
        self.main.current = state

        if state is DoorState.OPEN:
            if self.cycle is not None:
                if within_grace:
                    events += self._finish_cycle(changed_at, now, gap=gap_s)
                else:
                    _LOGGER.debug(
                        "Discarding cleaning cycle started %s: door found open "
                        "after an observation gap of %ss, outcome unknown",
                        self.cycle.started_at,
                        gap_s,
                    )
                    self._log(now, "cycle_discarded", gap_seconds=gap_s)
                    self.cycle = None
                    self._critical_change = True
            if self.fault is not None:
                events += self._clear_fault(now, "main_door_opened")
            return events

        # Door is closed.
        if self.cycle is not None:
            if not within_grace and self.cycle.continuity_verified:
                self.cycle.continuity_verified = False
                self._critical_change = True
                self._log(now, "cycle_unverified", gap_seconds=gap_s)
            return events

        if self.main.last_valid is DoorState.OPEN and within_grace:
            self._start_cycle(changed_at, StartSource.OBSERVED, now)
        else:
            # Start unknown: last_changed is a lower bound on elapsed time,
            # good enough for the timeout but never counted as a clean.
            self._start_cycle(changed_at, StartSource.ESTIMATED, now)
        return events

    def _start_cycle(self, at: datetime, source: StartSource, now: datetime) -> None:
        self.cycle = ActiveCycle(started_at=at, start_source=source)
        self._critical_change = True
        self._log(now, "cycle_started", started_at=_iso(at), source=source.value)

    def _finish_cycle(
        self, at: datetime, now: datetime, gap: int | None
    ) -> list[MachineEvent]:
        cycle = self.cycle
        events: list[MachineEvent] = []
        if self.fault is not None:
            events += self._clear_fault(now, "main_door_opened")
        if cycle is None:
            return events
        self.cycle = None
        self._critical_change = True

        at = max(at, cycle.started_at)
        duration = _seconds(at - cycle.started_at)
        faulted = any(e.type is EventType.FAULT_CLEARED for e in events)
        if cycle.start_source is StartSource.ESTIMATED or not cycle.continuity_verified:
            outcome = CycleOutcome.UNVERIFIED
        elif faulted or (
            self.config.fault_monitoring
            and duration > self.config.cleaning_timeout.total_seconds()
        ):
            outcome = CycleOutcome.OVERTIME
        else:
            outcome = CycleOutcome.COMPLETED

        record = CycleRecord(
            started_at=cycle.started_at,
            completed_at=at,
            duration_seconds=duration,
            date=self._local_date(at).isoformat(),
            outcome=outcome,
            start_source=cycle.start_source,
            observation_gap_seconds=gap,
        )
        self._log(now, "cycle_finished", outcome=outcome.value, duration=duration)

        if self.config.statistics:
            self.history.append(record)
            if outcome is CycleOutcome.COMPLETED:
                self.last_cleaning_at = at
                self.last_cleaning_duration = duration
                self.total_cleans += 1
                self.daily_counts[record.date] = (
                    self.daily_counts.get(record.date, 0) + 1
                )
            self.prune(self._local_date(now))

        if outcome is CycleOutcome.COMPLETED:
            events.append(
                MachineEvent(
                    EventType.CLEANING_COMPLETED,
                    {
                        "started_at": _iso(cycle.started_at),
                        "completed_at": _iso(at),
                        "duration_seconds": duration,
                        "date": record.date,
                        "cleans_today": self.daily_counts.get(record.date, 0),
                        "observation_gap_seconds": gap,
                    },
                )
            )
        return events

    def _clear_fault(self, now: datetime, resolution: str) -> list[MachineEvent]:
        fault = self.fault
        if fault is None:
            return []
        self.fault = None
        self._critical_change = True
        self._log(now, "fault_cleared", resolution=resolution)
        return [
            MachineEvent(
                EventType.FAULT_CLEARED,
                {
                    **fault.as_dict(),
                    "cleared_at": _iso(now),
                    "resolution": resolution,
                    "active_seconds": _seconds(now - fault.detected_at),
                },
            )
        ]

    def _log(self, now: datetime, event: str, **details: Any) -> None:
        self.transitions.append({"at": _iso(now), "event": event, **details})

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def as_dict(self, now: datetime) -> dict[str, Any]:
        """Serialize persistent state."""
        return {
            "main_door": self.main.as_dict(now),
            "bag_door": self.bag.as_dict(now),
            "cycle": self.cycle.as_dict() if self.cycle else None,
            "fault": self.fault.as_dict() if self.fault else None,
            "statistics": {
                "last_cleaning_at": _iso(self.last_cleaning_at),
                "last_cleaning_duration": self.last_cleaning_duration,
                "total_cleans": self.total_cleans,
                "daily_counts": dict(self.daily_counts),
                "history": [r.as_dict() for r in self.history],
            },
            "maintenance": {
                "bag_door_opened_at": _iso(self.bag_door_opened_at),
                "source": self.bag_door_source,
            },
        }

    def load(self, data: dict[str, Any]) -> None:
        """Restore persistent state, skipping anything malformed."""
        self.main.load(data.get("main_door") or {})
        self.bag.load(data.get("bag_door") or {})
        self.cycle = ActiveCycle.from_dict(data["cycle"]) if data.get("cycle") else None
        self.fault = Fault.from_dict(data["fault"]) if data.get("fault") else None

        stats = data.get("statistics") or {}
        self.last_cleaning_at = _parse_dt(stats.get("last_cleaning_at"))
        duration = stats.get("last_cleaning_duration")
        self.last_cleaning_duration = duration if isinstance(duration, int) else None
        total = stats.get("total_cleans")
        self.total_cleans = total if isinstance(total, int) and total >= 0 else 0
        self.daily_counts = {
            str(k): v
            for k, v in (stats.get("daily_counts") or {}).items()
            if isinstance(v, int) and v >= 0
        }
        self.history = [
            record
            for raw in stats.get("history") or []
            if isinstance(raw, dict) and (record := CycleRecord.from_dict(raw))
        ]

        maintenance = data.get("maintenance") or {}
        self.bag_door_opened_at = _parse_dt(maintenance.get("bag_door_opened_at"))
        try:
            self.bag_door_source = (
                MaintenanceSource(maintenance["source"])
                if self.bag_door_opened_at
                else None
            )
        except KeyError, ValueError:
            self.bag_door_source = MaintenanceSource.MANUAL
