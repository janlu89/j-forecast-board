# Deployment

J-Forecast Board is meant to run on the PC of the person who uses it. These are the ways to start it.

## On demand (default)

Windows: double-click `start.cmd` (or `.\start.ps1` in PowerShell). Linux: `./start.sh`.
Keep the window open while you use the board; close it (or press Ctrl+C) to stop.

## Start at logon on Windows (Task Scheduler)

1. Open **Task Scheduler** → **Create Task…**
2. *General*: name `J-Forecast Board`, "Run only when user is logged on".
3. *Triggers*: **At log on** of your user.
4. *Actions*: **Start a program**, program `powershell.exe`, arguments
   `-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "C:\path\to\j-forecast-board\start.ps1"`,
   start in `C:\path\to\j-forecast-board`.
5. *Settings*: untick "Stop the task if it runs longer than…".

## A systemd user service on Linux

`~/.config/systemd/user/j-forecast-board.service`:

```ini
[Unit]
Description=J-Forecast Board
After=network-online.target

[Service]
WorkingDirectory=%h/j-forecast-board
Environment=PYTHONUTF8=1
ExecStart=%h/j-forecast-board/.venv/bin/python -m j_forecast_board serve
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

Then `systemctl --user daemon-reload && systemctl --user enable --now j-forecast-board`.
Add `loginctl enable-linger $USER` to keep it running when you are logged out.

## Behind a reverse proxy or a tunnel

To let colleagues open the board, put it behind a reverse proxy (nginx, Caddy) or a tunnel
(Tailscale Serve/Funnel) **on the same PC**, with HTTPS:

- keep the board on `127.0.0.1` and keep sign-in on (`JFB_AUTH=on`, the default): the proxy
  connects from 127.0.0.1, so the board cannot tell its users apart from you;
- under a path prefix, set `JFB_ROOT_PATH` (e.g. `/board`); every URL in the app is relative;
- set `JFB_TRUST_PROXY=1` so the session cookie is marked `Secure` behind HTTPS;
- choose a strong password: `python -m j_forecast_board password`.

Example with Tailscale on Linux: `tailscale serve --bg --set-path=/board http://127.0.0.1:8000`
(`funnel` instead of `serve` publishes it on the internet: think twice).

Check your company's rules before exposing anything beyond your own PC. The board is a
single-user tool: see `SECURITY.md`.

## Offline PCs

On a PC without internet, start with `JFB_OFFLINE=1`. Copy beforehand, from a PC with internet:

- the runtime `data/` folder (public datasets) into the same place under `JFB_HOME`;
- the Hugging Face cache folder `models--mistralai--Timestral-28M` (in `~/.cache/huggingface/hub`)
  for real forecasts;
- the Python packages: `pip download -r requirements.txt -d wheels` there, then
  `pip install --no-index --find-links wheels -r requirements.txt` here.
