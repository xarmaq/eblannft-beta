"""eblanNFT Beta — sound effects.

Generates short WAV files on first use, caches them under the app's
files directory, and plays them via SoundPool. No audio resources are
shipped with the plugin — the WAVs are synthesised mathematically on
the device (pure Python ``math``/``wave``/``struct``) so the install
stays tiny and identical across hosts.

Public surface:
    init(context)        — call once, pre-loads all SFX into SoundPool.
    play(kind)           — non-blocking, swallows any failure.
    set_enabled(flag)    — disables every subsequent play() call.

Supported kinds: ``click``, ``open``, ``close``, ``success``,
``complete``, ``error``, ``badge``, ``copy``, ``toggle``.
"""

import math
import os
import struct
import threading
import wave


_log_prefix = "[NFT_SFX]"


def _log(msg):
    try:
        print(f"{_log_prefix} {msg}")
    except Exception:
        pass


_state = {
    "enabled": True,
    "pool": None,
    "ids": {},           # kind -> sound id
    "loaded": set(),     # kinds that finished loading
    "init_done": False,
    "cache_dir": None,
}

_RATE = 22050


def _write_wav(path, samples):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(_RATE)
        frames = b"".join(
            struct.pack("<h", max(-32767, min(32767, int(s))))
            for s in samples
        )
        w.writeframes(frames)


def _clamp(s):
    if s > 32767:
        return 32767
    if s < -32767:
        return -32767
    return int(s)


def _mix_into(dst, src, start_sample, scale=1.0):
    n = min(len(src), len(dst) - start_sample)
    for i in range(n):
        dst[start_sample + i] = _clamp(dst[start_sample + i] + src[i] * scale)


# ─── synthesis helpers ────────────────────────────────────────────────────

def _synth_click(rate=_RATE, dur=0.045):
    """Soft tick at 880 Hz with fast exponential decay."""
    n = int(rate * dur)
    out = [0] * n
    for i in range(n):
        t = i / rate
        env = math.exp(-t * 70.0)
        s = math.sin(2 * math.pi * 880 * t) * env * 0.42
        out[i] = int(s * 32767)
    return out


def _synth_toggle(rate=_RATE, dur=0.06):
    """Two-pulse soft click — a 'tick-tick' for toggles."""
    n = int(rate * dur)
    out = [0] * n
    for i in range(n):
        t = i / rate
        env = math.exp(-((t - 0.0) % 0.03) * 90.0)
        s = math.sin(2 * math.pi * 1100 * t) * env * 0.38
        out[i] = int(s * 32767)
    return out


def _synth_open(rate=_RATE, dur=0.16):
    """Sweep 480 → 980 Hz with smooth raised-cosine envelope."""
    n = int(rate * dur)
    out = [0] * n
    for i in range(n):
        t = i / rate
        u = t / dur
        freq = 480 + (980 - 480) * (u ** 0.65)
        env = math.sin(math.pi * u) ** 1.4
        s = math.sin(2 * math.pi * freq * t) * env * 0.40
        out[i] = int(s * 32767)
    return out


def _synth_close(rate=_RATE, dur=0.12):
    """Descending 800 → 420 Hz."""
    n = int(rate * dur)
    out = [0] * n
    for i in range(n):
        t = i / rate
        u = t / dur
        freq = 800 - (800 - 420) * (u ** 0.8)
        env = math.sin(math.pi * u) ** 1.5
        s = math.sin(2 * math.pi * freq * t) * env * 0.36
        out[i] = int(s * 32767)
    return out


def _synth_success(rate=_RATE, dur=0.28):
    """Two-note chime: A5 (880) → C6 (1046.5) with bell decay."""
    n = int(rate * dur)
    out = [0] * n
    # first note
    n1 = int(0.12 * rate)
    for i in range(n1):
        t = i / rate
        env = math.exp(-t * 6.5)
        s = (
            math.sin(2 * math.pi * 880 * t) * 0.45
            + math.sin(2 * math.pi * 1760 * t) * 0.10  # 2nd harmonic
        ) * env
        out[i] = int(s * 32767)
    # second note
    start = int(0.10 * rate)
    for i in range(start, n):
        tt = (i - start) / rate
        env = math.exp(-tt * 5.0)
        s = (
            math.sin(2 * math.pi * 1046.5 * tt) * 0.42
            + math.sin(2 * math.pi * 2093 * tt) * 0.08
        ) * env
        out[i] = _clamp(out[i] + int(s * 32767))
    return out


def _synth_complete(rate=_RATE, dur=0.36):
    """Ascending C5-E5-G5 arpeggio with bell envelope."""
    n = int(rate * dur)
    out = [0] * n

    def _bell(freq, start_s, length_s):
        samples = []
        ns = int(length_s * rate)
        for i in range(ns):
            t = i / rate
            env = math.exp(-t * 4.5)
            s = (
                math.sin(2 * math.pi * freq * t) * 0.34
                + math.sin(2 * math.pi * freq * 2 * t) * 0.08
            ) * env
            samples.append(s * 32767)
        _mix_into(out, samples, int(start_s * rate))

    _bell(523.25, 0.00, 0.30)
    _bell(659.25, 0.07, 0.28)
    _bell(783.99, 0.14, 0.22)
    return out


