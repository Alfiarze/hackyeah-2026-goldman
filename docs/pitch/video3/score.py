"""Synthesises the 180 s soundtrack (score.wav) for the 3-minute pitch: a quiet bed through the problem and the
insight, a lift under the proof (act 4, 110-150 s) with a hit on the blocked contract (116.2 s), and a calm major
resolve on the end card. Plain Python, no copyrighted material."""
import math
import random
import struct
import wave

SR, DUR = 44100, 180.0
HIT = 116.2
TAU = 2 * math.pi
random.seed(3)


def env(t, a, b, fade=1.0):
    if t < a - fade or t > b + fade:
        return 0.0
    x = min(1.0, (t - (a - fade)) / fade, ((b + fade) - t) / fade)
    return 0.5 - 0.5 * math.cos(math.pi * max(0.0, x))


MINOR = [55.0, 82.41, 110.0, 130.81]
MAJOR = [65.41, 98.0, 130.81, 164.81, 196.0]
BELLS = [(9.4, 523.25), (35.6, 659.25), (44.6, 587.33), (66.0, 659.25), (100.6, 783.99), (123.8, 523.25),
         (141.0, 659.25), (158.4, 783.99), (173.8, 783.99), (174.2, 1046.5)]

left, right = [], []
noise_lp = 0.0
for i in range(int(SR * DUR)):
    t = i / SR
    s = 0.0
    # bed: minor drone, slowly breathing, quieter after the hit until the resolve
    g = (0.06 + 0.03 * math.sin(TAU * t / 40)) * (1.0 if t < HIT else 0.5) * (1 - env(t, 152, 180, 3))
    for k, f in enumerate(MINOR):
        s += g * math.sin(TAU * f * t + k) / (k + 1)
    # pulse under the problem and under the proof
    for a, b, bpm0, bpm1 in ((10, 30, 60, 80), (110.5, HIT - 0.4, 80, 132)):
        if a <= t < b:
            bpm = bpm0 + (t - a) / (b - a) * (bpm1 - bpm0)
            ph = (t * bpm / 60) % 1.0
            s += 0.28 * env(t, a + 1, b - 0.6, 0.8) * math.exp(-ph * 14) * math.sin(TAU * 50 * ph / (bpm / 60))
    # lift under act 4
    if 110 <= t < 150:
        s += 0.035 * env(t, 112, 148, 2) * math.sin(TAU * (330 + (t - 110) * 2) * t) * (0.5 + 0.5 * math.sin(TAU * 5 * t))
    # the hit
    if t >= HIT and t < HIT + 4:
        dt = t - HIT
        s += 0.9 * math.exp(-dt * 1.6) * math.sin(TAU * (30 + 70 * math.exp(-dt * 3)) * dt)
        noise_lp += (random.uniform(-1, 1) - noise_lp) * 0.08
        s += 0.6 * math.exp(-dt * 6) * noise_lp
    # resolve from act 5
    if t >= 148:
        gm = 0.07 * env(t, 151, 178.6, 2)
        for k, f in enumerate(MAJOR):
            s += gm * math.sin(TAU * f * t + 0.3 * math.sin(TAU * 0.2 * t + k)) / (1 + 0.6 * k)
    for at, f in BELLS:
        if at <= t < at + 4:
            s += 0.1 * math.exp(-(t - at) * 1.8) * math.sin(TAU * f * (t - at))
    s *= env(t, 0.6, DUR - 1.4, 0.6)
    s = math.tanh(s * 1.4) * 0.8
    pan = 0.12 * math.sin(TAU * 0.05 * t)
    left.append(s * (1 - pan))
    right.append(s * (1 + pan))

with wave.open("score.wav", "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(b"".join(struct.pack("<hh", int(l * 32000), int(r * 32000)) for l, r in zip(left, right)))
print("score.wav", DUR, "s")
