"""
Enemy AI: A* pathfinding + tactical state machine.

States:
  PATROL  — Wander near spawn point, unaware of player
  CHASE   — A* path toward player (spotted or heard gunfire)
  ATTACK  — Close range: strafe while dealing damage
  RETREAT — Low HP: back away from player, seek cover

Line-of-sight raycasting determines awareness.
Nearby enemies are alerted when one spots the player or hears gunfire.
Enemies that patrol too long without contact will investigate toward the player.
"""

import math
import heapq
import random

# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------
STATE_PATROL = 0
STATE_CHASE = 1
STATE_ATTACK = 2
STATE_RETREAT = 3

# Tuning
SIGHT_RANGE = 20.0          # max distance to see the player
HEARING_RANGE = 60.0        # gunfire alert radius (covers entire 48x48 map)
ATTACK_RANGE = 3.0          # switch to strafe/attack behavior
RETREAT_HP_THRESHOLD = 1    # retreat when HP <= this
PATROL_RADIUS = 5.0         # wander distance from spawn
PATROL_SPEED = 0.7          # speed multiplier while patrolling
PATH_RECALC_INTERVAL = 0.5  # seconds between A* recalcs
ALERT_RADIUS = 15.0         # alert nearby enemies when spotted
INVESTIGATE_TIME = 2.0      # seconds before patrol enemy starts hunting player
INVESTIGATE_SPEED = 1.2     # speed multiplier when investigating (nearly full speed)
RETREAT_DURATION = 2.0      # seconds to retreat before switching back to chase
RETREAT_MAX_DIST = 10.0     # stop retreating if this far from player


