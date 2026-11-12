<h1 align="center">MAYA</h1>

<p align="center">
  <strong>Maya helistab sulle. Mitte vastupidi.</strong><br>
  <em>"Maya calls you. Not the other way round."</em>
</p>

<p align="center">
  An Estonian-first AI voice companion that talks to you naturally,<br>
  remembers what you are up to, and reminds you of the things that matter.
</p>

<p align="center">
  <a href="README.md">🇪🇪 Eesti keeles</a> ·
  <strong>🇬🇧 In English (this file)</strong> ·
  <a href="docs/PAIGALDAMINE_EN.md">📦 Installation</a> ·
  <a href="docs/README.md">📚 Documentation</a>
</p>

<p align="center">
  <a href="LICENSE"><img alt="License: Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-blue"></a>
  <img alt="Estonian" src="https://img.shields.io/badge/language-Estonian-success">
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-blue">
  <img alt="Android 8+" src="https://img.shields.io/badge/android-8.0%2B-green">
  <img alt="Self-hosted" src="https://img.shields.io/badge/hosting-your%20own%20server-orange">
</p>

> ### ⚠️ MAYA speaks Estonian
> The characters, the app interface and the log messages are all in
> **Estonian**, and there is currently no English UI. The installation
> is documented in English so that setting it up is accessible, but
> MAYA itself will talk to you in Estonian.

<p align="center">
  <strong>🚀 <a href="docs/PAIGALDAMINE_EN.md">START HERE: installation guide</a></strong><br>
  <sub>or run <code>./paigalda.sh</code> — the script walks you through it</sub>
</p>

---

## What makes MAYA different from an ordinary AI chatbot?

An ordinary chatbot **waits for you to start**. You open an app, type a
question, read the answer, close the app. The conversation ends where
you leave.

MAYA works the other way round:

| | Ordinary AI chatbot | **MAYA** |
|---|---|---|
| Who starts | always you | **MAYA reaches out** and pushes a call alert to your phone |
| How you interact | you type and read | **you talk** — at the rhythm of natural speech, interruption allowed |
| Silence in a conversation | the bot waits forever | **MAYA speaks up by itself** after a pause |
| When a sentence is cut off | it stays unfinished | **it continues by itself** from the same place |
| Remembering | forgets when the chat ends | **long-term memory** with Estonian-morphology search |
| Personality | one generic assistant | **10 characters** with their own voice and temperament |
| Language | Estonian is an afterthought | **Estonian is the starting point** — characters, prompts, UI, logs |
| Whose machine | someone else's cloud | **your own server, your own API key** |

**MAYA is not another ChatGPT wrapper.** It is an Estonian-language
voice companion that lives on your own machine and takes the initiative
in a conversation.

---

## 📞 MAYA calls you

This is the heart of the project, so here is **exactly** how it works,
with no embellishment.

```
  YOUR SERVER                                      YOUR PHONE
  ───────────                                      ──────────
  something happens                                the MAYA app is in
  (reminder / timer /                               the background, holding
   MAYA's own decision)                             an SSE connection open
        │                                                │
        ├── event → /api/call_events (SSE) ────────────► │
        │                                                │
        │                                    CallWatcherService
        │                                    (foreground service + wake lock)
        │                                                │
        │                                                ▼
        │                                    IncomingCallActivity
        │                                    • system ringtone + vibration
        │                                    • screen wakes, over the lock screen
        │                                    • "answer" / "decline"
        │                                                │
        └──────── you answer → Gemini Live session ──────┘
                  MAYA speaks FIRST
```

> ### ⚠️ What this is NOT
> **This is not a cellular phone call.** MAYA does not dial through the
> mobile network, does not use your number or SIM card, and the call
> does not appear in your call log. It is a **push event from your own
> server**; the app then opens a call screen on the phone that looks and
> behaves like an incoming call: it rings, vibrates and appears over the
> lock screen. The audio travels over the internet to your own server,
> not through a mobile operator's network.

**What can trigger it:**

