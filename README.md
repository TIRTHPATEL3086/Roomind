<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=4F46E5,8B5CF6,3B82F6,6366F1&height=250&section=header&text=RoomMind&fontSize=100&fontAlignY=38&desc=Intelligent%203D%20Spatial%20AI%20&%20Embodied%20Robotics&descAlignY=60&descAlign=50&fontColor=ffffff" width="100%" alt="Header" />

<br/>

<a href="https://github.com/TIRTHPATEL3086/Roomind" target="_blank">
  <img src="https://readme-typing-svg.demolab.com?font=Orbitron&weight=800&size=26&pause=1000&color=8B5CF6&center=true&vCenter=true&width=800&height=60&lines=TURN+ANY+ROOM+INTO+A+3D+WORLD;EMBODIED+HUMANOID+AI+(ARIA);GENERATIVE+IMAGE-TO-3D;SEMANTIC+SCENE+GRAPHS" alt="Typing SVG" />
</a>

<br/>

[![React](https://img.shields.io/badge/Frontend-React%2018%20%7C%20Vite%20%7C%20Three.js-61DAFB?style=for-the-badge&logo=react&logoColor=black)](https://reactjs.org/)
[![Python](https://img.shields.io/badge/Backend-Python%203.11%20%7C%20FastAPI-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org/)
[![AI/ML](https://img.shields.io/badge/AI%20Engine-PyTorch%20%7C%20Open3D-EE4C2C?style=for-the-badge&logo=pytorch&logoColor=white)](https://pytorch.org/)
[![Hardware](https://img.shields.io/badge/Robotics-Arduino%20UNO%20%7C%20MQTT-00979D?style=for-the-badge&logo=arduino&logoColor=white)](https://www.arduino.cc/)

<br/>

![Visitors](https://visitor-badge.laobi.icu/badge?page_id=TIRTHPATEL3086.Roomind&left_color=000&right_color=4F46E5&left_text=Platform%20Visits)
![GitHub Repo stars](https://img.shields.io/github/stars/TIRTHPATEL3086/Roomind?style=flat-square&color=8B5CF6)
![GitHub forks](https://img.shields.io/github/forks/TIRTHPATEL3086/Roomind?style=flat-square&color=6366F1)
![GitHub last commit](https://img.shields.io/github/last-commit/TIRTHPATEL3086/Roomind?style=flat-square&color=3B82F6)

<br/>

> **🚀 "Bridging the gap between physical reality and digital AI through Semantic Scene Graphs and Embodied Robotics."**

[🌐 **LIVE DEMO**](https://roommind-cpib.onrender.com/) &nbsp;•&nbsp; [▶️ **WATCH DEMO**](https://youtu.be/e9zUi_VcGUE)

</div>

---

<br/>

<div align="center">
  <img src="https://capsule-render.vercel.app/api?type=rect&color=8B5CF6&height=60&text=🏆%20HACKATHON%20WINNING%20USP&fontColor=ffffff&fontSize=30&stroke=000000" alt="USP Banner"/>
</div>

<br/>

Traditional smart home platforms are 2D dashboards blind to spatial reality. **RoomMind** completely reimagines environmental interaction with a **Semantic 3D Digital Twin** and an **Embodied AI Companion (ARIA)**:

- **🤖 Embodied Grounding (ARIA):** A humanoid AI that lives inside your digitized room. She knows where everything is, answers questions grounded in the actual room, turns her head to look, and physically drives over to point at objects.
- **📸 Generative Image-to-3D:** Hand ARIA an image (e.g., "a wooden chair") and she builds it in 3D, sizes it correctly, and places it in your room—immediately navigating to it as if it were physically scanned.
- **🗺️ Monocular & RGBD Reconstruction:** Scan your room with a phone; the system reconstructs a textured 3D environment complete with a fully navigable semantic scene graph.
- **⚡ Ultra-Low Latency Robotics:** Real-time 10Hz MQTT telemetry syncing a React Three Fiber rigged twin with physical Arduino hardware, including a 2ms emergency stop (E-stop).
- **🎬 GSAP Cinematic Layer:** Seamless, high-performance visual storytelling with code-split `<Canvas>` mounting for zero-flash handoffs.

<br/>

---

<div align="center">
  <img src="https://capsule-render.vercel.app/api?type=rect&color=6366F1&height=60&text=🎬%20APPLICATION%20SHOWCASE&fontColor=ffffff&fontSize=30&stroke=000000" alt="Showcase Banner"/>
</div>

<br/>

<div align="center">
# 3. Setup AI Services (Isolated Venvs)
py -3.11 -m venv genai3d\.venv
genai3d\.venv\Scripts\python -m pip install pillow numpy trimesh pygltflib pytest
py -3.11 -m venv reconstruction\.venv
reconstruction\.venv\Scripts\python -m pip install opencv-python-headless open3d numpy scipy trimesh pygltflib pillow pytest ultralytics --extra-index-url https://download.pytorch.org/whl/cpu
```
### 2️⃣ Launch System Components (Separate Terminals)
```powershell
# Terminal 1: MQTT Broker
py -3.11 -m venv .broker-venv
.broker-venv\Scripts\python -m pip install amqtt
.broker-venv\Scripts\amqtt.exe -c infra\amqtt\broker.yaml
# Terminal 2: FastAPI Backend
cd backend; .venv\Scripts\uvicorn.exe main:app --port 8000
# Terminal 3: Robot Simulator
backend\.venv\Scripts\python.exe firmware\sim\robot_sim.py
# Terminal 4: Frontend
cd frontend; npm install; npm run dev
# Visit http://localhost:5173
```
### 3️⃣ Interact via API (Try It!)
```powershell
# Ask ARIA about the room
curl -X POST localhost:8000/api/v1/chat -H "Content-Type: application/json" -d "{\"message\":\"how many chairs are there?\"}"
# Ask ARIA to point at something
curl -X POST localhost:8000/api/v1/chat -H "Content-Type: application/json" -d "{\"message\":\"where is the lamp?\"}"
# Emergency Stop
curl -X POST localhost:8000/api/v1/estop
```
<br/>
---
<div align="center">
<img src="https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=3B82F6,6366F1,8B5CF6&height=150&section=footer&text=Engineered%20for%20the%20Future%20of%20Spatial%20AI&fontSize=30&fontAlignY=60" width="100%" alt="Footer" />
*RoomMind — Breaking the boundaries between physical space and digital intelligence.* 🌌
</div>
