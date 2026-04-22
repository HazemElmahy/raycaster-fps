"""
Auto-generates weapon sprite PNGs for the FPS game.
Run once on first startup — sprites are saved to assets/weapons/.
You can replace them with custom art in any image editor.
"""

import os
import pygame
import math


def _outline_rect(surf, color, rect, thickness=2):
    """Draw a filled rect with a black outline."""
    x, y, w, h = rect
    pygame.draw.rect(surf, (0, 0, 0), (x - thickness, y - thickness,
                                        w + thickness * 2, h + thickness * 2))
    pygame.draw.rect(surf, color, rect)


def _outline_polygon(surf, color, points, thickness=2):
    """Draw a filled polygon with a black outline."""
    pygame.draw.polygon(surf, (0, 0, 0), points)
    # Shrink inward slightly for outline effect — just overdraw
    pygame.draw.polygon(surf, color, points)
    pygame.draw.polygon(surf, (0, 0, 0), points, thickness)


def _outline_circle(surf, color, center, radius, thickness=2):
    """Draw a filled circle with a black outline."""
    pygame.draw.circle(surf, (0, 0, 0), center, radius + thickness)
    pygame.draw.circle(surf, color, center, radius)


def _shade(base_color, factor):
    """Lighten (>1) or darken (<1) a color."""
    return tuple(max(0, min(255, int(c * factor))) for c in base_color)


# ---------------------------------------------------------------------------
# Pistol
# ---------------------------------------------------------------------------
def generate_pistol_idle():
    W, H = 200, 350
    surf = pygame.Surface((W, H), pygame.SRCALPHA)

    # Colors
    metal_dark = (55, 55, 60)
    metal_mid = (75, 75, 80)
    metal_light = (95, 95, 100)
    grip_dark = (40, 35, 30)
    grip_mid = (60, 50, 40)
    trigger_color = (70, 70, 75)

    cx = W // 2  # center x

    # --- Barrel ---
    _outline_rect(surf, metal_mid, (cx - 10, 30, 20, 70))
    # Barrel bore
    pygame.draw.rect(surf, (30, 30, 35), (cx - 4, 28, 8, 10))
    # Barrel highlight
    pygame.draw.rect(surf, metal_light, (cx - 8, 35, 4, 60))

    # --- Slide ---
    _outline_rect(surf, metal_dark, (cx - 22, 90, 44, 80))
    # Slide serrations (grip lines)
    for i in range(5):
        y = 95 + i * 12
        pygame.draw.line(surf, metal_light, (cx - 18, y), (cx + 18, y), 1)
    # Ejection port
    pygame.draw.rect(surf, (35, 35, 40), (cx + 8, 100, 12, 20))
    # Slide highlight (left edge)
    pygame.draw.rect(surf, metal_light, (cx - 20, 92, 4, 76))

    # --- Frame / lower receiver ---
    _outline_rect(surf, metal_mid, (cx - 20, 170, 40, 30))
    # Trigger guard
    _outline_rect(surf, metal_mid, (cx - 6, 200, 22, 30))
    pygame.draw.rect(surf, (0, 0, 0, 0), (cx - 2, 205, 14, 20))
    # Clear inside of trigger guard
    pygame.draw.rect(surf, (0, 0, 0, 0), (cx, 205, 12, 22))
    # Trigger
    pygame.draw.rect(surf, trigger_color, (cx + 2, 195, 4, 18))

    # --- Grip ---
    grip_points = [
        (cx - 18, 195),
        (cx - 24, 310),
        (cx - 16, 320),
        (cx + 16, 320),
        (cx + 18, 310),
        (cx + 18, 195),
    ]
    _outline_polygon(surf, grip_dark, grip_points)
    # Grip texture lines
    for i in range(8):
        y = 210 + i * 13
        pygame.draw.line(surf, grip_mid, (cx - 20, y), (cx + 14, y), 1)
    # Grip highlight
    pygame.draw.line(surf, _shade(grip_mid, 1.3), (cx - 22, 200), (cx - 22, 310), 2)

    # --- Magazine base ---
    _outline_rect(surf, metal_dark, (cx - 14, 316, 28, 10))

    # --- Front sight ---
    pygame.draw.rect(surf, (0, 0, 0), (cx - 3, 26, 6, 8))
    pygame.draw.rect(surf, (220, 220, 220), (cx - 1, 27, 2, 3))  # dot

    return surf


