"""
UDP networking for LAN multiplayer.

Protocol: JSON packets over UDP.
  - The host runs an authoritative server (enemy AI, hit detection, damage).
  - Clients send their position/angle/shoot state each frame.
  - Server broadcasts the full world state ~30 times per second.
"""

import json
import socket
import threading
import time
import math

from enemy_ai import ServerEnemyAI

BROADCAST_PORT = 5555
BUFFER_SIZE = 8192
SERVER_TICK_RATE = 30  # broadcasts per second

MAX_DEPTH = 50

# Weapon definitions (mirrored from main.py for server-side hit processing)
WPN_RIFLE = 0
WPN_PISTOL = 1
WPN_KNIFE = 2

SERVER_WEAPONS = {
    WPN_RIFLE:  {"damage": 2, "ammo_cost": 1, "range": MAX_DEPTH, "spread": 0.03},
    WPN_PISTOL: {"damage": 1, "ammo_cost": 1, "range": MAX_DEPTH, "spread": 0.06},
    WPN_KNIFE:  {"damage": 3, "ammo_cost": 0, "range": 1.5,       "spread": 0.2},
}

SPAWN_POSITIONS = [
    (2.0, 2.0),
    (13.5, 2.0),
    (2.0, 13.5),
    (13.5, 13.5),
]

PLAYER_COLORS = [
    (50, 200, 50),   # green
    (50, 120, 220),  # blue
    (220, 180, 50),  # yellow
    (200, 50, 200),  # purple
]


def _send(sock, data, addr):
    """Send a JSON packet."""
    try:
        raw = json.dumps(data, separators=(",", ":")).encode()
        sock.sendto(raw, addr)
    except OSError:
        pass


def _recv(sock):
    """Non-blocking receive. Returns (data_dict, addr) or (None, None)."""
    try:
        raw, addr = sock.recvfrom(BUFFER_SIZE)
        return json.loads(raw.decode()), addr
    except (BlockingIOError, OSError, json.JSONDecodeError):
        return None, None


