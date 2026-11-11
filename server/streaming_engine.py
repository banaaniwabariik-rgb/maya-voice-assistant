import os, json, tempfile, subprocess, asyncio, requests, base64, threading
from google.genai import types

PERMISSIVE_SAFETY = [
    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=types.HarmBlockThreshold.BLOCK_NONE),
    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
]



# ---------------------------------------------------------------------------
# SÜNKROONSE GEMINI VOO SILD ASÜNKROONSESSE MAAILMA
# ---------------------------------------------------------------------------
# Probleem: `generate_content_stream()` tagastab SÜNKROONSE generaatori ja
# selle itereerimine (`for chunk in stream`) blokeerib kutsuva lõime iga
# võrgupaketi ootamise ajaks. Kuna stream_generator on `async def`, blokeeris
# see kogu asyncio sündmustsükli – st tekstivestluse ajal seisis ÜHTLASI
# käimasolev häälkõne, meeldetuletuste valvur ja kõik HTTP-päringud.
#
# See on sama klassi viga nagu varem parandatud P0 blokeeriv I/O (8 kohta
# web_maya.py-s viidi asyncio.to_thread alla); see koht jäi tookord kahe
# silma vahele, sest see ei ole üksikkutse, vaid itereerimine.
#
# Lahendus: tootja-lõim loeb voogu ja lükkab tükid asyncio järjekorda.
# `run_coroutine_threadsafe(...).result()` blokeerib TOOTJA, kui järjekord
# on täis – nii tekib vastusurve ja mälu ei jookse täis, kui tarbija on
# aeglasem (nt TTS-i ootamas).
_STREAM_QUEUE_MAX = 32
_STREAM_DONE = object()


