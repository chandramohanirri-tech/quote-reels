"""Synthesize a few soft, sad piano + pad loops into music/ (original, copyright-free).

Usage: python make_music.py
Real royalty-free tracks (Pixabay Music, YouTube Audio Library) can be dropped
into music/ alongside these; make_reel.py picks one at random.
"""
import subprocess
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parent
SR = 44100

NOTE = {n: i for i, n in enumerate("C C# D D# E F F# G G# A A# B".split())}


def freq(name, octave):
    return 440.0 * 2 ** ((NOTE[name] + 12 * (octave + 1) - 69) / 12)


def piano(f, dur, vel=0.5):
    t = np.arange(int(SR * dur)) / SR
    tone = sum(a * np.sin(2 * np.pi * f * k * t) for k, a in [(1, 1), (2, 0.35), (3, 0.12), (4, 0.05)])
    env = np.minimum(t / 0.01, 1) * np.exp(-t * 1.6)
    return vel * tone * env


def pad(fs, dur):
    t = np.arange(int(SR * dur)) / SR
    tone = sum(np.sin(2 * np.pi * f * t + np.sin(2 * np.pi * 0.2 * t)) for f in fs) / len(fs)
    env = np.minimum(t / 1.5, 1) * np.minimum((dur - t) / 1.5, 1)
    return 0.12 * tone * env


# name: (folder, tempo, notes per beat, chords as (root, minor?)); each chord lasts 4 beats.
# sad/ is used for sad quotes, uplifting/ for motivation, inspiring and life quotes.
TRACKS = {
    "rain-piano": ("sad", 66, 1, [("A", 1), ("F", 0), ("C", 0), ("G", 0)]),
    "night-thoughts": ("sad", 66, 1, [("E", 1), ("C", 0), ("G", 0), ("D", 0)]),
    "letting-go": ("sad", 66, 1, [("D", 1), ("A#", 0), ("F", 0), ("C", 0)]),
    "quiet-heart": ("sad", 66, 1, [("C", 0), ("A", 1), ("F", 0), ("G", 0)]),
    "new-morning": ("uplifting", 96, 2, [("C", 0), ("G", 0), ("A", 1), ("F", 0)]),
    "rise-again": ("uplifting", 100, 2, [("D", 0), ("A", 0), ("B", 1), ("G", 0)]),
    "keep-going": ("uplifting", 92, 2, [("G", 0), ("D", 0), ("E", 1), ("C", 0)]),
    "golden-hour": ("uplifting", 88, 2, [("F", 0), ("C", 0), ("D", 1), ("A#", 0)]),
}


def chord_notes(root, minor):
    r = NOTE[root]
    third = 3 if minor else 4
    return [list(NOTE)[(r + i) % 12] for i in (0, third, 7)]


def render(name, folder, bpm, per_beat, chords, seed):
    rng = np.random.default_rng(seed)
    beat_len = 60 / bpm
    bar = 4 * beat_len
    total = bar * len(chords) * 2  # two passes
    out = np.zeros(int(SR * (total + 3)))
    for rep in range(2):
        for ci, (root, minor) in enumerate(chords):
            start = (rep * len(chords) + ci) * bar
            notes = chord_notes(root, minor)
            p = pad([freq(n, 3) for n in notes], bar + 1)
            i = int(SR * start)
            out[i:i + len(p)] += p
            # Bass note, then a gentle broken-chord melody.
            b = piano(freq(root, 2), bar, 0.35)
            out[i:i + len(b)] += b
            if per_beat == 1:
                pattern = [0, 1, 2, 1] if rep == 0 else [2, 1, 0, 2]
            else:  # brighter rising arpeggio
                pattern = [0, 1, 2, 3, 2, 1, 2, 3] if rep == 0 else [0, 2, 3, 2, 1, 2, 3, 3]
            step = beat_len / per_beat
            for k, idx in enumerate(pattern):
                name_, octave = (notes[0], 5) if idx == 3 else (notes[idx], 4)
                if per_beat == 1 and idx == 2 and rng.random() < 0.4:
                    octave = 5
                n = piano(freq(name_, octave), 2.5, 0.22 + 0.06 * rng.random())
                j = int(SR * (start + k * step))
                out[j:j + len(n)] += n
    out /= np.abs(out).max() * 1.1
    tmp = ROOT / "music" / folder / f"{name}.wav"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((out * 32767).astype(np.int16).tobytes())
    # Reverb + gentle low-pass for a soft, distant feel, then stereo mp3.
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp),
                    "-af", "aecho=0.8:0.7:60|120|240:0.35|0.25|0.15,lowpass=f=5000,"
                           f"afade=out:st={total - 1:.1f}:d=4,volume=1.6",
                    "-ac", "2", "-b:a", "160k", str(tmp.with_suffix(".mp3"))], check=True)
    tmp.unlink()


if __name__ == "__main__":
    for seed, (name, spec) in enumerate(TRACKS.items()):
        render(name, *spec, seed)
        print("made", name)
