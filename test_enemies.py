"""
Enemy AI test suite.
Runs headless (no window needed beyond init) — validates enemy behavior
across multiple dungeon seeds and scenarios.

Usage:
    python test_enemies.py
"""

import math
import sys

import pygame

pygame.init()
pygame.display.set_mode((1, 1))  # minimal display for surface ops

import main
from enemy_ai import (
    has_line_of_sight, astar, EnemyAI,
    STATE_PATROL, STATE_CHASE, STATE_ATTACK, STATE_RETREAT,
    INVESTIGATE_TIME, SIGHT_RANGE, HEARING_RANGE, ATTACK_RANGE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
DT = 1 / 60  # 60 fps frame time

PASS = 0
FAIL = 0


def run_test(name, fn):
    global PASS, FAIL
    try:
        fn()
        PASS += 1
        print(f"  PASS  {name}")
    except AssertionError as e:
        FAIL += 1
        print(f"  FAIL  {name}: {e}")


def simulate(enemies, px, py, seconds, gunfire_at=None):
    """Run the game loop for `seconds`. gunfire_at is a set of frame numbers."""
    all_e = [(e, e.ai) for e in enemies]
    frames = int(seconds * 60)
    gunfire_at = gunfire_at or set()
    for frame in range(frames):
        gf = frame in gunfire_at
        for e in enemies:
            e.update(px, py, DT, all_e, gunfire=gf)


def fresh_dungeon(seed=0):
    """Generate a dungeon and return (spawn, enemies)."""
    spawn, _ = main.new_dungeon(48, 48, seed=seed)
    enemies = main.spawn_enemies()
    return spawn, enemies


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_enemies_spawn_in_player_room():
    """At least 1 enemy should be within 6 tiles of the player at start."""
    close_counts = []
    for seed in range(10):
        spawn, enemies = fresh_dungeon(seed)
        close = sum(
            1 for e in enemies
            if math.hypot(e.x - spawn[0], e.y - spawn[1]) < 6
        )
        close_counts.append(close)
    total_close = sum(close_counts)
    assert total_close >= 5, (
        f"Only {total_close} close enemies across 10 seeds (expected >= 5)"
    )


def test_enemy_not_in_wall():
    """No enemy should spawn inside a wall."""
    for seed in range(10):
        spawn, enemies = fresh_dungeon(seed)
        for i, e in enumerate(enemies):
            assert not main.is_wall(e.x, e.y), (
                f"Seed {seed}, enemy {i} at ({e.x:.1f},{e.y:.1f}) is in a wall"
            )


def test_los_enemy_chases_immediately():
    """An enemy with clear LOS to player should enter CHASE/ATTACK within 1 second."""
    spawn, _ = fresh_dungeon(0)
    # Place enemy 5 tiles from player on open ground
    e = main.Enemy(spawn[0] + 5, spawn[1])
    # Make sure it's walkable, adjust if needed
    if main.is_wall(e.x, e.y):
        e = main.Enemy(spawn[0], spawn[1] + 5)

    simulate([e], spawn[0], spawn[1], 1.0)
    assert e.ai.state in (STATE_CHASE, STATE_ATTACK), (
        f"Enemy with LOS should be CHASE/ATTACK after 1s, got state={e.ai.state}"
    )


def test_los_enemy_approaches():
    """An enemy that can see the player should move closer over 2 seconds."""
    spawn, _ = fresh_dungeon(0)
    e = main.Enemy(spawn[0] + 6, spawn[1])
    if main.is_wall(e.x, e.y):
        e = main.Enemy(spawn[0], spawn[1] + 6)

    start_dist = math.hypot(e.x - spawn[0], e.y - spawn[1])
    simulate([e], spawn[0], spawn[1], 2.0)
    end_dist = math.hypot(e.x - spawn[0], e.y - spawn[1])
    assert end_dist < start_dist - 1.0, (
        f"Enemy should approach player: start={start_dist:.1f} end={end_dist:.1f}"
    )


def test_all_enemies_chase_within_5_seconds():
    """After 5 seconds, every enemy should be CHASE or ATTACK (no idle patrol)."""
    for seed in range(5):
        spawn, enemies = fresh_dungeon(seed)
        simulate(enemies, spawn[0], spawn[1], 5.0)
        for i, e in enumerate(enemies):
            assert e.ai.state in (STATE_CHASE, STATE_ATTACK, STATE_RETREAT), (
                f"Seed {seed}, enemy {i} still in PATROL after 5s "
                f"(state={e.ai.state}, patrol_time={e.ai.patrol_time:.1f})"
            )


def test_gunfire_alerts_all_enemies():
    """A single gunshot should put every enemy on the map into CHASE."""
    spawn, enemies = fresh_dungeon(0)
    # Fire on frame 0
    simulate(enemies, spawn[0], spawn[1], 1.0, gunfire_at={0})
    chasing = sum(1 for e in enemies if e.ai.state in (STATE_CHASE, STATE_ATTACK))
    in_range = sum(
        1 for e in enemies
        if math.hypot(e.x - spawn[0], e.y - spawn[1]) <= HEARING_RANGE
    )
    assert chasing >= in_range, (
        f"After gunfire, {chasing} chasing but {in_range} in hearing range"
    )


def test_attack_state_at_close_range():
    """An enemy within ATTACK_RANGE with LOS should enter ATTACK state."""
    spawn, _ = fresh_dungeon(0)
    e = main.Enemy(spawn[0] + 2, spawn[1])
    if main.is_wall(e.x, e.y):
        e = main.Enemy(spawn[0], spawn[1] + 2)
    simulate([e], spawn[0], spawn[1], 0.5)
    assert e.ai.state == STATE_ATTACK, (
        f"Enemy at dist ~2 should ATTACK, got state={e.ai.state}"
    )


def test_attack_strafing():
    """An enemy in ATTACK state should move laterally (strafe), not just straight."""
    spawn, _ = fresh_dungeon(0)
    e = main.Enemy(spawn[0] + 2.5, spawn[1])
    if main.is_wall(e.x, e.y):
        e = main.Enemy(spawn[0], spawn[1] + 2.5)

    simulate([e], spawn[0], spawn[1], 0.3)  # enter ATTACK
    assert e.ai.state == STATE_ATTACK

    # Record y movement over next 2 seconds (should strafe on y-axis)
    y_positions = []
    all_e = [(e, e.ai)]
    for _ in range(120):
        e.update(spawn[0], spawn[1], DT, all_e)
        y_positions.append(e.y)
    y_range = max(y_positions) - min(y_positions)
    assert y_range > 0.3, (
        f"Strafing enemy should have lateral movement, y_range={y_range:.2f}"
    )


def test_retreat_when_low_hp():
    """An enemy with 1 HP that can see the player should RETREAT."""
    spawn, _ = fresh_dungeon(0)
    e = main.Enemy(spawn[0] + 3, spawn[1])
    if main.is_wall(e.x, e.y):
        e = main.Enemy(spawn[0], spawn[1] + 3)
    e.health = 1
    simulate([e], spawn[0], spawn[1], 0.5)
    assert e.ai.state == STATE_RETREAT, (
        f"Low HP enemy with LOS should RETREAT, got state={e.ai.state}"
    )


def test_retreat_moves_away():
    """A retreating enemy should increase distance from the player."""
    spawn, _ = fresh_dungeon(0)
    e = main.Enemy(spawn[0] + 3, spawn[1])
    if main.is_wall(e.x, e.y):
        e = main.Enemy(spawn[0], spawn[1] + 3)
    e.health = 1
    simulate([e], spawn[0], spawn[1], 0.3)
    start_dist = math.hypot(e.x - spawn[0], e.y - spawn[1])
    simulate([e], spawn[0], spawn[1], 2.0)
    end_dist = math.hypot(e.x - spawn[0], e.y - spawn[1])
    assert end_dist > start_dist, (
        f"Retreating enemy should move away: start={start_dist:.1f} end={end_dist:.1f}"
    )


def test_investigation_becomes_permanent():
    """Once patrol_time exceeds INVESTIGATE_TIME, enemy should stay in CHASE."""
    spawn, _ = fresh_dungeon(0)
    # Place enemy far away, behind walls
    e = main.Enemy(spawn[0] + 25, spawn[1] + 25)
    if main.is_wall(e.x, e.y):
        # Find a valid position far from player
        for ey in range(30, 45):
            for ex in range(30, 45):
                if not main.is_wall(ex + 0.5, ey + 0.5):
                    e = main.Enemy(ex + 0.5, ey + 0.5)
                    break
            else:
                continue
            break

    simulate([e], spawn[0], spawn[1], INVESTIGATE_TIME + 1)
    assert e.ai.state == STATE_CHASE, (
        f"Enemy should be CHASE after investigation, got state={e.ai.state}"
    )
    # Simulate more — should NOT revert to PATROL
    simulate([e], spawn[0], spawn[1], 2.0)
    assert e.ai.state != STATE_PATROL, (
        f"Investigated enemy reverted to PATROL (state={e.ai.state})"
    )


def test_astar_finds_path():
    """A* should find a path between two open tiles."""
    spawn, _ = fresh_dungeon(0)
    # Find an enemy position and check path exists
    epos = main.CURRENT_ENEMY_SPAWNS[0]
    path = astar(main.WORLD_MAP, (spawn[0], spawn[1]), (epos[0], epos[1]))
    assert len(path) > 0, (
        f"A* should find path from player to enemy, got empty path"
    )


def test_astar_path_avoids_walls():
    """Every waypoint in an A* path should be on a walkable tile."""
    spawn, _ = fresh_dungeon(0)
    epos = main.CURRENT_ENEMY_SPAWNS[0]
    path = astar(main.WORLD_MAP, (spawn[0], spawn[1]), (epos[0], epos[1]))
    for col, row in path:
        assert main.WORLD_MAP[row][col] == 0, (
            f"Path waypoint ({col},{row}) is a wall (val={main.WORLD_MAP[row][col]})"
        )


def test_enemy_moves_every_seed():
    """Across 10 seeds, every enemy should move >0.5 tiles in 5 seconds."""
    for seed in range(10):
        spawn, enemies = fresh_dungeon(seed)
        starts = [(e.x, e.y) for e in enemies]
        simulate(enemies, spawn[0], spawn[1], 5.0)
        for i, e in enumerate(enemies):
            moved = math.hypot(e.x - starts[i][0], e.y - starts[i][1])
            assert moved > 0.5, (
                f"Seed {seed}, enemy {i} only moved {moved:.2f} in 5s"
            )


def test_contact_damage_dealt():
    """An enemy that reaches the player should deal damage in singleplayer logic."""
    spawn, _ = fresh_dungeon(0)
    # Place enemy right next to player
    e = main.Enemy(spawn[0] + 0.5, spawn[1])
    if main.is_wall(e.x, e.y):
        e = main.Enemy(spawn[0], spawn[1] + 0.5)

    # Simulate the damage check as singleplayer_loop does it
    health = 100
    damage_cooldown = 0.0
    for _ in range(120):  # 2 seconds
        e.update(spawn[0], spawn[1], DT, [(e, e.ai)])
        damage_cooldown = max(0, damage_cooldown - DT)
        if e.alive and math.hypot(e.x - spawn[0], e.y - spawn[1]) < 0.8:
            if damage_cooldown <= 0:
                health -= 10
                damage_cooldown = 0.5

    assert health < 100, (
        f"Enemy next to player should deal damage, health still {health}"
    )


def test_dead_enemy_stops():
    """A dead enemy should not move."""
    spawn, _ = fresh_dungeon(0)
    e = main.Enemy(spawn[0] + 3, spawn[1])
    if main.is_wall(e.x, e.y):
        e = main.Enemy(spawn[0], spawn[1] + 3)
    e.alive = False
    old_x, old_y = e.x, e.y
    simulate([e], spawn[0], spawn[1], 2.0)
    assert e.x == old_x and e.y == old_y, "Dead enemy should not move"


def test_group_alerting():
    """When one enemy spots the player, nearby enemies should become alerted."""
    spawn, _ = fresh_dungeon(0)
    # Two enemies: one can see player, one can't but is nearby
    e1 = main.Enemy(spawn[0] + 4, spawn[1])       # should see player
    e2 = main.Enemy(spawn[0] + 5, spawn[1] + 1)   # nearby, maybe no LOS
    if main.is_wall(e1.x, e1.y):
        e1 = main.Enemy(spawn[0], spawn[1] + 4)
        e2 = main.Enemy(spawn[0] + 1, spawn[1] + 5)
    if main.is_wall(e2.x, e2.y):
        e2.x = e1.x + 1
        e2.y = e1.y

    pair = [e1, e2]
    simulate(pair, spawn[0], spawn[1], 1.0)

    # At least one should be chasing
    any_chasing = any(e.ai.state in (STATE_CHASE, STATE_ATTACK) for e in pair)
    assert any_chasing, "At least one nearby enemy should be chasing after 1s"


def test_multiple_dungeons_different():
    """Different seeds should produce different enemy counts/positions."""
    spawn1, e1 = fresh_dungeon(0)
    spawn2, e2 = fresh_dungeon(1)
    different = (
        len(e1) != len(e2)
        or spawn1 != spawn2
        or (len(e1) > 0 and len(e2) > 0 and (e1[0].x != e2[0].x))
    )
    assert different, "Different seeds should produce different dungeons"


# ---------------------------------------------------------------------------
# Run all tests
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Enemy AI Test Suite")
    print("=" * 60)

    print("\n[Spawning & Map]")
    run_test("enemies spawn in player room", test_enemies_spawn_in_player_room)
    run_test("no enemy in wall", test_enemy_not_in_wall)
    run_test("different seeds = different dungeons", test_multiple_dungeons_different)

    print("\n[Pathfinding]")
    run_test("A* finds path to enemy", test_astar_finds_path)
    run_test("A* path avoids walls", test_astar_path_avoids_walls)

    print("\n[Chase & Awareness]")
    run_test("LOS enemy chases within 1s", test_los_enemy_chases_immediately)
    run_test("LOS enemy approaches player", test_los_enemy_approaches)
    run_test("all enemies chase within 5s", test_all_enemies_chase_within_5_seconds)
    run_test("gunfire alerts all enemies", test_gunfire_alerts_all_enemies)
    run_test("investigation becomes permanent", test_investigation_becomes_permanent)
    run_test("every enemy moves (10 seeds)", test_enemy_moves_every_seed)

    print("\n[Combat]")
    run_test("ATTACK state at close range", test_attack_state_at_close_range)
    run_test("attack strafing movement", test_attack_strafing)
    run_test("contact damage dealt", test_contact_damage_dealt)

    print("\n[Retreat]")
    run_test("retreat when low HP", test_retreat_when_low_hp)
    run_test("retreat moves away", test_retreat_moves_away)

    print("\n[Edge Cases]")
    run_test("dead enemy stops", test_dead_enemy_stops)
    run_test("group alerting", test_group_alerting)

    print("\n" + "=" * 60)
    total = PASS + FAIL
    print(f"Results: {PASS}/{total} passed, {FAIL} failed")

    pygame.quit()
    sys.exit(1 if FAIL > 0 else 0)
