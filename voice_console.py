"""
Localhost web console for turn-testing the pirate game with REAL ElevenLabs
ASR + TTS — no hosted agent, no Speech Engine session needed.

    temporal server start-dev
    PIRATE_AWS_PROFILE=brianz-admin .venv/bin/python temporal_worker.py
    .venv/bin/python voice_console.py          # http://localhost:8000

Browser (must be on localhost — mic requires a secure context, which
localhost counts as): mic capture + hold-to-talk button, 16-bit mono WAV
uploads to this server, which:

  1. POSTs the WAV to ElevenLabs Scribe (scribe_v1) for ASR
  2. Feeds the transcript to the Temporal workflow (same on_session_start /
     on_transcript logic as brain_server_sketch.py)
  3. POSTs the pirate's line to ElevenLabs TTS with the custom voice
  4. Streams the MP3 back to the browser, which plays it

The ElevenLabs key never leaves this process — the browser only ever talks
to this FastAPI app. If ASR or TTS fails, the error is shown in the console
so the turn is never silently dropped.
"""

import base64
import os
import uuid

import httpx
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

from brain_server_sketch import get_temporal_client, on_session_start
from temporal_workflows import PirateConversation

ELEVEN_KEY = os.environ["ELEVEN_LABS_API_KEY"]
VOICE_ID = os.environ.get("PIRATE_VOICE_ID", "TG2O4Qh067u8gMkJrjhR")
# eleven_v3 is required for audio tags ([laughs], [whispers], …) to be
# *performed* instead of read aloud. Flash models ignore the tag support
# and speak the bracket text literally. v3 doesn't take stability/
# similarity_boost the way flash does, but it accepts and ignores them —
# kept here so the request shape is model-agnostic.
TTS_MODEL = os.environ.get("PIRATE_TTS_MODEL", "eleven_v3")
ASR_MODEL = os.environ.get("PIRATE_ASR_MODEL", "scribe_v1")

app = FastAPI(title="Pirate voice console")

# session_id -> None yet; one browser session = one workflow = one kid
_session_id: str | None = None


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return PAGE


@app.post("/api/session/start")
async def start_session() -> dict:
    """New kid: fresh workflow id, then the (dynamic) greeting line + audio."""
    global _session_id
    _session_id = f"console-{uuid.uuid4().hex[:8]}"
    line = await on_session_start(_session_id)
    audio = await _tts(line)
    return {"line": line, "audio_b64": audio, "session_id": _session_id}


@app.post("/api/turn")
async def take_turn(audio: UploadFile) -> dict:
    """One turn: WAV in -> ASR -> workflow update -> pirate line + TTS."""
    if _session_id is None:
        raise HTTPException(400, "no session — POST /api/session/start first")
    wav = await audio.read()
    if not wav:
        raise HTTPException(400, "empty audio upload")

    transcript = await _asr(wav)
    if not transcript.strip():
        # Kid said nothing we could transcribe — keep the turn open so we
        # don't burn a clue on silence. The browser replays a "speak up" nudge.
        return {"transcript": "", "line": "", "no_speech": True}

    # Same as brain_server_sketch.on_transcript, but we keep the full result
    # dict (turn/done/guessed) so the browser can show game state.
    client = await get_temporal_client()
    handle = client.get_workflow_handle(f"pirate-{_session_id}")
    result = await handle.execute_update(
        PirateConversation.submit_utterance, transcript
    )
    pirate_audio = await _tts(result["line"])
    return {
        "transcript": transcript,
        "line": result["line"],
        "turn": result["turn"],
        "done": result["done"],
        "guessed": result["guessed"],
        "audio_b64": pirate_audio,
    }


@app.post("/api/tts")
async def tts_only(body: dict) -> dict:
    """TTS a line of our own (e.g. the 'speak up' nudge) without touching the workflow."""
    line = (body.get("text") or "").strip()
    if not line:
        raise HTTPException(400, "text required")
    return {"audio_b64": await _tts(line)}


