"""
Auto-generates combat drone enemy sprite PNGs.
Saved to assets/enemies/. Replace with custom art if desired.
"""

import os
import pygame
import math


def _outline_rect(surf, color, rect, thickness=2):
    x, y, w, h = rect
    pygame.draw.rect(surf, (0, 0, 0), (x - thickness, y - thickness,
                                        w + thickness * 2, h + thickness * 2))
    pygame.draw.rect(surf, color, rect)


def _outline_circle(surf, color, center, radius, thickness=2):
    pygame.draw.circle(surf, (0, 0, 0), center, radius + thickness)
    pygame.draw.circle(surf, color, center, radius)


def _shade(color, factor):
    return tuple(max(0, min(255, int(c * factor))) for c in color)


# ---------------------------------------------------------------------------
# Drone body (shared across all states)
# ---------------------------------------------------------------------------
def _draw_drone_body(surf, cx, cy, w, h):
    """Draw the drone chassis centered at (cx, cy)."""
    metal_dark = (55, 58, 62)
    metal_mid = (80, 84, 90)
    metal_light = (110, 114, 120)
    accent = (45, 45, 50)

    # Main hull — rounded rectangle shape via polygon
    hull_top = cy - h // 2
    hull_bot = cy + h // 4
    hw = w // 2

    # Hull body
    hull_pts = [
        (cx - hw + 8, hull_top),
        (cx + hw - 8, hull_top),
        (cx + hw, hull_top + 10),
        (cx + hw, hull_bot - 5),
        (cx + hw - 5, hull_bot),
        (cx - hw + 5, hull_bot),
        (cx - hw, hull_bot - 5),
        (cx - hw, hull_top + 10),
    ]
    pygame.draw.polygon(surf, (0, 0, 0), hull_pts)
    # Slightly inset fill
    inner = [
        (cx - hw + 10, hull_top + 2),
        (cx + hw - 10, hull_top + 2),
        (cx + hw - 2, hull_top + 12),
        (cx + hw - 2, hull_bot - 7),
        (cx + hw - 7, hull_bot - 2),
        (cx - hw + 7, hull_bot - 2),
        (cx - hw + 2, hull_bot - 7),
        (cx - hw + 2, hull_top + 12),
    ]
    pygame.draw.polygon(surf, metal_mid, inner)

    # Top armor plate
    _outline_rect(surf, metal_dark, (cx - hw + 12, hull_top + 4, w - 24, 14))
    # Highlight on top plate
    pygame.draw.rect(surf, metal_light, (cx - hw + 14, hull_top + 6, w - 28, 4))

    # Vent grille (horizontal lines)
    vent_y = cy - 5
    for i in range(4):
        y = vent_y + i * 6
        pygame.draw.line(surf, accent, (cx - hw + 15, y), (cx + hw - 15, y), 2)
        pygame.draw.line(surf, metal_light, (cx - hw + 15, y + 1), (cx + hw - 15, y + 1), 1)

    # Side armor panels
    pygame.draw.rect(surf, metal_dark, (cx - hw + 2, cy - 15, 8, 30))
    pygame.draw.rect(surf, metal_dark, (cx + hw - 10, cy - 15, 8, 30))

    # Bottom plate
    _outline_rect(surf, accent, (cx - hw + 8, hull_bot - 6, w - 16, 6))

    return hull_top, hull_bot


