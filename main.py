"""
Raycasting FPS Game with LAN Multiplayer

Controls:
  WASD          - Move
  Mouse         - Look around
  Left Click    - Shoot
  Space         - Shoot
  R             - Restart (when dead)
  ESC           - Quit / Back to menu
  TAB           - Scoreboard (multiplayer)
"""

import pygame
import math
import sys
import time

from network import (
    GameServer, GameClient, get_local_ip,
    PLAYER_COLORS, SPAWN_POSITIONS,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCREEN_WIDTH = 1024
SCREEN_HEIGHT = 768
FPS = 60

FOV = math.pi / 3
HALF_FOV = FOV / 2
NUM_RAYS = SCREEN_WIDTH // 2
DELTA_ANGLE = FOV / NUM_RAYS
MAX_DEPTH = 20
SCALE = SCREEN_WIDTH // NUM_RAYS

PLAYER_SPEED = 3.0
PLAYER_ROT_SPEED = 0.003
PLAYER_SIZE_SCALE = 0.3

MINIMAP_SCALE = 5
MINIMAP_OFFSET = 10

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
RED = (200, 50, 50)
GREEN = (50, 200, 50)
BLUE = (50, 120, 220)
DARK_GRAY = (40, 40, 40)
LIGHT_GRAY = (100, 100, 100)
SKY_BLUE = (135, 206, 235)
FLOOR_BROWN = (60, 40, 25)
YELLOW = (255, 220, 50)

WALL_COLORS = {
    1: (160, 160, 170),
    2: (130, 80, 50),
    3: (80, 100, 130),
}

# ---------------------------------------------------------------------------
# Map
# ---------------------------------------------------------------------------
WORLD_MAP = [
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1],
    [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1],
    [1, 0, 0, 2, 2, 0, 0, 0, 0, 0, 3, 3, 0, 0, 0, 1],
    [1, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 3, 0, 0, 0, 1],
    [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1],
    [1, 0, 0, 0, 0, 0, 1, 1, 1, 0, 0, 0, 0, 0, 0, 1],
    [1, 0, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 0, 0, 1],
    [1, 0, 0, 0, 0, 0, 1, 1, 1, 0, 0, 0, 0, 0, 0, 1],
    [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1],
    [1, 0, 0, 3, 0, 0, 0, 0, 0, 0, 0, 2, 0, 0, 0, 1],
    [1, 0, 0, 3, 3, 0, 0, 0, 0, 0, 2, 2, 0, 0, 0, 1],
    [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1],
    [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1],
    [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
]
MAP_ROWS = len(WORLD_MAP)
MAP_COLS = len(WORLD_MAP[0])


def is_wall(x, y):
    col, row = int(x), int(y)
    if 0 <= row < MAP_ROWS and 0 <= col < MAP_COLS:
        return WORLD_MAP[row][col] != 0
    return True


# ---------------------------------------------------------------------------
# Enemy (singleplayer only — multiplayer enemies come from server)
# ---------------------------------------------------------------------------
class Enemy:
    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.alive = True
        self.health = 3
        self.speed = 1.0
        self.damage_timer = 0.0

    def update(self, px, py, dt):
        if not self.alive:
            return
        self.damage_timer = max(0, self.damage_timer - dt)
        dx, dy = px - self.x, py - self.y
        dist = math.hypot(dx, dy)
        if dist > 0.8:
            mx = (dx / dist) * self.speed * dt
            my = (dy / dist) * self.speed * dt
            if not is_wall(self.x + mx, self.y):
                self.x += mx
            if not is_wall(self.x, self.y + my):
                self.y += my

    def take_damage(self):
        self.health -= 1
        self.damage_timer = 0.15
        if self.health <= 0:
            self.alive = False


ENEMY_SPAWNS = [
    (4.5, 4.5), (12.5, 3.5), (7.5, 12.5), (13.5, 10.5),
    (3.5, 12.5), (10.5, 7.5), (5.5, 9.5), (13.5, 13.5),
]


def spawn_enemies():
    return [Enemy(x, y) for x, y in ENEMY_SPAWNS]


# ---------------------------------------------------------------------------
# Raycasting
# ---------------------------------------------------------------------------
def cast_rays(px, py, pangle):
    walls = []
    ray_angle = pangle - HALF_FOV
    for ray in range(NUM_RAYS):
        sin_a = math.sin(ray_angle)
        cos_a = math.cos(ray_angle)
        depth = 0
        hit_wall = 1
        hit_side = 0
        for _ in range(MAX_DEPTH * 64):
            depth += 0.02
            tx = px + cos_a * depth
            ty = py + sin_a * depth
            c, r = int(tx), int(ty)
            if 0 <= r < MAP_ROWS and 0 <= c < MAP_COLS:
                if WORLD_MAP[r][c] != 0:
                    hit_wall = WORLD_MAP[r][c]
                    prev_x = px + cos_a * (depth - 0.02)
                    hit_side = 0 if int(prev_x) != c else 1
                    break
            else:
                break
        depth *= math.cos(pangle - ray_angle)
        if depth < 0.01:
            depth = 0.01
        wh = min(SCREEN_HEIGHT * 1.5, SCREEN_HEIGHT / depth)
        walls.append((ray, depth, wh, hit_wall, hit_side))
        ray_angle += DELTA_ANGLE
    return walls


def cast_single_ray(px, py, angle):
    sin_a, cos_a = math.sin(angle), math.cos(angle)
    for step in range(MAX_DEPTH * 64):
        d = step * 0.02
        c, r = int(px + cos_a * d), int(py + sin_a * d)
        if 0 <= r < MAP_ROWS and 0 <= c < MAP_COLS:
            if WORLD_MAP[r][c] != 0:
                return d
        else:
            return d
    return MAX_DEPTH


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------
def draw_sky_and_floor(surface):
    half = SCREEN_HEIGHT // 2
    for y in range(half):
        f = y / half
        color = (int(50 + 85 * f), int(50 + 156 * f), int(80 + 155 * f))
        pygame.draw.line(surface, color, (0, y), (SCREEN_WIDTH, y))
    for y in range(half, SCREEN_HEIGHT):
        f = (y - half) / half
        color = (int(60 * (0.3 + 0.7 * f)), int(40 * (0.3 + 0.7 * f)), int(25 * (0.3 + 0.7 * f)))
        pygame.draw.line(surface, color, (0, y), (SCREEN_WIDTH, y))


def draw_walls(surface, walls):
    for ray, depth, wh, wt, hs in walls:
        base = WALL_COLORS.get(wt, (160, 160, 170))
        shade = max(0.15, 1.0 - depth / MAX_DEPTH)
        sm = 0.7 if hs == 1 else 1.0
        color = tuple(max(0, min(255, int(c * shade * sm))) for c in base)
        x = ray * SCALE
        y = (SCREEN_HEIGHT - wh) / 2
        pygame.draw.rect(surface, color, (x, y, SCALE, wh))


def _draw_sprite(surface, screen_x, dist, body_color, head_color, wall_depths):
    sprite_height = min(SCREEN_HEIGHT, int(SCREEN_HEIGHT * 0.6 / max(dist, 0.1)))
    sprite_width = sprite_height // 2
    ray_idx = int(screen_x / SCREEN_WIDTH * NUM_RAYS)
    if 0 <= ray_idx < NUM_RAYS and dist > wall_depths[ray_idx]:
        return
    shade = max(0.2, 1.0 - dist / MAX_DEPTH)
    bc = tuple(max(0, min(255, int(c * shade))) for c in body_color)
    hc = tuple(max(0, min(255, int(c * shade))) for c in head_color)
    top = SCREEN_HEIGHT // 2 - sprite_height // 2
    # Body
    pygame.draw.rect(surface, bc, (
        screen_x - sprite_width // 2,
        top + sprite_height // 4,
        sprite_width,
        sprite_height * 3 // 4,
    ))
    # Head
    hr = max(2, sprite_width // 3)
    hy = top + sprite_height // 6
    pygame.draw.circle(surface, hc, (screen_x, hy), hr)
    if hr > 4:
        eo = hr // 3
        er = max(1, hr // 5)
        pygame.draw.circle(surface, BLACK, (screen_x - eo, hy - er), er)
        pygame.draw.circle(surface, BLACK, (screen_x + eo, hy - er), er)


def draw_enemies_from_list(surface, enemy_list, px, py, pangle, wall_depths):
    """Draw enemies from a list of dicts (multiplayer) or Enemy objects (singleplayer)."""
    render = []
    for e in enemy_list:
        if isinstance(e, dict):
            ex, ey, alive, dmg = e["x"], e["y"], e["alive"], e.get("dt", 0)
        else:
            ex, ey, alive, dmg = e.x, e.y, e.alive, e.damage_timer
        if not alive:
            continue
        dx, dy = ex - px, ey - py
        dist = math.hypot(dx, dy)
        if dist < 0.1:
            continue
        ad = math.atan2(dy, dx) - pangle
        while ad > math.pi: ad -= 2 * math.pi
        while ad < -math.pi: ad += 2 * math.pi
        if abs(ad) > HALF_FOV + 0.1:
            continue
        render.append((dist, ex, ey, ad, dmg))

    render.sort(key=lambda r: -r[0])
    for dist, ex, ey, ad, dmg in render:
        sx = int((ad / FOV + 0.5) * SCREEN_WIDTH)
        if dmg > 0:
            bc, hc = (255, 255, 255), (255, 255, 255)
        else:
            bc, hc = (200, 50, 50), (220, 180, 150)
        _draw_sprite(surface, sx, dist, bc, hc, wall_depths)


def draw_other_players(surface, players, my_id, px, py, pangle, wall_depths):
    """Draw other players as colored humanoid sprites."""
    render = []
    for pid_str, p in players.items():
        pid = int(pid_str)
        if pid == my_id or not p.get("alive", True):
            continue
        dx, dy = p["x"] - px, p["y"] - py
        dist = math.hypot(dx, dy)
        if dist < 0.1:
            continue
        ad = math.atan2(dy, dx) - pangle
        while ad > math.pi: ad -= 2 * math.pi
        while ad < -math.pi: ad += 2 * math.pi
        if abs(ad) > HALF_FOV + 0.1:
            continue
        render.append((dist, pid, ad))

    render.sort(key=lambda r: -r[0])
    for dist, pid, ad in render:
        sx = int((ad / FOV + 0.5) * SCREEN_WIDTH)
        pc = PLAYER_COLORS[pid % len(PLAYER_COLORS)]
        _draw_sprite(surface, sx, dist, pc, (220, 180, 150), wall_depths)


def draw_weapon(surface, shooting_timer):
    cx, by = SCREEN_WIDTH // 2, SCREEN_HEIGHT
    oy = int(20 * shooting_timer / 0.15) if shooting_timer > 0 else 0
    pygame.draw.rect(surface, (60, 60, 65), (cx - 20, by - 120 + oy, 40, 100))
    pygame.draw.rect(surface, (80, 80, 85), (cx - 6, by - 160 + oy, 12, 50))
    pygame.draw.rect(surface, (50, 50, 55), (cx - 8, by - 165 + oy, 16, 8))
    if shooting_timer > 0.1:
        pygame.draw.circle(surface, YELLOW, (cx, by - 170 + oy), 25)
        pygame.draw.circle(surface, WHITE, (cx, by - 170 + oy), 12)


def draw_crosshair(surface):
    cx, cy = SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2
    c = (0, 255, 0)
    pygame.draw.line(surface, c, (cx - 14, cy), (cx - 6, cy), 2)
    pygame.draw.line(surface, c, (cx + 6, cy), (cx + 14, cy), 2)
    pygame.draw.line(surface, c, (cx, cy - 14), (cx, cy - 6), 2)
    pygame.draw.line(surface, c, (cx, cy + 6), (cx, cy + 14), 2)


def draw_minimap(surface, px, py, pangle, enemies, other_players=None, my_id=0):
    s, ox, oy = MINIMAP_SCALE, MINIMAP_OFFSET, MINIMAP_OFFSET
    pygame.draw.rect(surface, BLACK, (ox - 2, oy - 2, MAP_COLS * s + 4, MAP_ROWS * s + 4))
    for row in range(MAP_ROWS):
        for col in range(MAP_COLS):
            c = DARK_GRAY if WORLD_MAP[row][col] == 0 else LIGHT_GRAY
            pygame.draw.rect(surface, c, (ox + col * s, oy + row * s, s, s))

    # Enemies
    for e in enemies:
        if isinstance(e, dict):
            ex, ey, alive = e["x"], e["y"], e["alive"]
        else:
            ex, ey, alive = e.x, e.y, e.alive
        if alive:
            pygame.draw.circle(surface, RED, (int(ox + ex * s), int(oy + ey * s)), 2)

    # Other players
    if other_players:
        for pid_str, p in other_players.items():
            pid = int(pid_str)
            if pid == my_id or not p.get("alive", True):
                continue
            pc = PLAYER_COLORS[pid % len(PLAYER_COLORS)]
            pygame.draw.circle(surface, pc, (int(ox + p["x"] * s), int(oy + p["y"] * s)), 3)

    # Self
    mpx, mpy = ox + px * s, oy + py * s
    pygame.draw.circle(surface, GREEN, (int(mpx), int(mpy)), 3)
    dx, dy = math.cos(pangle) * 8, math.sin(pangle) * 8
    pygame.draw.line(surface, GREEN, (int(mpx), int(mpy)), (int(mpx + dx), int(mpy + dy)), 1)


def draw_hud(surface, font, health, ammo, score):
    y = SCREEN_HEIGHT - 40
    surface.blit(font.render(f"HP: {health}", True, RED if health < 30 else WHITE), (20, y))
    surface.blit(font.render(f"AMMO: {ammo}", True, YELLOW), (180, y))
    surface.blit(font.render(f"SCORE: {score}", True, WHITE), (SCREEN_WIDTH - 200, y))


def draw_damage_overlay(surface, damage_timer):
    if damage_timer > 0:
        alpha = int(120 * (damage_timer / 0.3))
        ov = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        ov.fill((255, 0, 0, alpha))
        surface.blit(ov, (0, 0))


def draw_death_screen(surface, font, score):
    ov = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
    ov.fill((0, 0, 0, 180))
    surface.blit(ov, (0, 0))
    big = pygame.font.SysFont("monospace", 64, bold=True)
    t = big.render("YOU DIED", True, RED)
    surface.blit(t, t.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 40)))
    surface.blit(
        font.render(f"Final Score: {score}", True, WHITE),
        font.render(f"Final Score: {score}", True, WHITE).get_rect(
            center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 + 30)),
    )
    surface.blit(
        font.render("Press R to restart or ESC for menu", True, LIGHT_GRAY),
        font.render("Press R to restart or ESC for menu", True, LIGHT_GRAY).get_rect(
            center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 + 70)),
    )


