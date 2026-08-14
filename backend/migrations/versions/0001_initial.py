"""initial schema - rooms, scans, objects, waypoints, robots, commands,
telemetry, chat_messages, memories, imagine_jobs

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-09
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "rooms",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, server_default="Untitled Room"),
        sa.Column("mesh_path", sa.String(512)),
        sa.Column("navmesh_path", sa.String(512)),
        sa.Column("bounds", JSONB, nullable=False, server_default="{}"),
        sa.Column("floor_y", sa.Float, nullable=False, server_default="0"),
        sa.Column("robot_dock", JSONB, nullable=False, server_default="[0,0,0]"),
        sa.Column("scene_graph", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "scans",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("room_id", sa.String(64), sa.ForeignKey("rooms.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("progress", sa.Float, nullable=False, server_default="0"),
        sa.Column("stage", sa.String(64), nullable=False, server_default="idle"),
        sa.Column("frame_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.Text),
        sa.Column("frames_dir", sa.String(512)),
        sa.Column("intrinsics", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "objects",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("room_id", sa.String(64),
                  sa.ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column("position", JSONB, nullable=False),
        sa.Column("dimensions", JSONB, nullable=False),
        sa.Column("rotation_y", sa.Float, nullable=False, server_default="0"),
        sa.Column("color", sa.String(16), nullable=False, server_default="#888888"),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0"),
        sa.Column("is_obstacle", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("is_climbable", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("surface_height", sa.Float),
        sa.Column("source", sa.String(16), nullable=False, server_default="detected"),
        sa.Column("mesh_path", sa.String(512)),
        sa.Column("origin_image_path", sa.String(512)),
        sa.Column("scale_confidence", sa.Float, nullable=False, server_default="1"),
        sa.Column("attributes", JSONB, nullable=False, server_default="{}"),
        sa.Column("last_seen", TS, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_objects_room_id", "objects", ["room_id"])
    op.create_index("ix_objects_label", "objects", ["label"])
    op.create_index("ix_objects_room_label", "objects", ["room_id", "label"])

    op.create_table(
        "waypoints",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("room_id", sa.String(64),
                  sa.ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("position", JSONB, nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_waypoints_room_id", "waypoints", ["room_id"])

    op.create_table(
        "robots",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False, server_default="humanoid"),
        sa.Column("display_name", sa.String(64), nullable=False, server_default="ARIA"),
        sa.Column("accent_color", sa.String(16), nullable=False, server_default="#3B82F6"),
        sa.Column("capabilities", JSONB, nullable=False, server_default="[]"),
        sa.Column("persona", sa.String(32), nullable=False, server_default="aria"),
        sa.Column("online", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("battery", sa.Float, nullable=False, server_default="1"),
        sa.Column("pose", JSONB, nullable=False, server_default="{}"),
        sa.Column("joints", JSONB, nullable=False, server_default="{}"),
        sa.Column("emotion", sa.String(16), nullable=False, server_default="neutral"),
        sa.Column("state", sa.String(32), nullable=False, server_default="idle"),
        sa.Column("last_seen", TS),
    )

    op.create_table(
        "commands",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("room_id", sa.String(64), sa.ForeignKey("rooms.id", ondelete="SET NULL")),
        sa.Column("robot_id", sa.String(32), nullable=False, server_default="aria"),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("params", JSONB, nullable=False, server_default="{}"),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("reason", sa.Text),
        sa.Column("path", JSONB),
        sa.Column("source", sa.String(16), nullable=False, server_default="chat"),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_commands_robot_id", "commands", ["robot_id"])

    op.create_table(
        "telemetry",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("robot_id", sa.String(32), nullable=False),
        sa.Column("ts", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
    )
    op.create_index("ix_telemetry_robot_id", "telemetry", ["robot_id"])
    op.create_index("ix_telemetry_ts", "telemetry", ["ts"])

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("room_id", sa.String(64), sa.ForeignKey("rooms.id", ondelete="CASCADE")),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("meta", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_chat_messages_room_id", "chat_messages", ["room_id"])

    op.create_table(
        "memories",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("room_id", sa.String(64),
                  sa.ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_memories_room_id", "memories", ["room_id"])

    op.create_table(
        "imagine_jobs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("room_id", sa.String(64),
                  sa.ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Float, nullable=False, server_default="0"),
        sa.Column("stage", sa.String(32), nullable=False, server_default="idle"),
        sa.Column("backend", sa.String(32)),
        sa.Column("prompt", sa.Text),
        sa.Column("image_path", sa.String(512)),
        sa.Column("mesh_path", sa.String(512)),
        sa.Column("label", sa.String(64)),
        sa.Column("dimensions", JSONB),
        sa.Column("scale_confidence", sa.Float, nullable=False, server_default="0"),
        sa.Column("object_id", sa.String(64)),
        sa.Column("gen_ms", sa.Integer),
        sa.Column("error", sa.Text),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_imagine_jobs_room_id", "imagine_jobs", ["room_id"])


def downgrade() -> None:
    for t in (
        "imagine_jobs", "memories", "chat_messages", "telemetry", "commands",
        "robots", "waypoints", "objects", "scans", "rooms",
    ):
        op.drop_table(t)
