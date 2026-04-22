"""
Raycasting FPS Game with LAN Multiplayer

Controls:
  WASD          - Move
  Mouse         - Look around
  Left Click    - Shoot / Attack
  Space         - Shoot / Attack
  1             - Rifle
  2             - Pistol
  3             - Knife
  Mouse Wheel   - Cycle weapons
  R             - Restart (when dead)
  ESC           - Quit / Back to menu
  TAB           - Scoreboard (multiplayer)
"""

import os
import pygame
import math
import sys
import time

from network import (
    GameServer, GameClient, get_local_ip,
    PLAYER_COLORS, SPAWN_POSITIONS,
    DiscoveryBeacon, DiscoveryListener,
)
from generate_sprites import generate_all_sprites, sprites_exist
from generate_enemy_sprites import generate_all_enemy_sprites, enemy_sprites_exist
from generate_ui_sprites import generate_all_ui_sprites, ui_sprites_exist
from enemy_ai import EnemyAI, STATE_PATROL, STATE_CHASE, STATE_ATTACK, STATE_RETREAT

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
MAX_DEPTH = 50
SCALE = SCREEN_WIDTH // NUM_RAYS

PLAYER_SPEED = 3.0
PLAYER_ROT_SPEED = 0.003  # default, overridden by game_settings["mouse_sensitivity"]
PLAYER_SIZE_SCALE = 0.3
MAX_PITCH = 300  # max vertical look offset in pixels
ADS_FOV_MULT = 0.65       # FOV multiplier when aiming
ADS_SENS_MULT = 0.5       # sensitivity multiplier when aiming
ADS_LERP_SPEED = 10.0     # how fast ADS transitions (per second)

MINIMAP_SCALE = 5
MINIMAP_OFFSET = 10

# Game settings (mutable, shared across menus and game loops)
game_settings = {
    "fullscreen": False,
    "mouse_sensitivity": 0.003,
    "volume": 0.7,
}

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
# Weapons:  1 = Rifle, 2 = Pistol, 3 = Knife
# ---------------------------------------------------------------------------
WPN_RIFLE = 0
WPN_PISTOL = 1
WPN_KNIFE = 2
NUM_WEAPONS = 3

WEAPONS = {
    WPN_RIFLE: {
        "name": "Rifle",
        "damage": 2,        # hits to remove from enemy hp
        "fire_rate": 0.45,  # seconds between shots
        "ammo_cost": 1,     # ammo consumed per shot
        "range": MAX_DEPTH,
        "spread": 0.03,     # hit-angle tolerance (tighter = more precise)
    },
    WPN_PISTOL: {
        "name": "Pistol",
        "damage": 1,
        "fire_rate": 0.2,
        "ammo_cost": 1,
        "range": MAX_DEPTH,
        "spread": 0.06,
    },
    WPN_KNIFE: {
        "name": "Knife",
        "damage": 3,
        "fire_rate": 0.35,
        "ammo_cost": 0,     # no ammo needed
        "range": 1.5,       # melee range
        "spread": 0.2,      # wide swing
    },
}

# ---------------------------------------------------------------------------
# Map — dynamically generated, these are the current active map globals
# ---------------------------------------------------------------------------
DUNGEON_WIDTH = 48
DUNGEON_HEIGHT = 48

WORLD_MAP = [[1] * 16 for _ in range(16)]  # placeholder, replaced by new_dungeon()
MAP_ROWS = 16
MAP_COLS = 16
CURRENT_ENEMY_SPAWNS = []   # set by new_dungeon()
CURRENT_PLAYER_SPAWN = (2.0, 2.0)


def new_dungeon(width=DUNGEON_WIDTH, height=DUNGEON_HEIGHT, seed=None):
    """Generate a fresh dungeon and update the global map state."""
    global WORLD_MAP, MAP_ROWS, MAP_COLS, CURRENT_ENEMY_SPAWNS, CURRENT_PLAYER_SPAWN
    from worldgen import generate_dungeon

    grid, player_spawn, enemy_spawns, rooms = generate_dungeon(width, height, seed)
    WORLD_MAP = grid
    MAP_ROWS = len(grid)
    MAP_COLS = len(grid[0])
    CURRENT_PLAYER_SPAWN = player_spawn
    CURRENT_ENEMY_SPAWNS = enemy_spawns
    return player_spawn, enemy_spawns


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
        self.speed = 1.5
        self.damage_timer = 0.0
        self.ai = EnemyAI(x, y)

    def update(self, px, py, dt, all_enemies=None, gunfire=False):
        if not self.alive:
            return
        self.damage_timer = max(0, self.damage_timer - dt)
        self.ai.update(self, px, py, dt, WORLD_MAP, all_enemies, gunfire)

    def take_damage(self):
        self.health -= 1
        self.damage_timer = 0.15
        if self.health <= 0:
            self.alive = False


def spawn_enemies():
    """Spawn enemies at the current dungeon's positions."""
    return [Enemy(x, y) for x, y in CURRENT_ENEMY_SPAWNS]


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


def draw_walls(surface, walls, pitch_offset=0):
    for ray, depth, wh, wt, hs in walls:
        base = WALL_COLORS.get(wt, (160, 160, 170))
        shade = max(0.15, 1.0 - depth / MAX_DEPTH)
        sm = 0.7 if hs == 1 else 1.0
        color = tuple(max(0, min(255, int(c * shade * sm))) for c in base)
        x = ray * SCALE
        y = (SCREEN_HEIGHT - wh) / 2 + pitch_offset
        pygame.draw.rect(surface, color, (x, y, SCALE, wh))


def _draw_enemy_sprite(surface, screen_x, dist, wall_depths, ai_state, dmg_timer, game_time, pitch_offset=0):
    """Draw an enemy drone sprite at screen_x based on distance and AI state."""
    if not ENEMY_SPRITES:
        return

    # Depth check — don't draw if behind a wall
    ray_idx = int(screen_x / SCREEN_WIDTH * NUM_RAYS)
    if 0 <= ray_idx < NUM_RAYS and dist > wall_depths[ray_idx]:
        return

    # Pick sprite based on state / damage
    if dmg_timer > 0:
        sprite = ENEMY_SPRITES["hit"]
    else:
        sprite = ENEMY_SPRITES.get(ai_state, ENEMY_SPRITES[STATE_CHASE])

    # Scale based on distance
    scale_factor = max(0.05, SCREEN_HEIGHT * 0.5 / max(dist, 0.3))
    sw = int(sprite.get_width() * scale_factor / SCREEN_HEIGHT * 2.5)
    sh = int(sprite.get_height() * scale_factor / SCREEN_HEIGHT * 2.5)
    sw = max(4, min(SCREEN_WIDTH, sw))
    sh = max(4, min(SCREEN_HEIGHT, sh))

    scaled = pygame.transform.smoothscale(sprite, (sw, sh))

    # Distance shading
    shade = max(0.25, 1.0 - dist / MAX_DEPTH)
    if shade < 0.95:
        dark = pygame.Surface((sw, sh), pygame.SRCALPHA)
        dark.fill((0, 0, 0, int((1.0 - shade) * 200)))
        scaled.blit(dark, (0, 0))

    # Vertical position — centered on screen horizon with slight bob
    bob = int(math.sin(game_time * 6) * 2 * (scale_factor / 100)) if dmg_timer <= 0 else 0
    x = screen_x - sw // 2
    y = SCREEN_HEIGHT // 2 - sh // 2 + bob + pitch_offset

    surface.blit(scaled, (x, y))


