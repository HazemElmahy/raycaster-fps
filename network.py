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
DISCOVERY_PORT = 5556  # separate port for LAN game discovery
MULTICAST_GROUP = "239.255.77.77"  # multicast address for discovery (works across ZeroTier/VPN)
BUFFER_SIZE = 8192
SERVER_TICK_RATE = 30  # broadcasts per second
BEACON_INTERVAL = 1.0  # seconds between discovery beacons

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
    def __init__(self, world_map, spawn_enemies_fn, player_spawn=None, host_name="Game", dungeon_seed=None):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", BROADCAST_PORT))
        self.sock.setblocking(False)

        self.host_name = host_name
        self.dungeon_seed = dungeon_seed
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

        self.in_lobby = True    # True = waiting in lobby, False = game running
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

    def start_game(self):
        """Transition from lobby to active game."""
        self.in_lobby = False

    def get_lobby_players(self):
        """Return list of player info for lobby display."""
        return [
            {"id": pid, "name": p["name"]}
            for pid, p in sorted(self.players.items())
        ]

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
        return {"t": "world", "players": players, "enemies": enemies, "lobby": self.in_lobby}

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
                _send(self.sock, {"t": "welcome", "id": pid, "x": sx, "y": sy, "seed": self.dungeon_seed}, addr)

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

            elif msg_type == "ping":
                # Respond to discovery scan with game info
                _send(self.sock, {
                    "t": "pong",
                    "name": self.host_name,
                    "ip": get_local_ip(),
                    "port": BROADCAST_PORT,
                    "players": len(self.players),
                }, addr)

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
            if not self.in_lobby:
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
        self.in_lobby = True

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
                self.spawn_x = data.get("x", 2.0)
                self.spawn_y = data.get("y", 2.0)
                self.dungeon_seed = data.get("seed")
                self.connected = True
            elif msg_type == "world":
                self.world = data
                self.in_lobby = data.get("lobby", False)

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


# ---------------------------------------------------------------------------
# LAN Discovery — host broadcasts beacons, clients listen
# ---------------------------------------------------------------------------
class DiscoveryBeacon:
    """Sends game discovery beacons via multicast + broadcast."""

    def __init__(self, host_name, player_count_fn):
        self.host_name = host_name
        self.player_count_fn = player_count_fn
        self.ip = get_local_ip()

        # Multicast socket (works across ZeroTier / VPN / virtual LANs)
        self.msock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.msock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 4)
        self.msock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Broadcast socket (works on physical LAN)
        self.bsock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.bsock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.bsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        self.running = False
        self.thread = None

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
        try:
            self.msock.close()
        except OSError:
            pass
        try:
            self.bsock.close()
        except OSError:
            pass

    def _loop(self):
        while self.running:
            beacon = json.dumps({
                "t": "beacon",
                "name": self.host_name,
                "ip": self.ip,
                "port": BROADCAST_PORT,
                "players": self.player_count_fn(),
            }, separators=(",", ":")).encode()
            # Send on both multicast and broadcast for maximum compatibility
            try:
                self.msock.sendto(beacon, (MULTICAST_GROUP, DISCOVERY_PORT))
            except OSError:
                pass
            try:
                self.bsock.sendto(beacon, ("<broadcast>", DISCOVERY_PORT))
            except OSError:
                pass
            time.sleep(BEACON_INTERVAL)


