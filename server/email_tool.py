import os
import config  # MAYA seadistus (vt server/config.py)
import email
from email.header import decode_header
import imaplib

# Loeme .env faili puhtalt standardteegiga ilma väliste mooduliteta
def load_env(env_path=None):
    """Teed tulevad nüüd config.py-st (keskkonnamuutuja MAYA_ENV_FILE)."""
    if env_path is None:
        config.laadi_env()
        return
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip().strip("'\"")

load_env()

def decode_mime_words(raw_header):
    if not raw_header:
        return ""
    decoded_fragments = decode_header(raw_header)
    text_parts = []
    for frag, enc in decoded_fragments:
        if isinstance(frag, bytes):
            try:
                text_parts.append(frag.decode(enc or "utf-8", errors="replace"))
            except Exception:
                text_parts.append(frag.decode("latin-1", errors="replace"))
        else:
            text_parts.append(str(frag))
    return "".join(text_parts).strip()

def get_email_body_snippet(msg, max_chars=180):
    body = ""
    try:
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                cdisp = str(part.get("Content-Disposition", ""))
                if ctype == "text/plain" and "attachment" not in cdisp:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        body = payload.decode(charset, errors="replace")
                        break
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                body = payload.decode(charset, errors="replace")
    except Exception:
        pass

    lines = [l.strip() for l in body.splitlines() if l.strip()]
    snippet = " ".join(lines)
    if len(snippet) > max_chars:
        snippet = snippet[:max_chars].rstrip() + "..."
    return snippet or "Sisu puudub."

def fetch_recent_emails(user, password, folder="INBOX", limit=3):
    if not user or not password:
        return []

    clean_pass = password.strip().replace(" ", "").strip("\"'")
    clean_user = user.strip().strip("\"'")

    results = []
    mail = None
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        mail.sock.settimeout(6.0)
        mail.login(clean_user, clean_pass)
        status, _ = mail.select(folder, readonly=True)
        if status != "OK":
            return []

        status, data = mail.search(None, "UNSEEN")
        ids = data[0].split() if (status == "OK" and data[0]) else []

        if not ids:
            status, data = mail.search(None, "ALL")
            ids = data[0].split() if (status == "OK" and data[0]) else []

        if not ids:
            return []

        latest_ids = ids[-limit:]
        latest_ids.reverse()

        for mid in latest_ids:
            res, msg_data = mail.fetch(mid, "(RFC822)")
            if res != "OK":
                continue
            for part in msg_data:
                if isinstance(part, tuple):
                    msg = email.message_from_bytes(part[1])
                    subject = decode_mime_words(msg.get("Subject", "(ilma teemata)"))
                    from_header = decode_mime_words(msg.get("From", "Tundmatu saatja"))
                    sender_name = from_header.split("<")[0].strip().strip('"') or from_header
                    snippet = get_email_body_snippet(msg, max_chars=160)

                    results.append({
                        "sender": sender_name,
                        "subject": subject,
                        "snippet": snippet
                    })
    except Exception as e:
        print(f"IMAP viga konto {clean_user} puhul: {e}", flush=True)
    finally:
        if mail:
            try:
                mail.close()
            except Exception:
                pass
            try:
                mail.logout()
            except Exception:
                pass

    return results

def get_emails_summary():
    u1 = os.getenv("GMAIL_USER") or os.getenv("GMAIL_USER_1")
    p1 = os.getenv("GMAIL_APP_PASSWORD") or os.getenv("GMAIL_APP_PASSWORD_1")
    u2 = os.getenv("GMAIL_USER_2")
    p2 = os.getenv("GMAIL_APP_PASSWORD_2")

    accs = []
    if u1 and p1:
        accs.append((u1, p1))
    if u2 and p2:
        accs.append((u2, p2))

    summary_lines = []
    for user, pwd in accs:
        emails = fetch_recent_emails(user, pwd, limit=2)
        if emails:
            summary_lines.append(f"Konto {user}:")
            for i, m in enumerate(emails, 1):
                summary_lines.append(f"  {i}. Saatja: {m['sender']} | Teema: {m['subject']} | Sisu: {m['snippet']}")
        else:
            summary_lines.append(f"Konto {user}: kirju ei leitud või ühendus ebaõnnestus.")

    return "\n".join(summary_lines)

if __name__ == "__main__":
    print("--- TESTIME MÕLEMA GMAILI KONTO ÜHENDUST ---")
    print(get_emails_summary())
    print("--- TEST LÕPPENUD ---")