def _synth_badge(rate=_RATE, dur=0.22):
    """Bell-like ding at 1320 Hz with harmonic, slow decay."""
    n = int(rate * dur)
    out = [0] * n
    for i in range(n):
        t = i / rate
        env = math.exp(-t * 5.5)
        s = (
            math.sin(2 * math.pi * 1320 * t) * 0.38
            + math.sin(2 * math.pi * 1980 * t) * 0.12
        ) * env
        out[i] = int(s * 32767)
    return out


def _synth_copy(rate=_RATE, dur=0.05):
    """Subtle 600 Hz pluck — used for copy / save actions."""
    n = int(rate * dur)
    out = [0] * n
    for i in range(n):
        t = i / rate
        env = math.exp(-t * 80.0)
        s = math.sin(2 * math.pi * 600 * t) * env * 0.35
        out[i] = int(s * 32767)
    return out


def _synth_error(rate=_RATE, dur=0.22):
    """Low buzzy descend 240 → 160 Hz."""
    n = int(rate * dur)
    out = [0] * n
    for i in range(n):
        t = i / rate
        u = t / dur
        freq = 240 - (240 - 160) * u
        env = math.exp(-t * 6.5)
        # soft saturated sine for the 'buzz' character
        s = math.tanh(2.5 * math.sin(2 * math.pi * freq * t)) * env * 0.34
        out[i] = int(s * 32767)
    return out


_SYNTH = {
    "click":    _synth_click,
    "toggle":   _synth_toggle,
    "open":     _synth_open,
    "close":    _synth_close,
    "success":  _synth_success,
    "complete": _synth_complete,
    "badge":    _synth_badge,
    "copy":     _synth_copy,
    "error":    _synth_error,
}


# ─── lifecycle ────────────────────────────────────────────────────────────

def _ensure_files(cache_dir):
    """Write any missing WAVs into cache_dir. Returns dict[kind] = path."""
    try:
        os.makedirs(cache_dir, exist_ok=True)
    except Exception:
        pass
    out = {}
    for kind, synth in _SYNTH.items():
        path = os.path.join(cache_dir, f"sfx_{kind}.wav")
        try:
            if not os.path.exists(path) or os.path.getsize(path) < 64:
                _write_wav(path, synth())
            out[kind] = path
        except Exception as e:
            _log(f"synth {kind} failed: {e}")
    return out


def init(context):
    """Pre-generate all SFX WAVs and load them into a SoundPool. Idempotent."""
    if _state.get("init_done"):
        return True

    try:
        from java import jclass
        AudioAttributes = jclass("android.media.AudioAttributes")
        SoundPool = jclass("android.media.SoundPool")
    except Exception as e:
        _log(f"jclass unavailable: {e}")
        return False

    try:
        cache_dir = str(context.getFilesDir()) + "/eblannft_sfx"
    except Exception:
        try:
            cache_dir = str(context.getCacheDir()) + "/eblannft_sfx"
        except Exception:
            _log("no cache dir, abort init")
            return False
    _state["cache_dir"] = cache_dir

    def _worker():
        try:
            paths = _ensure_files(cache_dir)
            if not paths:
                _log("no SFX paths produced")
                return

            attrs = (
                AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_ASSISTANCE_SONIFICATION)
                .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                .build()
            )
            pool = (
                SoundPool.Builder()
                .setMaxStreams(4)
                .setAudioAttributes(attrs)
                .build()
            )

            try:
                from java import dynamic_proxy
                _Listener = dynamic_proxy(SoundPool.OnLoadCompleteListener)

                class _OnLoad(_Listener):
                    def onLoadComplete(self_obj, sp, sample_id, status):
                        try:
                            for k, sid in list(_state["ids"].items()):
                                if int(sid) == int(sample_id):
                                    if int(status) == 0:
                                        _state["loaded"].add(k)
                                    break
                        except Exception:
                            pass
                pool.setOnLoadCompleteListener(_OnLoad())
            except Exception as e:
                _log(f"load-listener setup failed: {e}")

            for kind, path in paths.items():
                try:
                    sid = pool.load(path, 1)
                    _state["ids"][kind] = int(sid)
                except Exception as e:
                    _log(f"pool.load({kind}) failed: {e}")

            _state["pool"] = pool
            _state["init_done"] = True
            _log(f"SFX initialised: {len(_state['ids'])} clips in {cache_dir}")
        except Exception as e:
            _log(f"init worker failed: {e}")

    try:
        threading.Thread(target=_worker, daemon=True).start()
    except Exception:
        _worker()
    return True


def set_enabled(flag):
    _state["enabled"] = bool(flag)


def is_enabled():
    return bool(_state.get("enabled", True))


def play(kind="click", volume=1.0):
    """Play a previously-loaded SFX. No-op if SFX is disabled or not yet
    initialised. Returns True if the stream was actually queued."""
    if not _state.get("enabled", True):
        return False
    pool = _state.get("pool")
    sid = _state.get("ids", {}).get(kind)
    if pool is None or sid is None:
        return False
    if kind not in _state.get("loaded", set()):
        # Sample is still loading; SoundPool.play() will silently no-op
        # in that case, so we let it through rather than throwing.
        pass
    try:
        v = float(volume)
        if v < 0.0:
            v = 0.0
        if v > 1.0:
            v = 1.0
        pool.play(int(sid), v, v, 1, 0, 1.0)
        return True
    except Exception as e:
        _log(f"play({kind}) failed: {e}")
        return False
