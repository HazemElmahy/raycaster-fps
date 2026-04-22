"""
BSP Dungeon Generator for the raycasting FPS.

Generates a 2D grid map with rooms connected by corridors.
Returns the map, player spawn, and enemy spawn positions.
"""

import random


# Wall types assigned to rooms based on BSP depth
WALL_TYPES = [1, 2, 3]

MIN_ROOM = 5
MAX_ROOM = 10
MIN_LEAF = 12       # smallest BSP leaf before we stop splitting
CORRIDOR_WIDTH = 2
ENEMIES_PER_ROOM = (1, 3)


class Rect:
    """Simple rectangle."""
    __slots__ = ("x", "y", "w", "h")

    def __init__(self, x, y, w, h):
        self.x = x
        self.y = y
        self.w = w
        self.h = h

    @property
    def cx(self):
        return self.x + self.w // 2

    @property
    def cy(self):
        return self.y + self.h // 2


class BSPNode:
    """Binary Space Partition tree node."""
    __slots__ = ("rect", "left", "right", "room")

    def __init__(self, rect):
        self.rect = rect
        self.left = None
        self.right = None
        self.room = None  # Rect if this is a leaf with a room


def _split(node, depth=0, max_depth=5):
    """Recursively split a BSP node."""
    r = node.rect

    if depth >= max_depth or r.w < MIN_LEAF * 2 and r.h < MIN_LEAF * 2:
        return

    # Decide split direction
    if r.w > r.h * 1.25:
        horizontal = False
    elif r.h > r.w * 1.25:
        horizontal = True
    else:
        horizontal = random.random() < 0.5

    if horizontal:
        if r.h < MIN_LEAF * 2:
            return
        split = random.randint(MIN_LEAF, r.h - MIN_LEAF)
        node.left = BSPNode(Rect(r.x, r.y, r.w, split))
        node.right = BSPNode(Rect(r.x, r.y + split, r.w, r.h - split))
    else:
        if r.w < MIN_LEAF * 2:
            return
        split = random.randint(MIN_LEAF, r.w - MIN_LEAF)
        node.left = BSPNode(Rect(r.x, r.y, split, r.h))
        node.right = BSPNode(Rect(r.x + split, r.y, r.w - split, r.h))

    _split(node.left, depth + 1, max_depth)
    _split(node.right, depth + 1, max_depth)


def _place_rooms(node, depth=0):
    """Place rooms in leaf nodes."""
    if node.left is None and node.right is None:
        # Leaf — place a room with some padding
        r = node.rect
        rw = random.randint(MIN_ROOM, min(MAX_ROOM, r.w - 2))
        rh = random.randint(MIN_ROOM, min(MAX_ROOM, r.h - 2))
        rx = r.x + random.randint(1, max(1, r.w - rw - 1))
        ry = r.y + random.randint(1, max(1, r.h - rh - 1))
        node.room = Rect(rx, ry, rw, rh)
        return

    if node.left:
        _place_rooms(node.left, depth + 1)
    if node.right:
        _place_rooms(node.right, depth + 1)


def _get_room(node):
    """Get a room from this subtree (any leaf's room)."""
    if node.room:
        return node.room
    if node.left:
        r = _get_room(node.left)
        if r:
            return r
    if node.right:
        r = _get_room(node.right)
        if r:
            return r
    return None


def _carve_rect(grid, rect, tile=0):
    """Set all tiles in a rect to the given value."""
    for row in range(rect.y, rect.y + rect.h):
        for col in range(rect.x, rect.x + rect.w):
            if 0 <= row < len(grid) and 0 <= col < len(grid[0]):
                grid[row][col] = tile


def _carve_corridor(grid, x1, y1, x2, y2, width=CORRIDOR_WIDTH):
    """Carve an L-shaped corridor between two points."""
    half = width // 2

    # Horizontal segment
    min_x, max_x = min(x1, x2), max(x1, x2)
    for col in range(min_x, max_x + 1):
        for w in range(-half, half + 1):
            row = y1 + w
            if 0 <= row < len(grid) and 0 <= col < len(grid[0]):
                grid[row][col] = 0

    # Vertical segment
    min_y, max_y = min(y1, y2), max(y1, y2)
    for row in range(min_y, max_y + 1):
        for w in range(-half, half + 1):
            col = x2 + w
            if 0 <= row < len(grid) and 0 <= col < len(grid[0]):
                grid[row][col] = 0