# ---------------------------------------------------------------------------
# Server (runs on the host's machine alongside their game client)
# ---------------------------------------------------------------------------
class GameServer:
    def __init__(self, world_map, spawn_enemies_fn, player_spawn=None):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", BROADCAST_PORT))
        self.sock.setblocking(False)

        self.world_map = world_map
        self.map_rows = len(world_map)
        self.map_cols = len(world_map[0])
        self.spawn_enemies_fn = spawn_enemies_fn
        # Use provided spawn or fall back to SPAWN_POSITIONS
        self.player_spawn = player_spawn or SPAWN_POSITIONS[0]

        self.players = {}       # id -> {x, y, angle, health, ammo, score, alive, addr, name, last_seen}
        self.next_id = 0
        self.addr_to_id = {}    # addr -> player_id

        self.enemies = []       # list of dicts: {x, y, hp, alive, dmg_timer, target_id}
        self._spawn_enemy_wave()

        self.running = False
        self.thread = None

    def _spawn_enemy_wave(self):
        raw = self.spawn_enemies_fn()
        self.enemies = [
            {"x": e.x, "y": e.y, "hp": e.health, "alive": True, "dmg_timer": 0.0}
            for e in raw
        ]
        self.enemy_ais = [
            ServerEnemyAI(e.x, e.y) for e in raw
        ]

    def _is_wall(self, x, y):
        col, row = int(x), int(y)
        if 0 <= row < self.map_rows and 0 <= col < self.map_cols:
            return self.world_map[row][col] != 0
        return True

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
        self.sock.close()

    def register_host(self, name="Host"):
        """Register the host as player 0."""
        pid = self._add_player(("127.0.0.1", 0), name)
        return pid

    def _add_player(self, addr, name):
        pid = self.next_id
        self.next_id += 1
        sx, sy = self.player_spawn
        self.players[pid] = {
            "x": sx, "y": sy, "angle": 0.0,
            "health": 100, "ammo": 50, "score": 0, "alive": True,
            "addr": addr, "name": name,
            "shoot": False, "shoot_processed": True,
            "weapon": WPN_PISTOL,
            "damage_cooldown": 0.0,
            "last_seen": time.time(),
        }
        self.addr_to_id[addr] = pid
        return pid

    def update_host_state(self, x, y, angle, shoot, weapon=WPN_PISTOL):
        """Called by the host's game loop to push its own state."""
        if 0 in self.players:
            p = self.players[0]
            p["x"] = x
            p["y"] = y
            p["angle"] = angle
            p["weapon"] = weapon
            if shoot and p["shoot_processed"]:
                p["shoot"] = True
                p["shoot_processed"] = False
            p["last_seen"] = time.time()

    def get_world_state(self):
        """Called by the host's game loop to get the current state for rendering."""
        return self._build_world_packet()

    def _build_world_packet(self):
        players = {}
        for pid, p in self.players.items():
            players[str(pid)] = {
                "x": round(p["x"], 3), "y": round(p["y"], 3),
                "a": round(p["angle"], 3),
                "hp": p["health"], "ammo": p["ammo"],
                "score": p["score"], "alive": p["alive"],
                "name": p["name"],
            }
        enemies = [
            {"x": round(e["x"], 3), "y": round(e["y"], 3),
             "hp": e["hp"], "alive": e["alive"],
             "dt": round(e["dmg_timer"], 2)}
            for e in self.enemies
        ]
        return {"t": "world", "players": players, "enemies": enemies}

    def _process_incoming(self):
        for _ in range(100):
            data, addr = _recv(self.sock)
            if data is None:
                break

            msg_type = data.get("t")

            if msg_type == "join":
                if addr not in self.addr_to_id:
                    pid = self._add_player(addr, data.get("name", "Player"))
                else:
                    pid = self.addr_to_id[addr]
                sx, sy = self.player_spawn
                _send(self.sock, {"t": "welcome", "id": pid, "x": sx, "y": sy}, addr)

            elif msg_type == "state":
                pid = self.addr_to_id.get(addr)
                if pid is not None and pid in self.players:
                    p = self.players[pid]
                    p["x"] = data.get("x", p["x"])
                    p["y"] = data.get("y", p["y"])
                    p["angle"] = data.get("a", p["angle"])
                    p["weapon"] = data.get("w", p["weapon"])
                    if data.get("shoot") and p["shoot_processed"]:
                        p["shoot"] = True
                        p["shoot_processed"] = False
                    p["last_seen"] = time.time()

            elif msg_type == "leave":
                pid = self.addr_to_id.pop(addr, None)
                if pid is not None:
                    self.players.pop(pid, None)

    def _update_enemies(self, dt):
        # Find nearest alive player for each enemy
        alive_players = [(pid, p) for pid, p in self.players.items() if p["alive"]]

        for i, e in enumerate(self.enemies):
            if not e["alive"]:
                continue
            e["dmg_timer"] = max(0, e["dmg_timer"] - dt)

            if not alive_players:
                continue

            # Find nearest player
            best_dist = float("inf")
            best_px, best_py = e["x"], e["y"]
            for pid, p in alive_players:
                d = math.hypot(p["x"] - e["x"], p["y"] - e["y"])
                if d < best_dist:
                    best_dist = d
                    best_px, best_py = p["x"], p["y"]

            # Use AI for movement
            if i < len(self.enemy_ais):
                ai = self.enemy_ais[i]
                ai.update(e, best_px, best_py, dt, self.world_map,
                          self._is_wall, best_dist)

        # Enemy contact damage to players
        for pid, p in alive_players:
            p["damage_cooldown"] = max(0, p["damage_cooldown"] - dt)
            for e in self.enemies:
                if not e["alive"]:
                    continue
                d = math.hypot(e["x"] - p["x"], e["y"] - p["y"])
                if d < 0.8 and p["damage_cooldown"] <= 0:
                    p["health"] -= 10
                    p["damage_cooldown"] = 0.5
                    if p["health"] <= 0:
                        p["health"] = 0
                        p["alive"] = False

    def _process_shots(self):
        for pid, p in self.players.items():
            if not p["alive"] or not p["shoot"]:
                continue
            p["shoot"] = False
            p["shoot_processed"] = True

            wpn = SERVER_WEAPONS.get(p["weapon"], SERVER_WEAPONS[WPN_PISTOL])

            if wpn["ammo_cost"] > 0 and p["ammo"] < wpn["ammo_cost"]:
                continue
            p["ammo"] -= wpn["ammo_cost"]

            # Find enemy in crosshair
            best_enemy = None
            best_dist = float("inf")
            for e in self.enemies:
                if not e["alive"]:
                    continue
                dx = e["x"] - p["x"]
                dy = e["y"] - p["y"]
                dist = math.hypot(dx, dy)
                if dist > wpn["range"]:
                    continue
                angle = math.atan2(dy, dx)
                diff = angle - p["angle"]
                while diff > math.pi:
                    diff -= 2 * math.pi
                while diff < -math.pi:
                    diff += 2 * math.pi
                hit_threshold = max(wpn["spread"], 0.3 / max(dist, 0.1))
                if abs(diff) < hit_threshold and dist < best_dist:
                    best_dist = dist
                    best_enemy = e

            if best_enemy:
                best_enemy["hp"] -= wpn["damage"]
                best_enemy["dmg_timer"] = 0.15
                if best_enemy["hp"] <= 0:
                    best_enemy["alive"] = False
                    p["score"] += 100

    def _check_wave_respawn(self):
        if all(not e["alive"] for e in self.enemies):
            self._spawn_enemy_wave()
            for p in self.players.values():
                p["ammo"] = min(p["ammo"] + 20, 99)

    def _drop_stale_clients(self):
        now = time.time()
        stale = [pid for pid, p in self.players.items()
                 if pid != 0 and now - p["last_seen"] > 5.0]
        for pid in stale:
            addr = self.players[pid].get("addr")
            self.players.pop(pid, None)
            if addr:
                self.addr_to_id.pop(addr, None)

    def _broadcast(self):
        world = self._build_world_packet()
        raw = json.dumps(world, separators=(",", ":")).encode()
        for pid, p in self.players.items():
            if pid == 0:
                continue  # host reads state directly
            try:
                self.sock.sendto(raw, p["addr"])
            except OSError:
                pass

    def _loop(self):
        last_tick = time.time()
        tick_interval = 1.0 / SERVER_TICK_RATE
        while self.running:
            now = time.time()
            dt = now - last_tick
            last_tick = now

            self._process_incoming()
            self._process_shots()
            self._update_enemies(dt)
            self._check_wave_respawn()
            self._drop_stale_clients()
            self._broadcast()

            elapsed = time.time() - now
            sleep_time = tick_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)


# ---------------------------------------------------------------------------
# Client (used by joining players)
# ---------------------------------------------------------------------------
class GameClient:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)
        self.server_addr = None
        self.my_id = None
        self.connected = False
        self.world = None  # latest world state from server

    def connect(self, host_ip, name="Player"):
        self.server_addr = (host_ip, BROADCAST_PORT)
        _send(self.sock, {"t": "join", "name": name}, self.server_addr)

    def send_state(self, x, y, angle, shoot, weapon=WPN_PISTOL):
        if self.server_addr:
            _send(self.sock, {
                "t": "state",
                "x": round(x, 3), "y": round(y, 3),
                "a": round(angle, 3), "shoot": shoot,
                "w": weapon,
            }, self.server_addr)

    def poll(self):
        """Process incoming packets. Call every frame."""
        for _ in range(50):
            data, addr = _recv(self.sock)
            if data is None:
                break
            msg_type = data.get("t")
            if msg_type == "welcome":
                self.my_id = data["id"]
                self.connected = True
            elif msg_type == "world":
                self.world = data

    def disconnect(self):
        if self.server_addr:
            _send(self.sock, {"t": "leave"}, self.server_addr)
        self.sock.close()


def get_local_ip():
    """Get this machine's LAN IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"
