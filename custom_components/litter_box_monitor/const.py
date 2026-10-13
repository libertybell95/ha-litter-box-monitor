"""Constants for the Litter Box Monitor integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "litter_box_monitor"
VERSION: Final = "0.1.0"

# Configuration keys (entry.data)
CONF_MAIN_DOOR: Final = "main_door_entity"
CONF_BAG_DOOR: Final = "bag_door_entity"
CONF_INITIAL_BAG_DOOR_OPENED: Final = "initial_bag_door_opened"
CONF_INITIALIZE_BAG_DOOR_NOW: Final = "initialize_bag_door_now"

# Option keys (entry.options)
CONF_CLEANING_TIMEOUT: Final = "cleaning_timeout"
CONF_FAULT_MONITORING: Final = "fault_monitoring"
CONF_MAINTENANCE_TRACKING: Final = "maintenance_tracking"
CONF_MAINTENANCE_THRESHOLD: Final = "maintenance_threshold_days"
CONF_STATISTICS: Final = "statistics"
CONF_FAULT_EVENTS: Final = "fault_events"
CONF_HISTORY_RETENTION: Final = "history_retention_days"

DEFAULT_NAME: Final = "Litter Box"
DEFAULT_MAIN_DOOR: Final = "binary_sensor.cat_litter_box_main_door"
DEFAULT_BAG_DOOR: Final = "binary_sensor.cat_litter_box_bag_door"
DEFAULT_CLEANING_TIMEOUT_MIN: Final = 5
DEFAULT_MAINTENANCE_THRESHOLD: Final = 0  # 0 = disabled
DEFAULT_HISTORY_RETENTION: Final = 90
MIN_HISTORY_RETENTION: Final = 30
MAX_HISTORY_RETENTION: Final = 365

DEFAULT_OPTIONS: Final = {
    CONF_CLEANING_TIMEOUT: DEFAULT_CLEANING_TIMEOUT_MIN,
    CONF_FAULT_MONITORING: True,
    CONF_MAINTENANCE_TRACKING: True,
    CONF_MAINTENANCE_THRESHOLD: DEFAULT_MAINTENANCE_THRESHOLD,
    CONF_STATISTICS: True,
    CONF_FAULT_EVENTS: True,
    CONF_HISTORY_RETENTION: DEFAULT_HISTORY_RETENTION,
}

# Observation gaps (sensor offline, Home Assistant restart) no longer than this
# are treated as a temporary disconnection: cycle continuity is assumed and the
# transition seen afterwards is attributed to the moment the sensor reconnected.
OBSERVATION_GRACE: Final = timedelta(seconds=60)

# Inputs unavailable (or missing) for longer than this raise a repair issue.
UNAVAILABLE_REPAIR_DELAY: Final = timedelta(minutes=30)

# Window used by the Average Cleaning Duration sensor.
AVERAGE_WINDOW_DAYS: Final = 30

# Number of recent internal transitions kept in memory for diagnostics.
TRANSITION_LOG_SIZE: Final = 50

# Interval for refreshing Current Cleaning Duration while a cycle is running.
CURRENT_DURATION_INTERVAL: Final = timedelta(seconds=10)

STORAGE_VERSION: Final = 1
# Delay used for non-critical writes; critical transitions are saved immediately.
STORAGE_SAVE_DELAY: Final = 30

# Home Assistant bus events (for automations).
EVENT_CLEANING_COMPLETED: Final = f"{DOMAIN}_cleaning_completed"
EVENT_FAULT_DETECTED: Final = f"{DOMAIN}_fault_detected"
EVENT_FAULT_CLEARED: Final = f"{DOMAIN}_fault_cleared"
EVENT_BAG_DOOR_OPENED: Final = f"{DOMAIN}_bag_door_opened"

# Services
SERVICE_SET_BAG_DOOR_OPENED: Final = "set_bag_door_opened"
ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
ATTR_TIMESTAMP: Final = "timestamp"

# Repair issue id prefixes
ISSUE_ENTITY_MISSING: Final = "entity_missing"
ISSUE_ENTITY_UNAVAILABLE: Final = "entity_unavailable"
