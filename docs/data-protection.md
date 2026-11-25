# Data protection

A one-page summary for people who decide whether J-Forecast Board may be used with their data.

## In short

- J-Forecast Board runs on your PC. It is a local tool, not an online service.
- Your data stays on the PC. The only optional exception is the AI assistant, and only when you
  connect it to an online service yourself and confirm it.
- The data you upload is never sent to an external AI assistant, unless an administrator's policy
  allows it and you confirm it a second time.
- There is no telemetry, no update check, no tracking and no content from the internet in the page.

## What leaves the PC, and when

| What | Where to | When |
|---|---|---|
| Model weights (Timestral, about 111 MB for the 28M size) | downloaded **from** Hugging Face | once, at the first real forecast; never with `JFB_OFFLINE=1` |
| Public datasets (Rossmann, bike sharing, …) | downloaded **from** their public hosts | once each, at the first start; never with `JFB_OFFLINE=1` |
| Python packages | downloaded **from** PyPI and download.pytorch.org | during setup only |
| Your question, the visible text and numbers of the current tab, compact chart data, the results of the tools the assistant calls | **to** the AI service you configured | only when you ask a question to an **External** assistant |

Nothing is ever sent to the authors of J-Forecast Board.

## The AI assistant

The assistant is **off** on a new install. To use it you choose one in the setup dialog:

- **Local model**: a model server on this PC (llama.cpp, Ollama, LM Studio, vLLM). Nothing leaves
  the PC. The chat shows a green **Local** badge.
- **External**: an online API (Groq, OpenRouter, Mistral, OpenAI, …) or the Claude Code CLI. The
  board shows who will receive the data and asks you to confirm it before the first question. The
  chat shows an amber **External: destination** badge. A new destination asks again.

You can choose how much of the page the assistant sees: everything (text, numbers and chart data),
the visible text and numbers only, or only your question.

**Uploaded data is private.** With an external assistant, a question asked on a page that shows an
uploaded dataset is refused before anything is sent, and the assistant's tools refuse to read such
a dataset. An administrator can allow it with `allow_private_data_to_external_ai` in the policy file;
the user must then confirm it a second time.

The provider's own terms and data retention apply to whatever it receives. Check your company's
rules before you send company data to an online service.

## Where the data lives on the PC

Everything the board writes is in one folder per user, outside the program folder:

- Windows: `%LOCALAPPDATA%\JForecastBoard`
- Linux: `~/.local/share/j-forecast-board`

| Content | Stored | Notes |
|---|---|---|
| Uploaded CSV files | **in memory only** | gone when the board stops; "Delete this dataset" removes one at once |
| Public datasets, cached results | `data/`, `results/` | public data |
| Sign-in password | `secrets/credentials.json` | only a scrypt hash, never the password |
| API keys of the assistants | `secrets/agent-keys.json` | never sent back to the browser |
| Assistant settings and consents | `config/assistant.json` | no keys |
| Audit log | `logs/audit.jsonl` | see below |

On Linux the folder is readable by your user only. On Windows it is in your own profile.

## How to check it yourself

- **Audit log** (`logs/audit.jsonl`): one line per sign-in, failed sign-in, lock-out, upload,
  deletion, assistant setting, consent, and **every call to an assistant** with time, destination,
  dataset name, whether it was private, the context level, the bytes sent, the tools used and the
  outcome. It never contains questions, answers, data values or keys.
- **Offline mode**: start with `JFB_OFFLINE=1`. The board then downloads nothing at all. The test
  suite runs every page with the network blocked except this PC.
- **Admin policy**: see `docs/configuration.md` to forbid external assistants, allow only some
  services, or force offline mode.

## How to delete everything

```
python -m j_forecast_board purge
```

It deletes the whole runtime folder: sign-in, API keys, settings, caches, logs. The model weights
stay in the Hugging Face cache (`~/.cache/huggingface` or `%USERPROFILE%\.cache\huggingface`):
delete the `models--mistralai--Timestral-*` folders there to remove them too.
