# MAYA — an Estonian voice assistant that calls you

**[🇪🇪 Eesti keeles](README.md)** · **🇬🇧 In English (this file)**

MAYA is a real-time voice assistant you talk to on your phone like a
person. It is not a tap-a-button question-and-answer machine: it speaks
with the rhythm of natural speech, starts talking on its own after a
pause, automatically finishes a sentence that got cut off, and **calls
your phone** when it has something to say.

The voice engine is the **Google Gemini Live API** (native audio, not
text-to-speech). The backend is Python/FastAPI, the client is an
Android app.

> ### ⚠️ MAYA speaks Estonian
> The characters, the app interface and the log messages are all in
> **Estonian**, and there is currently no English UI. The installation
> is documented in English so that setting it up is accessible, but
> MAYA itself will talk to you in Estonian.

> ### 🚀 Want to start right away?
> **[→ START HERE: installation guide](docs/PAIGALDAMINE_EN.md)** — or
> run `./paigalda.sh` and the script will walk you through it (its
> prompts are in Estonian).
>
> The three installation paths are described under
> [Installation](#installation).

> **MAYA is not a service.** This repository contains source code and an
> Android app — **no MAYA server runs here and there is nothing to sign
> up for**. You run the backend on your own machine with your own Gemini
> API key, and your phone connects to *your* server. The app asks for
> that address on first launch.
>
> **This is a public copy.** The project started as one person's
> personal assistant and was moved here with all personal content,
> keys, server addresses and conversation history removed. You install
> your own instance, with your own keys and your own characters.

---

## How it works

```
   ANDROID PHONE                         YOUR SERVER                    GOOGLE
┌────────────────────┐            ┌────────────────────────┐        ┌───────────┐
│  MAYA app          │            │  web_maya.py (FastAPI) │        │  Gemini   │
│                    │  HTTP(S)   │                        │        │  Live API │
│  microphone ──────────────────► │  /api/...   auth       │        │  (native  │
│  speaker    ◄────────────────── │                        │        │   audio)  │
│                    │ WebSocket  │  /ws/live_maya ────────────────► │           │
│  camera ──────────────────────► │     (audio both ways)           │           │
│                    │            │                        │ ◄──────┤           │
│  call alert ◄────────────────── │  /api/call_events (SSE)│        └───────────┘
└────────────────────┘            │                        │
                                  │  SQLite: a SEPARATE    │
                                  │  database per user     │
                                  └────────────────────────┘
```

**All traffic goes over a single port (8000)** and the phone only ever
talks to your server — never directly to Google. Your API key never
leaves the server.

---

## What MAYA does

| | |
|---|---|
| **Real-time voice conversation** | Gemini Live native audio, Estonian, interruptible at any moment |
| **Characters** | 10 distinct personalities with their own voice and temperament |
| **Custom character** | you write the instructions and MAYA takes that role |
| **Autonomous continuation** | after a natural pause MAYA speaks up by itself, with per-character timing |
| **Automatic recovery** | if a sentence gets cut off, it continues from the same place |
| **User priority** | your speech interrupts everything — self-initiated talk, recovery, pending requests |
| **Long-term memory** | fact extraction from conversation, FTS5 search, Estonian morphology |
| **Character-initiated calls** | MAYA rings your phone and starts the conversation |
| **Reminders and calendar** | recurring reminders delivered as a phone call |
| **Camera** | MAYA sees the camera and comments on it |
| **Singing** | lyrics lookup, key and tempo, line-by-line delivery (experimental) |
| **Everyday tools** | web search, reading pages and PDFs, YouTube subtitles, email |
| **Multiple users** | each user gets their own account and their own separate database |

---

## Installation

**Pick the path that suits you.** All three end up in the same place.

| | For whom | How long | Guide |
|---|---|---|---|
| 🟢 **1. Simple** | everyone, including first-timers | ~15 min | below + [docs/PAIGALDAMINE_EN.md](docs/PAIGALDAMINE_EN.md) |
| 🤖 **2. With AI help** | if you want each step explained | ~20 min | [docs/AI_ASSISTED_INSTALLATION.md](docs/AI_ASSISTED_INSTALLATION.md) |
| 🔧 **3. Manual** | if you want to understand everything | ~30 min | [docs/PAIGALDAMINE_EN.md](docs/PAIGALDAMINE_EN.md) |

### 🟢 1. Simple installation

You need **Python 3.11+**
([python.org](https://www.python.org/downloads/)) and a **Gemini API
key** ([aistudio.google.com/apikey](https://aistudio.google.com/apikey)).

```bash
git clone <repository-address> maya
cd maya
./paigalda.sh
```

`paigalda.sh` does the rest and asks you three things: whether to
continue, your API key (**it is never echoed to the screen**), and how
your phone will reach the server. It **never overwrites** an existing
installation, never opens firewall ports, and never puts MAYA on the
public internet.

Then:

```bash
./tervisekontroll.sh     # check that everything is fine
./kaivita.sh             # start MAYA
./kaivita.sh --ip        # print the address to enter on your phone
```

**On the phone:** install the Android app → it asks for the server
address on first launch → **"Testi ühendust"** (test connection) →
**"Loo uus konto"** (create account; the first one becomes admin) →
start talking.

> Building and installing the Android app:
> [docs/ANDROID.md](docs/ANDROID.md) (Estonian). The APK contains **no
> server address and no key** — the same file works with any MAYA
> installation.

### 🤖 2. Installation with an AI assistant

If you are not a programmer, an AI coding assistant (such as
[Claude Code](https://code.claude.com/docs/en/overview) or
[VS Code](https://code.visualstudio.com/) with an AI extension) can do
the installation for you and explain every step.

**[→ docs/AI_ASSISTED_INSTALLATION.md](docs/AI_ASSISTED_INSTALLATION.md)**
— contains a ready-made prompt you can paste to the assistant. The
prompt restricts it so that it cannot leak your key, open your
firewall, or deploy anything to someone else's server.

### 🔧 3. Manual installation

Every command explained, with sections on networking, security and
troubleshooting:
**[→ docs/PAIGALDAMINE_EN.md](docs/PAIGALDAMINE_EN.md)**

### Managing it

```bash
./peata.sh               # stop the server
./uuenda.sh              # pull a new version + update dependencies and schema
./tervisekontroll.sh     # diagnostics: install, config, database, server, network
```

---

## What you need

| | |
|---|---|
| **A Google Gemini API key** | [aistudio.google.com/apikey](https://aistudio.google.com/apikey). The Live API is paid — see below |
| **Python 3.11+** | verified on 3.13 and 3.14 |
| **An Android phone** | Android 8.0+ (API 26). The calling feature needs a real device |
| **A server** | your computer, a home server or a VPS. **Linux and macOS are supported**; on Windows use [WSL2](https://learn.microsoft.com/en-us/windows/wsl/install) (unverified) |

Hardware: **2 GB RAM and 2 GB of free disk is enough.** No GPU and no
fast CPU needed — the heavy work happens at Google.

Optional: a Groq key (text chat), Tavily (web search), a Gmail app
password (email). **Docker is not needed** — see
[why](docs/PAIGALDAMINE_EN.md#why-there-is-no-docker).

### 💳 Gemini API key and costs

MAYA's voice comes from the **Google Gemini Live API**, which needs
your own API key:

1. Open [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
   and create a key.
2. **The Gemini Live API is paid** and normally requires billing to be
   enabled. Pricing:
   [aistudio.google.com/docs/pricing](https://aistudio.google.com/docs/pricing).
3. **The bill goes to you, not to the MAYA project.** Prices, free
   quotas and billing requirements are set by Google and can change —
   this repository contains no price figures, because they would go
   stale.
4. **Set a budget alert before your first conversation:**
   [console.cloud.google.com/billing/budgets](https://console.cloud.google.com/billing/budgets).

**The key stays on the server.** The Android app never sees it: the
phone talks to your backend, the backend talks to Google. The key lives
in `.env`, which is in `.gitignore`.

Documentation: [ai.google.dev/gemini-api/docs](https://ai.google.dev/gemini-api/docs)

---

## Documentation

**[→ docs/README.md](docs/README.md)** is the full documentation index.

In English:

| File | Contents |
|---|---|
| **[docs/PAIGALDAMINE_EN.md](docs/PAIGALDAMINE_EN.md)** | **complete installation guide for beginners** |
| **[docs/AI_ASSISTED_INSTALLATION.md](docs/AI_ASSISTED_INSTALLATION.md)** | installing with an AI assistant |

In Estonian (the rest of the documentation):

| File | Contents |
|---|---|
| [docs/SEADISTAMINE.md](docs/SEADISTAMINE.md) | every environment variable |
| [docs/ANDROID.md](docs/ANDROID.md) | building and connecting the Android app |
| [docs/GEMINI_LIVE.md](docs/GEMINI_LIVE.md) | Gemini Live configuration, model, costs |
| [docs/TURVALISUS.md](docs/TURVALISUS.md) | authentication, user isolation, what is covered |
| [docs/ARHITEKTUUR.md](docs/ARHITEKTUUR.md) | modules, conversation lifecycle, memory |
| [docs/KARAKTERID.md](docs/KARAKTERID.md) | writing your own characters |
| [docs/KONEALGATUS.md](docs/KONEALGATUS.md) | how character-initiated calls work |
| [docs/MITU_SEADET.md](docs/MITU_SEADET.md) | multiple phones and accounts |
| [docs/SOLTUVUSED.md](docs/SOLTUVUSED.md) | dependencies and their licenses |
| [docs/ARENDUS.md](docs/ARENDUS.md) | tests, coding conventions, open issues |
| [CONTRIBUTING.md](CONTRIBUTING.md) | how to contribute and under which license |
| [SECURITY.md](SECURITY.md) | reporting vulnerabilities, existing protections |
| [LICENSE](LICENSE) · [NOTICE](NOTICE) | Apache License 2.0 |

---

## Local testing versus a public deployment

These are **two completely different situations** with different
requirements. Don't mix them up.

| | **Local testing** | **Public internet** |
|---|---|---|
| Where the server is | your computer or home server | VPS, cloud, public IP |
| Network | same Wi-Fi or a private network (Tailscale/WireGuard) | the open internet |
| Protocol | **HTTP is OK** | **HTTPS/WSS is MANDATORY** |
| Authentication | sufficient | sufficient, but HTTPS must be on |
| Registration | `MAYA_ALLOW_REGISTRATION=1` | **`=0` or an invite code** |
| Reverse proxy | not needed | **nginx/Caddy with TLS** |
| `MAYA_HOST` | `0.0.0.0` | `127.0.0.1` (behind the proxy) |

**Start with local testing.** Only go to the public internet once HTTPS
is in place — otherwise your speech, memory and authentication token
travel in clear text.

---

## ⚠️ Security warning — please read

MAYA's backend **does have authentication**: every `/api` endpoint, the
SSE stream and the Gemini Live WebSocket require a valid token. Each
user's data (memory, reminders, conversations, settings) lives in a
**separate database**, so one user cannot see another's data or call
them.

**But by default the traffic is HTTP, not HTTPS.** Authentication
protects against unauthorised users, not against eavesdropping. So:

1. **A private network** (Tailscale, WireGuard, ZeroTier) — simplest
   and recommended.
2. **A reverse proxy** (nginx/Caddy) with HTTPS, if the server is
   public.
3. **Local only** (`MAYA_HOST=127.0.0.1` + an SSH tunnel).

Full overview: **[docs/TURVALISUS.md](docs/TURVALISUS.md)** (Estonian)
· in English: [docs/PAIGALDAMINE_EN.md §6](docs/PAIGALDAMINE_EN.md#6-security-and-accounts)

**What is sent to Google:** during a voice conversation your speech
audio, camera frames (if enabled), the character instructions and the
memory facts included in that conversation are sent to the Gemini Live
API. MAYA cannot avoid this — it is what Gemini Live is. If a topic
must not reach the cloud, do not discuss it with MAYA.

---

## What is NOT here

In the interest of honesty, this public copy contains **none of**:

- any API key, password or access token;
- any database — memory facts, reminders and the conversation archive
  are empty;
- the original installation's personal character prompts — the
  characters are **generic examples** you overwrite yourself;
- server addresses, usernames or paths;
- Android signing keys;
- the original project's Git history.

**There is no prebuilt APK in this repository** — binaries do not
belong in version control. You build the Android app with one command
(`cd android && ./gradlew assembleDebug`, see
[docs/ANDROID.md](docs/ANDROID.md)). If a release is ever published,
the APK will be on the **Releases** page with its SHA-256 sum.

**No feature has been tested on a real phone** with this public copy.
The code has been reviewed and the automated tests pass, but no
physical-device verification has been done — don't treat it as proven.

---

## License

MAYA is licensed under the **Apache License 2.0** — full text in
[LICENSE](LICENSE), copyright and attribution notice in
[NOTICE](NOTICE).

In short:

| | |
|---|---|
| Use, modify, distribute | allowed, including commercially |
| Closed-source product | allowed |
| Publishing your changes | **not** required |
| Shipping `LICENSE` and `NOTICE` | **required** (§4a, §4d) |
| Marking modified files | **required** (§4b) |
| Patent grant from contributors | **granted** (§3) |
| Using the name "MAYA" as a trademark | **not granted** (§6) |
| Warranty | **none** (§7, §8) |

**Dependencies are separate.** MAYA bundles no third-party source code
— dependencies are installed from PyPI and Maven Central and remain
under their own licenses. The full list, including one case that needs
attention (`tld`, an indirect dependency), is in
[docs/SOLTUVUSED.md](docs/SOLTUVUSED.md).

**Gemini Live is not covered by this license.** The voice comes from
Google's API and Google's own terms and pricing always apply. MAYA is
not affiliated with or endorsed by Google.

---

## Contributing

Pull requests for fixes and improvements are welcome — see
[CONTRIBUTING.md](CONTRIBUTING.md).

Contributions come in **under Apache-2.0** (§5) and **you keep the
copyright to your own code** — no CLA is required.

**Important note:** this public project is independent and no MAYA
service runs here. No public contribution automatically reaches any
running installation — not the maintainer's and not anyone else's.
Every MAYA operator decides for themselves what to update.
