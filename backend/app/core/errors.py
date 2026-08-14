"""Domain errors. These map to HTTP status codes in the API layer - the services
layer raises them without knowing anything about HTTP (spec 1.4.2)."""
from __future__ import annotations


class RoomMindError(Exception):
    """Base for every domain error."""

    status_code = 500
    reason = "internal_error"


class NotFound(RoomMindError):
    status_code = 404
    reason = "not_found"


class InvalidCommand(RoomMindError):
    status_code = 422
    reason = "invalid_command"


class UnsupportedCapability(RoomMindError):
    """ARIA physically cannot do this - e.g. `gesture` with no waist servo fitted,
    or `imagine` with IMAGINE_ENABLED=false. Must stay visible in the UI."""

    status_code = 409
    reason = "unsupported_capability"


class RobotOffline(RoomMindError):
    status_code = 503
    reason = "robot_offline"


class NoPathFound(RoomMindError):
    status_code = 422
    reason = "no_path"


class Unsafe(RoomMindError):
    """The Safety Supervisor vetoed it."""

    status_code = 409
    reason = "unsafe"