def _get_all_subnet_ips():
    """Get /24 subnet base IPs for all network interfaces (including ZeroTier/VPN)."""
    subnets = set()

    # Method 1: getaddrinfo
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                parts = ip.split(".")
                if len(parts) == 4:
                    subnets.add(f"{parts[0]}.{parts[1]}.{parts[2]}")
    except OSError:
        pass

    # Method 2: default route
    try:
        default_ip = get_local_ip()
        if not default_ip.startswith("127."):
            parts = default_ip.split(".")
            if len(parts) == 4:
                subnets.add(f"{parts[0]}.{parts[1]}.{parts[2]}")
    except OSError:
        pass

    # Method 3: parse all interface IPs from /proc (Linux — catches ZeroTier)
    import subprocess
    try:
        out = subprocess.check_output(["ip", "-4", "addr"], timeout=2, stderr=subprocess.DEVNULL).decode()
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("inet "):
                ip = line.split()[1].split("/")[0]
                if not ip.startswith("127."):
                    parts = ip.split(".")
                    if len(parts) == 4:
                        subnets.add(f"{parts[0]}.{parts[1]}.{parts[2]}")
    except Exception:
        pass

    # Method 4: ipconfig on Windows
    try:
        out = subprocess.check_output(["ipconfig"], timeout=2, stderr=subprocess.DEVNULL).decode()
        for line in out.splitlines():
            if "IPv4" in line and ":" in line:
                ip = line.split(":")[-1].strip()
                if not ip.startswith("127."):
                    parts = ip.split(".")
                    if len(parts) == 4:
                        subnets.add(f"{parts[0]}.{parts[1]}.{parts[2]}")
    except Exception:
        pass

    return list(subnets)


class DiscoveryListener:
    """Listens for game beacons and actively scans subnets."""

    def __init__(self):
        # Receive socket — listens for beacons and ping replies
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("", DISCOVERY_PORT))
        self.sock.setblocking(False)

        # Join multicast group
        import struct
        try:
            mreq = struct.pack("4sL", socket.inet_aton(MULTICAST_GROUP), socket.INADDR_ANY)
            self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        except OSError:
            pass

        # Scan socket — sends ping requests to game port on subnet IPs
        self.scan_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.scan_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.scan_sock.setblocking(False)

        self.games = {}  # ip -> {name, ip, port, players, last_seen}
        self._scan_timer = 0.0
        self._scan_index = 0
        self._subnets = _get_all_subnet_ips()

    def poll(self, dt=0.033):
        """Read incoming beacons and scan responses. Call every frame."""
        # Read from discovery port (beacons)
        for _ in range(20):
            data, addr = _recv(self.sock)
            if data is None:
                break
            if data.get("t") == "beacon":
                ip = data.get("ip", addr[0])
                self._add_game(ip, data)

        # Read ping replies on scan socket
        for _ in range(20):
            data, addr = _recv(self.scan_sock)
            if data is None:
                break
            if data.get("t") == "pong":
                ip = data.get("ip", addr[0])
                self._add_game(ip, data)

        # Active subnet scan — send a few pings per frame
        self._scan_timer += dt
        if self._scan_timer >= 2.0:  # scan every 2 seconds
            self._scan_timer = 0.0
            self._scan_index = 1  # start scanning from .1

        if self._scan_index > 0 and self._scan_index <= 254:
            ping = json.dumps({"t": "ping"}, separators=(",", ":")).encode()
            # Scan a batch of IPs per frame (10 at a time for speed)
            for _ in range(10):
                if self._scan_index > 254:
                    break
                for subnet in self._subnets:
                    ip = f"{subnet}.{self._scan_index}"
                    try:
                        self.scan_sock.sendto(ping, (ip, BROADCAST_PORT))
                    except OSError:
                        pass
                self._scan_index += 1

        # Remove stale entries
        now = time.time()
        stale = [ip for ip, g in self.games.items() if now - g["last_seen"] > 5.0]
        for ip in stale:
            del self.games[ip]

    def _add_game(self, ip, data):
        self.games[ip] = {
            "name": data.get("name", "Unknown"),
            "ip": ip,
            "port": data.get("port", BROADCAST_PORT),
            "players": data.get("players", 0),
            "last_seen": time.time(),
        }

    def get_games(self):
        """Return list of discovered games, sorted by most recent."""
        return sorted(self.games.values(), key=lambda g: -g["last_seen"])

    def stop(self):
        try:
            self.sock.close()
        except OSError:
            pass
        try:
            self.scan_sock.close()
        except OSError:
            pass
