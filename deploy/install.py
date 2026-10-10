"""Install user timers pointing at this checkout. Private rollout flags gate all actions."""

from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
if any(x in str(root) for x in (" ", "\n", "%", '"')):
    raise SystemExit(
        "Checkout path must not contain spaces or systemd special characters"
    )
units = Path.home() / ".config/systemd/user"
units.mkdir(parents=True, exist_ok=True)
exe = root / ".venv/bin/pubmail"
for name, cmd, schedule in [
    ("hourly", "hourly", "hourly"),
    ("weekly", "weekly", "Fri *-*-* 11:00:00 Europe/Lisbon"),
]:
    service = f"""[Unit]
Description=Pubmail {name} (guarded by local rollout config)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory={root}
ExecStart={exe} {cmd}
Environment=PATH={Path.home()}/.local/bin:/home/linuxbrew/.linuxbrew/bin:/usr/local/bin:/usr/bin:/bin
UMask=0077
TimeoutStartSec=3600
"""
    timer = f"""[Unit]
Description=Pubmail {name} schedule

[Timer]
OnCalendar={schedule}
Persistent=true
Unit=pubmail-{name}.service

[Install]
WantedBy=timers.target
"""
    (units / f"pubmail-{name}.service").write_text(service)
    (units / f"pubmail-{name}.timer").write_text(timer)
subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
subprocess.run(
    [
        "systemctl",
        "--user",
        "enable",
        "--now",
        "pubmail-hourly.timer",
        "pubmail-weekly.timer",
    ],
    check=True,
)
print("Installed schedules. Rollout configuration controls whether either job acts.")