def _draw_wheels(surf, cx, hull_bot, w, rotation_frame=0):
    """Draw two wheels at the bottom of the drone."""
    wheel_r = 12
    wheel_color = (40, 40, 45)
    hub_color = (70, 70, 75)
    spoke_color = (90, 90, 95)

    for side in [-1, 1]:
        wx = cx + side * (w // 2 - 8)
        wy = hull_bot + wheel_r - 2

        # Wheel outline
        pygame.draw.circle(surf, (0, 0, 0), (wx, wy), wheel_r + 2)
        pygame.draw.circle(surf, wheel_color, (wx, wy), wheel_r)

        # Tire tread marks (rotate with frame)
        for i in range(6):
            angle = rotation_frame * 0.5 + i * (math.pi / 3)
            ex = wx + int(math.cos(angle) * (wheel_r - 2))
            ey = wy + int(math.sin(angle) * (wheel_r - 2))
            pygame.draw.line(surf, spoke_color, (wx, wy), (ex, ey), 1)

        # Hub cap
        pygame.draw.circle(surf, hub_color, (wx, wy), 4)
        pygame.draw.circle(surf, (0, 0, 0), (wx, wy), 4, 1)


def _draw_eye(surf, cx, hull_top, eye_color):
    """Draw the sensor eye on the drone."""
    ey = hull_top + 10
    # Eye socket
    pygame.draw.ellipse(surf, (20, 20, 25), (cx - 14, ey - 6, 28, 14))
    # Eye glow
    pygame.draw.ellipse(surf, eye_color, (cx - 10, ey - 4, 20, 10))
    # Bright center
    bright = tuple(min(255, c + 80) for c in eye_color)
    pygame.draw.ellipse(surf, bright, (cx - 4, ey - 2, 8, 5))
    # Glint
    pygame.draw.circle(surf, (255, 255, 255), (cx - 6, ey - 1), 2)


# ---------------------------------------------------------------------------
# Generate per-state sprites
# ---------------------------------------------------------------------------
DRONE_W, DRONE_H = 120, 100


def generate_drone_patrol():
    surf = pygame.Surface((DRONE_W, DRONE_H), pygame.SRCALPHA)
    cx, cy = DRONE_W // 2, DRONE_H // 2 - 5
    hull_top, hull_bot = _draw_drone_body(surf, cx, cy, 90, 60)
    _draw_wheels(surf, cx, hull_bot, 90, rotation_frame=0)
    _draw_eye(surf, cx, hull_top, (60, 130, 220))  # blue
    return surf


def generate_drone_chase():
    surf = pygame.Surface((DRONE_W, DRONE_H), pygame.SRCALPHA)
    cx, cy = DRONE_W // 2, DRONE_H // 2 - 5
    hull_top, hull_bot = _draw_drone_body(surf, cx, cy, 90, 60)
    _draw_wheels(surf, cx, hull_bot, 90, rotation_frame=2)
    _draw_eye(surf, cx, hull_top, (230, 180, 30))  # yellow
    return surf


def generate_drone_attack():
    surf = pygame.Surface((DRONE_W, DRONE_H), pygame.SRCALPHA)
    cx, cy = DRONE_W // 2, DRONE_H // 2 - 5
    hull_top, hull_bot = _draw_drone_body(surf, cx, cy, 90, 60)
    _draw_wheels(surf, cx, hull_bot, 90, rotation_frame=4)
    _draw_eye(surf, cx, hull_top, (220, 40, 40))  # red
    return surf


def generate_drone_retreat():
    surf = pygame.Surface((DRONE_W, DRONE_H), pygame.SRCALPHA)
    cx, cy = DRONE_W // 2, DRONE_H // 2 - 5
    hull_top, hull_bot = _draw_drone_body(surf, cx, cy, 90, 60)
    _draw_wheels(surf, cx, hull_bot, 90, rotation_frame=1)
    _draw_eye(surf, cx, hull_top, (180, 50, 200))  # purple
    return surf


def generate_drone_hit():
    """White flash version for damage feedback."""
    surf = pygame.Surface((DRONE_W, DRONE_H), pygame.SRCALPHA)
    cx, cy = DRONE_W // 2, DRONE_H // 2 - 5

    # Draw the same shape but all white/bright
    hw, hh = 45, 30
    hull_top = cy - hh
    hull_bot = cy + hh // 2

    hull_pts = [
        (cx - hw + 8, hull_top),
        (cx + hw - 8, hull_top),
        (cx + hw, hull_top + 10),
        (cx + hw, hull_bot - 5),
        (cx + hw - 5, hull_bot),
        (cx - hw + 5, hull_bot),
        (cx - hw, hull_bot - 5),
        (cx - hw, hull_top + 10),
    ]
    pygame.draw.polygon(surf, (255, 255, 255), hull_pts)
    pygame.draw.polygon(surf, (200, 200, 210), hull_pts, 2)

    # White wheels
    for side in [-1, 1]:
        wx = cx + side * 37
        wy = hull_bot + 10
        pygame.draw.circle(surf, (255, 255, 255), (wx, wy), 12)

    # White eye
    pygame.draw.ellipse(surf, (255, 255, 255), (cx - 14, hull_top + 4, 28, 14))

    return surf


def generate_drone_wheel():
    """Individual wheel sprite for rotation animation."""
    size = 30
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    cx, cy = size // 2, size // 2
    r = 12

    pygame.draw.circle(surf, (0, 0, 0), (cx, cy), r + 2)
    pygame.draw.circle(surf, (40, 40, 45), (cx, cy), r)

    # Spokes
    for i in range(6):
        angle = i * (math.pi / 3)
        ex = cx + int(math.cos(angle) * (r - 2))
        ey = cy + int(math.sin(angle) * (r - 2))
        pygame.draw.line(surf, (90, 90, 95), (cx, cy), (ex, ey), 1)

    # Hub
    pygame.draw.circle(surf, (70, 70, 75), (cx, cy), 4)
    pygame.draw.circle(surf, (0, 0, 0), (cx, cy), 4, 1)

    return surf


# ---------------------------------------------------------------------------
# Generate & save all
# ---------------------------------------------------------------------------
ENEMY_SPRITE_FILES = {
    "drone_patrol.png": generate_drone_patrol,
    "drone_chase.png": generate_drone_chase,
    "drone_attack.png": generate_drone_attack,
    "drone_retreat.png": generate_drone_retreat,
    "drone_hit.png": generate_drone_hit,
    "drone_wheel.png": generate_drone_wheel,
}


def generate_all_enemy_sprites(output_dir="assets/enemies"):
    os.makedirs(output_dir, exist_ok=True)
    for filename, gen_func in ENEMY_SPRITE_FILES.items():
        path = os.path.join(output_dir, filename)
        surface = gen_func()
        pygame.image.save(surface, path)
    print(f"Generated {len(ENEMY_SPRITE_FILES)} enemy sprites in {output_dir}/")


def enemy_sprites_exist(output_dir="assets/enemies"):
    return all(
        os.path.exists(os.path.join(output_dir, f))
        for f in ENEMY_SPRITE_FILES
    )


if __name__ == "__main__":
    pygame.init()
    pygame.display.set_mode((1, 1))
    generate_all_enemy_sprites()
    pygame.quit()
    print("Done!")