def generate_pistol_fire():
    surf = generate_pistol_idle()

    cx = 100  # W // 2

    # Muzzle flash — layered circles
    flash_colors = [
        ((255, 255, 200, 180), 35),
        ((255, 220, 80, 200), 25),
        ((255, 180, 50, 220), 16),
        ((255, 255, 255, 250), 8),
    ]
    flash_surf = pygame.Surface((200, 100), pygame.SRCALPHA)
    for color, radius in flash_colors:
        pygame.draw.circle(flash_surf, color, (100, 60), radius)
    # Flash spikes
    for angle_deg in [0, 45, 90, 135, 180, 225, 270, 315]:
        a = math.radians(angle_deg)
        ex = 100 + int(math.cos(a) * 40)
        ey = 60 + int(math.sin(a) * 40)
        pygame.draw.line(flash_surf, (255, 240, 150, 150), (100, 60), (ex, ey), 2)

    surf.blit(flash_surf, (0, -40))

    return surf


# ---------------------------------------------------------------------------
# Rifle
# ---------------------------------------------------------------------------
def generate_rifle_idle():
    W, H = 220, 400
    surf = pygame.Surface((W, H), pygame.SRCALPHA)

    metal_dark = (50, 50, 55)
    metal_mid = (70, 70, 75)
    metal_light = (90, 90, 95)
    wood_dark = (60, 40, 25)
    wood_mid = (85, 58, 35)
    wood_light = (110, 75, 45)
    scope_color = (35, 35, 40)

    cx = W // 2

    # --- Barrel (long) ---
    _outline_rect(surf, metal_mid, (cx - 7, 10, 14, 120))
    # Barrel highlight
    pygame.draw.rect(surf, metal_light, (cx - 5, 15, 3, 110))
    # Muzzle brake
    _outline_rect(surf, metal_dark, (cx - 10, 5, 20, 15))
    pygame.draw.rect(surf, (30, 30, 35), (cx - 3, 2, 6, 8))  # bore

    # --- Front sight ---
    pygame.draw.rect(surf, (0, 0, 0), (cx - 2, 20, 4, 10))
    pygame.draw.rect(surf, (200, 50, 50), (cx - 1, 21, 2, 3))  # red dot

    # --- Handguard ---
    _outline_rect(surf, metal_dark, (cx - 16, 125, 32, 60))
    # Rail on top
    for i in range(6):
        x_off = cx - 14 + i * 5
        pygame.draw.rect(surf, metal_light, (x_off, 126, 3, 58))
    # Heat vents
    for i in range(4):
        y = 135 + i * 12
        pygame.draw.rect(surf, (25, 25, 30), (cx - 12, y, 8, 3))
        pygame.draw.rect(surf, (25, 25, 30), (cx + 4, y, 8, 3))

    # --- Scope ---
    # Scope body
    _outline_rect(surf, scope_color, (cx - 8, 60, 16, 65))
    # Scope objective lens (front)
    _outline_circle(surf, (25, 40, 60), (cx, 58), 10)
    pygame.draw.circle(surf, (50, 80, 120), (cx, 58), 6)  # lens
    pygame.draw.circle(surf, (100, 150, 200, 100), (cx - 2, 56), 2)  # glint
    # Scope eyepiece (rear)
    _outline_circle(surf, scope_color, (cx, 128), 8)
    pygame.draw.circle(surf, (45, 45, 50), (cx, 128), 5)
    # Scope mount rings
    _outline_rect(surf, metal_mid, (cx - 12, 70, 24, 8))
    _outline_rect(surf, metal_mid, (cx - 12, 110, 24, 8))

    # --- Upper receiver ---
    _outline_rect(surf, metal_mid, (cx - 18, 185, 36, 50))
    # Ejection port
    pygame.draw.rect(surf, (30, 30, 35), (cx + 6, 195, 10, 20))
    # Charging handle
    _outline_rect(surf, metal_dark, (cx - 4, 182, 8, 8))

    # --- Magazine ---
    mag_points = [
        (cx + 14, 215),
        (cx + 30, 215),
        (cx + 34, 280),
        (cx + 18, 280),
    ]
    _outline_polygon(surf, metal_dark, mag_points)
    # Magazine ridges
    for i in range(4):
        y = 225 + i * 13
        pygame.draw.line(surf, metal_light, (cx + 16, y), (cx + 32, y), 1)

    # --- Lower receiver ---
    _outline_rect(surf, metal_mid, (cx - 18, 235, 36, 20))
    # Trigger guard
    trigger_guard = [
        (cx - 4, 240), (cx - 4, 270), (cx + 12, 270), (cx + 12, 240),
    ]
    pygame.draw.polygon(surf, (0, 0, 0), trigger_guard, 2)
    # Trigger
    pygame.draw.rect(surf, metal_light, (cx + 2, 245, 4, 16))

    # --- Pistol grip ---
    grip_points = [
        (cx - 16, 255),
        (cx - 26, 340),
        (cx - 18, 350),
        (cx + 2, 350),
        (cx + 4, 340),
        (cx - 2, 255),
    ]
    _outline_polygon(surf, wood_dark, grip_points)
    # Grip texture
    for i in range(6):
        y = 270 + i * 12
        pygame.draw.line(surf, wood_mid, (cx - 22, y), (cx, y), 1)
    # Grip highlight
    pygame.draw.line(surf, wood_light, (cx - 24, 260), (cx - 24, 340), 2)

    # --- Stock ---
    stock_points = [
        (cx + 2, 255),
        (cx + 8, 255),
        (cx + 30, 370),
        (cx + 24, 390),
        (cx + 6, 390),
        (cx - 4, 370),
    ]
    _outline_polygon(surf, wood_mid, stock_points)
    # Stock wood grain
    for i in range(7):
        y = 270 + i * 16
        x1 = cx + int(2 + (y - 255) * 0.08)
        x2 = cx + int(8 + (y - 255) * 0.15)
        pygame.draw.line(surf, wood_light, (x1, y), (x2, y), 1)
    # Buttplate
    _outline_rect(surf, (40, 40, 45), (cx + 6, 385, 20, 8))

    return surf