| Trigger | Status |
|---|---|
| `POST /api/trigger_call` — manually or from a script | ✅ **verified end to end** (the event arrived in the SSE stream; the server logged the device connecting) |
| MAYA's own decision during a conversation (the `schedule_call` tool — "call me back in 5 minutes") | ⚙️ implemented, in-memory timer (lost on server restart) |
| A scheduled reminder (including recurring) | ✅ **verified end to end** — two users with reminders due at the same time each received ONLY their own call event (real server, real auth, real SSE) |
| The alert reaching **all** devices on the account | ✅ fan-out, covered by 6 tests |
| The Android side (ringtone, lock screen, answering) | ⚙️ implemented, **unverified on a real device** |

---

## What MAYA can do

Every row has been checked against the code. Status: ✅ tested ·
⚙️ implemented but not fully verified · 🧪 partial / experimental ·
⚠️ broken or missing.

### Voice and conversation

| | Status | What exactly |
|---|---|---|
| **Estonian voice conversation** | ⚙️ | Gemini Live native audio (`gemini-2.5-flash-native-audio-preview-12-2025`), audio-only output. The Estonian comes from Estonian character prompts — **Gemini Live itself is a multilingual model, not an Estonian-only one** |
| **Interruption** | ✅ | your speech cuts MAYA off immediately — VAD `START_OF_ACTIVITY_INTERRUPTS`, covered by the conversation-lifecycle tests |
| **Speaking up after silence** | ✅ | a per-character pause, then MAYA takes the floor |
| **Automatic recovery** | ✅ | if a sentence is cut off, it continues from the same place without being asked |
| **User priority** | ✅ | your speech interrupts self-initiated talk, recovery and pending requests |
| **Voice tools during a conversation** | ⚙️ | 10 tools: `add_reminder`, `get_reminders`, `schedule_call`, `recall_memory`, `set_user_name`, `get_weather`, `get_electricity_price`, `get_email_status`, `get_song_lyrics`, `get_last_turn_state` |

> **An important caveat:** the conversation-lifecycle tests (turns,
> interruptions, recovery, cancellation — hundreds of tests) use a
> **mocked** Gemini session and clock. They prove MAYA's own logic,
> **not** Gemini Live's behaviour. There are no real-Gemini tests in the
> suite, because they would need a key and cost money.

### Characters and memory

| | Status | What exactly |
|---|---|---|
| **10 characters** | ✅ | `asjalik` (matter-of-fact), `sõber` (friend), `sarkastiline`, `romantiline`, `filosoof`, `mentor`, `treener` (coach), `zen`, `laulja` (singer), `kohandatud` (custom) — each with its own Gemini voice (Kore / Aoede / Leda / Zephyr) and its own initiative level |
| **Custom character** | ✅ | you write the instructions yourself; tests prove it **does not leak** into any other character's prompt |
| **Long-term memory** | ✅ | FTS5 search, Estonian morphology (cases), fact extraction from conversation |
| **Memory lifecycle** | ✅ | duplicate detection, superseding old facts, contradiction detection, confidence levels — 18 tests |
| **Memory isolation between characters** | ✅ | private / per-character / shared scopes — 58 + 49 tests |

### Reminders and calendar

| | Status | What exactly |
|---|---|---|
| **Reminder CRUD** | ⚙️ | `GET/POST/DELETE/PUT /api/reminders`, authenticated. Creation verified with a request |
| **Creating by voice** | ⚙️ | you say it in conversation and MAYA stores it (`add_reminder`) |
| **Repeats** | ⚙️ | `none`, `daily`, `weekly`, `workdays` |
| **Per-character delivery** | ⚙️ | the character that created a reminder also delivers it (e.g. a rhyming wake-up created as the singer) |
| **Morning briefing** | ⚙️ | `notify_type=briefing` gathers the data **at call time**, not when saved |
| **Calendar view** | 🧪 | month and list view (`calendar_module.js`), per-day filtering, edit/delete. **There is no separate calendar table** — the calendar is a view over reminders |
| **Scheduled reminder call** | ✅ | the background watcher walks every user database, sets each user's context and delivers the call event to the RIGHT user — 25 tests plus a live-server check |

### Android and the rest

