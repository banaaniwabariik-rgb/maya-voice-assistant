# Installing MAYA with an AI assistant

**You do not need to be a programmer.** This guide shows how to let an
AI coding assistant install MAYA on your machine while explaining every
step to you.

🇪🇪 Eesti keeles: **[AI_ABIGA_PAIGALDAMINE.md](AI_ABIGA_PAIGALDAMINE.md)**

> MAYA's own user interface is in Estonian. This document is in English
> so that the installation is accessible; the assistant you talk to can
> explain things in whichever language you prefer.
>
> If you would rather type the commands yourself, there is a
> [guided installer](#is-this-even-necessary) (`./paigalda.sh`) and a
> [complete manual guide](PAIGALDAMINE_EN.md).

---

## First, the important distinction: two kinds of AI help

These are not the same thing, and the difference decides how much work
you do yourself.

| | **Agentic assistant** | **Chatbot** |
|---|---|---|
| Examples | Claude Code, Cursor, GitHub Copilot in agent mode, Gemini CLI | claude.ai, ChatGPT, Gemini on the web |
| Can see your files | **yes** (you give it a folder) | no — only what you paste |
| Can run commands | **yes, with your permission** | **no** |
| Reads error output itself | **yes** | no — you copy it over |
| What you do | approve steps, answer questions | paste commands into the terminal and paste output back |

**An agentic assistant does the work. A chatbot tells you what to do.**
Both work; the second one just needs more copying.

> ⚠️ **No AI gets into your computer by itself.** An agentic assistant
> can only see the folder you open for it, and can only run the commands
> you allow. If a service claims otherwise, don't believe it.

---

## Part 1 — With an agentic assistant (recommended)

### Step 1. Install the tools

Required:

| Tool | What for | Link |
|---|---|---|
| **Terminal** | running commands | macOS/Linux: already there. Windows: [WSL2](https://learn.microsoft.com/en-us/windows/wsl/install) |
| **Git** | downloading MAYA | https://git-scm.com/downloads/ |
| **Python 3.11+** | the MAYA backend | https://www.python.org/downloads/ |
| **An AI assistant** | doing the work | see below |

Assistant options:

| | Installation | Notes |
|---|---|---|
| **Claude Code** | https://code.claude.com/docs/en/overview | Command-line tool. Runs in the terminal, sees the project folder, asks before running commands. |
| **Visual Studio Code** + an AI extension | https://code.visualstudio.com/ | Graphical editor. Install an AI extension into it (e.g. the Claude Code extension or GitHub Copilot). |
| **Another agentic assistant** | — | Fine, as long as it can read files and run commands with your approval. |

A GitHub account (https://github.com/) is only needed if you want to
clone from a private repository or contribute. Downloading a public
repository needs no account.

**MAYA does not need Docker** — see
[PAIGALDAMINE_EN.md](PAIGALDAMINE_EN.md#why-there-is-no-docker).

### Step 2. Download MAYA

```bash
git clone <repository-address> maya
cd maya
```

`<repository-address>` is this project's Git address. If you don't have
Git, download the ZIP from the repository and unpack it.

### Step 3. Open the project in the assistant

**Claude Code:**

```bash
cd maya
claude
```

**VS Code:**

```bash
cd maya
code .
```

Then open the AI panel. **Important: open exactly the folder MAYA lives
in** — that way the assistant sees the project but not the rest of your
computer.

### Step 4. Give it the installation prompt

Copy the whole prompt below and paste it to the assistant. **Do not
remove the restrictions** — they keep your API key and your machine
safe.

```text
Help me install the MAYA voice assistant on this computer. I am not a
programmer – explain every step in plain language.

BEFORE YOU CHANGE ANYTHING:
1. Read README.md, docs/PAIGALDAMINE_EN.md, server/requirements.txt,
   .env.example and paigalda.sh. Tell me in your own words what this
   project does and what the installation requires.
2. Check what already exists on my machine (Python version, an existing
   .venv, .env, database) and tell me what is missing.
3. Only then make a plan and ask me for permission.

HOW TO WORK:
- Do ONLY the steps needed to install MAYA.
- Use the project's OWN scripts (./paigalda.sh, ./kaivita.sh,
  ./tervisekontroll.sh, ./peata.sh) – do not write new ones when an
  existing script already does the job.
- Explain each command in one sentence before running it: what it does
  and why.
- Test after every stage that it actually works, and tell me the result.
- If something fails, explain the error in plain language and propose a
  safe fix. Do not try random fixes one after another.

WHAT YOU MUST NOT DO:
- Never print, log or commit my Gemini API key. The key belongs ONLY in
  the .env file (permissions 600), which is in .gitignore.
- Do not change anything outside this project folder without asking.
- Do not open firewall ports, change router settings, or expose MAYA to
  the public internet without explaining the risks and getting my
  explicit permission.
- Do not delete or overwrite an existing .env file or database without
  warning me and getting permission.
- Do not deploy anything to any remote server or anyone else's machine.
  This installation goes ONLY on my computer.
- Do not download or execute scripts from random internet sources. Use
  only this project's files, the official package manager (apt, brew,
  dnf) and PyPI.
- Do not change the Gemini Live model, the voice configuration or the
  conversation behaviour.
- Do not weaken tests or security checks just to make something pass.

WHAT TO ASK ME:
- My Gemini API key (and enter it so that it does not appear on screen
  or in shell history).
- How my phone will reach the server: this computer only, home network,
  VPN (Tailscale), or the public internet.
- Permission before any change that cannot easily be undone.

AT THE END:
Give me a clear report: what works (proven by a check), what is
incomplete, what I still have to do myself (e.g. phone permissions,
battery exemption), and what the next steps are.
```

### Step 5. Let it inspect the project first

A good assistant **reads before writing**. If it starts changing files
without looking at the project, stop it and say: *"First read README.md
and docs/PAIGALDAMINE_EN.md, then tell me what you intend to do."*

### Step 6. Answer its questions

It will ask you two things:

**1. Your Gemini API key.** Get it first at
[aistudio.google.com/apikey](https://aistudio.google.com/apikey). Read
the cost section:
[PAIGALDAMINE_EN.md section 3](PAIGALDAMINE_EN.md#3-gemini-api-key-and-costs).
**Google bills this to you, not to the MAYA project.**

**2. How your phone reaches the server.** If you don't know, pick
**home network** (simplest) or **Tailscale** (works away from home
without opening any ports).

### Step 7. When the assistant MUST ask permission

These steps are irreversible or affect security. **If the assistant
does them without asking, stop it.**

| Action | Why permission is needed |
|---|---|
| overwriting an existing `.env` or database | your key and memory are lost |
| deleting files | irreversible |
| changing firewall rules (`ufw`, `firewall-cmd`, `pfctl`) | opens your machine to the network |
| router port forwarding | opens your machine to the internet |
| `MAYA_ALLOW_REGISTRATION=1` on the public internet | anyone can create an account |
| `sudo` for anything | system-wide effect |
| anything outside the project folder | unrelated to MAYA |
| `git push`, creating a repository, publishing | your code leaves your machine |

### Step 8. Verify that the installation worked

**Don't take the assistant's word for it.** Run this yourself:

```bash
./tervisekontroll.sh
```

It checks the installation, configuration, database, whether the server
responds, and your network addresses, marking every line ✓, ! or ✗. A
successful installation shows **"KÕIK KORRAS"** (all good) or
"TÖÖKORRAS, aga hoiatus(t)" (working, with warnings).

Then:

```bash
./kaivita.sh
```

and check **from your phone's browser** that the server is reachable:
`http://<server-ip>:8000/api/auth/status` → it must return JSON.

Full checklist:
[PAIGALDAMINE_EN.md section 8](PAIGALDAMINE_EN.md#8-your-first-voice-conversation).

### Step 9. What the assistant cannot do for you

| Thing | Why |
|---|---|
| installing the APK on your phone | needs the physical phone |
| granting microphone/camera permissions | you tap your own screen |
| the battery exemption | in Android settings, by hand |
| entering the server address in the app | on the phone screen |
| creating the Gemini key | your Google account |
| setting up billing | your Google Cloud account |

Those steps are in
[PAIGALDAMINE_EN.md section 7](PAIGALDAMINE_EN.md#7-the-android-app).

---

## Part 2 — With a chatbot (if you have no agentic assistant)

This works too; you just copy more.

1. Open an AI chat (claude.ai, ChatGPT, Gemini on the web).
2. Paste **the same prompt** as above, with this added in front:

   ```text
   You do NOT have access to my computer or files. Give me commands one
   at a time so I can run them in a terminal, and wait for my answer
   each time. Ask me for project files when you need them.
   ```

3. Paste it the files it needs: `README.md`,
   `docs/PAIGALDAMINE_EN.md`, `server/requirements.txt`,
   `.env.example`. **Never paste `.env` — your key is in it.**
4. Run its commands one by one and paste the output back.
5. On an error, paste the **complete** error message, not just "it
   doesn't work".

> ⚠️ **Never paste your API key, passwords or the contents of `.env`
> into a chatbot.** If an assistant asks for your key "to verify it",
> refuse. The key is only ever needed in the `.env` file on your own
> machine.

---

## Is this even necessary?

Honestly: **MAYA has a guided installer** that does the same job without
any AI:

```bash
./paigalda.sh
```

It checks prerequisites, explains what is missing, creates the
environment, installs dependencies, asks for the key without echoing
it, sets up networking and creates the database.

**An AI assistant is useful when:**

- something goes wrong and you can't make sense of the error;
- you want each step explained as it happens;
- your system is unusual (old Linux, WSL, some quirk);
- you want to set up a reverse proxy, HTTPS or a systemd service;
- you want to customise MAYA (your own characters, your own settings).

**An AI assistant is not magic.** It can be wrong, invent commands that
don't exist, or do more than needed. That is why the prompt above is
written so restrictively — and why you should always finish by running
`./tervisekontroll.sh` yourself.

---

## Security rules, summarised

1. **The key belongs only in `.env`.** Not in a chat, not in Git, not
   in a screenshot.
2. **No AI may open your firewall or router for you.** Those decisions
   are yours, after the risks have been explained to you.
3. **No AI deploys anything to someone else's server.** A MAYA
   installation goes on your own machine only.
4. **Don't run commands you don't understand.** Ask: *"what exactly
   does this do, and what happens if it's wrong?"*
5. **Verify the result yourself.** `./tervisekontroll.sh` is evidence;
   the assistant's summary is not.

---

## If you get stuck

| | |
|---|---|
| Errors and fixes | [PAIGALDAMINE_EN.md section 9](PAIGALDAMINE_EN.md#9-troubleshooting) |
| Network, ports, HTTPS | [PAIGALDAMINE_EN.md section 5](PAIGALDAMINE_EN.md#5-network-ports-and-remote-access) |
| Android problems | [ANDROID.md](ANDROID.md) (Estonian) |
| All settings | [SEADISTAMINE.md](SEADISTAMINE.md) (Estonian) |
| Security | [TURVALISUS.md](TURVALISUS.md) (Estonian) |
