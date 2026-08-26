<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=4F46E5,8B5CF6,3B82F6,6366F1&height=280&section=header&text=RoomMind&fontSize=110&fontAlignY=38&desc=Intelligent%203D%20Spatial%20AI%20%7C%20Embodied%20Robotics&descAlignY=60&descAlign=50&fontColor=ffffff" width="100%" alt="RoomMind Banner" />

<br/>

<a href="https://roommind-cpib.onrender.com" target="_blank">
  <img src="https://readme-typing-svg.demolab.com?font=Orbitron&weight=800&size=24&pause=1000&color=8B5CF6&center=true&vCenter=true&width=800&height=60&lines=TURN+ANY+ROOM+INTO+A+3D+WORLD;EMBODIED+HUMANOID+AI+(ARIA);GENERATIVE+IMAGE-TO-3D+PIPELINE;SEMANTIC+SCENE+GRAPH+ENGINE;2ms+EMERGENCY+STOP+%E2%80%94+MEASURED" alt="Typing SVG" />
</a>

<br/>

[![Live Demo](https://img.shields.io/badge/🌐%20LIVE%20DEMO-roommind--cpib.onrender.com-6366F1?style=for-the-badge)](https://roommind-cpib.onrender.com)
[![Watch Demo](https://img.shields.io/badge/▶️%20WATCH%20DEMO-YouTube-FF0000?style=for-the-badge&logo=youtube)](https://youtu.be/e9zUi_VcGUE)

<br/>

[![React](https://img.shields.io/badge/React%2018-61DAFB?style=flat-square&logo=react&logoColor=black)](https://reactjs.org/)
[![Three.js](https://img.shields.io/badge/Three.js-000000?style=flat-square&logo=three.js&logoColor=white)](https://threejs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/Python%203.11-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org/)
[![PostgreSQL](https://img.shields.io/badge/Neon%20PostgreSQL-4169E1?style=flat-square&logo=postgresql&logoColor=white)](https://neon.tech/)
[![Render](https://img.shields.io/badge/Deployed%20on-Render-46E3B7?style=flat-square&logo=render&logoColor=white)](https://render.com/)
[![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white)](https://docker.com/)
[![Arduino](https://img.shields.io/badge/Arduino%20UNO-00979D?style=flat-square&logo=arduino&logoColor=white)](https://www.arduino.cc/)

<br/>

![Visitors](https://visitor-badge.laobi.icu/badge?page_id=TIRTHPATEL3086.Roomind&left_color=000&right_color=4F46E5&left_text=Platform%20Visits)
![GitHub stars](https://img.shields.io/github/stars/TIRTHPATEL3086/Roomind?style=flat-square&color=8B5CF6)
![GitHub forks](https://img.shields.io/github/forks/TIRTHPATEL3086/Roomind?style=flat-square&color=6366F1)
![GitHub last commit](https://img.shields.io/github/last-commit/TIRTHPATEL3086/Roomind?style=flat-square&color=3B82F6)

</div>

---

## ✨ What is RoomMind?

**RoomMind** transforms any physical room into an intelligent, interactive **3D Digital Twin** powered by an **Embodied AI Companion — ARIA**. Unlike traditional smart home apps that show you a 2D floor plan, RoomMind builds a full semantic 3D world from a simple phone scan, then lets you talk to a robot that *actually knows where everything is* and can physically walk over and point at it.

> **"Scan it once. Then talk to a robot that actually knows what's in it — and can walk over and point."**

---

## 🖥️ Live Application

<div align="center">

### 🌟 Cinematic Landing Page

<img src="docs/screenshots/room_dashboard.png" width="90%" style="border-radius:12px; box-shadow: 0 20px 60px rgba(99,102,241,0.4);" alt="RoomMind Landing Page" />

*GSAP-powered landing — 60fps 3D room preview, live stats: 9 joints · 60 FPS · &lt;3 min scan · 2ms E-stop*

<br/>

### 🤖 Live 3D Dashboard — ARIA in Action
<img src="docs/screenshots/cinematic_intro.png" width="90%" style="border-radius:12px; box-shadow: 0 20px 60px rgba(139,92,246,0.4);" alt="RoomMind 3D Dashboard" />

*ARIA navigating to `chair_01` — real-time joint telemetry HUD, semantic object labels, Quick Commands panel*

</div>

---

## 🏆 Key Capabilities

| Feature | Description |
|:---|:---|
| **🤖 Embodied ARIA** | Humanoid AI that lives in your 3D room. She navigates to objects, turns her head, waves, dances, and answers spatial questions. |
| **📸 Generative Image-to-3D** | Upload a photo of any object → ARIA builds it in 3D, correctly sizes it, and places it in the room instantly. |
| **🗺️ Semantic Scene Graph** | Every object has a full semantic record: position, dimensions, colour, surface height, obstacle status, and spatial relations. |
| **⚡ 2ms E-Stop** | Hardware emergency stop with sub-millisecond in-app latency, verified by the `X-Server-Time-Ms` middleware. |
| **📡 10Hz MQTT Telemetry** | Real-time bidirectional sync between the React Three Fiber twin and physical Arduino hardware. |
| **🧠 LLM Spatial Reasoning** | Groq-powered intent parsing with full scene-graph grounding — ARIA answers "where is the red chair near the table" correctly. |
| **🎬 GSAP Cinematic Layer** | 6-beat camera flight intro, code-split `<Canvas>` mounting for zero-flash route handoffs. |

---

## 🗺️ System Architecture

```mermaid
flowchart TB
    User(["👤 User"]):::external
    Hardware(["🤖 Arduino UNO\nPhysical Robot"]):::external
    Phone(["📱 Phone Scan\nRGBD / Monocular"]):::external

    subgraph Cloud ["☁️ Render Cloud Platform"]
        subgraph Frontend ["🖥️ Frontend — React 18 + Vite"]
            Landing["🎬 GSAP Cinematic Landing"]
            Dashboard["📊 3D Dashboard\nReact Three Fiber"]
            ChatUI["💬 ARIA Chat Panel"]
        end

        subgraph API ["⚙️ Backend — FastAPI (Python 3.11)"]
            Router["🔀 API Router\n/api/v1/*"]
            WS["🔌 WebSocket\nReal-time Events"]
            MQTT_Client["📡 MQTT Client\n10Hz Telemetry"]
        end

        subgraph Services ["🧠 Orchestration Services"]
            SceneService["🗺️ Scene Service\nIn-Memory Graph"]
            RobotService["🤖 Robot Manager\nKinematics + State"]
            LLMService["💡 LLM Service\nGroq / Intent Parse"]
            RAGService["📚 RAG Service\nLexical Search"]
        end

        MQTT_Broker["📡 amqtt Broker\nEmbedded MQTT"]
    end

    subgraph DataLayer ["🗄️ Data Layer"]
        DB[("🐘 Neon\nPostgreSQL")]
        SceneJSON["📄 contracts/\ndemo_room.json"]
    end

    subgraph ML ["🔬 AI / ML (Isolated Envs)"]
        Reconstruction["👁️ Open3D Pipeline\nRGBD Depth Fusion"]
        GenAI3D["✨ GenAI Image-to-3D\nTripoSR / Trellis"]
        YOLO["🎯 YOLOv8\nObject Detection"]
    end

    User -->|"HTTPS"| Landing
    User -->|"HTTPS"| Dashboard
    User -->|"WSS"| WS
    Phone -->|"Upload"| Reconstruction
    Hardware <-->|"MQTT"| MQTT_Broker

    Dashboard --> Router
    ChatUI --> Router
    Router --> SceneService
    Router --> RobotService
    Router --> LLMService
    WS --> RobotService
    MQTT_Client <--> MQTT_Broker
    MQTT_Client --> RobotService

    RobotService --> MQTT_Client
    LLMService --> RAGService
    RAGService --> SceneService
    SceneService --> SceneJSON
    SceneService <--> DB
    Reconstruction --> SceneService
    GenAI3D --> SceneService
    YOLO --> Reconstruction

    classDef external fill:#1e1b4b,stroke:#6366f1,color:#c4b5fd
```

---

## 🧠 AI Conversation Flow

```mermaid
sequenceDiagram
    participant U as 👤 User
    participant C as 💬 Chat UI
    participant API as ⚙️ FastAPI
    participant LLM as 🧠 Groq LLM
    participant Scene as 🗺️ Scene Graph
    participant Robot as 🤖 ARIA (MQTT)

    U->>C: "Where is the red chair?"
    C->>API: POST /api/v1/chat
    API->>Scene: Fetch room objects + relations
    Scene-->>API: Full semantic graph (9 objects)
    API->>LLM: Prompt with grounded context
    LLM-->>API: Intent: navigate + point_at chair_01
    API->>Robot: MQTT publish → navigate(chair_01)
    Robot-->>API: Telemetry: position, joints at 10Hz
    API-->>C: WebSocket: pose update stream
    C-->>U: ARIA walks to chair_01 in 3D twin
```

---

## 🏗️ Monorepo Layout

```
roommind/
├── 🖥️  frontend/          # React 18 + Vite + Three.js SPA
│   ├── src/
│   │   ├── components/    # Dashboard, Chat, Imagine, HUD panels
│   │   ├── three/         # SceneRoot, RobotAvatar, CameraRig, R3F
│   │   ├── motion/        # GSAP cinematic layer, smooth scroll
│   │   ├── store/         # Zustand: scene, robot, chat, UI state
│   │   └── api/           # REST client + WebSocket hooks
│   └── public/models/     # 100+ Kenney GLB furniture models
│
├── ⚙️  backend/           # FastAPI + Uvicorn (Python 3.11)
│   ├── app/
│   │   ├── api/v1/        # REST: rooms, chat, robot, imagine, health
│   │   ├── services/      # Scene, Robot, LLM, RAG, MQTT services
│   │   ├── db/            # SQLAlchemy models + Alembic migrations
│   │   └── core/          # Event bus, enrich, errors
│   └── alembic/           # DB migrations (10 tables)
│
├── 📄  contracts/          # JSON scene graph schemas + demo fixtures
│   ├── demo_room.json      # Primary living room demo
│   ├── demo_room_bedroom.json
│   ├── demo_room_office.json
│   └── scene_graph.schema.json
│
├── 🔬  reconstruction/    # Open3D RGBD pipeline (isolated venv)
├── ✨  genai3d/           # Image-to-3D pipeline (isolated venv)
├── 🤖  firmware/          # Arduino UNO firmware + ARIA simulator
├── 📡  infra/amqtt/       # Embedded MQTT broker config
├── 🐳  Dockerfile         # Multi-stage: Node build → Python serve
└── 📦  render.yaml        # Render Blueprint deployment
```

---

## 🛠️ Technology Stack

<div align="center">
<img src="https://skillicons.dev/icons?i=react,typescript,vite,tailwind,threejs,python,fastapi,pytorch,opencv,arduino,docker,postgres&perline=6" alt="Tech Stack" />
</div>

<br/>

| Layer | Technology | Purpose |
|:---|:---|:---|
| **Frontend** | `React 18`, `Three.js`, `React Three Fiber`, `GSAP` | 3D twin, cinematic landing, zero-flash route handoffs |
| **Backend** | `Python 3.11`, `FastAPI`, `Uvicorn`, `WebSocket` | Async REST + real-time event streaming |
| **AI / LLM** | `Groq API`, `LLM Intent Parsing`, `Lexical RAG` | Spatial question answering, grounded command dispatch |
| **Computer Vision** | `Open3D`, `OpenCV`, `YOLOv8`, `MiDaS` | RGBD fusion, object detection, monocular depth |
| **Generative 3D** | `TripoSR`, `Trellis`, `PyTorch` | Image → 3D mesh → auto-placed in scene |
| **Database** | `Neon PostgreSQL`, `SQLAlchemy`, `Alembic` | Persistent scene graph, robot state, chat history |
| **IoT / Hardware** | `MQTT (amqtt)`, `Arduino UNO`, `paho-mqtt` | 10Hz bidirectional telemetry stream |
| **Infrastructure** | `Docker`, `Render`, `GitHub Actions` | Multi-stage build, cloud deployment |

---
<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=3B82F6,6366F1,8B5CF6&height=150&section=footer&text=Engineered%20for%20the%20Future%20of%20Spatial%20AI&fontSize=28&fontAlignY=60&fontColor=ffffff" width="100%" alt="Footer" />



*RoomMind — Breaking the boundaries between physical space and digital intelligence.* 🌌

</div>