| | Status | What exactly |
|---|---|---|
| **Android app** | ⚙️ | WebView + native audio plumbing, call screen, foreground service, proximity sensor, Bluetooth/speaker switching |
| **Server address in the app** | ✅ | the user enters it, with a connection test; 29 Kotlin tests on the pure logic |
| **Multiple devices / accounts** | ✅ | a call alert reaches every device on the account; separate accounts are isolated |
| **Camera** | ⚙️ | the app sends frames (768 px, ~1.5 s) into the live session and MAYA comments on what it sees |
| **Authentication** | ✅ | scrypt passwords, SHA-256 token hashes, **single-use WebSocket ticket**, per-user database, rate limiting — 61 tests |
| **Singing** | 🧪 | lyrics lookup, key and tempo, line-by-line delivery — experimental |
| **Web and file tools** | ⚙️ | web search, reading pages and PDFs, YouTube subtitles, email status |
| **Cost tracker** | ⚙️ | estimated session cost in the server log (**MAYA's own estimate, not Google's invoice**) |

---

## What does not work yet

An honest list. If it doesn't put you off, see
[Contributing](#why-contribute) — these are exactly the places where
help counts most.

| Problem | The actual situation |
|---|---|
| **Unverified on a real device** | no feature has been tested on a **physical phone** with this public build |
| **`schedule_call` doesn't survive a restart** | the timer is in memory (`asyncio`); restarting the server loses it |
| **HTTPS is not built in** | a reverse proxy is mandatory on the public internet; documented, not automated |
| **Call alerts use SSE, not FCM** | which is why the Android **battery exemption is mandatory**; the FCM analysis is in [docs/KONEALGATUS.md](docs/KONEALGATUS.md) (Estonian) |
| **No iOS app** | considerations: [docs/IOS.md](docs/IOS.md) (Estonian) |
| **Windows unverified** | WSL2 should work, but it has not been checked |
| **No external calendar sync** | no Google Calendar, no CalDAV |

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

| Part | What it does |
|---|---|
| **Android app** | microphone, speaker, camera, call screen. Never talks to Google directly |
| **Backend** (`server/web_maya.py`, Python/FastAPI) | authentication, memory, reminders, tools; relays audio to Gemini Live |
| **Gemini Live API** | produces the voice — native audio, not text-to-speech |
| **SQLite** | memory, reminders, accounts. **A separate database per user** |
| **WebSocket** `/ws/live_maya` | real-time two-way audio |
| **SSE** `/api/call_events` | server-initiated call alerts to the phone |

### Self-hosted: you are the only operator

> **MAYA is not a service.** This repository contains source code and an
> Android app — **no MAYA server runs here and there is nothing to sign
> up for**. You run the backend on your own machine with your own Gemini
> API key, and your phone connects to *your* server. The app asks for
> that address on first launch.
>
> This also means: **the MAYA project cannot see your conversations**,
> does not manage your server and has no access to your data. The
> conversation audio travels from your server to Google's Gemini Live
> (unavoidable — that is where the voice comes from), but never to
> anyone else's MAYA instance.
>
> **This is a public copy.** The project started as one person's
> personal assistant and was moved here with all personal content,
> keys, server addresses and conversation history removed. You install
> your own instance, with your own keys and your own characters.

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
git clone https://github.com/banaaniwabariik-rgb/maya-voice-assistant.git maya
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
| [docs/GITHUB_ESITLUS.md](docs/GITHUB_ESITLUS.md) | ready-made GitHub description, slogan and topics |
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

## Why contribute

**This is not an idea or an empty prototype.** The repository contains a
working system: a Python/FastAPI backend, an Android app, 10 characters,
FTS5 memory with Estonian morphology, authentication with a per-user
database, and a Gemini Live audio pipeline with interruption,
self-initiated speech and automatic recovery — plus **702 Python and 29
Kotlin tests** that pass.

At the same time, the [broken and unfinished
parts](#what-does-not-work-yet) are named honestly. Those are the best
places to start.

### Where to start — real tasks, not invented ones

| Difficulty | Task | Why it matters |
|---|---|---|
| 🟡 medium | **The reminder watcher is now multi-user** (`tootle_meeldetuletused`). Next step: the interval is a fixed 5 s and the database list is rebuilt every cycle — worth making smarter for large user counts | fine today, but it will not scale to hundreds of users |
| 🟡 medium | **Make `schedule_call` survive a restart** — the timer is currently in memory | MAYA's promise "I'll call you in 5 minutes" should hold across a restart too |
| 🟡 medium | **Android work**: battery-saver behaviour across OEMs, call-screen polish, audio routing (Bluetooth, earpiece, speaker) | the calling feature lives or dies on Android background restrictions |
| 🟡 medium | **Memory, reminders, calendar**: repeat rules (4 types today), calendar-view fixes, external sync | the calendar is currently a view over reminders, not a real calendar |
| 🟡 medium | **Estonian voice quality**: pronunciation of cases and numbers, abbreviation normalisation, a speech-recognition fallback | [TartuNLP's `tts_preprocess_et`](https://github.com/TartuNLP/tts_preprocess_et) and [estnltk](https://github.com/estnltk/estnltk) exist and are permissively licensed |
| 🟡 medium | **New characters** — temperament, voice, initiative level, memory scope. Guide: [docs/KARAKTERID.md](docs/KARAKTERID.md) (Estonian) | each character is a separate entry, and tests keep them from leaking into each other |
| 🔴 large | **An iOS client** — the considerations are already written up in [docs/IOS.md](docs/IOS.md) (Estonian) | only Android works today |
| 🔴 large | **HTTPS and deployment** — ready-made reverse-proxy recipes, systemd, a container | going to the public internet is handwork right now |

### What makes contributing here pleasant

- **The tests exist and they run.** `for f in tests/tests_*.py; do python3 "$f"; done` — 702 tests, 0 failures. You see immediately if something broke.
- **The code explains itself.** Comments say **WHY**, not what: in many places they record what was measured, what was broken and why the solution looks the way it does.
- **Estonian is the starting point**, not a translation. Characters, prompts, UI, logs and documentation are in Estonian.
- **The licence is clear**: Apache-2.0, no CLA required, **you keep the copyright to your own code**.
- **Honesty is the rule.** [CONTRIBUTING.md](CONTRIBUTING.md) states it outright: tests must not be weakened to make something pass, and a claim that "this is broken" needs evidence — a log line, a timestamp or a number.

> **Note on language:** the project's documentation and code comments are
> mostly in Estonian. You do not need to write Estonian to contribute
> code, but user-facing strings must be in Estonian — that is the point
> of the project.

### Estonian-first open source

There are few **working** Estonian-language voice assistants. If you
want Estonian to be a language you can genuinely talk to a machine in,
this is one of the places where that is actually being built — and
where one targeted pull request shows up immediately.

**Start here:** [CONTRIBUTING.md](CONTRIBUTING.md) ·
[docs/ARENDUS.md](docs/ARENDUS.md) (tests, conventions, open issues) ·
[docs/ARHITEKTUUR.md](docs/ARHITEKTUUR.md) (how the pieces fit together)

Contributions come in **under Apache-2.0** (§5) and no CLA is required.

**Important note:** this public project is independent and no MAYA
service runs here. No public contribution automatically reaches any
running installation — not the maintainer's and not anyone else's.
Every MAYA operator decides for themselves what to update.

---

## 📬 Contact

**Project maintainer: [banaaniwabariik@gmail.com](mailto:banaaniwabariik@gmail.com)**

Feel free to write — in English or Estonian:

| What about | Where |
|---|---|
| **Installation question** | open an [issue](https://github.com/banaaniwabariik-rgb/maya-voice-assistant/issues) — that way the answer helps the next person too |
| **Bug report** | open an [issue](https://github.com/banaaniwabariik-rgb/maya-voice-assistant/issues) |
| **Collaboration proposal, idea, question** | [banaaniwabariik@gmail.com](mailto:banaaniwabariik@gmail.com) |
| **I want to contribute but don't know where to start** | [banaaniwabariik@gmail.com](mailto:banaaniwabariik@gmail.com) or [CONTRIBUTING.md](CONTRIBUTING.md) |
| **🔒 Security vulnerability** | **do NOT open a public issue** — see [SECURITY.md](SECURITY.md) |

> **Please do not email** API keys, passwords, the contents of your
> `.env` file or conversation recordings. If you need to show an
> example, replace the values with placeholders.

This is a volunteer project — a reply may take days rather than hours.

**Note on language:** MAYA's interface, characters and most of the
documentation are in Estonian. You are welcome to write in English.
