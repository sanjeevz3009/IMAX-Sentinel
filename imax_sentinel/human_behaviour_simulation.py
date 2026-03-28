# Human-like interactions
from __future__ import annotations

import random


def human_mouse_move(*, page, target_x: int, target_y: int, steps: int = 20) -> None:
    """Move mouse to target along a slightly curved Bézier path with jitter."""
    viewport_size = page.viewport_size or {"width": 1440, "height": 900}

    start_x = viewport_size["width"] // 2
    start_y = viewport_size["height"] // 2

    control_point_x = random.randint(min(start_x, target_x), max(start_x, target_x))
    control_point_y = random.randint(
        min(start_y, target_y) - 60,
        max(start_y, target_y) + 60,
    )

    for i in range(1, steps + 1):
        t = i / steps

        x = int((1 - t) ** 2 * start_x + 2 * (1 - t) * t * control_point_x + t**2 * target_x)
        y = int((1 - t) ** 2 * start_y + 2 * (1 - t) * t * control_point_y + t**2 * target_y)

        x += random.randint(-2, 2)
        y += random.randint(-2, 2)

        page.mouse.move(x, y)
        page.wait_for_timeout(random.randint(8, 25))


def human_scroll(page) -> None:
    """Scroll in irregular chunks, occasionally drifting back up slightly."""
    total_scroll = random.randint(300, 800)
    num_steps = random.randint(3, 6)

    for _ in range(num_steps):
        chunk = random.randint(60, total_scroll // num_steps + 40)

        page.mouse.wheel(0, chunk)
        page.wait_for_timeout(random.randint(120, 400))

    if random.random() < 0.4:
        page.mouse.wheel(0, -random.randint(80, 200))
        page.wait_for_timeout(random.randint(200, 500))


def random_idle_movement(page) -> None:
    """Move cursor to a few random positions, simulating absent-minded reading."""
    viewport_size = page.viewport_size or {"width": 1440, "height": 900}

    for _ in range(random.randint(2, 5)):
        x = random.randint(100, viewport_size["width"] - 100)
        y = random.randint(100, viewport_size["height"] - 100)

        human_mouse_move(page=page, target_x=x, target_y=y)

        page.wait_for_timeout(random.randint(200, 700))


def hover_random_link(page) -> None:
    """Hover over a random link near the top of the page without clicking."""
    try:
        links = page.query_selector_all("a")

        if not links:
            return

        link = random.choice(links[:10])
        box = link.bounding_box()

        if box:
            human_mouse_move(
                page=page,
                target_x=int(box["x"] + box["width"] / 2),
                target_y=int(box["y"] + box["height"] / 2),
            )
    except Exception:
        pass  # stale element or off-screen — not critical