def generate_rifle_fire():
    surf = generate_rifle_idle()

    cx = 110  # W // 2

    # Large muzzle flash
    flash_surf = pygame.Surface((220, 120), pygame.SRCALPHA)
    flash_colors = [
        ((255, 255, 200, 160), 50),
        ((255, 220, 80, 190), 38),
        ((255, 180, 50, 210), 24),
        ((255, 255, 255, 240), 12),
    ]
    for color, radius in flash_colors:
        pygame.draw.circle(flash_surf, color, (110, 70), radius)
    # Directional flash spikes (more intense)
    for angle_deg in range(0, 360, 30):
        a = math.radians(angle_deg)
        length = 55 if angle_deg % 90 == 0 else 35
        ex = 110 + int(math.cos(a) * length)
        ey = 70 + int(math.sin(a) * length)
        pygame.draw.line(flash_surf, (255, 240, 150, 140), (110, 70), (ex, ey), 3)

    surf.blit(flash_surf, (0, -65))

    return surf


# ---------------------------------------------------------------------------
# Knife
# ---------------------------------------------------------------------------
def generate_knife_idle():
    W, H = 180, 380
    surf = pygame.Surface((W, H), pygame.SRCALPHA)

    blade_light = (195, 200, 210)
    blade_mid = (160, 165, 175)
    blade_dark = (120, 125, 135)
    guard_color = (140, 140, 150)
    handle_dark = (55, 35, 20)
    handle_mid = (80, 55, 35)
    handle_light = (100, 70, 45)

    cx = W // 2

    # --- Blade ---
    blade_points = [
        (cx, 15),           # tip
        (cx + 18, 80),      # right edge widens
        (cx + 16, 180),     # right edge at base
        (cx - 12, 180),     # left edge at base
        (cx - 14, 100),     # left edge
    ]
    _outline_polygon(surf, blade_mid, blade_points, 3)

    # Blade spine (darker top edge)
    spine_points = [
        (cx, 18),
        (cx - 12, 105),
        (cx - 10, 178),
        (cx - 6, 178),
        (cx - 8, 100),
        (cx + 2, 22),
    ]
    pygame.draw.polygon(surf, blade_dark, spine_points)

    # Blade bevel / fuller (groove)
    fuller_points = [
        (cx + 2, 50),
        (cx + 12, 90),
        (cx + 10, 165),
        (cx + 4, 165),
        (cx + 6, 90),
        (cx - 2, 55),
    ]
    pygame.draw.polygon(surf, blade_light, fuller_points)

    # Edge highlight
    pygame.draw.line(surf, (220, 225, 235), (cx + 17, 82), (cx + 15, 178), 2)

    # Tip highlight
    pygame.draw.line(surf, (230, 235, 240), (cx + 1, 18), (cx + 16, 78), 1)

    # --- Guard / crossguard ---
    guard_points = [
        (cx - 28, 180),
        (cx + 30, 180),
        (cx + 26, 196),
        (cx - 24, 196),
    ]
    _outline_polygon(surf, guard_color, guard_points, 2)
    # Guard highlight
    pygame.draw.line(surf, _shade(guard_color, 1.3), (cx - 24, 183), (cx + 26, 183), 2)
    # Guard shadow
    pygame.draw.line(surf, _shade(guard_color, 0.6), (cx - 22, 193), (cx + 24, 193), 1)

    # --- Handle ---
    handle_points = [
        (cx - 14, 196),
        (cx + 16, 196),
        (cx + 18, 320),
        (cx - 12, 320),
    ]
    _outline_polygon(surf, handle_dark, handle_points, 2)

    # Handle wrap / texture (leather wrapping)
    for i in range(10):
        y = 204 + i * 12
        # Alternating light/dark bands
        color = handle_mid if i % 2 == 0 else handle_dark
        band = [
            (cx - 12, y),
            (cx + 14, y),
            (cx + 14, y + 8),
            (cx - 12, y + 8),
        ]
        pygame.draw.polygon(surf, color, band)
        pygame.draw.polygon(surf, (0, 0, 0), band, 1)

    # Handle highlight (left edge)
    pygame.draw.line(surf, handle_light, (cx - 12, 200), (cx - 10, 316), 2)

    # --- Pommel ---
    _outline_rect(surf, guard_color, (cx - 16, 318, 34, 14))
    pygame.draw.rect(surf, _shade(guard_color, 1.2), (cx - 14, 320, 30, 4))
    # Pommel rivet
    _outline_circle(surf, (100, 100, 110), (cx + 1, 325), 4)

    return surf


