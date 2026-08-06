# Signaling Protocol

Simple JSON messages over a single WebSocket connection.

Default signaling URL: `ws://<host>:8080/ws`

## Roles

| Role     | Identity   | Behavior                                      |
|----------|------------|-----------------------------------------------|
| Desktop  | `host`     | WebRTC offerer; sends screen track            |
| Android  | `viewer`   | WebRTC answerer; receives and displays video  |

Only **one** viewer is allowed. A second viewer is rejected with `error`.

## Message envelope

```json
{
  "type": "<message-type>",
  "...": "type-specific fields"
}
```

## Messages

### `hello` (client → server)

Register role after connect.

```json
{ "type": "hello", "role": "host" | "viewer" }
```

### `ready` (server → client)

Sent when the peer of the other role is connected (or when you connect and the other is already present).

```json
{ "type": "ready", "role": "host" | "viewer" }
```

`role` is the role that just became ready (the remote peer).

### `offer` (host → server → viewer)

```json
{
  "type": "offer",
  "sdp": "<SDP string>"
}
```

### `answer` (viewer → server → host)

```json
{
  "type": "answer",
  "sdp": "<SDP string>"
}
```

### `ice` (either → server → peer)

```json
{
  "type": "ice",
  "candidate": "<candidate string or null>",
  "sdpMid": "<mid or null>",
  "sdpMLineIndex": <int or null>
}
```

A message with `"candidate": null` means end-of-candidates.

### `stats` (optional, either direction)

Used for latency overlay. Host may echo viewer NTP-style timestamps.

```json
{
  "type": "stats",
  "t_client": <ms epoch>,
  "t_server": <ms epoch, optional>
}
```

### `error` (server → client)

```json
{
  "type": "error",
  "message": "<human-readable reason>",
  "code": "viewer_busy" | "invalid" | "peer_disconnected"
}
```

### `bye` (server → client)

Peer disconnected; clients should tear down the WebRTC session and wait to reconnect.

```json
{ "type": "bye", "reason": "peer_disconnected" }
```

## Connection flow

1. Host connects, sends `{ "type": "hello", "role": "host" }`.
2. Viewer connects, sends `{ "type": "hello", "role": "viewer" }`.
3. Server sends `ready` to both.
4. Host creates offer, sends `offer`.
5. Viewer sets remote description, creates answer, sends `answer`.
6. Both sides exchange `ice` until connected.
7. On disconnect, server sends `bye` to the remaining peer.

## ADB port forwarding (signaling only)

```bash
adb reverse tcp:8080 tcp:8080
```

Android app connects to `ws://127.0.0.1:8080/ws`.  
WebRTC media still uses host LAN ICE candidates (same Wi‑Fi).