async def _asr(wav_bytes: bytes) -> str:
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            "https://api.elevenlabs.io/v1/speech-to-text",
            headers={"xi-api-key": ELEVEN_KEY},
            files={"file": ("utt.wav", wav_bytes, "audio/wav")},
            data={"model_id": ASR_MODEL, "language_code": "eng"},
        )
    if resp.status_code != 200:
        raise HTTPException(502, f"ElevenLabs ASR failed: {resp.text[:300]}")
    return resp.json().get("text", "")


async def _tts(line: str) -> str:
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}?output_format=mp3_44100_128",
            headers={"xi-api-key": ELEVEN_KEY},
            json={
                "text": line,
                "model_id": TTS_MODEL,
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.8},
            },
        )
    if resp.status_code != 200:
        raise HTTPException(502, f"ElevenLabs TTS failed: {resp.text[:300]}")
    return base64.b64encode(resp.content).decode()


PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Captain Barnaby Bones — voice console</title>
<style>
  body { font-family: ui-monospace, Menlo, monospace; background: #10141a; color: #e8dcc0;
         max-width: 640px; margin: 2rem auto; padding: 0 1rem; }
  h1 { color: #d4a94e; font-size: 1.3rem; }
  #log { border: 1px solid #3a3123; border-radius: 6px; padding: 1rem;
         height: 300px; overflow-y: auto; background: #171c24; }
  .pirate { color: #d4a94e; }
  .kid { color: #7fc7c7; }
  .sys { color: #888; }
  button { font-size: 1rem; padding: .6rem 1.2rem; border-radius: 6px; border: none;
           cursor: pointer; margin: 1rem .5rem 0 0; }
  #talk { background: #8b2f2f; color: #fff; }
  #talk.recording { background: #d45050; }
  #start { background: #3a6b3a; color: #fff; }
  button:disabled { opacity: .4; cursor: default; }
  #status { margin-top: .5rem; color: #888; font-size: .85rem; }
</style>
</head>
<body>
<h1>☠ Captain Barnaby Bones — voice console</h1>
<div id="log"><span class="sys">Press "New kid" to start a session, then hold "Hold to talk" and speak.</span></div>
<button id="start">☠ New kid</button>
<button id="talk" disabled>🎙 Hold to talk (or hold Space)</button>
<div id="status"></div>

<script>
const logEl = document.getElementById('log');
const talkBtn = document.getElementById('talk');
const startBtn = document.getElementById('start');
const statusEl = document.getElementById('status');
let sessionActive = false, busy = false;

function log(text, cls) {
  const div = document.createElement('div');
  div.className = cls;
  div.textContent = (cls === 'pirate' ? '☠ ' : cls === 'kid' ? '🧒 ' : '') + text;
  logEl.appendChild(div);
  logEl.scrollTop = logEl.scrollHeight;
}
function setStatus(s) { statusEl.textContent = s; }

function b64ToAudioUrl(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return URL.createObjectURL(new Blob([bytes], {type: 'audio/mpeg'}));
}
function play(url) {
  return new Promise(resolve => {
    const a = new Audio(url);
    a.onended = resolve;
    a.play();
  });
}

startBtn.onclick = async () => {
  if (busy) return;
  busy = true; sessionActive = false; talkBtn.disabled = true;
  logEl.innerHTML = ''; setStatus('Starting session…');
  try {
    const resp = await fetch('/api/session/start', {method: 'POST'});
    if (!resp.ok) throw new Error((await resp.text()).slice(0, 200));
    const data = await resp.json();
    sessionActive = true; talkBtn.disabled = false;
    log(data.line, 'pirate');
    await play(b64ToAudioUrl(data.audio_b64));
    setStatus('Listening — hold to talk.');
  } catch (e) { log('ERROR: ' + e.message, 'sys'); setStatus(''); }
  busy = false;
};

// ---- mic capture: hold-to-talk with an energy VAD safety release --------
let mediaStream, audioCtx, recorder, chunks = [];
const targetSampleRate = 16000;

async function beginRecording() {
  if (!sessionActive || busy || recorder) return;
  chunks = [];
  mediaStream = await navigator.mediaDevices.getUserMedia(
    {audio: {echoCancellation: true, noiseSuppression: true}});
  audioCtx = new AudioContext();
  const src = audioCtx.createMediaStreamSource(mediaStream);
  // Downsample to 16k by routing through a lower-rate context via ScriptProcessor
  const proc = audioCtx.createScriptProcessor(4096, 1, 1);
  proc.onaudioprocess = e => {
    // resample: crude but fine for speech (16k target, ctx rate typically 48k)
    const input = e.inputBuffer.getChannelData(0);
    const ratio = audioCtx.sampleRate / targetSampleRate;
    const n = Math.floor(input.length / ratio);
    const out = new Float32Array(n);
    for (let i = 0; i < n; i++) out[i] = input[Math.floor(i * ratio)];
    const buf = new Int16Array(n);
    for (let i = 0; i < n; i++) {
      const s = Math.max(-1, Math.min(1, out[i]));
      buf[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    chunks.push(buf);
  };
  src.connect(proc);
  proc.connect(audioCtx.destination); // needed or onaudioprocess never fires
  recorder = {proc, src};
  talkBtn.classList.add('recording');
  talkBtn.textContent = '🔴 Recording — release to send';
}

async function endRecording() {
  if (!recorder) return;
  const {proc, src} = recorder; recorder = null;
  talkBtn.classList.remove('recording');
  talkBtn.textContent = '🎙 Hold to talk (or hold Space)';
  try { proc.disconnect(); src.disconnect(); } catch {}
  mediaStream.getTracks().forEach(t => t.stop());
  await audioCtx.close();
  const total = chunks.reduce((n, c) => n + c.length, 0);
  if (total === 0) return;
  const wav = new Uint8Array(44 + total * 2);
  const view = new DataView(wav.buffer);
  const ws = (o, s) => { for (let i = 0; i < s.length; i++) view.setUint8(o + i, s.charCodeAt(i)); };
  ws(0, 'RIFF'); view.setUint32(4, 36 + total * 2, true); ws(8, 'WAVE');
  ws(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
  view.setUint16(22, 1, true); view.setUint32(24, targetSampleRate, true);
  view.setUint32(28, targetSampleRate * 2, true); view.setUint16(32, 2, true);
  view.setUint16(34, 16, true); ws(36, 'data'); view.setUint32(40, total * 2, true);
  let off = 44;
  for (const c of chunks) { for (let i = 0; i < c.length; i++) view.setInt16(off, c[i], true); off += 2; }

  busy = true; setStatus('Transcribing…');
  try {
    const body = new FormData();
    body.append('audio', new Blob([wav], {type: 'audio/wav'}), 'utt.wav');
    const resp = await fetch('/api/turn', {method: 'POST', body});
    if (!resp.ok) throw new Error((await resp.text()).slice(0, 200));
    const data = await resp.json();
    if (data.no_speech) {
      log('(nothing transcribed)', 'sys');
      await play(b64ToAudioUrl(await speak('Speak up, ye scurvy seadog!')));
      setStatus('Listening — hold to talk.');
    } else {
      log(data.transcript, 'kid');
      log(data.line, 'pirate');
      await play(b64ToAudioUrl(data.audio_b64));
      setStatus(data.done
        ? (data.guessed ? '☠ Guessed it! Password revealed. Press "New kid" for the next one.'
                        : 'Turns used up — password revealed. Press "New kid" for the next one.')
        : `Turn ${data.turn} — listening.`);
    }
  } catch (e) {
    log('ERROR: ' + e.message, 'sys');
    setStatus('Listening — hold to talk.');
  }
  busy = false;
}

// speak() — server-side TTS for the no-speech nudge
async function speak(text) {
  const resp = await fetch('/api/tts', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({text})});
  if (!resp.ok) throw new Error('tts failed');
  return (await resp.json()).audio_b64;
}

talkBtn.addEventListener('pointerdown', e => { e.preventDefault(); beginRecording(); });
talkBtn.addEventListener('pointerup', e => { e.preventDefault(); endRecording(); });
talkBtn.addEventListener('pointerleave', () => endRecording());
document.addEventListener('keydown', e => {
  if (e.code === 'Space' && !e.repeat && sessionActive && !busy) { e.preventDefault(); beginRecording(); }
});
document.addEventListener('keyup', e => { if (e.code === 'Space') { e.preventDefault(); endRecording(); } });
</script>
</body>
</html>
"""