def _connect_rooms(node, grid):
    """Connect sibling rooms with corridors."""
    if node.left is None or node.right is None:
        return

    _connect_rooms(node.left, grid)
    _connect_rooms(node.right, grid)

    room_a = _get_room(node.left)
    room_b = _get_room(node.right)
    if room_a and room_b:
        _carve_corridor(grid, room_a.cx, room_a.cy, room_b.cx, room_b.cy)


def _collect_rooms(node, rooms=None):
    """Collect all rooms from the BSP tree."""
    if rooms is None:
        rooms = []
    if node.room:
        rooms.append(node.room)
    if node.left:
        _collect_rooms(node.left, rooms)
    if node.right:
        _collect_rooms(node.right, rooms)
    return rooms


def _assign_wall_types(grid, rooms):
    """Give different rooms different wall types for visual variety."""
    rows, cols = len(grid), len(grid[0])

    for i, room in enumerate(rooms):
        wt = WALL_TYPES[i % len(WALL_TYPES)]
        # Set walls surrounding this room to the room's wall type
        for row in range(max(0, room.y - 1), min(rows, room.y + room.h + 1)):
            for col in range(max(0, room.x - 1), min(cols, room.x + room.w + 1)):
                if grid[row][col] != 0:
                    grid[row][col] = wt


def generate_dungeon(width=48, height=48, seed=None):
    """
    Generate a BSP dungeon.

    Returns:
        grid:          2D list (height x width), 0=floor, 1/2/3=wall
        player_spawn:  (x, y) float tuple — center of first room
        enemy_spawns:  list of (x, y) float tuples
        rooms:         list of Rect objects (for minimap, etc.)
    """
    if seed is not None:
        random.seed(seed)

    # Start with all walls
    grid = [[1] * width for _ in range(height)]

    # BSP split
    root = BSPNode(Rect(1, 1, width - 2, height - 2))
    max_depth = 4 if width <= 32 else 5
    _split(root, max_depth=max_depth)

    # Place rooms
    _place_rooms(root)
    rooms = _collect_rooms(root)

    if not rooms:
        # Fallback: single room
        rooms = [Rect(2, 2, width - 4, height - 4)]
        root.room = rooms[0]

    # Carve rooms into grid
    for room in rooms:
        _carve_rect(grid, room, 0)

    # Connect rooms with corridors
    _connect_rooms(root, grid)

    # Ensure border walls
    for row in range(height):
        grid[row][0] = 1
        grid[row][width - 1] = 1
    for col in range(width):
        grid[0][col] = 1
        grid[height - 1][col] = 1

    # Assign wall types for visual variety
    _assign_wall_types(grid, rooms)

    # Player spawns in the center of the first room
    first = rooms[0]
    player_spawn = (first.cx + 0.5, first.cy + 0.5)

    # Enemies spawn in ALL rooms including the first
    enemy_spawns = []
    for i, room in enumerate(rooms):
        count = random.randint(*ENEMIES_PER_ROOM)
        for _ in range(count):
            ex = random.uniform(room.x + 1, room.x + room.w - 1)
            ey = random.uniform(room.y + 1, room.y + room.h - 1)
            # Don't spawn right on top of the player in the first room
            if i == 0 and abs(ex - player_spawn[0]) < 2 and abs(ey - player_spawn[1]) < 2:
                # Push to room edge
                ex = room.x + 1.5
                ey = room.y + 1.5
            enemy_spawns.append((ex, ey))

    return grid, player_spawn, enemy_spawns, rooms


if __name__ == "__main__":
    grid, spawn, enemies, rooms = generate_dungeon(48, 48)
    print(f"Map: {len(grid[0])}x{len(grid)} | Rooms: {len(rooms)} | Enemies: {len(enemies)}")
    print(f"Player spawn: ({spawn[0]:.1f}, {spawn[1]:.1f})")
    # ASCII preview
    for row in grid:
        print("".join("#" if c else "." for c in row))