def draw_enemies_from_list(surface, enemy_list, px, py, pangle, wall_depths, game_time=0.0, pitch_offset=0):
    """Draw enemies as drone sprites."""
    render = []
    for e in enemy_list:
        if isinstance(e, dict):
            ex, ey, alive, dmg = e["x"], e["y"], e["alive"], e.get("dt", 0)
            ai_state = STATE_CHASE  # multiplayer enemies default to chase look
        else:
            ex, ey, alive, dmg = e.x, e.y, e.alive, e.damage_timer
            ai_state = e.ai.state if hasattr(e, "ai") else STATE_CHASE
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
        render.append((dist, ad, ai_state, dmg))

    render.sort(key=lambda r: -r[0])
    for dist, ad, ai_state, dmg in render:
        sx = int((ad / FOV + 0.5) * SCREEN_WIDTH)
        _draw_enemy_sprite(surface, sx, dist, wall_depths, ai_state, dmg, game_time, pitch_offset)


def _draw_player_sprite(surface, screen_x, dist, body_color, wall_depths, pitch_offset=0):
    """Draw a player as a simple colored humanoid."""
    sprite_height = min(SCREEN_HEIGHT, int(SCREEN_HEIGHT * 0.6 / max(dist, 0.1)))
    sprite_width = sprite_height // 2
    ray_idx = int(screen_x / SCREEN_WIDTH * NUM_RAYS)
    if 0 <= ray_idx < NUM_RAYS and dist > wall_depths[ray_idx]:
        return
    shade = max(0.2, 1.0 - dist / MAX_DEPTH)
    bc = tuple(max(0, min(255, int(c * shade))) for c in body_color)
    hc = tuple(max(0, min(255, int(c * shade))) for c in (220, 180, 150))
    top = SCREEN_HEIGHT // 2 - sprite_height // 2 + pitch_offset
    pygame.draw.rect(surface, bc, (
        screen_x - sprite_width // 2, top + sprite_height // 4,
        sprite_width, sprite_height * 3 // 4))
    hr = max(2, sprite_width // 3)
    hy = top + sprite_height // 6
    pygame.draw.circle(surface, hc, (screen_x, hy), hr)
    if hr > 4:
        eo = hr // 3
        er = max(1, hr // 5)
        pygame.draw.circle(surface, BLACK, (screen_x - eo, hy - er), er)
        pygame.draw.circle(surface, BLACK, (screen_x + eo, hy - er), er)


def draw_other_players(surface, players, my_id, px, py, pangle, wall_depths, pitch_offset=0):
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
        _draw_player_sprite(surface, sx, dist, pc, wall_depths, pitch_offset)


# ---------------------------------------------------------------------------
# Weapon sprite loading
# ---------------------------------------------------------------------------
WEAPON_SPRITES = {}  # populated by load_weapon_sprites()
ENEMY_SPRITES = {}   # populated by load_enemy_sprites()

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "weapons")
ENEMY_ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "enemies")
UI_ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "ui")

UI_SPRITES = {}  # populated by load_ui_sprites()


def load_weapon_sprites():
    """Load weapon PNGs from assets/weapons/, generating them if needed."""
    global WEAPON_SPRITES

    if not sprites_exist(ASSETS_DIR):
        generate_all_sprites(ASSETS_DIR)

    WEAPON_SPRITES[WPN_PISTOL] = {
        "idle": pygame.image.load(os.path.join(ASSETS_DIR, "pistol_idle.png")).convert_alpha(),
        "fire": pygame.image.load(os.path.join(ASSETS_DIR, "pistol_fire.png")).convert_alpha(),
    }
    WEAPON_SPRITES[WPN_RIFLE] = {
        "idle": pygame.image.load(os.path.join(ASSETS_DIR, "rifle_idle.png")).convert_alpha(),
        "fire": pygame.image.load(os.path.join(ASSETS_DIR, "rifle_fire.png")).convert_alpha(),
    }
    WEAPON_SPRITES[WPN_KNIFE] = {
        "idle": pygame.image.load(os.path.join(ASSETS_DIR, "knife_idle.png")).convert_alpha(),
        "fire": pygame.image.load(os.path.join(ASSETS_DIR, "knife_swing.png")).convert_alpha(),
    }

    # Scale sprites to fit the screen nicely
    target_h = int(SCREEN_HEIGHT * 0.45)
    for wpn_id in WEAPON_SPRITES:
        for key in WEAPON_SPRITES[wpn_id]:
            sprite = WEAPON_SPRITES[wpn_id][key]
            orig_w, orig_h = sprite.get_size()
            scale = target_h / orig_h
            new_w = int(orig_w * scale)
            WEAPON_SPRITES[wpn_id][key] = pygame.transform.smoothscale(
                sprite, (new_w, target_h)
            )


def load_enemy_sprites():
    """Load drone enemy PNGs, generating if needed."""
    global ENEMY_SPRITES

    if not enemy_sprites_exist(ENEMY_ASSETS_DIR):
        generate_all_enemy_sprites(ENEMY_ASSETS_DIR)

    _load = lambda f: pygame.image.load(os.path.join(ENEMY_ASSETS_DIR, f)).convert_alpha()
    ENEMY_SPRITES = {
        STATE_PATROL:  _load("drone_patrol.png"),
        STATE_CHASE:   _load("drone_chase.png"),
        STATE_ATTACK:  _load("drone_attack.png"),
        STATE_RETREAT: _load("drone_retreat.png"),
        "hit":         _load("drone_hit.png"),
        "wheel":       _load("drone_wheel.png"),
    }


def load_ui_sprites():
    """Load pixel-art UI PNGs, generating if needed."""
    global UI_SPRITES

    if not ui_sprites_exist(UI_ASSETS_DIR):
        generate_all_ui_sprites(UI_ASSETS_DIR)

    _load = lambda f: pygame.image.load(os.path.join(UI_ASSETS_DIR, f)).convert_alpha()
    UI_SPRITES = {
        "btn_normal":    _load("btn_normal.png"),
        "btn_hover":     _load("btn_hover.png"),
        "btn_active":    _load("btn_active.png"),
        "panel_small":   _load("panel_small.png"),
        "panel_large":   _load("panel_large.png"),
        "input_field":   _load("input_field.png"),
        "input_active":  _load("input_active.png"),
        "title_bg":      _load("title_bg.png"),
        "health_bar_bg": _load("health_bar_bg.png"),
        "lobby_row":     _load("lobby_row.png"),
    }


# Pixel-art font helper — small sizes with no anti-aliasing for crisp pixel look
def _pixel_font(size=16):
    return pygame.font.SysFont("monospace", size, bold=True)


def _pixel_text(font, text, color, antialias=False):
    return font.render(text, antialias, color)


def draw_weapon(surface, shooting_timer, weapon_id=WPN_PISTOL, ads_amount=0.0):
    if weapon_id not in WEAPON_SPRITES:
        return
    fire_rate = WEAPONS[weapon_id]["fire_rate"]

    # Pick idle or fire frame
    if shooting_timer > fire_rate * 0.5:
        frame = WEAPON_SPRITES[weapon_id]["fire"]
    else:
        frame = WEAPON_SPRITES[weapon_id]["idle"]

    # Recoil bob
    bob = int(25 * (shooting_timer / fire_rate)) if shooting_timer > 0 else 0

    fw, fh = frame.get_size()

    if ads_amount > 0.01 and weapon_id != WPN_KNIFE:
        # ADS: scale up weapon and center it
        zoom = 1.0 + ads_amount * 0.4
        new_w = int(fw * zoom)
        new_h = int(fh * zoom)
        frame = pygame.transform.smoothscale(frame, (new_w, new_h))
        x = (SCREEN_WIDTH - new_w) // 2
        y = SCREEN_HEIGHT - new_h + int(20 * (1 - ads_amount)) + bob
        # Raise weapon toward center when aiming
        y -= int(ads_amount * fh * 0.15)
    else:
        x = (SCREEN_WIDTH - fw) // 2
        y = SCREEN_HEIGHT - fh + 20 + bob

    surface.blit(frame, (x, y))


def draw_crosshair(surface, ads_amount=0.0):
    cx, cy = SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2

    if ads_amount > 0.5:
        # ADS crosshair: tight dot
        c = (255, 50, 50)
        pygame.draw.circle(surface, c, (cx, cy), 2)
        gap = 3
        length = 6
        w = 1
        pygame.draw.line(surface, c, (cx - length, cy), (cx - gap, cy), w)
        pygame.draw.line(surface, c, (cx + gap, cy), (cx + length, cy), w)
        pygame.draw.line(surface, c, (cx, cy - length), (cx, cy - gap), w)
        pygame.draw.line(surface, c, (cx, cy + gap), (cx, cy + length), w)
    else:
        # Normal crosshair
        c = (0, 255, 0)
        pygame.draw.line(surface, c, (cx - 14, cy), (cx - 6, cy), 2)
        pygame.draw.line(surface, c, (cx + 6, cy), (cx + 14, cy), 2)
        pygame.draw.line(surface, c, (cx, cy - 14), (cx, cy - 6), 2)
        pygame.draw.line(surface, c, (cx, cy + 6), (cx, cy + 14), 2)


def draw_minimap(surface, px, py, pangle, enemies, other_players=None, my_id=0):
    # Scale minimap to fit max 180px
    max_px = 180
    s = max(1, min(MINIMAP_SCALE, max_px // max(MAP_COLS, MAP_ROWS)))
    ox, oy = MINIMAP_OFFSET, MINIMAP_OFFSET
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


def draw_hud(surface, font, health, ammo, score, weapon_id=WPN_PISTOL, enemies_left=None):
    y = SCREEN_HEIGHT - 40
    surface.blit(font.render(f"HP: {health}", True, RED if health < 30 else WHITE), (20, y))
    wpn = WEAPONS[weapon_id]
    if wpn["ammo_cost"] > 0:
        surface.blit(font.render(f"AMMO: {ammo}", True, YELLOW), (180, y))
    else:
        surface.blit(font.render("AMMO: --", True, LIGHT_GRAY), (180, y))
    # Weapon name
    wname = font.render(f"[{wpn['name'].upper()}]", True, (180, 180, 200))
    surface.blit(wname, (SCREEN_WIDTH // 2 - wname.get_width() // 2, y))
    surface.blit(font.render(f"SCORE: {score}", True, WHITE), (SCREEN_WIDTH - 200, y))
    # Enemy counter
    if enemies_left is not None:
        ec = font.render(f"ENEMIES: {enemies_left}", True, RED if enemies_left > 0 else GREEN)
        surface.blit(ec, (SCREEN_WIDTH - 220, y - 30))


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
        font.render("Press R for new dungeon or ESC for menu", True, LIGHT_GRAY),
        font.render("Press R for new dungeon or ESC for menu", True, LIGHT_GRAY).get_rect(
            center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 + 70)),
    )


def draw_win_screen(surface, font, score):
    ov = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
    ov.fill((0, 0, 0, 160))
    surface.blit(ov, (0, 0))
    big = pygame.font.SysFont("monospace", 56, bold=True)
    t = big.render("DUNGEON CLEARED!", True, GREEN)
    surface.blit(t, t.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 50)))
    surface.blit(
        font.render(f"Score: {score}", True, WHITE),
        font.render(f"Score: {score}", True, WHITE).get_rect(
            center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 + 10)),
    )
    surface.blit(
        font.render("Press R for new dungeon or ESC for menu", True, LIGHT_GRAY),
        font.render("Press R for new dungeon or ESC for menu", True, LIGHT_GRAY).get_rect(
            center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 + 50)),
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
# Weapon switching helper
# ---------------------------------------------------------------------------
def handle_weapon_switch(event, current_weapon):
    """Check event for weapon switch keys/wheel. Returns new weapon_id or current."""
    if event.type == pygame.KEYDOWN:
        if event.key == pygame.K_1:
            return WPN_RIFLE
        if event.key == pygame.K_2:
            return WPN_PISTOL
        if event.key == pygame.K_3:
            return WPN_KNIFE
    elif event.type == pygame.MOUSEWHEEL:
        return (current_weapon + (1 if event.y < 0 else -1)) % NUM_WEAPONS
    return current_weapon


# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------
class TextInput:
    """Pixel-art styled text input widget."""
    def __init__(self, x, y, w, h, font, default=""):
        self.rect = pygame.Rect(x, y, w, h)
        self.font = font
        self.text = default
        self.active = False
        self._cursor_timer = 0.0

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN:
            self.active = self.rect.collidepoint(event.pos)
        elif event.type == pygame.KEYDOWN and self.active:
            if event.key == pygame.K_BACKSPACE:
                self.text = self.text[:-1]
            elif event.key == pygame.K_v and (event.mod & pygame.KMOD_CTRL):
                # Ctrl+V paste from clipboard
                try:
                    pasted = pygame.scrap.get_text()
                    if pasted:
                        self.text = (self.text + pasted.strip())[:30]
                except Exception:
                    try:
                        clip = pygame.scrap.get(pygame.SCRAP_TEXT)
                        if clip:
                            self.text = (self.text + clip.decode("utf-8").rstrip("\x00").strip())[:30]
                    except Exception:
                        pass
            elif event.key == pygame.K_a and (event.mod & pygame.KMOD_CTRL):
                pass  # Ctrl+A select all (no-op, prevent typing 'a')
            elif event.key in (pygame.K_RETURN, pygame.K_TAB):
                self.active = False
            elif len(self.text) < 30 and event.unicode.isprintable():
                self.text += event.unicode

    def draw(self, surface, dt=0.033):
        self._cursor_timer += dt
        if UI_SPRITES:
            key = "input_active" if self.active else "input_field"
            img = pygame.transform.scale(UI_SPRITES[key], (self.rect.width, self.rect.height))
            surface.blit(img, self.rect.topleft)
        else:
            border_color = WHITE if self.active else LIGHT_GRAY
            pygame.draw.rect(surface, DARK_GRAY, self.rect)
            pygame.draw.rect(surface, border_color, self.rect, 2)
        txt = _pixel_text(self.font, self.text, WHITE) if UI_SPRITES else self.font.render(self.text, True, WHITE)
        surface.blit(txt, (self.rect.x + 8, self.rect.y + (self.rect.h - txt.get_height()) // 2))
        # Blinking cursor
        if self.active and int(self._cursor_timer * 2) % 2 == 0:
            cx = self.rect.x + 10 + txt.get_width()
            pygame.draw.rect(surface, WHITE, (cx, self.rect.y + 8, 2, self.rect.h - 16))


def apply_display_mode():
    """Create/recreate the display with the current settings. Returns new screen surface."""
    flags = 0
    if game_settings["fullscreen"]:
        flags = pygame.FULLSCREEN
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), flags)
    pygame.display.set_caption("Raycaster FPS")
    return screen


