# Configuration

J-Forecast Board reads its settings once, at start, from environment variables that begin with
`JFB_`. Nothing has to be set for a normal local start. An invalid value stops the start with a
message that names the variable.

Command line options of `python -m j_forecast_board serve` (`--host`, `--port`) win over the
variables.

| Variable | Default | Meaning |
|---|---|---|
| `JFB_HOME` | Windows: `%LOCALAPPDATA%\JForecastBoard`; Linux: `$XDG_DATA_HOME/j-forecast-board`, else `~/.local/share/j-forecast-board` | Folder for every runtime file (see below). It is never inside the code folder. |
| `JFB_HOST` | `127.0.0.1` | Address to listen on. `127.0.0.1` means "this PC only". |
| `JFB_PORT` | `8000` | Port. |
| `JFB_MODEL` | `timestral` | `timestral` runs Mistral AI's Timestral models. `stub` is a deterministic stand-in for tests and installation checks: it downloads nothing, and its numbers are **not** forecasts. |
| `JFB_DEFAULT_MODEL_SIZE` | `28M` | Model evaluated in the background at start: `5M`, `28M`, `123M` or `209M`. |
| `JFB_BACKGROUND_EVAL` | `1` | `0` = do not evaluate the built-in datasets at start. |
| `JFB_OFFLINE` | `0` | `1` = never download datasets or model weights; only what is already in `JFB_HOME` and in the Hugging Face cache is used. Also sets `HF_HUB_OFFLINE=1`. |
| `JFB_AUTH` | `on` | `on` = sign-in page required. `off` = no sign-in, accepted only when `JFB_HOST` is this PC (`127.0.0.1`, `localhost`, `::1`). |
| `JFB_ROOT_PATH` | empty | Path prefix when the app is served behind a reverse proxy, for example `/board`. |
| `JFB_TRUST_PROXY` | `0` | `1` = honour `X-Forwarded-*` headers from a reverse proxy on this PC. |
| `JFB_CHAT_TIMEOUT` | `240` | Seconds an assistant answer may take. |
| `JFB_LOG_LEVEL` | `info` | `critical`, `error`, `warning`, `info`, `debug` or `trace`. |

## The runtime folder

| Path under `JFB_HOME` | Content | Sensitive |
|---|---|---|
| `secrets/credentials.json` | sign-in user and password, created at the first start | yes |
| `secrets/agents.json` | assistant settings, including API keys | yes |
| `config/` | reserved for settings without secrets | no |
| `data/` | downloaded public datasets | no |
| `results/` | cached backtests of the Timestral models | no |
| `results-stub/` | cached backtests of the stub model, kept apart | no |
| `uploads/` | reserved for uploaded files (today uploads stay in memory) | yes |
| `logs/` | reserved for logs | no |

On Linux the folder and `secrets/` are readable by the owner only (`0700`), and secret files are
`0600`. On Windows the folder sits in the user's own profile, which other standard users cannot
read.

At the first start the app creates `secrets/credentials.json` with the user `admin` and a random
password, and prints both once in the console. To see them again, open that file.
