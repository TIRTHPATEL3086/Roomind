from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Anchor the .env at the repo ROOT, not at the process CWD.
#
# A bare env_file=".env" resolves relative to wherever the process was started.
# The API starts from backend/, alembic from backend/, the scripts from the
# root -- so `.env` was found only by the last of those. Everything else silently
# fell back to the defaults below, which is exactly the kind of bug that looks
# like "the config is being ignored": it IS being ignored, half the time.
#
# backend/app/config.py -> parents[2] is the repo root.
ROOT = Path(__file__).resolve().parents[2]
# Root first, then backend/, so a per-checkout backend/.env can still override.
_ENV_FILES = (ROOT / ".env", ROOT / "backend" / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILES, extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5173"

    database_url: str = "postgresql+asyncpg://roommind:roommind@localhost:5432/roommind"
    database_url_sync: str = "postgresql+psycopg2://roommind:roommind@localhost:5432/roommind"
    redis_url: str = "redis://localhost:6379/0"

    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_client_id: str = "roommind-backend"
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_qos: int = 1

    chroma_host: str = "localhost"
    chroma_port: int = 8001
    chroma_collection: str = "roommind_scene"
    embed_model: str = "all-MiniLM-L6-v2"
    # lexical | chroma. Lexical is the default - see rag_service._pick_backend
    # for the measurement behind that choice.
    rag_backend: str = "lexical"

    anthropic_api_key: str = ""
    groq_api_key: str = ""
    llm_provider: str = "auto"   # auto | groq | anthropic
    llm_model: str = "openai/gpt-oss-120b"
    llm_effort: str = "high"
    llm_max_tokens: int = 4096
    mock_llm: bool = False

    storage_root: str = "./storage"
    mesh_max_mb: int = 25

    # ── Robot: there is exactly one, ARIA ──
    robot_mode: str = "sim"
    robot_id: str = "aria"
    robot_display_name: str = "ARIA"
    robot_accent: str = "#3B82F6"
    robot_glow: str = "#22D3EE"
    robot_has_waist: bool = False
    robot_arm_reach_m: float = 0.24
    command_timeout_s: int = 30
    estop_latency_budget_ms: int = 200

    # ── Imagine: image -> 3D (spec 10B) ──
    imagine_enabled: bool = True
    imagine_backend: str = "auto"
    imagine_device: str = "cpu"
    imagine_timeout_s: int = 45
    imagine_max_upload_mb: int = 8
    imagine_max_tris: int = 40000
    imagine_max_glb_mb: int = 2
    imagine_rembg_model: str = "u2net"
    imagine_size_estimator: str = "vlm"
    imagine_model_cache: str = "./storage/genai3d_models"
    imagine_out_dir: str = "./storage/generated"

    geofence_margin_m: float = 0.15
    min_obstacle_dist_m: float = 0.25
    max_speed_mps: float = 0.45

    yolo_weights: str = "./ml/models/yolo_furniture_v1.pt"
    yolo_conf: float = 0.35
    device: str = "cpu"

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
