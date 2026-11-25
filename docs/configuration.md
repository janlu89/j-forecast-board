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
| `JFB_AUTH` | `on` | `on` = sign-in page required. `off` = no sign-in, accepted only when `JFB_HOST` is this PC (`127.0.0.1`, `localhost`, `::1`). Keep it `on` behind a reverse proxy on the same PC: the proxy connects from 127.0.0.1. |
| `JFB_ROOT_PATH` | empty | Path prefix when the app is served behind a reverse proxy, for example `/board`. |
| `JFB_TRUST_PROXY` | `0` | `1` = honour `X-Forwarded-*` headers from a reverse proxy on this PC. |
| `JFB_CHAT_TIMEOUT` | `240` | Seconds an assistant answer may take. |
| `JFB_LOG_LEVEL` | `info` | `critical`, `error`, `warning`, `info`, `debug` or `trace`. |
| `JFB_MAX_UPLOAD_MB` | `200` | Largest CSV file accepted, in MB. |
| `JFB_POLICY_FILE` | `config/policy.json` under `JFB_HOME` | Admin policy (see below). |
| `JFB_AGENT_API_KEY` | not set | API key for `python -m j_forecast_board agent set … --key`, instead of typing it. |

## The runtime folder

| Path under `JFB_HOME` | Content | Sensitive |
|---|---|---|
| `secrets/credentials.json` | sign-in user and a scrypt hash of the password (never the password) | yes |
| `secrets/initial-password.txt` | the first-start password, deleted at the first sign-in | yes |
| `secrets/session.key` | random key that signs the session cookies | yes |
| `secrets/agent-keys.json` | API keys of the assistants | yes |
| `config/assistant.json` | assistant settings and consents, no keys | no |
| `config/policy.json` | admin policy, optional | no |
| `data/` | downloaded public datasets | no |
| `results/` | cached backtests of the Timestral models | no |
| `results-stub/` | cached backtests of the stub model, kept apart | no |
| `uploads/` | reserved: uploads stay in memory and are never written to disk | yes |
| `logs/audit.jsonl` | audit log (see docs/data-protection.md) | no values by design |

On Linux the folder and `secrets/` are readable by the owner only (`0700`), and secret files are
`0600`. On Windows the folder sits in the user's own profile, which other standard users cannot
read.

At the first start the app creates the user `admin` with a random password, prints it in the
console and keeps it in `secrets/initial-password.txt` until the first sign-in. To choose a new
password at any time: `python -m j_forecast_board password` (or `--generate` for a random one).

## Admin policy

An administrator can put a `policy.json` in `config/` (or point `JFB_POLICY_FILE` to a file the
user cannot edit). Its rules win over the user's own settings. Every key is optional:

```json
{
  "allow_external_ai": false,
  "allow_private_data_to_external_ai": false,
  "allowed_ai_hosts": ["api.mistral.ai"],
  "offline": true
}
```

| Key | Default | Meaning |
|---|---|---|
| `allow_external_ai` | `true` | `false` = only an assistant on this PC can be used. |
| `allow_private_data_to_external_ai` | `false` | `true` = uploaded data may go to an external assistant, after a second confirmation by the user. |
| `allowed_ai_hosts` | any | The only online services allowed (host names, or `claude-cli`). |
| `persist_uploads` | `false` | Reserved; uploads are never written to disk today. |
| `offline` | `false` | `true` = like `JFB_OFFLINE=1`, whatever the user sets. |

An unknown key or a wrong value stops the start with a message, so a typo cannot silently weaken
the policy.
