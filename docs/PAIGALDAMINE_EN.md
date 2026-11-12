# Installing MAYA — complete guide

**This guide assumes you have never set up a server before.** Every
command is explained. If a step fails, section
[9. Troubleshooting](#9-troubleshooting) tells you what to do.

🇪🇪 Eesti keeles: **[PAIGALDAMINE.md](PAIGALDAMINE.md)**

> **MAYA's user interface and log messages are in Estonian.** The
> installation is documented in English, but the app itself will speak
> and write Estonian to you. There is currently no English UI.

> **Want it faster?** Use the guided installer: `./paigalda.sh`. This
> guide explains the same thing thoroughly and by hand.
>
> **Even easier?** Let an AI assistant walk you through it:
> [AI_ASSISTED_INSTALLATION.md](AI_ASSISTED_INSTALLATION.md).

---

## Contents

1. [What MAYA is and what it does](#1-what-maya-is-and-what-it-does)
2. [What you need](#2-what-you-need)
3. [Gemini API key and costs](#3-gemini-api-key-and-costs)
4. [Installing the backend](#4-installing-the-backend)
5. [Network, ports and remote access](#5-network-ports-and-remote-access)
6. [Security and accounts](#6-security-and-accounts)
7. [The Android app](#7-the-android-app)
8. [Your first voice conversation](#8-your-first-voice-conversation)
9. [Troubleshooting](#9-troubleshooting)
10. [Stopping, restarting, updating](#10-stopping-restarting-updating)

---

## 1. What MAYA is and what it does

MAYA is an **Estonian-language voice assistant** you talk to on your
phone like a person. It is not a tap-a-button question-and-answer
machine:

- it speaks with the rhythm of natural speech and you can interrupt it
  at any moment;
- after a pause it **starts talking on its own**, with per-character
  timing;
- if its sentence gets cut off, it **continues by itself** from the
  same place;
- it **calls your phone** when it has something to say;
- it remembers earlier conversations (long-term memory with
  Estonian-morphology search);
- it can see the camera and comment on what it sees;
- it can search the web, read pages and PDFs, read YouTube subtitles;
- 10 characters with different personalities, plus one whose
  instructions you write yourself.

### How the pieces fit together

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

| Part | What it does |
|---|---|
| **Android app** | microphone, speaker, camera, call screen. Never talks to Google directly. |
| **Backend** (`server/web_maya.py`) | authentication, memory, reminders, tools; relays audio to Gemini Live |
| **Gemini Live API** | produces the voice (native audio, not text-to-speech) |
| **SQLite** | memory, reminders, accounts. **A separate database per user** |
| **WebSocket** | real-time two-way audio (`/ws/live_maya`) |
| **SSE** | server-initiated call alerts to the phone (`/api/call_events`) |

### What is finished and what is not

| State | Meaning |
|---|---|
| ✅ **Works** | voice conversation, characters, memory, reminders, camera, authentication, per-user isolation, character-initiated calls |
| ⚠️ **You must configure it** | HTTPS (mandatory on the public internet), backups, firewall |
| ⚠️ **Limited** | singing is experimental; call alerts use SSE (not FCM), so they need the Android battery exemption |
| ❌ **Missing** | iOS app; a web interface without Android; any central service |
| ❓ **Unverified** | **no feature has been tested on a real phone** with this public build |

### MAYA is self-hosted

**There is no central MAYA service.** There is no server to sign up to.
GitHub carries the source code and an Android APK, nothing else.

Every user:
- runs **their own** backend on their own machine or server;
- uses **their own** Gemini API key and pays Google for their own usage;
- keeps **their own** data on their own machine.

The MAYA project cannot see your conversations, does not manage your
server, and has no access to your data.

---

## 2. What you need

### Hardware

| | Minimum | Recommended |
|---|---|---|
| **Server** (the machine MAYA runs on) | 2 GB RAM, 2 cores, 2 GB free disk | 4 GB RAM, a machine that stays on |
| **Network** | a stable internet connection | wired network on the server |
| **Phone** | Android 8.0 (API 26) | Android 10+ |

MAYA needs no GPU and no fast CPU — the heavy work happens at Google.
The server mostly relays audio.

**Will a Raspberry Pi do?** Probably (Pi 4, 4 GB), but **we have not
verified it**. Don't treat it as proven.

### Operating system

| | State |
|---|---|
| **Linux** (Debian, Ubuntu, Fedora) | ✅ supported |
| **macOS** | ✅ supported |
| **Windows** | ⚠️ **unverified**. Use [WSL2](https://learn.microsoft.com/en-us/windows/wsl/install) (Ubuntu) and follow the Linux instructions. The installer scripts are bash scripts. |

**A VPS works well** (Hetzner, DigitalOcean, Contabo, …) — the cheapest
tier is usually enough. If the server is on the public internet, read
sections [5](#5-network-ports-and-remote-access) and
[6](#6-security-and-accounts) carefully.

### Where to host the server

Three sensible options. MAYA behaves identically on all three.

| | Suits you if | Pros | Cons |
|---|---|---|---|
| **Your own computer at home** | you just want to try it | free, fastest to start | must stay on; remote access needs a VPN |
| **A small VPS** | you want a cheap always-on server | cheap, simple | you administer it yourself |
| **Google Cloud** (recommended if you choose a cloud) | you want an always-on server close to Estonia/Finland | nearest region, trial credit for new customers | **the free trial credit does NOT cover Gemini API** (see [section 3](#3-gemini-api-key-and-costs)) |

> **An important distinction to get straight right away:** the server
> and the Gemini API are **two separate bills**. The server is the
> computer MAYA runs on; Gemini is the voice. Neither covers the other.
> See [“What costs what”](#what-costs-what).

### Google Cloud: recommended configuration

If you pick Google Cloud, this is a sensible starting point:

| Setting | Recommendation | Why this one |
|---|---|---|
| **Service** | Compute Engine (a virtual machine) | an ordinary Linux server, where MAYA runs like on any other machine. Not Cloud Run or App Engine — MAYA holds **long-lived WebSocket and SSE connections** and writes to a local SQLite file, which would not survive in a serverless container |
| **Region** | **`europe-north1`** (Hamina, **Finland**) | a **geographically sensible nearby region** for Estonian users — Finland is just across the gulf and this is Google's closest Nordic region. Google also flags it as “low CO₂”. Zones: `europe-north1-a/-b/-c`. **We do not guarantee latency:** actual delay depends on your internet connection, ISP and route, not only on distance. If it matters to you, measure it yourself (`ping`, `mtr`) and compare with e.g. `europe-west1` |
| **Machine** | **`e2-standard-2`** — 2 vCPUs, 8 GB RAM | **headroom, not a requirement.** MAYA's minimum is 2 GB RAM; 8 GB means SQLite, the Python process, a reverse proxy and system updates won't start competing with each other even with several users. `e2` is Google's cheapest general-purpose series |
| **Operating system** | **Ubuntu 22.04 LTS** or **24.04 LTS** | LTS = long-term support, no frequent major upgrades. MAYA is **verified** on Linux and the installer scripts are bash scripts. Ubuntu's repositories carry Python 3.11+ |
| **Disk** | **30–50 GB SSD** (balanced) | the OS plus the Python environment takes ~3–5 GB. The rest is for **your data and backups**: memory facts, the conversation archive and logs grow slowly but continuously. The 10 GB default fills up, and resizing later is more hassle than choosing right now |

**Does it have to be exactly this?** No. MAYA also runs on an
`e2-small` (2 GB RAM) with a 20 GB disk. `e2-standard-2` is the
recommendation where you **don't have to think** about running out of
resources. To start cheaper, pick a smaller machine — in Google Cloud
you can change the machine type later (the instance must be stopped
while you do).

Official machine type and region lists:
- Machine types: https://cloud.google.com/compute/docs/machine-resource
- Regions and zones: https://cloud.google.com/compute/docs/regions-zones
- Pricing calculator: https://cloud.google.com/products/calculator

### The Google Cloud free trial

Google offers **new customers** trial credit:

- **$300 of credit, valid for 90 days** (Google's own wording: “$300 in
  Welcome credit to spend over 90 days”).
- Terms and activation: **https://cloud.google.com/free**

**How to activate it:**

1. Open https://cloud.google.com/free and click “Get started for free”.
2. Sign in with a Google account and fill in your details. **A payment
   card is required even for the trial** — Google uses it for identity
   verification, but does not charge you within the credit during the
   trial.
3. Once you accept, you get a billing account with the credit attached.
4. Google does **not** silently switch you to paid billing: after the
   trial you have to choose “Activate full account” yourself. If you
   don't, your resources are stopped.

> ### ⚠️ The most important thing about this credit
> **The $300 trial credit does NOT cover Gemini API usage.** Google
> states this outright in its own documentation: *“The $300 credit
> can't pay for Gemini API in AI Studio costs”*, and as of **March
> 2026** Gemini API costs are **explicitly excluded** from the trial
> credit programme.
>
> That means: the trial credit covers the **server** (Compute Engine,
> disk, network), but **the voice must be paid for separately**. Two
> separate bills, two separate places where cost accrues.
>
> Google has also published that for accounts starting **after 16
> November 2026** the credit does not apply to Gemini platform services
> at all. Because these terms change, **always check
> [cloud.google.com/free](https://cloud.google.com/free)** rather than
> relying on this guide.

**What the trial credit covers for MAYA:**

| | Covered by the $300 credit? |
|---|---|
| Compute Engine VM (`e2-standard-2`) | ✅ yes |
| Persistent disk (30–50 GB SSD) | ✅ yes |
| Network traffic | ✅ yes |
| Static IP address | ✅ yes |
| **Gemini API / AI Studio (MAYA's voice)** | ❌ **NO** |

> Google Cloud's **Always Free** tier includes one `e2-micro` instance
> per month — that is considerably smaller than `e2-standard-2` and
> does not replace this recommendation. `e2-standard-2` usage is drawn
> from the trial credit.

### Software

**Required:**

| What | Why | Where |
|---|---|---|
| **Python 3.11 or newer** | the backend is Python | https://www.python.org/downloads/ |
| **Python venv module** | to isolate dependencies | Debian/Ubuntu: `sudo apt install python3-venv` |
| **A Gemini API key** | the voice | [section 3](#3-gemini-api-key-and-costs) |

**Recommended:**

| What | Why | Where |
|---|---|---|
| **Git** | downloading and updating the project | https://git-scm.com/downloads/ |
| **curl** | the check commands in this guide | usually already installed |

**To build the Android app yourself** (optional — a prebuilt APK also
works):

| What | Where |
|---|---|
| **JDK 17** | https://adoptium.net/ |
| **Android SDK (API 34)** | [Android Studio](https://developer.android.com/studio) or `cmdline-tools` |

**Optional extra keys** (MAYA works without them):

| Key | What it adds |
|---|---|
| `GROQ_API_KEY` | text chat and Whisper transcription |
| `TAVILY_API_KEY` | web search |
| `GMAIL_USER` + `GMAIL_APP_PASSWORD` | reading email |

> **MAYA does not need Docker.** See [why not](#why-there-is-no-docker).

---

### What costs what

Four **separate** sources of cost. None of them covers another:

| Cost | Who you pay | What it depends on | Official pricing |
|---|---|---|---|
| **1. Server rental** (monthly) | your cloud provider (e.g. Google Cloud) or VPS host | machine type, disk size, region. Runs **all the time**, even when you are not talking to MAYA | [Compute Engine pricing](https://cloud.google.com/compute/vm-instance-pricing) · [calculator](https://cloud.google.com/products/calculator) |
| **2. Gemini API usage** | Google (AI Studio / Gemini API) | **conversation length** and token volume (audio in, audio out, camera frames). Accrues **only while you talk** | [Gemini pricing](https://aistudio.google.com/docs/pricing) |
| **3. Domain** (optional) | your domain registrar | the TLD (`.ee`, `.com`, …), usually billed yearly | your registrar's price list |
| **4. Backups** (optional) | your cloud provider | how much you keep and for how long | [GCP storage pricing](https://cloud.google.com/storage/pricing) |

**The minimum you need:** item 1 (a server, or your own computer =
free) plus item 2 (Gemini). A domain and backups are optional — you
only need a domain for the public internet and HTTPS
([option 3](#option-3--public-internet-domain--https)), and backups can
go to your own computer for free ([section 6.3](#63-backups)).

**This guide deliberately contains no price figures.** Prices, free
quotas and billing requirements are set by Google and by service
providers, and they change. Any number written here would go stale and
mislead you when planning costs. **Always check the official links
above.**

## 3. Gemini API key and costs

### What it is and why MAYA needs it

MAYA's voice is **not** generated on your computer. The audio comes
from Google's **Gemini Live API**, which produces native audio (not
text-to-speech — that is why MAYA sounds like a live person and can
interject).

An **API key** is a long secret string that tells Google who made the
request and who gets billed. Without it MAYA **will not speak**.

### Getting a key

1. Open **[Google AI Studio](https://aistudio.google.com/)** and sign
   in with a Google account.
2. Go to **[aistudio.google.com/apikey](https://aistudio.google.com/apikey)**.
3. Click **"Create API key"** and pick (or create) a Google Cloud
   project.
4. Copy the key. It usually starts with `AIza`.

Documentation: **https://ai.google.dev/gemini-api/docs**

### Can you get by on the free tier?

The Gemini API **does** have a free tier: limited access to certain
models, free input and output tokens, and use of AI Studio.

**But for MAYA's voice, expect to need the paid tier.** MAYA uses the
native-audio model **`gemini-2.5-flash-native-audio-preview-12-2025`**,
and Google's pricing page lists native-audio Live API models under the
**paid tier**. I checked this on the pricing page, but **check it
yourself too** — this is exactly the sort of thing that changes:
**https://aistudio.google.com/docs/pricing**

Documented free-tier limitations worth knowing:

| Limitation | What it means |
|---|---|
| **Content is used to improve Google's products** | on the free tier your content is also used as training material; on paid tiers this is explicitly excluded |
| Lower rate limits | fewer requests per minute/day |
| Some models and features are unavailable | including the **native-audio Live API** that MAYA needs |

**Practical advice:** try your key on the free tier first. If MAYA
answers in text but **no voice comes and the log shows an access or
quota error**, this is the likely reason — enable billing.

### Billing and the $5 minimum

**The bill goes to you.** The MAYA project does not process payments,
takes no share of your usage, and is not responsible for your costs.

To enable billing, Google asks for a **minimum prepayment**. Google's
own wording: *“Asked to prepay a minimum of \$5 to complete billing
setup”* and *“The minimum purchase is \$5”* (or the local-currency
equivalent where that applies).

What that $5 **is** and **is not**:

| | |
|---|---|
| ✅ **It IS** | **API credit** — a prepayment you then spend on requests |
| ❌ **It is NOT** | a monthly fee or subscription |
| ❌ **It is NOT** | an activation or sign-up fee |
| ⏳ **BUT** | **the credit does expire** — see below |

#### Prepaid credit expires, and the voice stops when it runs out

Two things worth knowing before you prepay:

**1. The credit expires.** Google's wording: *“Purchased credits expire
after 1 year. After expiration, credits are forfeited and can't be
retrieved”* — purchased credit expires **12 months after the purchase
date** and is forfeited after that. So there is no point prepaying more
than you can use within a year.

**2. When the balance reaches zero, the API stops.** Google's wording:
*“When your Prepay credit balance on the billing account hits \$0, all
API keys in all projects linked to that billing account will stop
working simultaneously”*. In practice:

| | |
|---|---|
| What happens | **all** API keys linked to that billing account stop working **at the same time** |
| What the API returns | `HTTP 402 Payment Required` |
| Does it fall back to the free tier? | **NO** — there is no automatic downgrade; the service simply stops |
| What that means for MAYA | **the voice simply stops.** MAYA will not speak until you add credit |
| How to recover | top up the credit in Google's billing view |

> **Recommendation:** set a budget alert (see
> [“Limiting spend”](#limiting-spend)) **before** the balance runs out,
> so the voice stopping doesn't surprise you mid-conversation.

> **$5 does NOT equal any fixed number of conversation minutes.** Cost
> depends on how long and how much you talk: **incoming audio, outgoing
> audio and camera frames are all billed as tokens**. A long
> conversation with the camera on costs many times more than a short
> question. Nobody — including this guide — can promise you “$5 gets
> you X minutes”. The only honest way to find out: have one short
> conversation and look at the actual cost in Google's console.

Official pages:
- Billing and the minimum: **https://ai.google.dev/gemini-api/docs/billing**
  (currently redirects to `aistudio.google.com/docs/billing`)
- Pricing: **https://ai.google.dev/gemini-api/docs/pricing**
  (currently redirects to `aistudio.google.com/docs/pricing`)
- AI Studio (key, usage, billing): **https://aistudio.google.com/**

> ⚠️ **The Google Cloud $300 trial credit does NOT cover the Gemini
> API.** If you took the Google Cloud trial for the server, the voice
> still has to be paid for separately — see
> [section 2](#the-google-cloud-free-trial).

**Prices, free quotas and billing requirements are set by Google and
can change.** This guide contains no price figures other than Google's
own documented $5 minimum. **Always check Google's own page.**

### Limiting spend

In the Google Cloud console you can set **budget alerts** and quota
limits:

- Budgets and alerts: https://console.cloud.google.com/billing/budgets
- Quotas: https://console.cloud.google.com/apis/api/generativelanguage.googleapis.com/quotas

**Advice for beginners:** set a budget alert *before* your first
conversation, so you get an email if spending passes an amount you
choose. The exact steps and available options live on Google's side and
may change — follow their documentation.

MAYA has a built-in **cost tracker** that prints an estimated session
cost to the server log. That is **MAYA's own estimate**, not Google's
invoice. Trust only the Google console for billing.

### Protecting the key

| Rule | Why |
|---|---|
| The key lives **only** in `.env` | that file is in `.gitignore` |
| `.env` permissions **600** | only your user can read it |
| The key is **never** in the Android APK | the phone only talks to your server |
| Never put the key in an issue, a PR or a screenshot | these get harvested automatically |
| If the key leaks: **revoke it immediately** in AI Studio and create a new one | a leaked key stays leaked even after deletion |

Anyone who can reach your server can use your key. That is why section
[6](#6-security-and-accounts) matters.

---

## 4. Installing the backend

### 4.0 Terminal basics

Every command runs in a **terminal** (macOS: Terminal; Linux:
Terminal; Windows: a WSL2 window).

| Command | What it does |
|---|---|
| `pwd` | shows which folder you are in |
| `ls` | lists the files in it |
| `cd maya` | enters the folder `maya` |
| `cd ..` | goes up one folder |
| Ctrl+C | stops the program currently running |

Run commands **one at a time**: copy the line, paste it, press Enter,
wait for it to finish. Don't copy the `$` — it just marks the prompt.

### 4.0b Creating the server in Google Cloud (only if you have no server yet)

**Skip this step** if MAYA will run on your own computer or you already
have a VPS — continue from 4.1.

The reasoning behind the configuration is in
[section 2](#google-cloud-recommended-configuration). This is just the
steps.

**1. Create a project.** Open [console.cloud.google.com](https://console.cloud.google.com/)
→ the project picker at the top → **“New project”** → give it a name
(e.g. `maya`) → **“Create”**. A project is simply a folder your
resources and bill live in.

**2. Enable billing.** **Billing** in the left menu. You cannot create a
VM without a billing account, not even with trial credit. Activating the
trial: [section 2](#the-google-cloud-free-trial).

**3. Enable the Compute Engine API.** Search for `Compute Engine` at the
top → **“Compute Engine API”** → **“Enable”**. The first time takes a
couple of minutes.

**4. Create the VM.** **Compute Engine → VM instances → “Create
instance”**. Fill in:

| Field in the console | What to choose |
|---|---|
| **Name** | e.g. `maya-server` |
| **Region** | **`europe-north1 (Finland)`** |
| **Zone** | any (`europe-north1-b` is a fine default) |
| **Machine configuration** | **General purpose → E2** |
| **Machine type** | **`e2-standard-2` (2 vCPU, 8 GB memory)** |
| **Boot disk → Change** | Operating system: **Ubuntu**, Version: **Ubuntu 22.04 LTS** or **24.04 LTS** (x86/64) |
| **Boot disk → Size** | **30–50 GB**, type **Balanced persistent disk (SSD)** |
| **Firewall** | **do NOT tick** “Allow HTTP traffic” or “Allow HTTPS traffic” — you only need those once you set up a reverse proxy ([option 3](#option-3--public-internet-domain--https)) |

Click **“Create”**. The machine boots in about a minute.

**5. Connect with browser SSH.** In the VM list, your machine's row has
an **“SSH”** button → **“Open in browser window”**. A terminal opens
right in the browser — **you do not need to create SSH keys or use the
`ssh` command**. Google manages the keys for you.

> **Why browser SSH is better for a beginner:** you don't have to open
> port 22 to the public internet or manage private keys. See
> [section 6.2 → SSH](#62-what-you-must-configure-yourself).

**6. Prepare the machine.** In the browser terminal:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip git curl
```

**7. Continue with the normal installation.** You are now on a Linux
machine and everything below applies exactly as written: step
[4.2](#42-download-maya) (download MAYA) and
[4.3](#43-guided-installation-easiest) (`./paigalda.sh`).

> **Note:** in Google Cloud **`ufw` alone is not enough.** On top of the
> server's own firewall there is a **VPC firewall** at the cloud level.
> If your phone needs to reach the server, the rule must be added in
> **both** — see [section 5.3](#53-three-deployment-options).

### 4.1 Install Python

Check whether you already have it:

```bash
python3 --version
```

If it says `Python 3.11.x` or newer, you are set. If not:

```bash
# macOS (with Homebrew: https://brew.sh/)
brew install python@3.13

# Debian / Ubuntu
sudo apt update
sudo apt install python3 python3-venv python3-pip

# Fedora
sudo dnf install python3 python3-pip
```

### 4.2 Download MAYA

**Option A — with Git (recommended, easy to update):**

```bash
git clone https://github.com/banaaniwabariik-rgb/maya-voice-assistant.git maya
cd maya
```

**Option B — as a ZIP (no Git needed):**

Download the ZIP from the repository, unpack it, and enter the folder.

> A ZIP installation **cannot** be updated with `./uuenda.sh` — you have
> to download a new ZIP and copy your `.env` and database across.

### 4.3 Guided installation (easiest)

```bash
./paigalda.sh
```

This script:

1. checks the Python version, the `venv` module, disk space and
   internet access, and **tells you exactly what is missing**;
2. warns you if this folder already has an installation (**it never
   overwrites**);
3. creates the Python environment `.venv`;
4. installs the dependencies from `server/requirements.txt`;
5. creates `.env` and asks for your Gemini API key **without echoing it
   to the screen**, then sets the file permissions to 600;
6. asks how your phone will reach the server and sets `MAYA_HOST`;
7. creates an empty database.

The script's prompts are in Estonian. If you prefer doing everything by
hand, continue from 4.4; otherwise jump to 4.8.

### 4.4 Create the Python environment

```bash
python3 -m venv .venv
```

**What it does:** creates a `.venv` folder that holds only MAYA's
dependencies, so MAYA does not interfere with other Python programs on
your system.

### 4.5 Install dependencies

```bash
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r server/requirements.txt
```

**What it does:** downloads the libraries listed in
`server/requirements.txt` (FastAPI, uvicorn, google-genai and others)
from PyPI. Takes 1–3 minutes.

> These commands use `./.venv/bin/pip` so you never have to remember to
> "activate" anything. All later commands follow the same pattern.

### 4.6 Create the configuration file and add the API key

```bash
cp .env.example .env
chmod 600 .env
```

**What it does:** `.env.example` is a template **with no keys in it**.
`cp` turns it into your real configuration file `.env`. `chmod 600`
makes it readable only by you.

Open `.env` in any text editor (`nano .env`, `vim .env`, …) and fill in
at least:

```
GEMINI_API_KEY=your_key_here
MAYA_USER_NAME=YourName
```

`MAYA_USER_NAME` is the name the characters will call you by.

Check that the configuration is being read (**real values are never
printed**):

```bash
./.venv/bin/python server/config.py
```

### 4.7 Create the database

```bash
./.venv/bin/python server/init_db.py
```

**What it does:** creates an **empty** database with the correct schema
— reminders, shopping list, journal, conversation archive, memory
facts, FTS5 search indexes and the user registry. No personal data is
shipped with the project.

By default the database lands in **`server/data/`**:

| File | Contents |
|---|---|
| `server/data/reminders.db` | reminders, memory, conversation archive |
| `server/data/users.db` | accounts and tokens (belongs to no single user) |

Use `MAYA_DATA_DIR` to put it somewhere else.

A read-only check:

```bash
./.venv/bin/python server/init_db.py --check
```

### 4.8 Start MAYA

```bash
./kaivita.sh
```

This verifies the prerequisites, creates the database if missing, warns
about the macOS firewall, **prints the address to enter on your phone**,
and starts the server.

To only print the address (without starting):

```bash
./kaivita.sh --ip
```

A successful start looks like this:

```
--> [MÄLUMOOTOR]: SQLite journal_mode=wal
--> [MAYA]: kuulan aadressil 0.0.0.0:8000
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

> The line `GROQ_API_KEY puudub` ("missing") is **expected** if you did
> not supply that optional key. The voice works regardless.

The server runs as long as that window stays open. Stop it with Ctrl+C
or, from another window, `./peata.sh`.

### 4.9 Check that everything is fine

```bash
./tervisekontroll.sh
```

It walks through five blocks — installation, configuration, database,
whether the server responds, network addresses — and marks each line ✓,
! or ✗. **It never prints your key's value**, only whether its shape
looks right.

A manual check:

```bash
curl http://127.0.0.1:8000/api/auth/status
```

Expected response (JSON):

```json
{"seadistatud":false,"registreerimine_lubatud":true,"kutsekood_noutud":false}
```

`"seadistatud":false` means "no accounts yet" — correct for a fresh
installation.

The API documentation is browsable at `http://127.0.0.1:8000/docs`.

### 4.10 Create the first account

**The first account becomes the admin.** The easiest way is in the
Android app ("Loo uus konto" = create new account), but the command line
works too:

```bash
curl -X POST http://127.0.0.1:8000/api/auth/register \
     -H 'Content-Type: application/json' \
     -d '{"username":"your_name","password":"at_least_10_characters"}'
```

The response contains a `token`. Verify it works:

```bash
TOKEN=<paste the token here>
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/auth/me
```

Requirements: username 3–32 characters (letters, digits, `_ . -`),
password **at least 10 characters**.

### Why there is no Docker

We evaluated Docker Compose and decided **against** adding it:

| | |
|---|---|
| **Python installation** (the current choice) | one prerequisite (Python 3.11+), usually already present on Linux and macOS. The database is an ordinary file, logs go straight to the screen, troubleshooting is transparent. |
| **Docker** | adds a **large new prerequisite** for a beginner (Docker Desktop / Engine), complicates file permissions and SQLite persistence, and hides errors inside a container. It buys nothing real here: MAYA has no database server, no message queue and no multiple services to orchestrate. |

MAYA is **one Python process and one SQLite file**. Docker would solve a
problem this project does not have. You are of course free to
containerise it yourself — but we do not ship an official `Dockerfile`
that we do not test.

---

## 5. Network, ports and remote access

**This is the most important section.** Most "it doesn't work" cases
are network problems, not MAYA bugs.

### 5.1 Ports — what is actually needed

| Port | What is there | Who must reach it |
|---|---|---|
| **8000** | all of MAYA: `/api/...`, SSE (`/api/call_events`), WebSocket (`/ws/live_maya`) | **the phone** |

**That's it. One port.** Verified facts:

- the HTTP API, SSE and the WebSocket **all go over the same port** —
  a WebSocket is just an upgraded HTTP connection;
- the port is configurable with `MAYA_PORT`;
- **you never need to open SSH or any other port for MAYA.**

**So what is port 22 (SSH)?** SSH is how **you** get into the server to
run commands. MAYA itself never uses it and your phone never touches
it. Therefore:

| | |
|---|---|
| In Google Cloud | use **browser SSH** ([step 4.0b](#40b-creating-the-server-in-google-cloud-only-if-you-have-no-server-yet)) — port 22 need not be open to the public internet |
| On your own VPS | restrict SSH to **your own IP** or use a VPN; allow key-based login and disable passwords |
| At home | you don't need SSH at all — you're sitting at the machine |

> **Don't open port 22 to the whole internet.** SSH exposed to the
> public internet receives constant automated login attempts. That is
> not a MAYA problem but the server's own — except that your Gemini key
> lives on that same machine.

> **Ports 8001 and 8002** appear in the code for historical reasons
> (the original installation ran separate helper services there).
> **Those services do not exist in public MAYA** and you never need to
> open or start them. The Android client derives those addresses, but
> when nothing answers, the corresponding optional feature simply stays
> quiet.

### 5.2 The listening address (`MAYA_HOST`)

```
MAYA_HOST=127.0.0.1   ->  the server listens ONLY on this machine.
                          The phone CANNOT reach it. Most secure.

MAYA_HOST=0.0.0.0     ->  the server listens on all interfaces.
                          A phone on the same network can reach it.
```

Set this in `.env`. **The variable really takes effect** — the server
reads it at startup and prints where it is listening.

### 5.3 Three deployment options

#### Option 1 — Home network (simplest start)

Server and phone on the same Wi-Fi.

```
.env:  MAYA_HOST=0.0.0.0
```

In the app you enter the server's local network address. To find it:

```bash
./kaivita.sh --ip
```

| Pros | Cons |
|---|---|
| no domain, certificate or router setup | works **at home only** |
| no port visible from the internet | traffic is **unencrypted HTTP** |
| | the router-assigned IP can change |

**Firewall.** The server must allow incoming connections on port 8000:

```bash
# Ubuntu / Debian (ufw) – from the local network only, not the whole internet
sudo ufw allow from 192.168.0.0/16 to any port 8000 proto tcp

# Fedora (firewalld)
sudo firewall-cmd --add-port=8000/tcp --permanent
sudo firewall-cmd --reload
```

macOS asks for permission on first start — answer **"Allow"**. If it got
denied: `System Settings → Network → Firewall → Options…` and add
`<project-folder>/.venv/bin/python3`.

**In Google Cloud the firewall is in TWO places.** This is the most
common place a beginner gets stuck: the `ufw` rule is there on the
server, but the connection still doesn't get through.

```
phone  →  [1] VPC firewall (in Google's cloud)  →  [2] ufw (on the server)  →  MAYA
```

Adding the VPC rule in the console: **VPC network → Firewall → “Create
firewall rule”**:

| Field | Value |
|---|---|
| Name | `maya-8000` |
| Direction | **Ingress** |
| Targets | **All instances in the network** (or the tag you gave the VM) |
| Source IPv4 ranges | **your own public IP** `/32` — not `0.0.0.0/0` |
| Protocols and ports | **TCP**, port **`8000`** |

Find your public IP with `curl -s ifconfig.me` or in a browser.

> **`0.0.0.0/0` means “the whole internet”.** Don't use it on port
> 8000, because then your MAYA is speaking unencrypted HTTP to the
> public internet. If you want remote access there are two correct
> routes: [Tailscale](#option-2--private-network--vpn-recommended)
> (simpler, opens no ports) or
> [a reverse proxy with HTTPS](#option-3--public-internet-domain--https).

> `192.168.0.0/16` is an example of a typical home network. Yours may
> differ (e.g. `10.0.0.0/8`). Check your own address with
> `./kaivita.sh --ip`.

**The single most useful check:** open
`http://<server-ip>:8000/api/auth/status` **in your phone's browser**.
If JSON appears, the network is fine. If it doesn't, installing the app
won't help either.

#### Option 2 — Private network / VPN (**recommended**)

Tailscale (or WireGuard, ZeroTier) puts your server and phone on their
own encrypted network. **No port needs opening and the router stays
untouched.**

1. Install Tailscale **on both the server and the phone**:
   **https://tailscale.com/kb/**
2. Sign in to the same account on both.
3. Keep `MAYA_HOST=0.0.0.0` on the server.
4. Get the Tailscale address: `./kaivita.sh --ip` (shown on its own
   line).
5. Enter that address in the MAYA app.

| Pros | Cons |
|---|---|
| **works away from home** (mobile data) | depends on a third-party service |
| traffic is encrypted at the VPN layer | the free tier is limited to personal use |
| **no port exposed to the public internet** | |
| the address does not change | |

For most users this is the best option: remote access without going
onto the public internet.

#### Option 3 — Public internet (domain + HTTPS)

Only needed if you want access without a VPN, or want to share MAYA
with several people over the internet.

> **Do not expose port 8000 directly.** Without HTTPS your speech,
> memory and authentication token travel in clear text. On the public
> internet MAYA always sits **behind a reverse proxy**.

What you need:

1. A **domain** pointing at your server's public IP (e.g.
   `maya.example.com` — that is an example, use your own).
2. A **reverse proxy** that terminates HTTPS and forwards to
   `127.0.0.1:8000`.
3. A **certificate** — free from
   [Let's Encrypt](https://letsencrypt.org/getting-started/).
4. `.env`: **`MAYA_HOST=127.0.0.1`** — so the backend listens only
   inside the server and only the proxy can reach it.
5. `.env`: **`MAYA_ALLOW_REGISTRATION=0`** after creating your own
   accounts (or `MAYA_INVITE_CODE=<long random word>`).

**Recommended reverse proxy: [Caddy](https://caddyserver.com/docs/)** —
it obtains and renews the certificate itself and handles WebSockets and
SSE without extra configuration. The entire `Caddyfile`:

```caddyfile
maya.example.com {
    reverse_proxy 127.0.0.1:8000 {
        flush_interval -1
    }
}
```

`flush_interval -1` disables buffering — **required for SSE**, otherwise
call alerts never reach the phone.

If you prefer [nginx](https://nginx.org/en/docs/):

```nginx
server {
    listen 443 ssl http2;
    server_name maya.example.com;

    ssl_certificate     /etc/letsencrypt/live/maya.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/maya.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;

        # REQUIRED for the WebSocket (/ws/live_maya):
        proxy_set_header Upgrade    $http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # REQUIRED for SSE (/api/call_events):
        proxy_buffering off;
        proxy_cache     off;

        # Voice sessions are long-lived – don't cut them off:
        proxy_read_timeout  3600s;
        proxy_send_timeout  3600s;
    }
}
```

In the app you then enter `https://maya.example.com` (no port). MAYA
derives the **`wss://`** WebSocket address from it automatically.

**Router port forwarding.** If the server is at home, the router must
forward incoming connections to it. Example (**all numbers are
placeholders, yours will differ**):

```
External port 443  ->  server's LAN IP, port 443   (the reverse proxy)
```

Note: **the router's external port and the backend's internal port need
not be the same.** Typically 443 is exposed and MAYA listens on 8000
internally, with the reverse proxy between them. **Port 8000 is never
forwarded directly.**

**On a cloud server (e.g. Google Cloud) there is no router** — instead
of port forwarding there is the VPC firewall. For the public internet:

| Step | What to do |
|---|---|
| **1. Static IP** | VPC network → IP addresses → reserve a **static external IP** for the VM. The default ephemeral IP can change on restart, after which your domain no longer points at the server |
| **2. VPC firewall** | allow **only** `tcp:443` (and `tcp:80`, which Let's Encrypt needs for certificate validation) from `0.0.0.0/0`. **Do NOT open port 8000** |
| **3. DNS** | at your domain registrar create an **`A` record** pointing your domain (e.g. `maya.example.com`) at that static IP. Propagation usually takes minutes to hours |
| **4. `.env`** | **`MAYA_HOST=127.0.0.1`** — so MAYA listens only inside the server and only the reverse proxy can reach it |
| **5. Reverse proxy** | install Caddy (below) — it obtains the certificate itself |

**What is DNS and why do you need it?** It is easier to type
`https://maya.example.com` on a phone than an IP address, and **an
HTTPS certificate is issued for a domain, not a bare IP**. That is why
public-internet access always goes through a domain.

**What are HTTPS and WSS?** `https://` is encrypted HTTP and `wss://`
is an encrypted WebSocket. Both travel over **the same port 443**. MAYA
derives `wss://` from your `https://` address automatically — you don't
configure it separately. The reverse proxy only has to pass the
`Upgrade` header through (the examples below do).

### 5.4 Summary

| | Home network | VPN (Tailscale) | Public internet |
|---|---|---|---|
| Remote access | no | **yes** | yes |
| Port open to the internet | no | **no** | 443 (proxy) |
| HTTPS | no (HTTP) | VPN encrypts | **mandatory** |
| Router setup | no | **no** | yes |
| Domain | no | no | yes |
| Complexity | low | low | high |
| `MAYA_HOST` | `0.0.0.0` | `0.0.0.0` | `127.0.0.1` |

---

## 6. Security and accounts

### 6.1 What is already built in

| Protection | How it works |
|---|---|
| **Authentication everywhere** | every `/api` endpoint, the SSE stream and the Gemini Live WebSocket require a valid token |
| **Passwords** | salted `scrypt` hashes; passwords are never stored or logged in plain text |
| **Tokens** | only a SHA-256 hash is stored; default lifetime 30 days (`MAYA_TOKEN_TTL_S`) |
| **Single-use WebSocket ticket** | the long-lived token never ends up in a URL: the WS handshake uses a separate ticket valid for 60 seconds and **for one connection only** |
| **Per-user isolation** | each user's memory, reminders, conversations and settings live in a **separate database** — one user cannot see another's data or call them |
| **Rate limiting** | on login and the API (`MAYA_LOGIN_RATE_LIMIT`, `MAYA_RATE_LIMIT`) |
| **First account = admin** | everyone else is a regular user |

### 6.2 What you must configure yourself

| Item | What to do |
|---|---|
| **HTTPS** | mandatory on the public internet — reverse proxy, see [5.3 option 3](#option-3--public-internet-domain--https) |
| **Closing registration** | `MAYA_ALLOW_REGISTRATION=0` or `MAYA_INVITE_CODE=<long random word>` after creating your accounts |
| **Database backups** | MAYA does not back itself up (see below) |
| **Database encryption** | SQLite is **plain text**; use an encrypted disk if that matters |
| **API key protection** | `.env` permissions 600, restrict access to the server |
| **The server itself** | system updates, firewall, restricted SSH (see below) |

#### SSH access must be restricted

SSH is your own administrative access to the server. MAYA does not need
it, but **your Gemini key and all user data live on that same
machine** — so protecting SSH is part of protecting MAYA.

| Situation | What to do |
|---|---|
| **Google Cloud** | use **browser SSH** ([step 4.0b](#40b-creating-the-server-in-google-cloud-only-if-you-have-no-server-yet)). Port 22 need not be open to the public internet and Google manages the keys |
| **Your own VPS** | restrict SSH to **your own IP** in the firewall; allow **key-based** login only and **disable passwords** (`PasswordAuthentication no` in `/etc/ssh/sshd_config`, then `sudo systemctl restart ssh`) |
| **Home server** | no need to expose SSH at all |

> **Don't open port 22 to the whole internet** (`0.0.0.0/0`). SSH on
> the public internet receives constant automated login attempts.

#### The public internet requires HTTPS/WSS

This is not a suggestion but a **requirement**. Without HTTPS the
following travel in clear text:

- your **speech audio** (`ws://` instead of `wss://`),
- your **authentication token** (whoever captures it gets into your
  MAYA),
- your **memory facts** and reminder contents.

The MAYA backend **does not speak HTTPS itself** — the encryption is
done by the reverse proxy. Setup:
[5.3 option 3](#option-3--public-internet-domain--https). Until HTTPS
is in place, use your home network or
[a VPN](#option-2--private-network--vpn-recommended).

### 6.3 Backups

All your content is in two files. Stop the server and copy them:

```bash
./peata.sh
cp -r server/data ~/maya-backup-$(date +%Y%m%d)
./kaivita.sh
```

To restore: copy `server/data` back (with the server stopped).

> Copy with the server **stopped**. Copying a live SQLite file can
> produce a truncated copy.

### 6.4 Limits of the rate limiting

Rate limiting is **per process** and kept in memory. That means: with
multiple workers the limit multiplies, and restarting the server resets
the counters. It protects against casual brute force, **not** against a
determined distributed attack.

### 6.5 What is sent to Google

Gemini Live is a **cloud service**. During a voice conversation the
following is sent to Google:

- your **speech audio** (in real time);
- **camera frames**, if the camera is on;
- the **character instructions** and conversation context;
- the **memory facts** included in that conversation;
- text messages, if you use the text path.

MAYA **cannot avoid this** — it is what Gemini Live is. Google's terms
and privacy policy apply. If a topic must not reach the cloud, **do not
discuss it with MAYA.**

What is **not** sent: your password, your tokens, or whole database
files.

---

## 7. The Android app

### 7.1 Where to get the APK

| Option | How |
|---|---|
| **Build it yourself** | `cd android && ./gradlew assembleDebug` → `android/app/build/outputs/apk/debug/app-debug.apk` |
| **Prebuilt file** | if a release has been published, the APK is on the repository's **Releases** page. Always verify the SHA-256 sum. |

**The APK contains no server address and no key.** The same file works
with any MAYA installation — you enter the address in the app. The app
is **not** tied to any developer's server and never contacts anything
other than your own backend.

> **The original works; this build is unverified.** MAYA has run on a
> OnePlus 6 for several months, and the demo video in the README comes
> from that phone. This **public copy's** APK has been built and
> inspected byte by byte, but **this particular build has not been
> tested on a physical device**. Don't treat it as proven.

### 7.2 Installation

```bash
# On the phone: Settings → About phone → tap "Build number" 7×
#               → back → Developer options → USB debugging ON
adb install -r app-debug.apk
```

Without a computer: copy the APK to the phone, open it in a file
manager and allow "install from unknown sources".

If you get `INSTALL_FAILED_UPDATE_INCOMPATIBLE`, a differently-signed
MAYA is already installed: `adb uninstall com.maya.live`, then install
again. **That only deletes the phone's local data — your account and
memory live on the server.**

### 7.3 Permissions

| Permission | What for | Required? |
|---|---|---|
| Microphone (`RECORD_AUDIO`) | voice conversation | **yes** |
| Camera (`CAMERA`) | MAYA sees the camera | only for camera use |
| Notifications (`POST_NOTIFICATIONS`) | incoming calls | yes, if you want MAYA to call |
| Gallery (`READ_MEDIA_IMAGES`) | showing a picture | no |
| Foreground service (`FOREGROUND_SERVICE_MICROPHONE`) | background call watcher | automatic |
| Full-screen intent (`USE_FULL_SCREEN_INTENT`) | call screen over the lock screen | automatic |

**The battery exemption is MANDATORY** for MAYA to be able to call you:

```
Settings → Apps → MAYA → Battery → Unrestricted
```

Xiaomi/Redmi, Huawei, OnePlus and Samsung also need "Autostart" and
"Lock app" settings — see [ANDROID.md](ANDROID.md) (Estonian).

### 7.4 The server address

On first launch MAYA shows a **server setup screen**. Enter your
backend's address, for example:

```
http://192.168.1.50:8000      (home Wi-Fi – use YOUR IP)
http://100.64.0.5:8000        (Tailscale – use YOUR IP)
https://maya.example.com      (your domain, HTTPS, no port)
```

**All three are examples.** Find your own address with
`./kaivita.sh --ip`.

Short forms work: `192.168.1.50` becomes `http://192.168.1.50:8000`
(MAYA's default port is appended for IP addresses and `localhost`, but
not for named hosts — those sit behind a proxy on 443).

Press **"Testi ühendust"** (test connection). The screen says exactly
what happened: whether the server answered, whether it is a MAYA
backend, whether accounts exist. If the test fails, **do not save** —
fix the network or the address first.

You can change the address later: settings → **"Minu MAYA server"**, or
"Muuda serveri aadressi" on the login screen.

### 7.5 Creating an account

After saving the server you get the login screen. Press **"Loo uus
konto"** (create new account) — the first account becomes the admin.
Password at least 10 characters.

The token is stored in Android `SharedPreferences` (the app's private
storage), **not** in the web layer's `localStorage` — that way the
background call watcher can use it too.

---

## 8. Your first voice conversation

Work through this list in order. Each row assumes the previous one
worked.

| # | Check | How | Expected |
|---|---|---|---|
| 1 | The server is running | `./tervisekontroll.sh` | "Server vastab aadressil…" |
| 2 | The API key is set | same command | "GEMINI_API_KEY on seatud (kuju sobib)" |
| 3 | The server is visible on the network | **in the phone's browser**: `http://<server-ip>:8000/api/auth/status` | JSON appears |
| 4 | The app connects | "Testi ühendust" on the setup screen | "✓ MAYA server vastas" |
| 5 | The account works | "Loo uus konto" | the overlay disappears |
| 6 | Microphone | press the call button | Android asks for permission → grant it |
| 7 | **The voice works** | say something | MAYA answers out loud |
| 8 | The Gemini key is genuinely valid | the server log | `[LIVE WS]: Klient ühendatud` and **no** auth error |
| 9 | Interruption | talk over MAYA | it goes quiet immediately |
| 10 | Self-initiated speech | stay silent 5–15 s | MAYA starts talking |

If row 7 fails, look at the **server log** — the reason is printed there.

---

## 9. Troubleshooting

### The server won't start

| Symptom | Cause and fix |
|---|---|
| `ModuleNotFoundError: No module named 'fastapi'` | dependencies not installed, or the wrong Python. Run `./.venv/bin/pip install -r server/requirements.txt` |
| `RuntimeError: Form data requires "python-multipart"` | same — reinstall the dependencies |
| `GEMINI_API_KEY on seadistamata` | `.env` missing or in the wrong folder. Check with `./.venv/bin/python server/config.py` |
| `Address already in use` | port 8000 is taken. Stop the old server (`./peata.sh`) or change `MAYA_PORT` |
| `NameError` / `SyntaxError` | you have an old version. Run `./uuenda.sh` |
| `no such table: reminders` at startup | the database was never created: `./.venv/bin/python server/init_db.py` |

### The phone cannot reach the server

Check **in this order**:

1. **Is the server running at all?** `./tervisekontroll.sh`
2. **Is it listening on the right interface?** With
   `MAYA_HOST=127.0.0.1` the phone **cannot** reach it. Set `0.0.0.0`.
3. **Is the phone on the same network?** A home IP will not work over
   mobile data. Turn on Wi-Fi or use a VPN.
4. **Does the phone's browser reach it?** Open
   `http://<server-ip>:8000/api/auth/status`. If the browser can't, the
   app can't either — the problem is the network, not MAYA.
5. **Firewall.** See [5.3](#option-1--home-network-simplest-start).
6. **Router "client isolation" / "AP isolation"** (common on guest
   networks) blocks device-to-device traffic. Turn it off or use the
   main network.

| Error in the app | Meaning |
|---|---|
| "Ühendust ei saadud" | server not running, wrong port, or firewall |
| "Serveri nime ei leitud" | typo in the hostname — try the IP address |
| "Server vastas, aga see ei ole MAYA backend" | the address points at some other service — check the port |
| "Server ei vastanud 8 sekundi jooksul" | wrong network or firewall |
| "HTTPS/TLS viga" | a self-signed certificate will not work — use Let's Encrypt |

### HTTP versus HTTPS

| Situation | What to enter in the app |
|---|---|
| Home network / VPN | `http://...:8000` |
| Behind a reverse proxy | `https://domain` (**no port**) |

**Don't enter an `https://` address without a reverse proxy** — the
backend does not speak HTTPS itself and the connection will fail.
Conversely, with a proxy in place don't use `http://`, or the token
travels in clear text.

### The WebSocket won't connect (everything else works, no voice)

| Cause | Fix |
|---|---|
| The reverse proxy doesn't forward the `Upgrade` header | add nginx's `proxy_set_header Upgrade/Connection` (see 5.3) |
| Wrong scheme | `https://` must yield `wss://` — MAYA derives this; make sure the address starts with `https` |
| Token expired | log out and back in |
| The server closes immediately with code **1008** | authentication failed — the ticket or token never arrived |
| The server closes with code **1007** | Gemini rejected the session — check the server log |

### SSE drops (MAYA never calls)

| Cause | Fix |
|---|---|
| The reverse proxy buffers | Caddy: `flush_interval -1`; nginx: `proxy_buffering off` |
| Proxy timeout | raise `proxy_read_timeout` (e.g. 3600s) |
| Android battery saver killed the background service | grant the battery exemption (see 7.3) |
| The phone is not logged in | the log says "Token puudub – ootan sisselogimist" |

### Authentication errors

| Message | Meaning |
|---|---|
| `401 Autentimine nurjus` | token missing or expired — log in again |
| `403` | the account is not an admin but the endpoint requires it |
| `429 Liiga palju päringuid` | rate limit — wait a minute or raise `MAYA_RATE_LIMIT` |
| "Sisselogimine nurjus" | wrong password, or the server isn't running |
| The login screen appears every time | the token isn't being saved — make sure you're using the APK, not a browser |

### Gemini API errors

| Symptom | Cause |
|---|---|
| No voice at all, auth error in the log | wrong or revoked API key |
| `429` / quota error from Google | quota exhausted or billing missing — check [AI Studio](https://aistudio.google.com/) |
| The session closes immediately with code 1007 | the model or configuration doesn't fit — see [GEMINI_LIVE.md](GEMINI_LIVE.md) (Estonian) |
| "The bill is higher than I expected" | the Live API is billed by conversation time. Set a budget alert (see [3](#limiting-spend)) |

**Billing problems are resolved by Google, not by MAYA.** If the key
doesn't work, check in AI Studio whether the project has billing
enabled and the Live API allowed.

### Microphone and Android

| Symptom | Cause |
|---|---|
| Permission is never requested | grant it manually: Settings → Apps → MAYA → Permissions → Microphone |
| The microphone goes silent in the background | `FOREGROUND_SERVICE_MICROPHONE` missing — use the official APK |
| MAYA hears itself | echo gate — see `JITTER_BUFFER_S` and the RMS threshold in `index.html` |
| MAYA never calls when the screen is off | **the battery exemption is missing** (see 7.3) |

### Server restart and recovery

The app reconnects by itself if the server restarts in between — SSE
retries every few seconds. You don't need to do anything.

If the server crashed, look at the last lines before the crash. The log
goes to the screen; to keep it, redirect it to a file:

```bash
./kaivita.sh 2>&1 | tee ~/maya.log
```

---

## 10. Stopping, restarting, updating

```bash
./peata.sh            # stop the server gracefully
./peata.sh --joud     # force stop if it didn't stop
./kaivita.sh          # start
./tervisekontroll.sh  # check that everything is fine
./uuenda.sh           # pull a new version + update dependencies and schema
```

`./peata.sh` finds the server via the `.maya.pid` file and stops **only
this project folder's** process. It never touches other programs.

### Updating

`./uuenda.sh` runs in order: checks whether the server is running (and
offers to stop it) → **refuses if you have uncommitted changes** →
`git pull` → dependencies → database schema. **Your `.env` and your
data are never touched.**

> If the Android side changed, the APK must be rebuilt — a server
> update alone does not change the phone.

### Starting automatically (Linux, optional)

```ini
# /etc/systemd/system/maya.service
[Unit]
Description=MAYA Voice Agent
After=network.target

[Service]
Type=simple
User=maya
WorkingDirectory=/opt/maya/server
EnvironmentFile=/opt/maya/.env
ExecStart=/opt/maya/.venv/bin/python /opt/maya/server/web_maya.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now maya.service
journalctl -u maya.service -f     # view the log
```

Replace `/opt/maya` with your own installation folder.

---

## Further reading

Most of MAYA's documentation is in Estonian. These two files are in
English:

| Document | Contents |
|---|---|
| **PAIGALDAMINE_EN.md** (this file) | complete installation guide |
| [AI_ASSISTED_INSTALLATION.md](AI_ASSISTED_INSTALLATION.md) | installing with an AI assistant |

In Estonian:

| Document | Contents |
|---|---|
| [SEADISTAMINE.md](SEADISTAMINE.md) | every environment variable |
| [TURVALISUS.md](TURVALISUS.md) | authentication and user isolation in depth |
| [ANDROID.md](ANDROID.md) | building and troubleshooting the Android app |
| [GEMINI_LIVE.md](GEMINI_LIVE.md) | model, voice, VAD, costs |
| [KARAKTERID.md](KARAKTERID.md) | writing your own characters |
| [KONEALGATUS.md](KONEALGATUS.md) | how MAYA calls you |
| [MITU_SEADET.md](MITU_SEADET.md) | multiple phones and multiple accounts |
| [ARHITEKTUUR.md](ARHITEKTUUR.md) | modules and the conversation lifecycle |