def _draw_button(surface, rect, label, font, hovered=False, active=False):
    """Draw a pixel-art styled button."""
    if UI_SPRITES:
        key = "btn_active" if active else ("btn_hover" if hovered else "btn_normal")
        btn_img = UI_SPRITES[key]
        scaled = pygame.transform.scale(btn_img, (rect.width, rect.height))
        surface.blit(scaled, rect.topleft)
    else:
        color = (60, 65, 90) if hovered else (45, 48, 65)
        pygame.draw.rect(surface, color, rect)
        pygame.draw.rect(surface, (90, 95, 120), rect, 2)
    lbl = _pixel_text(font, label, WHITE) if UI_SPRITES else font.render(label, True, WHITE)
    surface.blit(lbl, lbl.get_rect(center=rect.center))


def _draw_slider(surface, rect, value, min_val, max_val, label, font):
    """Draw a horizontal slider. Returns new value if dragged."""
    # Track
    track_y = rect.centery
    pygame.draw.line(surface, LIGHT_GRAY, (rect.x, track_y), (rect.right, track_y), 2)
    # Fill
    frac = (value - min_val) / (max_val - min_val)
    fill_x = rect.x + int(frac * rect.width)
    pygame.draw.line(surface, GREEN, (rect.x, track_y), (fill_x, track_y), 3)
    # Handle
    pygame.draw.circle(surface, WHITE, (fill_x, track_y), 8)
    pygame.draw.circle(surface, LIGHT_GRAY, (fill_x, track_y), 8, 2)
    # Label
    lbl = font.render(label, True, WHITE)
    surface.blit(lbl, (rect.x, rect.y - 28))
    # Value text
    val_text = font.render(f"{value:.3f}", True, LIGHT_GRAY)
    surface.blit(val_text, (rect.right + 10, rect.y - 5))
    return frac


def options_screen(screen, clock, font):
    """
    Options menu. Returns ("back", screen) or ("quit", screen).
    Screen may be a new surface if display mode changed.
    """
    pygame.mouse.set_visible(True)
    pygame.event.set_grab(False)

    title_font = pygame.font.SysFont("monospace", 36, bold=True)
    small = pygame.font.SysFont("monospace", 18)

    cx = SCREEN_WIDTH // 2

    # Buttons
    back_btn = pygame.Rect(cx - 140, SCREEN_HEIGHT - 80, 280, 44)
    fullscreen_btn = pygame.Rect(cx - 140, 180, 280, 44)

    # Slider rects
    sens_rect = pygame.Rect(cx - 120, 290, 240, 30)

    dragging_sens = False

    while True:
        mouse_pos = pygame.mouse.get_pos()
        mouse_pressed = pygame.mouse.get_pressed()[0]

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return ("quit", screen)
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return ("back", screen)

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if back_btn.collidepoint(event.pos):
                    return ("back", screen)

                if fullscreen_btn.collidepoint(event.pos):
                    game_settings["fullscreen"] = not game_settings["fullscreen"]
                    screen = apply_display_mode()

                # Start slider drag
                if sens_rect.inflate(10, 20).collidepoint(event.pos):
                    dragging_sens = True

            if event.type == pygame.MOUSEBUTTONUP:
                dragging_sens = False

        # Update slider while dragging
        if dragging_sens and mouse_pressed:
            frac = max(0.0, min(1.0, (mouse_pos[0] - sens_rect.x) / sens_rect.width))
            game_settings["mouse_sensitivity"] = 0.001 + frac * 0.009  # range 0.001 – 0.010

        # --- Draw ---
        screen.fill((20, 20, 30))

        # Title
        t = title_font.render("OPTIONS", True, (200, 200, 220))
        screen.blit(t, t.get_rect(center=(cx, 80)))

        # Separator
        pygame.draw.line(screen, (50, 50, 65), (cx - 200, 120), (cx + 200, 120), 1)

        # Section: Display
        screen.blit(font.render("Display", True, (150, 150, 170)), (cx - 140, 145))

        # Fullscreen toggle button
        fs_label = "Fullscreen: ON" if game_settings["fullscreen"] else "Fullscreen: OFF"
        fs_hovered = fullscreen_btn.collidepoint(mouse_pos)
        color = (80, 80, 100) if fs_hovered else (50, 50, 65)
        pygame.draw.rect(screen, color, fullscreen_btn, border_radius=6)
        border_color = GREEN if game_settings["fullscreen"] else LIGHT_GRAY
        pygame.draw.rect(screen, border_color, fullscreen_btn, 2, border_radius=6)
        lbl = font.render(fs_label, True, GREEN if game_settings["fullscreen"] else WHITE)
        screen.blit(lbl, lbl.get_rect(center=fullscreen_btn.center))

        # Section: Controls
        pygame.draw.line(screen, (50, 50, 65), (cx - 200, 248), (cx + 200, 248), 1)
        screen.blit(font.render("Controls", True, (150, 150, 170)), (cx - 140, 258))

        # Sensitivity slider
        _draw_slider(
            screen, sens_rect,
            game_settings["mouse_sensitivity"],
            0.001, 0.010,
            "Mouse Sensitivity",
            font,
        )

        # Back button
        _draw_button(screen, back_btn, "Back", font, back_btn.collidepoint(mouse_pos))

        # Footer hint
        foot = small.render("ESC to go back", True, DARK_GRAY)
        screen.blit(foot, foot.get_rect(center=(cx, SCREEN_HEIGHT - 25)))

        pygame.display.flip()
        clock.tick(30)


def _draw_menu_bg(screen):
    """Dark background with subtle pixel grid pattern."""
    screen.fill((16, 18, 26))
    # Subtle grid
    for x in range(0, SCREEN_WIDTH, 32):
        pygame.draw.line(screen, (20, 22, 30), (x, 0), (x, SCREEN_HEIGHT))
    for y in range(0, SCREEN_HEIGHT, 32):
        pygame.draw.line(screen, (20, 22, 30), (0, y), (SCREEN_WIDTH, y))


