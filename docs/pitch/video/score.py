"""Synthesises the 60 s soundtrack (score.wav) in plain Python: tension while the agent is hijacked, a hush and a
sub-drop on BLOCK (31.4 s), then a calm major resolve. Timings match the scenes in index.html."""
import math
import random
import struct
import wave

SR, DUR = 44100, 60.0
HIT = 31.4
N = int(SR * DUR)
TAU = 2 * math.pi
random.seed(3)


def env(t, a, b, fade=1.0):
    """1 inside [a, b], smooth ramps of `fade` seconds at both ends."""
    if t < a - fade or t > b + fade:
        return 0.0
    x = min(1.0, (t - (a - fade)) / fade, ((b + fade) - t) / fade)
    return 0.5 - 0.5 * math.cos(math.pi * max(0.0, x))


MINOR = [55.0, 82.41, 110.0, 130.81]          # A minor: tension
MAJOR = [65.41, 98.0, 130.81, 164.81, 196.0]  # C major: resolve

left, right = [], []
noise_lp = 0.0
for i in range(N):
    t = i / SR
    s = 0.0
    # drone, slowly swelling until the hit
    if t < HIT:
        g = 0.05 + 0.10 * (t / HIT) ** 1.5
        trem = 0.8 + 0.2 * math.sin(TAU * (0.3 + t * 0.05) * t)
        for k, f in enumerate(MINOR):
            s += g * trem * math.sin(TAU * f * t + k) / (k + 1)
    # heartbeat pulse, accelerating from the poisoned contract to the gate
    if 8 <= t < HIT - 0.5:
        bpm = 60 + (t - 8) / (HIT - 8) * 70
        ph = (t * bpm / 60) % 1.0
        s += 0.35 * env(t, 9, HIT - 1.2, 1.0) * math.exp(-ph * 14) * math.sin(TAU * 50 * ph / (bpm / 60))
    # rising shimmer as Aegis draws itself
    if 20 <= t < HIT:
        s += 0.03 * env(t, 21, HIT - 0.6, 1.2) * math.sin(TAU * (440 + (t - 20) * 30) * t) * (0.5 + 0.5 * math.sin(TAU * 6 * t))
    # the hit: sub drop + noise burst
    if t >= HIT:
        dt = t - HIT
        f = 30 + 70 * math.exp(-dt * 3)
        s += 0.9 * math.exp(-dt * 1.6) * math.sin(TAU * f * dt)
        n = random.uniform(-1, 1)
        noise_lp += (n - noise_lp) * 0.08
        s += 0.6 * math.exp(-dt * 6) * noise_lp
    # resolve
    if t >= 33:
        g = 0.07 * env(t, 34.5, 58.5, 1.5) * (1.0 if t < 43 else 1.4)
        for k, f in enumerate(MAJOR):
            s += g * math.sin(TAU * f * t + 0.3 * math.sin(TAU * 0.2 * t + k)) / (1 + 0.6 * k)
        # soft bell notes on proof (37 s), zero over budget (48 s), tagline (54 s)
        for at, f in ((37.6, 523.25), (47.8, 659.25), (54.0, 783.99), (54.4, 1046.5)):
            if t >= at:
                d = t - at
                s += 0.12 * math.exp(-d * 1.8) * math.sin(TAU * f * d)
    s *= env(t, 0.6, DUR - 1.4, 0.6)
    s = math.tanh(s * 1.4) * 0.8
    pan = 0.12 * math.sin(TAU * 0.07 * t)
    left.append(s * (1 - pan))
    right.append(s * (1 + pan))

with wave.open("score.wav", "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(b"".join(struct.pack("<hh", int(l * 32000), int(r * 32000)) for l, r in zip(left, right)))
print("score.wav", DUR, "s")
