"""Status bar widget — robot name, connection, task, elapsed time."""

from __future__ import annotations

from textual.reactive import reactive
from textual.widgets import Static


class StatusBar(Static):
    """Top status bar showing robot name, world, connection, health, task, and elapsed time."""

    robot_name: reactive[str] = reactive("unknown")
    world_name: reactive[str] = reactive("none")
    connection: reactive[str] = reactive("Disconnected")
    health: reactive[str] = reactive("")
    task_info: reactive[str] = reactive("")
    elapsed: reactive[str] = reactive("0m00s")

    def render(self) -> str:
        # Connection indicator with color
        conn_lower = self.connection.lower()
        if "connected" in conn_lower and "dis" not in conn_lower and "re" not in conn_lower:
            conn = f"[green]● {self.connection}[/green]"
        elif "connecting" in conn_lower or "reconnect" in conn_lower:
            conn = f"[yellow]● {self.connection}[/yellow]"
        else:
            conn = f"[red]● {self.connection}[/red]"

        # Health indicator
        if self.health:
            if "OK" in self.health:
                health = f"[green]✓ {self.health}[/green]"
            elif "MISSING" in self.health:
                health = f"[yellow]⚠ {self.health}[/yellow]"
            else:
                health = f"[dim]{self.health}[/dim]"
        else:
            health = "[dim]… checking[/dim]"

        parts = [
            f"[bold]{self.robot_name}[/bold]",
            f"[dim]world:[/dim] {self.world_name}",
            conn,
            health,
        ]
        if self.task_info:
            parts.append(self.task_info)
        parts.append(self.elapsed)
        return "  │  ".join(parts)
