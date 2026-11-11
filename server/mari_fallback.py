import re
import subprocess
import requests
import asyncio

def synthesize_mari_pcm(text_to_speak: str) -> bytes:
    try:
        clean = re.sub(r"[*#_\[\]`|•]", "", text_to_speak).strip()
        resp = requests.post(
            "https://api.tartunlp.ai/text-to-speech/v2",
            json={"text": clean[:250], "speaker": "mari"},
            timeout=8
        )
        if resp.status_code == 200 and resp.content:
            proc = subprocess.Popen(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
                 "-f", "s16le", "-acodec", "pcm_s16le", "-ac", "1", "-ar", "24000", "pipe:1"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE
            )
            pcm_out, _ = proc.communicate(input=resp.content)
            return pcm_out
    except Exception as e:
        print(f"--> [MARI TTS VIGA]: {e}", flush=True)
    return b""

async def trigger_emergency_mari(websocket):
    try:
        pcm = synthesize_mari_pcm("Ühendus Google serveriga katkes. Mina olen Mari ja võtsin kõne üle.")
        if pcm:
            await websocket.send_bytes(pcm)
            print("--> [MARI]: Teade saadetud kõlarisse, hoian liini lahti...", flush=True)
            # Kriitiline: ootame kuni heli on telefonis ette mängitud enne kui ühendus sulgub!
            await asyncio.sleep(4.5)
    except Exception as err:
        print(f"--> [MARI SAATMISE VIGA]: {err}", flush=True)
