"""
Auto-generates pixel-art UI sprites for menus and HUD.
Saved to assets/ui/. Replace with custom art if desired.
"""

import os
import pygame


def _pixel_border(surf, color, rect, thickness=2):
    """Draw a pixel-art border (no anti-aliasing)."""
    x, y, w, h = rect
    # Top
    pygame.draw.rect(surf, color, (x, y, w, thickness))
    # Bottom
    pygame.draw.rect(surf, color, (x, y + h - thickness, w, thickness))
    # Left
    pygame.draw.rect(surf, color, (x, y, thickness, h))
    # Right
    pygame.draw.rect(surf, color, (x + w - thickness, y, thickness, h))


def _pixel_panel(surf, x, y, w, h, bg=(20, 22, 30), border=(80, 85, 110),
                 highlight=(100, 108, 140), shadow=(40, 42, 55)):
    """Draw a pixel-art panel with beveled edges."""
    # Background
    pygame.draw.rect(surf, bg, (x, y, w, h))
    # Top highlight
    pygame.draw.rect(surf, highlight, (x, y, w, 2))
    pygame.draw.rect(surf, highlight, (x, y, 2, h))
    # Bottom shadow
    pygame.draw.rect(surf, shadow, (x, y + h - 2, w, 2))
    pygame.draw.rect(surf, shadow, (x + w - 2, y, 2, h))
    # Border
    _pixel_border(surf, border, (x, y, w, h), 1)


def generate_button_normal():
    """280x44 button — normal state."""
    W, H = 280, 44
    surf = pygame.Surface((W, H), pygame.SRCALPHA)
    _pixel_panel(surf, 0, 0, W, H,
                 bg=(45, 48, 65), border=(90, 95, 120),
                 highlight=(70, 75, 100), shadow=(30, 32, 45))
    return surf


def generate_button_hover():
    """280x44 button — hover state."""
    W, H = 280, 44
    surf = pygame.Surface((W, H), pygame.SRCALPHA)
    _pixel_panel(surf, 0, 0, W, H,
                 bg=(60, 65, 90), border=(120, 130, 170),
                 highlight=(90, 100, 140), shadow=(40, 42, 60))
    # Subtle glow line at top
    pygame.draw.rect(surf, (140, 150, 200), (4, 2, W - 8, 1))
    return surf


def generate_button_active():
    """280x44 button — active/selected state."""
    W, H = 280, 44
    surf = pygame.Surface((W, H), pygame.SRCALPHA)
    _pixel_panel(surf, 0, 0, W, H,
                 bg=(40, 70, 55), border=(60, 160, 100),
                 highlight=(70, 130, 90), shadow=(25, 50, 35))
    return surf


def generate_panel_small():
    """400x120 panel for server browser / lobby list."""
    W, H = 400, 150
    surf = pygame.Surface((W, H), pygame.SRCALPHA)
    _pixel_panel(surf, 0, 0, W, H,
                 bg=(25, 27, 38), border=(60, 65, 85),
                 highlight=(50, 55, 75), shadow=(15, 16, 22))
    return surf


def generate_panel_large():
    """500x400 panel for lobby screen."""
    W, H = 500, 400
    surf = pygame.Surface((W, H), pygame.SRCALPHA)
    _pixel_panel(surf, 0, 0, W, H,
                 bg=(22, 24, 35), border=(70, 75, 100),
                 highlight=(55, 60, 80), shadow=(12, 13, 20))
    # Inner frame line
    _pixel_border(surf, (40, 42, 58), (6, 6, W - 12, H - 12), 1)
    return surf


def generate_input_field():
    """240x36 text input field."""
    W, H = 240, 36
    surf = pygame.Surface((W, H), pygame.SRCALPHA)
    pygame.draw.rect(surf, (15, 16, 25), (0, 0, W, H))
    _pixel_border(surf, (60, 65, 85), (0, 0, W, H), 1)
    # Inner shadow
    pygame.draw.rect(surf, (10, 11, 18), (1, 1, W - 2, 2))
    return surf


def generate_input_field_active():
    """240x36 text input field — active/focused."""
    W, H = 240, 36
    surf = pygame.Surface((W, H), pygame.SRCALPHA)
    pygame.draw.rect(surf, (20, 22, 35), (0, 0, W, H))
    _pixel_border(surf, (100, 140, 200), (0, 0, W, H), 1)
    pygame.draw.rect(surf, (15, 18, 28), (1, 1, W - 2, 2))
    return surf


def generate_title_bg():
    """Decorative background for title text."""
    W, H = 600, 80
    surf = pygame.Surface((W, H), pygame.SRCALPHA)
    # Horizontal accent lines
    for i in range(3):
        y = 10 + i * 28
        alpha = 40 - i * 10
        pygame.draw.line(surf, (80, 90, 130, alpha), (0, y), (W, y), 1)
        pygame.draw.line(surf, (80, 90, 130, alpha), (0, H - y), (W, H - y), 1)
    return surf


def generate_health_bar_bg():
    """200x16 health bar background."""
    W, H = 200, 16
    surf = pygame.Surface((W, H), pygame.SRCALPHA)
    pygame.draw.rect(surf, (15, 16, 22), (0, 0, W, H))
    _pixel_border(surf, (50, 52, 65), (0, 0, W, H), 1)
    return surf


def generate_lobby_player_row():
    """460x32 player row for lobby."""
    W, H = 460, 32
    surf = pygame.Surface((W, H), pygame.SRCALPHA)
    pygame.draw.rect(surf, (30, 33, 48), (0, 0, W, H))
    _pixel_border(surf, (50, 55, 72), (0, 0, W, H), 1)
    return surf


# ---------------------------------------------------------------------------
# Generate & save
# ---------------------------------------------------------------------------
UI_SPRITE_FILES = {
    "btn_normal.png": generate_button_normal,
    "btn_hover.png": generate_button_hover,
    "btn_active.png": generate_button_active,
    "panel_small.png": generate_panel_small,
    "panel_large.png": generate_panel_large,
    "input_field.png": generate_input_field,
    "input_active.png": generate_input_field_active,
    "title_bg.png": generate_title_bg,
    "health_bar_bg.png": generate_health_bar_bg,
    "lobby_row.png": generate_lobby_player_row,
}


def generate_all_ui_sprites(output_dir="assets/ui"):
    os.makedirs(output_dir, exist_ok=True)
    for filename, gen_func in UI_SPRITE_FILES.items():
        path = os.path.join(output_dir, filename)
        surface = gen_func()
        pygame.image.save(surface, path)
    print(f"Generated {len(UI_SPRITE_FILES)} UI sprites in {output_dir}/")


def ui_sprites_exist(output_dir="assets/ui"):
    return all(
        os.path.exists(os.path.join(output_dir, f))
        for f in UI_SPRITE_FILES
    )


if __name__ == "__main__":
    pygame.init()
    pygame.display.set_mode((1, 1))
    generate_all_ui_sprites()
    pygame.quit()
    print("Done!")
