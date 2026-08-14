# RoomMind MQTT topic map — FROZEN CONTRACT (spec §8.5)

There is exactly one robot: `aria`. `{robot_id}` is always `aria`, but the topics keep the
placeholder so a second body could be added later without a contract change.

| Topic | Direction | QoS | Retain | Payload |
|---|---|---|---|---|
| `room/cmd/{robot_id}` | backend → robot | 1 | no | Command JSON (§8.3) |
| `room/cmd/{robot_id}/estop` | backend → robot | **0** | no | `{"stop":true,"ts":...}` (QoS 0 for lowest latency) |
| `room/path/{robot_id}` | backend → robot | 1 | no | `{"command_id":"...","waypoints":[[x,z],...],"speed":0.3}` |
| `room/telemetry/{robot_id}` | robot → backend | 0 | no | Telemetry JSON (§8.4), 10 Hz, includes `joints` |
| `room/status/{robot_id}` | robot → backend | 1 | **yes** | `{"online":true,"fw":"1.0.3","caps":[...]}` |
| `room/ack/{robot_id}` | robot → backend | 1 | no | `{"command_id":"...","status":"accepted\|rejected\|done\|failed","reason":"..."}` |
| `room/event/{robot_id}` | robot → backend | 1 | no | `{"type":"obstacle\|arrived\|photo","data":{...}}` |
| `room/scan/{room_id}` | backend → all | 1 | no | `{"type":"scene_updated"}` |

## LWT (Last Will & Testament)

ARIA connects with will topic `room/status/aria`, **retained**, payload `{"online":false}`.
This is how the backend detects a dead robot in under 5 seconds.

## Ordering rule that is load-bearing

The e-stop path publishes to `room/cmd/{robot_id}/estop` at **QoS 0, before any DB write**.
Persisting first adds latency to the one path where latency can break something physical.

## Idempotency

QoS 1 permits redelivery. Every handler must be idempotent on `command_id`.