# ---------------------------------------------------------------------------
# A* pathfinding on the grid
# ---------------------------------------------------------------------------
def _heuristic(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def astar(grid, start, goal):
    """
    A* on a 2D grid. start/goal are (col, row) integer tuples.
    Returns a list of (col, row) waypoints, or empty if no path.
    """
    rows = len(grid)
    cols = len(grid[0]) if rows else 0

    sc, sr = int(start[0]), int(start[1])
    gc, gr = int(goal[0]), int(goal[1])

    sc = max(0, min(cols - 1, sc))
    sr = max(0, min(rows - 1, sr))
    gc = max(0, min(cols - 1, gc))
    gr = max(0, min(rows - 1, gr))

    if grid[sr][sc] != 0 or grid[gr][gc] != 0:
        return []

    open_set = [(0, sc, sr)]
    came_from = {}
    g_score = {(sc, sr): 0}
    closed = set()

    neighbors = [(0, 1), (0, -1), (1, 0), (-1, 0)]

    while open_set:
        _, cx, cy = heapq.heappop(open_set)

        if (cx, cy) in closed:
            continue
        closed.add((cx, cy))

        if cx == gc and cy == gr:
            path = []
            node = (gc, gr)
            while node in came_from:
                path.append(node)
                node = came_from[node]
            path.reverse()
            return path

        for dx, dy in neighbors:
            nx, ny = cx + dx, cy + dy
            if 0 <= ny < rows and 0 <= nx < cols and grid[ny][nx] == 0:
                if (nx, ny) in closed:
                    continue
                ng = g_score[(cx, cy)] + 1
                if ng < g_score.get((nx, ny), float("inf")):
                    g_score[(nx, ny)] = ng
                    f = ng + _heuristic((nx, ny), (gc, gr))
                    came_from[(nx, ny)] = (cx, cy)
                    heapq.heappush(open_set, (f, nx, ny))

    return []


# ---------------------------------------------------------------------------
# Line-of-sight check (simple DDA ray)
# ---------------------------------------------------------------------------
def has_line_of_sight(grid, x1, y1, x2, y2):
    """Check if there's a clear line between two points (no walls)."""
    rows = len(grid)
    cols = len(grid[0]) if rows else 0
    dx = x2 - x1
    dy = y2 - y1
    dist = math.hypot(dx, dy)
    if dist < 0.1:
        return True
    steps = int(dist * 10)
    if steps == 0:
        return True
    for i in range(1, steps):
        t = i / steps
        tx = x1 + dx * t
        ty = y1 + dy * t
        c, r = int(tx), int(ty)
        if 0 <= r < rows and 0 <= c < cols:
            if grid[r][c] != 0:
                return False
        else:
            return False
    return True


def _is_walkable(grid, x, y):
    """Check if a world position is on a walkable tile."""
    c, r = int(x), int(y)
    rows = len(grid)
    cols = len(grid[0]) if rows else 0
    if 0 <= r < rows and 0 <= c < cols:
        return grid[r][c] == 0
    return False


def _grid_is_wall(grid, x, y):
    """Check if a position is a wall using the given grid (no module imports)."""
    c, r = int(x), int(y)
    rows = len(grid)
    cols = len(grid[0]) if rows else 0
    if 0 <= r < rows and 0 <= c < cols:
        return grid[r][c] != 0
    return True


# ---------------------------------------------------------------------------
# AI state for one enemy (used by singleplayer Enemy objects)
# ---------------------------------------------------------------------------
class EnemyAI:
    """Attach to an Enemy to give it smart behavior."""

    def __init__(self, spawn_x, spawn_y):
        self.state = STATE_PATROL
        self.spawn_x = spawn_x
        self.spawn_y = spawn_y
        self.path = []
        self.path_timer = 0.0
        self.patrol_target = None
        self.patrol_time = 0.0  # time spent in patrol without seeing player
        self.strafe_dir = random.choice([-1, 1])
        self.strafe_timer = 0.0
        self.alert_timer = 0.0
        self.retreat_timer = 0.0
        self.last_known_px = None  # last known player position
        self.last_known_py = None

    def update(self, enemy, px, py, dt, grid, all_enemies=None, gunfire=False):
        if not enemy.alive:
            return

        self._grid = grid  # store for use by movement methods
        dist_to_player = math.hypot(px - enemy.x, py - enemy.y)
        can_see = (
            dist_to_player <= SIGHT_RANGE
            and has_line_of_sight(grid, enemy.x, enemy.y, px, py)
        )

        # Track last known player position when we can see them
        if can_see:
            self.last_known_px = px
            self.last_known_py = py

        # Gunfire alert — covers most of the map
        if gunfire and dist_to_player <= HEARING_RANGE:
            self.alert_timer = 5.0
            self.last_known_px = px
            self.last_known_py = py

        if self.alert_timer > 0:
            self.alert_timer -= dt

        # Alert nearby enemies when we spot the player
        if can_see and self.state == STATE_PATROL and all_enemies:
            for other_e, other_ai in all_enemies:
                if other_e is enemy or not other_e.alive:
                    continue
                if math.hypot(other_e.x - enemy.x, other_e.y - enemy.y) < ALERT_RADIUS:
                    if other_ai.state == STATE_PATROL:
                        other_ai.alert_timer = 5.0
                        other_ai.last_known_px = px
                        other_ai.last_known_py = py

        # --- State transitions ---
        aware = can_see or self.alert_timer > 0
        # Once an enemy has started investigating, it never goes back to idle
        investigating = self.patrol_time >= INVESTIGATE_TIME
        active = aware or investigating

        # Retreat is time-limited: flee briefly, then fight
        can_retreat = (
            enemy.health <= RETREAT_HP_THRESHOLD
            and active
            and self.retreat_timer < RETREAT_DURATION
            and dist_to_player < RETREAT_MAX_DIST
        )

        if can_retreat:
            self.state = STATE_RETREAT
            self.retreat_timer += dt
        elif active and dist_to_player <= ATTACK_RANGE:
            self.state = STATE_ATTACK
            self.retreat_timer = 0.0
        elif active:
            self.state = STATE_CHASE
            self.retreat_timer = 0.0
        else:
            self.state = STATE_PATROL
            self.patrol_time += dt

        # --- State behavior ---
        self.path_timer -= dt

        if self.state == STATE_PATROL:
            self._do_patrol(enemy, px, py, dt, grid)
        elif self.state == STATE_CHASE:
            self._do_chase(enemy, px, py, dt, grid)
        elif self.state == STATE_ATTACK:
            self._do_attack(enemy, px, py, dt, grid)
        elif self.state == STATE_RETREAT:
            self._do_retreat(enemy, px, py, dt, grid)

    def _move_toward(self, enemy, tx, ty, dt, speed_mult=1.0):
        """Move enemy toward a target point with collision margin."""
        dx = tx - enemy.x
        dy = ty - enemy.y
        dist = math.hypot(dx, dy)
        if dist < 0.1:
            return
        speed = enemy.speed * speed_mult
        mx = (dx / dist) * speed * dt
        my = (dy / dist) * speed * dt
        g = self._grid
        margin = 0.25
        # Check with margin on both sides of movement axis
        sign_x = 1 if mx > 0 else -1
        sign_y = 1 if my > 0 else -1
        if not _grid_is_wall(g, enemy.x + mx + sign_x * margin, enemy.y):
            enemy.x += mx
        if not _grid_is_wall(g, enemy.x, enemy.y + my + sign_y * margin):
            enemy.y += my

    def _follow_path(self, enemy, tx, ty, dt, speed_mult=1.0):
        """Follow the current A* path. Falls back to direct movement if path is empty."""
        if not self.path:
            # Fallback: move directly toward target
            self._move_toward(enemy, tx, ty, dt, speed_mult)
            return
        wx, wy = self.path[0]
        wpx, wpy = wx + 0.5, wy + 0.5
        dist = math.hypot(wpx - enemy.x, wpy - enemy.y)
        if dist < 0.4:
            self.path.pop(0)
            if not self.path:
                self._move_toward(enemy, tx, ty, dt, speed_mult)
                return
            wx, wy = self.path[0]
            wpx, wpy = wx + 0.5, wy + 0.5
        self._move_toward(enemy, wpx, wpy, dt, speed_mult)

    def _recalc_path(self, enemy, tx, ty, grid):
        """Recalculate A* path if timer expired."""
        if self.path_timer <= 0:
            self.path_timer = PATH_RECALC_INTERVAL
            self.path = astar(grid, (enemy.x, enemy.y), (tx, ty))

    def _pick_patrol_target(self, grid):
        """Pick a valid (non-wall) patrol target near spawn."""
        for _ in range(10):
            angle = random.uniform(0, 2 * math.pi)
            r = random.uniform(1.0, PATROL_RADIUS)
            tx = self.spawn_x + math.cos(angle) * r
            ty = self.spawn_y + math.sin(angle) * r
            if _is_walkable(grid, tx, ty):
                return (tx, ty)
        # Fallback: just use spawn position
        return (self.spawn_x, self.spawn_y)

    def _do_patrol(self, enemy, px, py, dt, grid):
        """Wander near spawn point. After INVESTIGATE_TIME, hunt the player."""
        # Investigation: after patrolling too long, actively hunt the player
        if self.patrol_time > INVESTIGATE_TIME:
            self._recalc_path(enemy, px, py, grid)
            self._follow_path(enemy, px, py, dt, speed_mult=INVESTIGATE_SPEED)
            return

        if self.patrol_target is None or math.hypot(
            self.patrol_target[0] - enemy.x, self.patrol_target[1] - enemy.y
        ) < 0.5:
            self.patrol_target = self._pick_patrol_target(grid)

        self._recalc_path(enemy, self.patrol_target[0], self.patrol_target[1], grid)
        self._follow_path(enemy, self.patrol_target[0], self.patrol_target[1], dt, speed_mult=PATROL_SPEED)

    def _do_chase(self, enemy, px, py, dt, grid):
        """A* path to player at full speed."""
        self._recalc_path(enemy, px, py, grid)
        self._follow_path(enemy, px, py, dt, speed_mult=1.3)

    def _do_attack(self, enemy, px, py, dt, grid):
        """Strafe around player at close range."""
        self.strafe_timer -= dt
        if self.strafe_timer <= 0:
            self.strafe_dir *= -1
            self.strafe_timer = random.uniform(0.8, 2.0)

        dx = px - enemy.x
        dy = py - enemy.y
        dist = math.hypot(dx, dy)
        if dist < 0.1:
            return

        perp_x = -dy / dist * self.strafe_dir
        perp_y = dx / dist * self.strafe_dir
        approach_x = dx / dist * 0.3
        approach_y = dy / dist * 0.3

        move_x = (perp_x + approach_x) * enemy.speed * dt
        move_y = (perp_y + approach_y) * enemy.speed * dt

        g = self._grid
        margin = 0.25
        sx = 1 if move_x > 0 else -1
        sy = 1 if move_y > 0 else -1
        if not _grid_is_wall(g, enemy.x + move_x + sx * margin, enemy.y):
            enemy.x += move_x
        if not _grid_is_wall(g, enemy.x, enemy.y + move_y + sy * margin):
            enemy.y += move_y

    def _do_retreat(self, enemy, px, py, dt, grid):
        """Move away from player."""
        dx = enemy.x - px
        dy = enemy.y - py
        dist = math.hypot(dx, dy)
        if dist < 0.1:
            dx, dy = 1.0, 0.0
            dist = 1.0

        retreat_x = dx / dist
        retreat_y = dy / dist
        tx = enemy.x + retreat_x * 3
        ty = enemy.y + retreat_y * 3

        self._recalc_path(enemy, tx, ty, grid)
        if self.path:
            self._follow_path(enemy, tx, ty, dt, speed_mult=0.8)
        else:
            mx = retreat_x * enemy.speed * 0.8 * dt
            my = retreat_y * enemy.speed * 0.8 * dt
            g = self._grid
            margin = 0.25
            sx = 1 if mx > 0 else -1
            sy = 1 if my > 0 else -1
            if not _grid_is_wall(g, enemy.x + mx + sx * margin, enemy.y):
                enemy.x += mx
            if not _grid_is_wall(g, enemy.x, enemy.y + my + sy * margin):
                enemy.y += my


# ---------------------------------------------------------------------------
# Server-side AI (for multiplayer — operates on dict-based enemies)
# ---------------------------------------------------------------------------
class ServerEnemyAI:
    """Simplified AI for the multiplayer server (operates on enemy dicts)."""

    def __init__(self, spawn_x, spawn_y):
        self.state = STATE_PATROL
        self.spawn_x = spawn_x
        self.spawn_y = spawn_y
        self.path = []
        self.path_timer = 0.0
        self.patrol_target = None
        self.patrol_time = 0.0
        self.strafe_dir = random.choice([-1, 1])
        self.strafe_timer = 0.0
        self.alert_timer = 0.0
        self.retreat_timer = 0.0

    def update(self, e, target_x, target_y, dt, grid, is_wall_fn, dist_to_target):
        if not e["alive"]:
            return

        can_see = (
            dist_to_target <= SIGHT_RANGE
            and has_line_of_sight(grid, e["x"], e["y"], target_x, target_y)
        )

        if self.alert_timer > 0:
            self.alert_timer -= dt

        aware = can_see or self.alert_timer > 0
        investigating = self.patrol_time >= INVESTIGATE_TIME
        active = aware or investigating

        can_retreat = (
            e["hp"] <= RETREAT_HP_THRESHOLD
            and active
            and self.retreat_timer < RETREAT_DURATION
            and dist_to_target < RETREAT_MAX_DIST
        )

        if can_retreat:
            self.state = STATE_RETREAT
            self.retreat_timer += dt
        elif active and dist_to_target <= ATTACK_RANGE:
            self.state = STATE_ATTACK
            self.retreat_timer = 0.0
        elif active:
            self.state = STATE_CHASE
            self.retreat_timer = 0.0
        else:
            self.state = STATE_PATROL
            self.patrol_time += dt

        self.path_timer -= dt

        if self.state == STATE_PATROL:
            self._patrol(e, target_x, target_y, dt, grid, is_wall_fn)
        elif self.state == STATE_CHASE:
            self._chase(e, target_x, target_y, dt, grid, is_wall_fn)
        elif self.state == STATE_ATTACK:
            self._attack(e, target_x, target_y, dt, is_wall_fn)
        elif self.state == STATE_RETREAT:
            self._retreat(e, target_x, target_y, dt, grid, is_wall_fn)

    def _move_toward(self, e, tx, ty, dt, is_wall_fn, speed=1.0):
        dx, dy = tx - e["x"], ty - e["y"]
        dist = math.hypot(dx, dy)
        if dist < 0.1:
            return
        mx = (dx / dist) * speed * dt
        my = (dy / dist) * speed * dt
        if not is_wall_fn(e["x"] + mx, e["y"]):
            e["x"] += mx
        if not is_wall_fn(e["x"], e["y"] + my):
            e["y"] += my

    def _follow_path(self, e, tx, ty, dt, is_wall_fn, speed=1.0):
        """Follow path with fallback to direct movement."""
        if not self.path:
            self._move_toward(e, tx, ty, dt, is_wall_fn, speed)
            return
        wx, wy = self.path[0]
        wpx, wpy = wx + 0.5, wy + 0.5
        if math.hypot(wpx - e["x"], wpy - e["y"]) < 0.4:
            self.path.pop(0)
            if not self.path:
                self._move_toward(e, tx, ty, dt, is_wall_fn, speed)
                return
            wx, wy = self.path[0]
            wpx, wpy = wx + 0.5, wy + 0.5
        self._move_toward(e, wpx, wpy, dt, is_wall_fn, speed)

    def _recalc(self, e, tx, ty, grid):
        if self.path_timer <= 0:
            self.path_timer = PATH_RECALC_INTERVAL
            self.path = astar(grid, (e["x"], e["y"]), (tx, ty))

    def _pick_patrol_target(self, grid):
        for _ in range(10):
            angle = random.uniform(0, 2 * math.pi)
            r = random.uniform(1.0, PATROL_RADIUS)
            tx = self.spawn_x + math.cos(angle) * r
            ty = self.spawn_y + math.sin(angle) * r
            if _is_walkable(grid, tx, ty):
                return (tx, ty)
        return (self.spawn_x, self.spawn_y)

    def _patrol(self, e, target_x, target_y, dt, grid, is_wall_fn):
        # After INVESTIGATE_TIME, hunt the nearest player
        if self.patrol_time > INVESTIGATE_TIME:
            self._recalc(e, target_x, target_y, grid)
            self._follow_path(e, target_x, target_y, dt, is_wall_fn, speed=INVESTIGATE_SPEED)
            return

        if self.patrol_target is None or math.hypot(
            self.patrol_target[0] - e["x"], self.patrol_target[1] - e["y"]
        ) < 0.5:
            self.patrol_target = self._pick_patrol_target(grid)
        self._recalc(e, self.patrol_target[0], self.patrol_target[1], grid)
        self._follow_path(e, self.patrol_target[0], self.patrol_target[1], dt, is_wall_fn, speed=PATROL_SPEED)

    def _chase(self, e, tx, ty, dt, grid, is_wall_fn):
        self._recalc(e, tx, ty, grid)
        self._follow_path(e, tx, ty, dt, is_wall_fn, speed=1.5)

    def _attack(self, e, tx, ty, dt, is_wall_fn):
        self.strafe_timer -= dt
        if self.strafe_timer <= 0:
            self.strafe_dir *= -1
            self.strafe_timer = random.uniform(0.8, 2.0)
        dx, dy = tx - e["x"], ty - e["y"]
        dist = math.hypot(dx, dy)
        if dist < 0.1:
            return
        perp_x = -dy / dist * self.strafe_dir
        perp_y = dx / dist * self.strafe_dir
        mx = (perp_x + dx / dist * 0.3) * 1.5 * dt
        my = (perp_y + dy / dist * 0.3) * 1.5 * dt
        if not is_wall_fn(e["x"] + mx, e["y"]):
            e["x"] += mx
        if not is_wall_fn(e["x"], e["y"] + my):
            e["y"] += my

    def _retreat(self, e, tx, ty, dt, grid, is_wall_fn):
        dx, dy = e["x"] - tx, e["y"] - ty
        dist = math.hypot(dx, dy)
        if dist < 0.1:
            dx, dy, dist = 1.0, 0.0, 1.0
        rx, ry = e["x"] + dx / dist * 3, e["y"] + dy / dist * 3
        self._recalc(e, rx, ry, grid)
        if self.path:
            self._follow_path(e, rx, ry, dt, is_wall_fn, speed=0.8)
        else:
            mx = dx / dist * 0.8 * dt
            my = dy / dist * 0.8 * dt
            if not is_wall_fn(e["x"] + mx, e["y"]):
                e["x"] += mx
            if not is_wall_fn(e["x"], e["y"] + my):
                e["y"] += my
