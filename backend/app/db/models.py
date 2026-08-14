from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


class Room(Base):
    __tablename__ = "rooms"
    id:           Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    name:         Mapped[str] = mapped_column(String(128), default="Untitled Room")
    mesh_path:    Mapped[str | None] = mapped_column(String(512))
    navmesh_path: Mapped[str | None] = mapped_column(String(512))
    bounds:       Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    floor_y:      Mapped[float] = mapped_column(Float, default=0.0)
    robot_dock:   Mapped[list[float]] = mapped_column(JSONB, default=lambda: [0.0, 0.0, 0.0])
    scene_graph:  Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at:   Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at:   Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    objects:   Mapped[list["SceneObject"]] = relationship(
        back_populates="room", cascade="all, delete-orphan"
    )
    waypoints: Mapped[list["Waypoint"]] = relationship(
        back_populates="room", cascade="all, delete-orphan"
    )


class Scan(Base):
    __tablename__ = "scans"
    id:          Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    room_id:     Mapped[str | None] = mapped_column(ForeignKey("rooms.id", ondelete="SET NULL"))
    status:      Mapped[str] = mapped_column(String(32), default="pending")
    # pending|uploading|queued|processing|completed|failed
    progress:    Mapped[float] = mapped_column(Float, default=0.0)
    stage:       Mapped[str] = mapped_column(String(64), default="idle")
    frame_count: Mapped[int] = mapped_column(Integer, default=0)
    error:       Mapped[str | None] = mapped_column(Text)
    frames_dir:  Mapped[str | None] = mapped_column(String(512))
    intrinsics:  Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at:  Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SceneObject(Base):
    __tablename__ = "objects"
    id:         Mapped[str] = mapped_column(String(64), primary_key=True)   # e.g. "table_01"
    room_id:    Mapped[str] = mapped_column(
        ForeignKey("rooms.id", ondelete="CASCADE"), index=True
    )
    label:      Mapped[str] = mapped_column(String(64), index=True)
    position:   Mapped[list[float]] = mapped_column(JSONB)   # [x,y,z] centre, metres
    dimensions: Mapped[list[float]] = mapped_column(JSONB)   # [w,h,d]
    rotation_y: Mapped[float] = mapped_column(Float, default=0.0)  # yaw radians
    color:      Mapped[str] = mapped_column(String(16), default="#888888")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    is_obstacle:   Mapped[bool] = mapped_column(Boolean, default=True)
    is_climbable:  Mapped[bool] = mapped_column(Boolean, default=False)
    surface_height: Mapped[float | None] = mapped_column(Float)
    # ── generated-object fields (spec 10B) ──
    source:            Mapped[str] = mapped_column(String(16), default="detected")
    mesh_path:         Mapped[str | None] = mapped_column(String(512))
    origin_image_path: Mapped[str | None] = mapped_column(String(512))
    scale_confidence:  Mapped[float] = mapped_column(Float, default=1.0)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    last_seen:  Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    room: Mapped[Room] = relationship(back_populates="objects")

    __table_args__ = (Index("ix_objects_room_label", "room_id", "label"),)


class Waypoint(Base):
    __tablename__ = "waypoints"
    id:       Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    room_id:  Mapped[str] = mapped_column(
        ForeignKey("rooms.id", ondelete="CASCADE"), index=True
    )
    name:     Mapped[str] = mapped_column(String(64))
    position: Mapped[list[float]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    room: Mapped[Room] = relationship(back_populates="waypoints")


class Robot(Base):
    """There is exactly one row: id='aria'. The table stays plural/generic so a second
    body could be added later without a migration - do not collapse it into a singleton."""

    __tablename__ = "robots"
    id:           Mapped[str] = mapped_column(String(32), primary_key=True)   # 'aria'
    kind:         Mapped[str] = mapped_column(String(32), default="humanoid")
    display_name: Mapped[str] = mapped_column(String(64), default="ARIA")
    accent_color: Mapped[str] = mapped_column(String(16), default="#3B82F6")
    capabilities: Mapped[list[str]] = mapped_column(JSONB, default=list)
    persona:      Mapped[str] = mapped_column(String(32), default="aria")
    online:       Mapped[bool] = mapped_column(Boolean, default=False)
    battery:      Mapped[float] = mapped_column(Float, default=1.0)
    pose:         Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # {x,y,z,yaw}
    joints:       Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # 8.3.2, degrees
    emotion:      Mapped[str] = mapped_column(String(16), default="neutral")
    state:        Mapped[str] = mapped_column(String(32), default="idle")
    last_seen:    Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Command(Base):
    __tablename__ = "commands"
    id:       Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    room_id:  Mapped[str | None] = mapped_column(ForeignKey("rooms.id", ondelete="SET NULL"))
    robot_id: Mapped[str] = mapped_column(String(32), index=True, default="aria")
    action:   Mapped[str] = mapped_column(String(32))
    params:   Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status:   Mapped[str] = mapped_column(String(32), default="queued")
    # queued|planning|dispatched|executing|succeeded|failed|cancelled|rejected
    reason:   Mapped[str | None] = mapped_column(Text)
    path:     Mapped[list[list[float]] | None] = mapped_column(JSONB)
    source:   Mapped[str] = mapped_column(String(16), default="chat")  # chat|ui|api|voice
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Telemetry(Base):
    __tablename__ = "telemetry"
    id:       Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    robot_id: Mapped[str] = mapped_column(String(32), index=True)
    ts:       Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    payload:  Mapped[dict[str, Any]] = mapped_column(JSONB)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id:      Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    room_id: Mapped[str | None] = mapped_column(
        ForeignKey("rooms.id", ondelete="CASCADE"), index=True
    )
    role:    Mapped[str] = mapped_column(String(16))   # user|assistant|system|tool
    content: Mapped[str] = mapped_column(Text)
    meta:    Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Memory(Base):
    __tablename__ = "memories"
    id:      Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    room_id: Mapped[str] = mapped_column(
        ForeignKey("rooms.id", ondelete="CASCADE"), index=True
    )
    kind:    Mapped[str] = mapped_column(String(32))  # object_location|preference|event|note
    text:    Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ImagineJob(Base):
    """One image -> 3D generation job (spec 10B)."""

    __tablename__ = "imagine_jobs"
    id:      Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    room_id: Mapped[str] = mapped_column(
        ForeignKey("rooms.id", ondelete="CASCADE"), index=True
    )
    status:  Mapped[str] = mapped_column(String(32), default="queued")
    # queued|preparing|understanding|generating|cleaning|texturing|scaling
    # |exporting|preview|committed|failed
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    stage:    Mapped[str] = mapped_column(String(32), default="idle")
    backend:  Mapped[str | None] = mapped_column(String(32))   # triposr|trellis|proxy
    prompt:   Mapped[str | None] = mapped_column(Text)
    image_path: Mapped[str | None] = mapped_column(String(512))
    mesh_path:  Mapped[str | None] = mapped_column(String(512))
    label:      Mapped[str | None] = mapped_column(String(64))
    dimensions: Mapped[list[float] | None] = mapped_column(JSONB)   # [w,h,d] metres
    scale_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    object_id: Mapped[str | None] = mapped_column(String(64))       # set on commit
    gen_ms:    Mapped[int | None] = mapped_column(Integer)
    error:     Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