def generate_knife_swing():
    """Generate a rotated knife for the swing/attack frame."""
    idle = generate_knife_idle()
    # Rotate 30 degrees for a slashing motion
    rotated = pygame.transform.rotate(idle, -35)
    # Create a new surface at the same size, centered
    W, H = 220, 400
    surf = pygame.Surface((W, H), pygame.SRCALPHA)
    # Position the rotated knife offset to the right (swing direction)
    rx, ry = rotated.get_rect().center
    surf.blit(rotated, (W // 2 - rx + 30, H // 2 - ry))
    return surf


# ---------------------------------------------------------------------------
# Generate all & save
# ---------------------------------------------------------------------------
SPRITE_FILES = {
    "pistol_idle.png": generate_pistol_idle,
    "pistol_fire.png": generate_pistol_fire,
    "rifle_idle.png": generate_rifle_idle,
    "rifle_fire.png": generate_rifle_fire,
    "knife_idle.png": generate_knife_idle,
    "knife_swing.png": generate_knife_swing,
}


def generate_all_sprites(output_dir="assets/weapons"):
    """Generate all weapon PNGs and save to output_dir."""
    os.makedirs(output_dir, exist_ok=True)
    for filename, gen_func in SPRITE_FILES.items():
        path = os.path.join(output_dir, filename)
        surface = gen_func()
        pygame.image.save(surface, path)
    print(f"Generated {len(SPRITE_FILES)} weapon sprites in {output_dir}/")


def sprites_exist(output_dir="assets/weapons"):
    """Check if all sprite files already exist."""
    return all(
        os.path.exists(os.path.join(output_dir, f))
        for f in SPRITE_FILES
    )


if __name__ == "__main__":
    pygame.init()
    # Need a display for some surface operations
    pygame.display.set_mode((1, 1))
    generate_all_sprites()
    pygame.quit()
    print("Done! Check assets/weapons/")