def menu_screen(screen, clock, font):
    """
    Main menu. Returns one of:
      ("singleplayer", name, None, screen)
      ("multiplayer", name, None, screen)
      ("options", None, None, screen)
      ("quit", None, None, screen)
    """
    pygame.mouse.set_visible(True)
    pygame.event.set_grab(False)

    title_font = _pixel_font(48)
    sub_font = _pixel_font(18)

    cx = SCREEN_WIDTH // 2
    name_input = TextInput(cx - 120, 270, 240, 36, _pixel_font(20), "Player")

    buttons = {
        "single":      pygame.Rect(cx - 140, 340, 280, 44),
        "multiplayer": pygame.Rect(cx - 140, 400, 280, 44),
        "options":     pygame.Rect(cx - 140, 460, 280, 44),
        "quit":        pygame.Rect(cx - 140, 520, 280, 44),
    }

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return ("quit", None, None, screen)
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                return ("quit", None, None, screen)
            name_input.handle_event(event)
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                for key, rect in buttons.items():
                    if rect.collidepoint(event.pos):
                        name = name_input.text or "Player"
                        if key == "single":
                            return ("singleplayer", name, None, screen)
                        elif key == "multiplayer":
                            return ("multiplayer", name, None, screen)
                        elif key == "options":
                            return ("options", None, None, screen)
                        elif key == "quit":
                            return ("quit", None, None, screen)

        mouse_pos = pygame.mouse.get_pos()
        _draw_menu_bg(screen)

        # Title
        if UI_SPRITES:
            tbg = UI_SPRITES["title_bg"]
            screen.blit(tbg, (cx - tbg.get_width() // 2, 60))
        t = _pixel_text(title_font, "RAYCASTER  FPS", (180, 185, 210))
        screen.blit(t, t.get_rect(center=(cx, 100)))
        sub = _pixel_text(sub_font, "COMBAT  DRONE  EDITION", (80, 85, 110))
        screen.blit(sub, sub.get_rect(center=(cx, 140)))

        # Decorative line
        pygame.draw.line(screen, (50, 55, 75), (cx - 160, 170), (cx + 160, 170), 2)

        # Name input
        screen.blit(_pixel_text(_pixel_font(16), "CALL SIGN:", (120, 125, 150)), (cx - 120, 248))
        name_input.draw(screen)

        # Buttons
        labels = {"single": "SINGLEPLAYER", "multiplayer": "MULTIPLAYER",
                  "options": "OPTIONS", "quit": "QUIT"}
        for key, rect in buttons.items():
            hov = rect.collidepoint(mouse_pos)
            _draw_button(screen, rect, labels[key], _pixel_font(20), hov)

        # Version
        screen.blit(_pixel_text(sub_font, "v0.2", (40, 42, 55)), (10, SCREEN_HEIGHT - 24))

        pygame.display.flip()
        clock.tick(30)


def multiplayer_screen(screen, clock, font):
    """
    Multiplayer submenu — Host, Browse/Join, Back.
    Returns one of:
      ("host", name, None, screen)
      ("join", name, ip, screen)
      ("back", None, None, screen)
      ("quit", None, None, screen)
    """
    pygame.mouse.set_visible(True)
    pygame.event.set_grab(False)

    title_font = _pixel_font(36)
    sub_font = _pixel_font(18)
    row_font = _pixel_font(16)

    local_ip = get_local_ip()
    cx = SCREEN_WIDTH // 2

    ip_input = TextInput(cx - 120, 570, 240, 36, _pixel_font(20), "")

    host_btn = pygame.Rect(cx - 140, 130, 280, 44)
    join_manual_btn = pygame.Rect(cx + 130, 566, 100, 40)
    back_btn = pygame.Rect(cx - 140, SCREEN_HEIGHT - 70, 280, 44)

    browser_rect = pygame.Rect(cx - 220, 200, 440, 340)
    selected_game = None

    listener = DiscoveryListener()

    try:
        while True:
            listener.poll(1.0 / 30)
            games = listener.get_games()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return ("quit", None, None, screen)
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        return ("back", None, None, screen)
                    if event.key == pygame.K_RETURN and selected_game:
                        return ("join", None, selected_game, screen)

                ip_input.handle_event(event)

                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if host_btn.collidepoint(event.pos):
                        return ("host", None, None, screen)
                    if back_btn.collidepoint(event.pos):
                        return ("back", None, None, screen)
                    if join_manual_btn.collidepoint(event.pos) and ip_input.text.strip():
                        return ("join", None, ip_input.text.strip(), screen)

                    # Click server browser rows
                    if browser_rect.collidepoint(event.pos):
                        gy = event.pos[1] - (browser_rect.y + 30)
                        idx = gy // 34
                        if 0 <= idx < len(games):
                            selected_game = games[idx]["ip"]

                # Double-click to join
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if selected_game and browser_rect.collidepoint(event.pos):
                        gy = event.pos[1] - (browser_rect.y + 30)
                        idx = gy // 34
                        if 0 <= idx < len(games) and games[idx]["ip"] == selected_game:
                            return ("join", None, selected_game, screen)

            mouse_pos = pygame.mouse.get_pos()
            _draw_menu_bg(screen)

            # Title
            t = _pixel_text(title_font, "MULTIPLAYER", (180, 185, 210))
            screen.blit(t, t.get_rect(center=(cx, 60)))
            pygame.draw.line(screen, (50, 55, 75), (cx - 140, 85), (cx + 140, 85), 2)

            # Host button
            _draw_button(screen, host_btn, f"HOST GAME ({local_ip})", _pixel_font(18),
                         host_btn.collidepoint(mouse_pos))

            # --- Server Browser Panel ---
            if UI_SPRITES:
                panel = pygame.transform.scale(UI_SPRITES["panel_small"],
                                               (browser_rect.width, browser_rect.height))
                screen.blit(panel, browser_rect.topleft)
            else:
                pygame.draw.rect(screen, (25, 27, 38), browser_rect)
                pygame.draw.rect(screen, (60, 65, 85), browser_rect, 1)

            screen.blit(_pixel_text(row_font, "LAN GAMES", (100, 105, 130)),
                        (browser_rect.x + 10, browser_rect.y + 8))

            if games:
                for i, game in enumerate(games[:8]):
                    gy = browser_rect.y + 30 + i * 34
                    row_rect = pygame.Rect(browser_rect.x + 6, gy, browser_rect.width - 12, 30)

                    # Row background
                    if UI_SPRITES:
                        row_bg = pygame.transform.scale(UI_SPRITES["lobby_row"],
                                                        (row_rect.width, row_rect.height))
                        screen.blit(row_bg, row_rect.topleft)

                    if game["ip"] == selected_game:
                        pygame.draw.rect(screen, (40, 65, 95), row_rect)
                        pygame.draw.rect(screen, (80, 120, 180), row_rect, 1)
                    elif row_rect.collidepoint(mouse_pos):
                        pygame.draw.rect(screen, (35, 45, 65), row_rect)

                    screen.blit(_pixel_text(row_font, game["name"][:22], WHITE),
                                (row_rect.x + 8, gy + 6))
                    info = f"{game['ip']}  {game['players']}P"
                    it = _pixel_text(row_font, info, LIGHT_GRAY)
                    screen.blit(it, (row_rect.right - it.get_width() - 8, gy + 6))

                # Join button
                if selected_game:
                    jb = pygame.Rect(browser_rect.right - 120, browser_rect.bottom - 40, 110, 34)
                    _draw_button(screen, jb, "JOIN", _pixel_font(18), jb.collidepoint(mouse_pos))
                    if pygame.mouse.get_pressed()[0] and jb.collidepoint(mouse_pos):
                        return ("join", None, selected_game, screen)
            else:
                nt = _pixel_text(sub_font, "Scanning for games...", (50, 52, 65))
                screen.blit(nt, nt.get_rect(center=browser_rect.center))

            # Manual IP
            screen.blit(_pixel_text(row_font, "OR ENTER IP:", (80, 85, 110)), (cx - 120, 552))
            ip_input.draw(screen)
            _draw_button(screen, join_manual_btn, "JOIN", _pixel_font(16),
                         join_manual_btn.collidepoint(mouse_pos))

            # Back
            _draw_button(screen, back_btn, "BACK", _pixel_font(20),
                         back_btn.collidepoint(mouse_pos))

            pygame.display.flip()
            clock.tick(30)
    finally:
        listener.stop()


def lobby_screen(screen, clock, font, server, beacon, player_name):
    """
    Host lobby — waits for players, shows connected list.
    Returns "start" when host clicks Start, "quit" to exit, "back" to cancel.
    """
    pygame.mouse.set_visible(True)
    pygame.event.set_grab(False)

    title_font = _pixel_font(32)
    row_font = _pixel_font(18)
    sub_font = _pixel_font(16)
    local_ip = get_local_ip()
    cx = SCREEN_WIDTH // 2

    start_btn = pygame.Rect(cx - 140, SCREEN_HEIGHT - 130, 280, 48)
    back_btn = pygame.Rect(cx - 140, SCREEN_HEIGHT - 70, 280, 44)
    panel_rect = pygame.Rect(cx - 230, 160, 460, 380)

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return "quit"
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return "back"
                if event.key == pygame.K_RETURN:
                    return "start"
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if start_btn.collidepoint(event.pos):
                    return "start"
                if back_btn.collidepoint(event.pos):
                    return "back"

        mouse_pos = pygame.mouse.get_pos()
        _draw_menu_bg(screen)

        # Title
        t = _pixel_text(title_font, "GAME LOBBY", (180, 185, 210))
        screen.blit(t, t.get_rect(center=(cx, 50)))
        info = _pixel_text(sub_font, f"HOSTING ON {local_ip}", GREEN)
        screen.blit(info, info.get_rect(center=(cx, 85)))
        pygame.draw.line(screen, (50, 55, 75), (cx - 160, 110), (cx + 160, 110), 2)

        # Waiting message
        msg = _pixel_text(sub_font, "Waiting for players to join...", (80, 85, 110))
        screen.blit(msg, msg.get_rect(center=(cx, 135)))

        # Player list panel
        if UI_SPRITES:
            panel = pygame.transform.scale(UI_SPRITES["panel_large"],
                                           (panel_rect.width, panel_rect.height))
            screen.blit(panel, panel_rect.topleft)
        else:
            pygame.draw.rect(screen, (22, 24, 35), panel_rect)
            pygame.draw.rect(screen, (60, 65, 85), panel_rect, 1)

        screen.blit(_pixel_text(sub_font, "CONNECTED PLAYERS", (100, 105, 130)),
                    (panel_rect.x + 14, panel_rect.y + 10))

        players = server.get_lobby_players()
        for i, p in enumerate(players[:10]):
            py_pos = panel_rect.y + 38 + i * 34
            row_rect = pygame.Rect(panel_rect.x + 8, py_pos, panel_rect.width - 16, 30)

            if UI_SPRITES:
                row_bg = pygame.transform.scale(UI_SPRITES["lobby_row"],
                                                (row_rect.width, row_rect.height))
                screen.blit(row_bg, row_rect.topleft)
            else:
                pygame.draw.rect(screen, (30, 33, 48), row_rect)
                pygame.draw.rect(screen, (50, 55, 72), row_rect, 1)

            # Player color dot
            pc = PLAYER_COLORS[p["id"] % len(PLAYER_COLORS)]
            pygame.draw.circle(screen, pc, (row_rect.x + 16, py_pos + 15), 6)
            pygame.draw.circle(screen, BLACK, (row_rect.x + 16, py_pos + 15), 6, 1)

            # Name
            screen.blit(_pixel_text(row_font, p["name"][:20], WHITE),
                        (row_rect.x + 30, py_pos + 5))

            # Host badge
            if p["id"] == 0:
                badge = _pixel_text(sub_font, "HOST", YELLOW)
                screen.blit(badge, (row_rect.right - badge.get_width() - 10, py_pos + 7))

        # Player count
        count_txt = _pixel_text(row_font, f"{len(players)} / 4", LIGHT_GRAY)
        screen.blit(count_txt, (panel_rect.right - count_txt.get_width() - 14, panel_rect.y + 10))

        # Buttons
        can_start = len(players) >= 1
        if can_start:
            _draw_button(screen, start_btn, "START GAME", _pixel_font(22),
                         start_btn.collidepoint(mouse_pos), active=True)
        else:
            _draw_button(screen, start_btn, "WAITING...", _pixel_font(22), False)

        _draw_button(screen, back_btn, "CANCEL", _pixel_font(20),
                     back_btn.collidepoint(mouse_pos))

        pygame.display.flip()
        clock.tick(30)


def client_lobby_screen(screen, clock, font, client, host_ip, player_name="Player"):
    """
    Client lobby — waits for host to start.
    Returns "start" when game begins, "quit" to exit, "back" to cancel.
    """
    pygame.mouse.set_visible(True)
    pygame.event.set_grab(False)

    title_font = _pixel_font(32)
    row_font = _pixel_font(18)
    sub_font = _pixel_font(16)
    cx = SCREEN_WIDTH // 2

    back_btn = pygame.Rect(cx - 140, SCREEN_HEIGHT - 70, 280, 44)
    panel_rect = pygame.Rect(cx - 230, 160, 460, 380)
    retry_timer = 0.0

    while True:
        dt = clock.tick(30) / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return "quit"
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                return "back"
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if back_btn.collidepoint(event.pos):
                    return "back"

        client.poll()

        # Retry join if not connected yet
        if not client.connected:
            retry_timer += dt
            if retry_timer >= 1.0:
                retry_timer = 0.0
                client.connect(host_ip, player_name)

        # Check if game started
        if client.connected and not client.in_lobby:
            return "start"

        mouse_pos = pygame.mouse.get_pos()
        _draw_menu_bg(screen)

        # Title
        t = _pixel_text(title_font, "GAME LOBBY", (180, 185, 210))
        screen.blit(t, t.get_rect(center=(cx, 50)))
        info = _pixel_text(sub_font, f"CONNECTED TO {host_ip}", BLUE)
        screen.blit(info, info.get_rect(center=(cx, 85)))
        pygame.draw.line(screen, (50, 55, 75), (cx - 160, 110), (cx + 160, 110), 2)

        if not client.connected:
            msg = _pixel_text(sub_font, "Connecting...", YELLOW)
            screen.blit(msg, msg.get_rect(center=(cx, 135)))
        else:
            msg = _pixel_text(sub_font, "Waiting for host to start...", (80, 85, 110))
            screen.blit(msg, msg.get_rect(center=(cx, 135)))

        # Player list panel
        if UI_SPRITES:
            panel = pygame.transform.scale(UI_SPRITES["panel_large"],
                                           (panel_rect.width, panel_rect.height))
            screen.blit(panel, panel_rect.topleft)
        else:
            pygame.draw.rect(screen, (22, 24, 35), panel_rect)
            pygame.draw.rect(screen, (60, 65, 85), panel_rect, 1)

        screen.blit(_pixel_text(sub_font, "PLAYERS", (100, 105, 130)),
                    (panel_rect.x + 14, panel_rect.y + 10))

        if client.world:
            players = client.world.get("players", {})
            for i, (pid_str, p) in enumerate(sorted(players.items())):
                pid = int(pid_str)
                py_pos = panel_rect.y + 38 + i * 34
                row_rect = pygame.Rect(panel_rect.x + 8, py_pos, panel_rect.width - 16, 30)

                if UI_SPRITES:
                    row_bg = pygame.transform.scale(UI_SPRITES["lobby_row"],
                                                    (row_rect.width, row_rect.height))
                    screen.blit(row_bg, row_rect.topleft)
                else:
                    pygame.draw.rect(screen, (30, 33, 48), row_rect)

                pc = PLAYER_COLORS[pid % len(PLAYER_COLORS)]
                pygame.draw.circle(screen, pc, (row_rect.x + 16, py_pos + 15), 6)
                screen.blit(_pixel_text(row_font, p.get("name", f"Player {pid}")[:20], WHITE),
                            (row_rect.x + 30, py_pos + 5))
                if pid == 0:
                    badge = _pixel_text(sub_font, "HOST", YELLOW)
                    screen.blit(badge, (row_rect.right - badge.get_width() - 10, py_pos + 7))

        # Back
        _draw_button(screen, back_btn, "DISCONNECT", _pixel_font(20),
                     back_btn.collidepoint(mouse_pos))

        pygame.display.flip()
        clock.tick(30)


# ---------------------------------------------------------------------------
# Game loops
# ---------------------------------------------------------------------------
def singleplayer_loop(screen, clock, font, bg_surface):
    pygame.mouse.set_visible(False)
    pygame.event.set_grab(True)

    def reset():
        player_spawn, _ = new_dungeon()
        return {
            "px": player_spawn[0], "py": player_spawn[1], "pangle": 0.0,
            "pitch": 0.0, "ads": 0.0,
            "health": 100, "ammo": 50, "score": 0,
            "enemies": spawn_enemies(),
            "total_enemies": len(CURRENT_ENEMY_SPAWNS),
            "shooting_timer": 0.0, "damage_timer": 0.0,
            "damage_cooldown": 0.0, "dead": False,
            "won": False, "weapon": WPN_PISTOL,
        }

    st = reset()
    _game_time = 0.0

    while True:
        dt = clock.tick(FPS) / 1000.0
        _game_time += dt
        shoot = False

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return "quit"
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return "menu"
                if event.key == pygame.K_r and (st["dead"] or st["won"]):
                    st = reset()
                if event.key == pygame.K_SPACE and not st["dead"] and not st["won"]:
                    shoot = True
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1 and not st["dead"] and not st["won"]:
                    shoot = True
            elif event.type == pygame.MOUSEMOTION and not st["dead"] and not st["won"]:
                sens = game_settings["mouse_sensitivity"]
                if st["ads"] > 0.1:
                    sens *= ADS_SENS_MULT
                st["pangle"] += event.rel[0] * sens
                st["pitch"] -= event.rel[1] * 0.5 * (ADS_SENS_MULT if st["ads"] > 0.1 else 1.0)
                st["pitch"] = max(-MAX_PITCH, min(MAX_PITCH, st["pitch"]))
            if not st["dead"] and not st["won"]:
                st["weapon"] = handle_weapon_switch(event, st["weapon"])

        # ADS (right mouse button held)
        aiming = pygame.mouse.get_pressed()[2] and not st["dead"] and not st["won"]
        aiming = aiming and st["weapon"] != WPN_KNIFE  # knife can't ADS
        target_ads = 1.0 if aiming else 0.0
        st["ads"] += (target_ads - st["ads"]) * min(1.0, ADS_LERP_SPEED * dt)

        enemies_left = sum(1 for e in st["enemies"] if e.alive)
        pitch_offset = int(st["pitch"])

        # Frozen screens (dead / won)
        if st["dead"] or st["won"]:
            screen.blit(bg_surface, (0, pitch_offset))
            walls = cast_rays(st["px"], st["py"], st["pangle"])
            draw_walls(screen, walls, pitch_offset)
            wd = [w[1] for w in walls]
            draw_enemies_from_list(screen, st["enemies"], st["px"], st["py"], st["pangle"], wd, _game_time, pitch_offset)
            if st["dead"]:
                draw_death_screen(screen, font, st["score"])
            else:
                draw_win_screen(screen, font, st["score"])
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
        move_speed = PLAYER_SPEED * (0.5 if st["ads"] > 0.5 else 1.0)
        if ln > 0:
            mx = mx / ln * move_speed * dt
            my = my / ln * move_speed * dt
        nx, ny = st["px"] + mx, st["py"] + my
        m = PLAYER_SIZE_SCALE
        if not is_wall(nx + m, st["py"]) and not is_wall(nx - m, st["py"]):
            st["px"] = nx
        if not is_wall(st["px"], ny + m) and not is_wall(st["px"], ny - m):
            st["py"] = ny

        # Shooting
        wpn = WEAPONS[st["weapon"]]
        st["shooting_timer"] = max(0, st["shooting_timer"] - dt)
        can_fire = st["shooting_timer"] <= 0
        has_ammo = wpn["ammo_cost"] == 0 or st["ammo"] >= wpn["ammo_cost"]

        if shoot and can_fire and has_ammo:
            st["ammo"] -= wpn["ammo_cost"]
            st["shooting_timer"] = wpn["fire_rate"]
            best, bd = None, float("inf")
            for e in st["enemies"]:
                if not e.alive:
                    continue
                dx, dy = e.x - st["px"], e.y - st["py"]
                d = math.hypot(dx, dy)
                if d > wpn["range"]:
                    continue
                ea = math.atan2(dy, dx)
                diff = ea - st["pangle"]
                while diff > math.pi: diff -= 2 * math.pi
                while diff < -math.pi: diff += 2 * math.pi
                spread = wpn["spread"] * (0.4 if st["ads"] > 0.5 else 1.0)
                ht = max(spread, 0.3 / max(d, 0.1))
                if abs(diff) < ht and d < bd:
                    wd2 = cast_single_ray(st["px"], st["py"], ea)
                    if wd2 > d - 0.3:
                        bd, best = d, e
            if best:
                for _ in range(wpn["damage"]):
                    best.take_damage()
                if not best.alive:
                    st["score"] += 100

        # Enemies
        st["damage_cooldown"] = max(0, st["damage_cooldown"] - dt)
        st["damage_timer"] = max(0, st["damage_timer"] - dt)
        all_enemies = [(e, e.ai) for e in st["enemies"]]
        did_shoot = shoot and can_fire and has_ammo
        for e in st["enemies"]:
            e.update(st["px"], st["py"], dt, all_enemies, gunfire=did_shoot)
            if e.alive and math.hypot(e.x - st["px"], e.y - st["py"]) < 0.8 and st["damage_cooldown"] <= 0:
                st["health"] -= 10
                st["damage_timer"] = 0.3
                st["damage_cooldown"] = 0.5
                if st["health"] <= 0:
                    st["health"] = 0
                    st["dead"] = True

        # Win condition: all enemies dead
        if enemies_left == 0 and not st["won"]:
            st["won"] = True

        # Render
        screen.fill(FLOOR_BROWN)  # fill gaps when looking up/down
        screen.blit(bg_surface, (0, pitch_offset))
        walls = cast_rays(st["px"], st["py"], st["pangle"])
        draw_walls(screen, walls, pitch_offset)
        wd = [w[1] for w in walls]
        draw_enemies_from_list(screen, st["enemies"], st["px"], st["py"], st["pangle"], wd, _game_time, pitch_offset)
        draw_weapon(screen, st["shooting_timer"], st["weapon"], st["ads"])
        draw_crosshair(screen, st["ads"])
        draw_minimap(screen, st["px"], st["py"], st["pangle"], st["enemies"])
        draw_hud(screen, font, st["health"], st["ammo"], st["score"], st["weapon"], enemies_left)
        draw_damage_overlay(screen, st["damage_timer"])
        screen.blit(font.render(f"FPS: {int(clock.get_fps())}", True, WHITE), (SCREEN_WIDTH - 150, 10))
        pygame.display.flip()


def host_loop(screen, clock, font, bg_surface, player_name, server=None, beacon=None):
    """Host a multiplayer game. Runs a server + plays as player 0."""
    if server is None:
        # Legacy path: create server inline (no lobby)
        new_dungeon()
        game_name = f"{player_name}'s Game"
        server = GameServer(WORLD_MAP, spawn_enemies, CURRENT_PLAYER_SPAWN, host_name=game_name)
        server.start()
        server.register_host(player_name)
        server.start_game()
    if beacon is None:
        beacon = DiscoveryBeacon(f"{player_name}'s Game", lambda: len(server.players))
        beacon.start()

    host_id = 0  # host is always player 0

    pygame.mouse.set_visible(False)
    pygame.event.set_grab(True)

    local_ip = get_local_ip()

    px, py = CURRENT_PLAYER_SPAWN
    pangle_val = 0.0
    pitch_val = 0.0
    shooting_timer = 0.0
    damage_timer = 0.0
    prev_health = 100
    weapon = WPN_PISTOL
    _game_time = 0.0

    result = "menu"

    try:
        while True:
            dt = clock.tick(FPS) / 1000.0
            _game_time += dt
            pitch_offset = int(pitch_val)
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
                    pangle_val += event.rel[0] * game_settings["mouse_sensitivity"]
                    pitch_val -= event.rel[1] * 0.5
                    pitch_val = max(-MAX_PITCH, min(MAX_PITCH, pitch_val))
                weapon = handle_weapon_switch(event, weapon)

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

            wpn = WEAPONS[weapon]
            shooting_timer = max(0, shooting_timer - dt)
            actual_shoot = False
            if shoot and shooting_timer <= 0:
                shooting_timer = wpn["fire_rate"]
                actual_shoot = True

            server.update_host_state(px, py, pangle_val, actual_shoot, weapon)
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
            screen.fill(FLOOR_BROWN)
            screen.blit(bg_surface, (0, pitch_offset))
            walls = cast_rays(px, py, pangle_val)
            draw_walls(screen, walls, pitch_offset)
            wd = [w[1] for w in walls]
            draw_enemies_from_list(screen, world["enemies"], px, py, pangle_val, wd, _game_time, pitch_offset)
            draw_other_players(screen, world["players"], host_id, px, py, pangle_val, wd, pitch_offset)
            draw_weapon(screen, shooting_timer, weapon)
            draw_crosshair(screen)
            draw_minimap(screen, px, py, pangle_val, world["enemies"], world["players"], host_id)
            draw_hud(screen, font, health, ammo, score, weapon)
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
        beacon.stop()
        server.stop()


def join_loop(screen, clock, font, bg_surface, player_name, host_ip, client=None):
    """Join a multiplayer game as a client."""
    if client is None:
        client = GameClient()
        client.connect(host_ip, player_name)

    pygame.mouse.set_visible(False)
    pygame.event.set_grab(True)

    # We'll start at a default pos and update once we get the welcome
    px, py, pangle_val = 2.0, 2.0, 0.0
    pitch_val = 0.0
    shooting_timer = 0.0
    damage_timer = 0.0
    prev_health = 100
    connecting_time = 0.0
    weapon = WPN_PISTOL
    _game_time = 0.0

    result = "menu"

    try:
        while True:
            dt = clock.tick(FPS) / 1000.0
            _game_time += dt
            pitch_offset = int(pitch_val)
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
                    pangle_val += event.rel[0] * game_settings["mouse_sensitivity"]
                    pitch_val -= event.rel[1] * 0.5
                    pitch_val = max(-MAX_PITCH, min(MAX_PITCH, pitch_val))
                weapon = handle_weapon_switch(event, weapon)

            client.poll()

            # Use spawn position from server once connected
            if client.connected and hasattr(client, 'spawn_x') and px == 2.0 and py == 2.0:
                px = client.spawn_x
                py = client.spawn_y

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

            wpn = WEAPONS[weapon]
            shooting_timer = max(0, shooting_timer - dt)
            actual_shoot = False
            if shoot and shooting_timer <= 0:
                shooting_timer = wpn["fire_rate"]
                actual_shoot = True

            client.send_state(px, py, pangle_val, actual_shoot, weapon)

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
            screen.fill(FLOOR_BROWN)
            screen.blit(bg_surface, (0, pitch_offset))
            walls = cast_rays(px, py, pangle_val)
            draw_walls(screen, walls, pitch_offset)
            wd = [w[1] for w in walls]
            draw_enemies_from_list(screen, world["enemies"], px, py, pangle_val, wd, _game_time, pitch_offset)
            draw_other_players(screen, world["players"], client.my_id, px, py, pangle_val, wd, pitch_offset)
            draw_weapon(screen, shooting_timer, weapon)
            draw_crosshair(screen)
            draw_minimap(screen, px, py, pangle_val, world["enemies"], world["players"], client.my_id)
            draw_hud(screen, font, health, ammo, score, weapon)
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
    screen = apply_display_mode()
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("monospace", 24, bold=True)

    bg_surface = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    draw_sky_and_floor(bg_surface)

    load_weapon_sprites()
    load_enemy_sprites()
    load_ui_sprites()

    player_name = "Player"

    while True:
        choice, name, ip, screen = menu_screen(screen, clock, font)
        if name:
            player_name = name

        if choice == "quit":
            break

        elif choice == "options":
            result, screen = options_screen(screen, clock, font)
            if result == "quit":
                break

        elif choice == "singleplayer":
            result = singleplayer_loop(screen, clock, font, bg_surface)
            if result == "quit":
                break

        elif choice == "multiplayer":
            # Multiplayer submenu
            mp_result, _, mp_ip, screen = multiplayer_screen(screen, clock, font)

            if mp_result == "quit":
                break
            elif mp_result == "back":
                continue
            elif mp_result == "host":
                # Create server + beacon, show lobby
                new_dungeon()
                game_name = f"{player_name}'s Game"
                server = GameServer(WORLD_MAP, spawn_enemies, CURRENT_PLAYER_SPAWN,
                                    host_name=game_name)
                server.start()
                server.register_host(player_name)
                beacon = DiscoveryBeacon(game_name, lambda: len(server.players))
                beacon.start()

                lobby_result = lobby_screen(screen, clock, font, server, beacon, player_name)

                if lobby_result == "start":
                    server.start_game()
                    result = host_loop(screen, clock, font, bg_surface, player_name,
                                       server=server, beacon=beacon)
                    if result == "quit":
                        break
                elif lobby_result == "quit":
                    beacon.stop()
                    server.stop()
                    break
                else:  # back
                    beacon.stop()
                    server.stop()

            elif mp_result == "join":
                # Connect to server, show client lobby
                client = GameClient()
                client.connect(mp_ip, player_name)

                lobby_result = client_lobby_screen(screen, clock, font, client, mp_ip, player_name)

                if lobby_result == "start":
                    result = join_loop(screen, clock, font, bg_surface, player_name,
                                       mp_ip, client=client)
                    if result == "quit":
                        break
                elif lobby_result == "quit":
                    client.disconnect()
                    break
                else:  # back
                    client.disconnect()

    pygame.mouse.set_visible(True)
    pygame.event.set_grab(False)
    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