def draw_scoreboard(surface, font, players):
    """Draw a TAB scoreboard overlay for multiplayer."""
    ov = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
    ov.fill((0, 0, 0, 160))
    surface.blit(ov, (0, 0))

    title = pygame.font.SysFont("monospace", 36, bold=True)
    surface.blit(
        title.render("SCOREBOARD", True, WHITE),
        title.render("SCOREBOARD", True, WHITE).get_rect(
            center=(SCREEN_WIDTH // 2, 120)),
    )

    sorted_players = sorted(players.items(), key=lambda kv: -kv[1].get("score", 0))
    y = 180
    header = font.render(f"{'NAME':<16} {'SCORE':>6}  {'HP':>4}  {'STATUS':<8}", True, LIGHT_GRAY)
    surface.blit(header, (SCREEN_WIDTH // 2 - 220, y))
    y += 35

    for pid_str, p in sorted_players:
        pid = int(pid_str)
        pc = PLAYER_COLORS[pid % len(PLAYER_COLORS)]
        name = p.get("name", f"Player {pid}")[:16]
        status = "ALIVE" if p.get("alive", True) else "DEAD"
        line = font.render(
            f"{name:<16} {p.get('score', 0):>6}  {p.get('hp', 0):>4}  {status:<8}",
            True, pc,
        )
        surface.blit(line, (SCREEN_WIDTH // 2 - 220, y))
        y += 30


# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------
class TextInput:
    """Simple single-line text input widget."""
    def __init__(self, x, y, w, h, font, default=""):
        self.rect = pygame.Rect(x, y, w, h)
        self.font = font
        self.text = default
        self.active = False

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN:
            self.active = self.rect.collidepoint(event.pos)
        elif event.type == pygame.KEYDOWN and self.active:
            if event.key == pygame.K_BACKSPACE:
                self.text = self.text[:-1]
            elif event.key in (pygame.K_RETURN, pygame.K_TAB):
                self.active = False
            elif len(self.text) < 30 and event.unicode.isprintable():
                self.text += event.unicode

    def draw(self, surface):
        border_color = WHITE if self.active else LIGHT_GRAY
        pygame.draw.rect(surface, DARK_GRAY, self.rect)
        pygame.draw.rect(surface, border_color, self.rect, 2)
        txt = self.font.render(self.text, True, WHITE)
        surface.blit(txt, (self.rect.x + 8, self.rect.y + (self.rect.h - txt.get_height()) // 2))


def menu_screen(screen, clock, font):
    """
    Main menu. Returns one of:
      ("singleplayer", None, None)
      ("host", name, None)
      ("join", name, ip)
      ("quit", None, None)
    """
    pygame.mouse.set_visible(True)
    pygame.event.set_grab(False)

    title_font = pygame.font.SysFont("monospace", 48, bold=True)
    small = pygame.font.SysFont("monospace", 18)

    local_ip = get_local_ip()

    cx = SCREEN_WIDTH // 2
    name_input = TextInput(cx - 120, 250, 240, 36, font, "Player")
    ip_input = TextInput(cx - 120, 430, 240, 36, font, "")

    buttons = {
        "single": pygame.Rect(cx - 140, 320, 280, 44),
        "host":   pygame.Rect(cx - 140, 375, 280, 44),
        "join":   pygame.Rect(cx - 140, 480, 280, 44),
    }

    hovered = None

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return ("quit", None, None)
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                return ("quit", None, None)

            name_input.handle_event(event)
            ip_input.handle_event(event)

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if buttons["single"].collidepoint(event.pos):
                    return ("singleplayer", name_input.text or "Player", None)
                if buttons["host"].collidepoint(event.pos):
                    return ("host", name_input.text or "Host", None)
                if buttons["join"].collidepoint(event.pos) and ip_input.text.strip():
                    return ("join", name_input.text or "Player", ip_input.text.strip())

        mouse_pos = pygame.mouse.get_pos()
        hovered = None
        for key, rect in buttons.items():
            if rect.collidepoint(mouse_pos):
                hovered = key

        screen.fill((20, 20, 30))

        # Title
        t = title_font.render("RAYCASTER FPS", True, (200, 200, 220))
        screen.blit(t, t.get_rect(center=(cx, 100)))

        # Subtitle
        sub = small.render("LAN Multiplayer", True, LIGHT_GRAY)
        screen.blit(sub, sub.get_rect(center=(cx, 150)))

        # Name label + input
        screen.blit(font.render("Your Name:", True, WHITE), (cx - 120, 222))
        name_input.draw(screen)

        # Buttons
        for key, rect in buttons.items():
            color = (80, 80, 100) if hovered == key else (50, 50, 65)
            pygame.draw.rect(screen, color, rect, border_radius=6)
            pygame.draw.rect(screen, LIGHT_GRAY, rect, 2, border_radius=6)

        labels = {
            "single": "Singleplayer",
            "host": f"Host Game  (your IP: {local_ip})",
            "join": "Join Game",
        }
        for key, rect in buttons.items():
            lbl = font.render(labels[key], True, WHITE)
            screen.blit(lbl, lbl.get_rect(center=rect.center))

        # IP input (only for join)
        screen.blit(font.render("Host IP Address:", True, WHITE), (cx - 120, 402))
        ip_input.draw(screen)

        # Footer
        foot = small.render("ESC to quit", True, DARK_GRAY)
        screen.blit(foot, foot.get_rect(center=(cx, SCREEN_HEIGHT - 30)))

        pygame.display.flip()
        clock.tick(30)


# ---------------------------------------------------------------------------
# Game loops
# ---------------------------------------------------------------------------
def singleplayer_loop(screen, clock, font, bg_surface):
    pygame.mouse.set_visible(False)
    pygame.event.set_grab(True)

    def reset():
        return {
            "px": 2.0, "py": 2.0, "pangle": 0.0,
            "health": 100, "ammo": 50, "score": 0,
            "enemies": spawn_enemies(),
            "shooting_timer": 0.0, "damage_timer": 0.0,
            "damage_cooldown": 0.0, "dead": False,
        }

    st = reset()

    while True:
        dt = clock.tick(FPS) / 1000.0
        shoot = False

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return "quit"
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return "menu"
                if event.key == pygame.K_r and st["dead"]:
                    st = reset()
                if event.key == pygame.K_SPACE and not st["dead"]:
                    shoot = True
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1 and not st["dead"]:
                    shoot = True
            elif event.type == pygame.MOUSEMOTION and not st["dead"]:
                st["pangle"] += event.rel[0] * PLAYER_ROT_SPEED

        if st["dead"]:
            screen.blit(bg_surface, (0, 0))
            walls = cast_rays(st["px"], st["py"], st["pangle"])
            draw_walls(screen, walls)
            wd = [w[1] for w in walls]
            draw_enemies_from_list(screen, st["enemies"], st["px"], st["py"], st["pangle"], wd)
            draw_death_screen(screen, font, st["score"])
            pygame.display.flip()
            continue

        # Movement
        keys = pygame.key.get_pressed()
        mx, my = 0.0, 0.0
        ca, sa = math.cos(st["pangle"]), math.sin(st["pangle"])
        if keys[pygame.K_w]: mx += ca; my += sa
        if keys[pygame.K_s]: mx -= ca; my -= sa
        if keys[pygame.K_a]: mx += sa; my -= ca
        if keys[pygame.K_d]: mx -= sa; my += ca
        ln = math.hypot(mx, my)
        if ln > 0:
            mx = mx / ln * PLAYER_SPEED * dt
            my = my / ln * PLAYER_SPEED * dt
        nx, ny = st["px"] + mx, st["py"] + my
        m = PLAYER_SIZE_SCALE
        if not is_wall(nx + m, st["py"]) and not is_wall(nx - m, st["py"]):
            st["px"] = nx
        if not is_wall(st["px"], ny + m) and not is_wall(st["px"], ny - m):
            st["py"] = ny

        # Shooting
        st["shooting_timer"] = max(0, st["shooting_timer"] - dt)
        if shoot and st["ammo"] > 0 and st["shooting_timer"] <= 0:
            st["ammo"] -= 1
            st["shooting_timer"] = 0.15
            best, bd = None, float("inf")
            for e in st["enemies"]:
                if not e.alive:
                    continue
                dx, dy = e.x - st["px"], e.y - st["py"]
                d = math.hypot(dx, dy)
                ea = math.atan2(dy, dx)
                diff = ea - st["pangle"]
                while diff > math.pi: diff -= 2 * math.pi
                while diff < -math.pi: diff += 2 * math.pi
                ht = max(0.05, 0.3 / max(d, 0.1))
                if abs(diff) < ht and d < bd:
                    wd2 = cast_single_ray(st["px"], st["py"], ea)
                    if wd2 > d - 0.3:
                        bd, best = d, e
            if best:
                best.take_damage()
                if not best.alive:
                    st["score"] += 100

        # Enemies
        st["damage_cooldown"] = max(0, st["damage_cooldown"] - dt)
        st["damage_timer"] = max(0, st["damage_timer"] - dt)
        for e in st["enemies"]:
            e.update(st["px"], st["py"], dt)
            if e.alive and math.hypot(e.x - st["px"], e.y - st["py"]) < 0.8 and st["damage_cooldown"] <= 0:
                st["health"] -= 10
                st["damage_timer"] = 0.3
                st["damage_cooldown"] = 0.5
                if st["health"] <= 0:
                    st["health"] = 0
                    st["dead"] = True

        if all(not e.alive for e in st["enemies"]):
            st["enemies"] = spawn_enemies()
            st["ammo"] = min(st["ammo"] + 20, 99)

        # Render
        screen.blit(bg_surface, (0, 0))
        walls = cast_rays(st["px"], st["py"], st["pangle"])
        draw_walls(screen, walls)
        wd = [w[1] for w in walls]
        draw_enemies_from_list(screen, st["enemies"], st["px"], st["py"], st["pangle"], wd)
        draw_weapon(screen, st["shooting_timer"])
        draw_crosshair(screen)
        draw_minimap(screen, st["px"], st["py"], st["pangle"], st["enemies"])
        draw_hud(screen, font, st["health"], st["ammo"], st["score"])
        draw_damage_overlay(screen, st["damage_timer"])
        screen.blit(font.render(f"FPS: {int(clock.get_fps())}", True, WHITE), (SCREEN_WIDTH - 150, 10))
        pygame.display.flip()


def host_loop(screen, clock, font, bg_surface, player_name):
    """Host a multiplayer game. Runs a server + plays as player 0."""
    server = GameServer(WORLD_MAP, spawn_enemies)
    server.start()
    host_id = server.register_host(player_name)

    pygame.mouse.set_visible(False)
    pygame.event.set_grab(True)

    local_ip = get_local_ip()

    px, py, pangle = SPAWN_POSITIONS[0]
    pangle_val = 0.0
    shooting_timer = 0.0
    damage_timer = 0.0
    prev_health = 100

    result = "menu"

    try:
        while True:
            dt = clock.tick(FPS) / 1000.0
            shoot = False

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    result = "quit"
                    return result
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        return result
                    if event.key == pygame.K_SPACE:
                        shoot = True
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    shoot = True
                elif event.type == pygame.MOUSEMOTION:
                    pangle_val += event.rel[0] * PLAYER_ROT_SPEED

            # Movement (client-side, sent to server)
            keys = pygame.key.get_pressed()
            show_tab = keys[pygame.K_TAB]
            mx, my = 0.0, 0.0
            ca, sa = math.cos(pangle_val), math.sin(pangle_val)
            if keys[pygame.K_w]: mx += ca; my += sa
            if keys[pygame.K_s]: mx -= ca; my -= sa
            if keys[pygame.K_a]: mx += sa; my -= ca
            if keys[pygame.K_d]: mx -= sa; my += ca
            ln = math.hypot(mx, my)
            if ln > 0:
                mx = mx / ln * PLAYER_SPEED * dt
                my = my / ln * PLAYER_SPEED * dt
            nx, ny = px + mx, py + my
            m = PLAYER_SIZE_SCALE
            if not is_wall(nx + m, py) and not is_wall(nx - m, py):
                px = nx
            if not is_wall(px, ny + m) and not is_wall(px, ny - m):
                py = ny

            shooting_timer = max(0, shooting_timer - dt)
            actual_shoot = False
            if shoot and shooting_timer <= 0:
                shooting_timer = 0.15
                actual_shoot = True

            server.update_host_state(px, py, pangle_val, actual_shoot)
            world = server.get_world_state()

            # Read own state from server
            my_data = world["players"].get(str(host_id), {})
            health = my_data.get("hp", 100)
            ammo = my_data.get("ammo", 50)
            score = my_data.get("score", 0)
            alive = my_data.get("alive", True)

            # Damage flash
            damage_timer = max(0, damage_timer - dt)
            if health < prev_health:
                damage_timer = 0.3
            prev_health = health

            # Death handling
            if not alive:
                # Respawn after 3 seconds
                pass

            # Render
            screen.blit(bg_surface, (0, 0))
            walls = cast_rays(px, py, pangle_val)
            draw_walls(screen, walls)
            wd = [w[1] for w in walls]
            draw_enemies_from_list(screen, world["enemies"], px, py, pangle_val, wd)
            draw_other_players(screen, world["players"], host_id, px, py, pangle_val, wd)
            draw_weapon(screen, shooting_timer)
            draw_crosshair(screen)
            draw_minimap(screen, px, py, pangle_val, world["enemies"], world["players"], host_id)
            draw_hud(screen, font, health, ammo, score)
            draw_damage_overlay(screen, damage_timer)

            # Connection info
            n_players = len(world["players"])
            info = font.render(f"HOSTING ({local_ip}) - {n_players} player{'s' if n_players != 1 else ''}", True, GREEN)
            screen.blit(info, (SCREEN_WIDTH // 2 - info.get_width() // 2, 10))

            screen.blit(font.render(f"FPS: {int(clock.get_fps())}", True, WHITE), (SCREEN_WIDTH - 150, 10))

            if show_tab:
                draw_scoreboard(screen, font, world["players"])

            pygame.display.flip()

    finally:
        server.stop()


def join_loop(screen, clock, font, bg_surface, player_name, host_ip):
    """Join a multiplayer game as a client."""
    client = GameClient()
    client.connect(host_ip, player_name)

    pygame.mouse.set_visible(False)
    pygame.event.set_grab(True)

    # We'll start at a default pos and update once we get the welcome
    px, py, pangle_val = 2.0, 2.0, 0.0
    shooting_timer = 0.0
    damage_timer = 0.0
    prev_health = 100
    connecting_time = 0.0

    result = "menu"

    try:
        while True:
            dt = clock.tick(FPS) / 1000.0
            shoot = False

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    result = "quit"
                    return result
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        return result
                    if event.key == pygame.K_SPACE:
                        shoot = True
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    shoot = True
                elif event.type == pygame.MOUSEMOTION:
                    pangle_val += event.rel[0] * PLAYER_ROT_SPEED

            client.poll()

            # Retry connection
            if not client.connected:
                connecting_time += dt
                if connecting_time > 1.0:
                    client.connect(host_ip, player_name)
                    connecting_time = 0.0
                screen.fill((20, 20, 30))
                msg = font.render(f"Connecting to {host_ip}...", True, WHITE)
                screen.blit(msg, msg.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)))
                hint = font.render("Press ESC to cancel", True, LIGHT_GRAY)
                screen.blit(hint, hint.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 + 40)))
                pygame.display.flip()
                continue

            # Movement
            keys = pygame.key.get_pressed()
            show_tab = keys[pygame.K_TAB]
            mx, my = 0.0, 0.0
            ca, sa = math.cos(pangle_val), math.sin(pangle_val)
            if keys[pygame.K_w]: mx += ca; my += sa
            if keys[pygame.K_s]: mx -= ca; my -= sa
            if keys[pygame.K_a]: mx += sa; my -= ca
            if keys[pygame.K_d]: mx -= sa; my += ca
            ln = math.hypot(mx, my)
            if ln > 0:
                mx = mx / ln * PLAYER_SPEED * dt
                my = my / ln * PLAYER_SPEED * dt
            nx, ny = px + mx, py + my
            m = PLAYER_SIZE_SCALE
            if not is_wall(nx + m, py) and not is_wall(nx - m, py):
                px = nx
            if not is_wall(px, ny + m) and not is_wall(px, ny - m):
                py = ny

            shooting_timer = max(0, shooting_timer - dt)
            actual_shoot = False
            if shoot and shooting_timer <= 0:
                shooting_timer = 0.15
                actual_shoot = True

            client.send_state(px, py, pangle_val, actual_shoot)

            # Read world state
            world = client.world
            if world is None:
                screen.fill((20, 20, 30))
                screen.blit(
                    font.render("Waiting for game state...", True, WHITE),
                    (SCREEN_WIDTH // 2 - 150, SCREEN_HEIGHT // 2),
                )
                pygame.display.flip()
                continue

            my_data = world["players"].get(str(client.my_id), {})
            health = my_data.get("hp", 100)
            ammo = my_data.get("ammo", 50)
            score = my_data.get("score", 0)
            alive = my_data.get("alive", True)

            damage_timer = max(0, damage_timer - dt)
            if health < prev_health:
                damage_timer = 0.3
            prev_health = health

            # Render
            screen.blit(bg_surface, (0, 0))
            walls = cast_rays(px, py, pangle_val)
            draw_walls(screen, walls)
            wd = [w[1] for w in walls]
            draw_enemies_from_list(screen, world["enemies"], px, py, pangle_val, wd)
            draw_other_players(screen, world["players"], client.my_id, px, py, pangle_val, wd)
            draw_weapon(screen, shooting_timer)
            draw_crosshair(screen)
            draw_minimap(screen, px, py, pangle_val, world["enemies"], world["players"], client.my_id)
            draw_hud(screen, font, health, ammo, score)
            draw_damage_overlay(screen, damage_timer)

            n_players = len(world["players"])
            info = font.render(f"CONNECTED ({host_ip}) - {n_players} player{'s' if n_players != 1 else ''}", True, BLUE)
            screen.blit(info, (SCREEN_WIDTH // 2 - info.get_width() // 2, 10))

            screen.blit(font.render(f"FPS: {int(clock.get_fps())}", True, WHITE), (SCREEN_WIDTH - 150, 10))

            if show_tab:
                draw_scoreboard(screen, font, world["players"])

            pygame.display.flip()

    finally:
        client.disconnect()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("Raycaster FPS")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("monospace", 24, bold=True)

    bg_surface = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    draw_sky_and_floor(bg_surface)

    while True:
        choice, name, ip = menu_screen(screen, clock, font)

        if choice == "quit":
            break
        elif choice == "singleplayer":
            result = singleplayer_loop(screen, clock, font, bg_surface)
            if result == "quit":
                break
        elif choice == "host":
            result = host_loop(screen, clock, font, bg_surface, name)
            if result == "quit":
                break
        elif choice == "join":
            result = join_loop(screen, clock, font, bg_surface, name, ip)
            if result == "quit":
                break

    pygame.mouse.set_visible(True)
    pygame.event.set_grab(False)
    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