async def aiter_sync_stream(make_stream):
    """Teeb sünkroonsest voost asünkroonse iteraatori, blokeerimata tsüklit.

    make_stream on kutsutav, mis loob voo. Ka LOOMINE käib tootja-lõimes,
    sest ka see teeb võrgupäringu ja blokeerib.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue(maxsize=_STREAM_QUEUE_MAX)

    def _put(item):
        asyncio.run_coroutine_threadsafe(queue.put(item), loop).result()

    def _producer():
        try:
            for chunk in make_stream():
                _put(chunk)
        except Exception as exc:          # anname vea tarbijale edasi
            try:
                _put(exc)
            except Exception:
                pass
        finally:
            try:
                _put(_STREAM_DONE)
            except Exception:
                pass

    threading.Thread(target=_producer, name="gemini-stream", daemon=True).start()

    while True:
        item = await queue.get()
        if item is _STREAM_DONE:
            return
        if isinstance(item, BaseException):
            raise item
        yield item


def clean_text(t: str) -> str:
    replacements = [
        ("°C", " kraadi"),
        ("°", " kraadi"),
        ("%", " protsenti"),
        ("m/s", " meetrit sekundis"),
        ("km/h", " kilomeetrit tunnis"),
        ("*", ""), ("#", ""), ("_", ""), ("[", ""), ("]", ""), ("`", ""), ("|", ""), ("•", "")
    ]
    for old, new in replacements:
        t = t.replace(old, new)
    return " ".join(t.split()).strip()

def tts_tartunlp(clean: str, ogg_path: str) -> bool:
    try:
        r = requests.post(
            "https://api.tartunlp.ai/text-to-speech/v2",
            json={"text": clean[:400], "speaker": "mari"},
            timeout=6
        )
        if r.status_code == 200 and len(r.content) > 0:
            wav = ogg_path + ".wav"
            with open(wav, "wb") as f:
                f.write(r.content)
            subprocess.run([
                "ffmpeg", "-y", "-i", wav, "-c:a", "libopus", "-b:a", "32k", ogg_path
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.exists(wav):
                os.remove(wav)
            return os.path.exists(ogg_path) and os.path.getsize(ogg_path) > 0
    except Exception as e:
        print("TartuNLP err:", e, flush=True)
    return False

def synthesize_sentence(text: str, voice_pref: str, gemini_client) -> str:
    clean = clean_text(text)
    if not clean:
        return ""
    with tempfile.NamedTemporaryFile(suffix=".pcm", delete=False) as tf:
        pcm = tf.name
    ogg = pcm + ".ogg"
    def _run_gemini_tts():
        try:
            res = gemini_client.models.generate_content(
                model="gemini-2.5-flash-preview-tts",
                contents=clean,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Aoede")
                        )
                    )
                )
            )
            raw = None
            if res and res.candidates and len(res.candidates) > 0:
                cand = res.candidates[0]
                if cand.content and cand.content.parts and len(cand.content.parts) > 0:
                    raw = getattr(cand.content.parts[0].inline_data, "data", None)
            if raw:
                with open(pcm, "wb") as f:
                    f.write(raw)
                subprocess.run([
                    "ffmpeg", "-y", "-f", "s16le", "-ar", "24000", "-ac", "1",
                    "-i", pcm, "-af", "apad=pad_dur=0.4", "-c:a", "libopus", "-b:a", "32k", ogg
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return os.path.exists(ogg) and os.path.getsize(ogg) > 0
        except Exception as ge:
            print(f"Gemini TTS viga lausele '{clean}': {ge}", flush=True)
        return False

    try:
        success = False
        if voice_pref == "mari":
            success = tts_tartunlp(clean, ogg)
            if not success:
                print(f"-> TartuNLP Mari timeout/viga, lülitun Gemini Aoede peale: '{clean}'", flush=True)
                success = _run_gemini_tts()
        else:
            success = _run_gemini_tts()
            if not success:
                print(f"-> Gemini TTS tühi/viga, lülitun TartuNLP Mari peale: '{clean}'", flush=True)
                success = tts_tartunlp(clean, ogg)

        if success and os.path.exists(ogg) and os.path.getsize(ogg) > 0:
            with open(ogg, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        print("Sentence TTS err:", e, flush=True)
    finally:
        for p in [pcm, ogg]:
            if os.path.exists(p):
                try: os.remove(p)
                except: pass
    return ""

def pop_complete_sentence(buf: str):
    for i, ch in enumerate(buf):
        if ch in ("!", "?", "\n"):
            return buf[:i+1].strip(), buf[i+1:]
        if ch == ".":
            is_dec = (i > 0 and buf[i-1].isdigit()) and (i + 1 < len(buf) and buf[i+1].isdigit())
            if not is_dec:
                return buf[:i+1].strip(), buf[i+1:]
    return None, buf

def extract_action(text: str):
    s = text.find("[ACTION:")
    if s != -1:
        e = text.find("]", s)
        if e != -1:
            raw_action = text[s+8:e].strip()
            clean_str = (text[:s] + text[e+1:]).strip()
            return raw_action, clean_str
    return None, text

async def stream_generator(user_text, system_prompt, conv_prompt, voice_pref, core, bg_learn, image_bytes=None):
    buf, full_reply, idx = "", "", 0
    yield json.dumps({"type": "user_transcription", "text": user_text}, ensure_ascii=False) + "\n"
    try:
        contents_payload = conv_prompt
        if image_bytes:
            m_type = "image/jpeg"
            if len(image_bytes) > 4 and image_bytes[:4] == bytes([0x89, 0x50, 0x4E, 0x47]):
                m_type = "image/png"
            elif len(image_bytes) > 12 and image_bytes[:4] == b"RIFF" and b"WEBP" in image_bytes[:16]:
                m_type = "image/webp"
            contents_payload = [
                types.Part.from_bytes(data=image_bytes, mime_type=m_type),
                conv_prompt
            ]
        def _make_stream():
            return core.gemini_client.models.generate_content_stream(
                model=core.GEMINI_MODEL,
                contents=contents_payload,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.7,
                    safety_settings=PERMISSIVE_SAFETY,
                ),
            )

        # Varem: `for chunk in stream:` otse siin – blokeeris sündmustsükli.
        async for chunk in aiter_sync_stream(_make_stream):
            c = chunk.text or ""
            if not c:
                continue
            buf += c
            full_reply += c

            while True:
                sent, buf = pop_complete_sentence(buf)
                if not sent:
                    break
                act, sent = extract_action(sent)
                if act:
                    yield json.dumps({"type": "action", "payload": act}, ensure_ascii=False) + "\n"
                if sent:
                    b64 = await asyncio.to_thread(synthesize_sentence, sent, voice_pref, core.gemini_client)
                    yield json.dumps({"type": "sentence", "index": idx, "text": sent, "audio_base64": b64}, ensure_ascii=False) + "\n"
                    idx += 1

        rem = buf.strip()
        if rem:
            act, rem = extract_action(rem)
            if act:
                yield json.dumps({"type": "action", "payload": act}, ensure_ascii=False) + "\n"
            if rem:
                b64 = await asyncio.to_thread(synthesize_sentence, rem, voice_pref, core.gemini_client)
                yield json.dumps({"type": "sentence", "index": idx, "text": rem, "audio_base64": b64}, ensure_ascii=False) + "\n"

        _, clean_full = extract_action(full_reply)
        clean_full = clean_full.strip()

        # ARHIVEERIMINE JA ÕPPIMINE EI TOHI VASTUST MAHA VÕTTA.
        # Varem olid mõlemad otse siin, kaitseta:
        #   * log_conversation_turn teeb SQLite kirjutuse – sünkroonne I/O
        #     keset async-funktsiooni, mis blokeeris sündmustsükli;
        #   * asyncio.create_task(bg_learn(...)) eeldas korutiini, aga
        #     bg_learn oli sünkroonne ja tagastas None -> TypeError
        #     "a coroutine was expected, got None". See lendas välja ENNE
        #     "done" sündmust, nii et iga voogedastatud vastus lõppes
        #     kliendile veaga ja telefon ei saanud teada, et vastus on valmis.
        # Nüüd on mõlemad eraldi kaitstud ja vastus jõuab alati lõpuni.
        try:
            if hasattr(core, "log_conversation_turn"):
                await asyncio.to_thread(core.log_conversation_turn, user_text, clean_full)
        except Exception as arch_err:
            print(f"[STREAM] Arhiveerimine ebaõnnestus: {arch_err}", flush=True)

        try:
            maybe = bg_learn(user_text, clean_full)
            if asyncio.iscoroutine(maybe):
                asyncio.create_task(maybe)
        except Exception as learn_err:
            print(f"[STREAM] Taustaõpe ebaõnnestus: {learn_err}", flush=True)

        yield json.dumps({"type": "done", "full_text": clean_full}, ensure_ascii=False) + "\n"
    except Exception as e:
        yield json.dumps({"type": "error", "error": str(e)}, ensure_ascii=False) + "\n"
