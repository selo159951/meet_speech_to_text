"""Decode any audio/video file to 16 kHz mono (PyAV) and write an mp3 for playback."""
from __future__ import annotations

from pathlib import Path

import av
import numpy as np


def convert(src: Path, playback_mp3: Path) -> tuple[np.ndarray, float]:
    """Return (float32 mono 16 kHz samples, duration seconds); also writes playback_mp3."""
    chunks: list[np.ndarray] = []
    try:
        inp = av.open(str(src))
    except av.error.FFmpegError:
        raise ValueError("This file is not a supported audio/video format") from None
    with inp:
        stream = next((s for s in inp.streams if s.type == "audio"), None)
        if stream is None:
            raise ValueError("This file has no audio track")
        res16 = av.AudioResampler(format="s16", layout="mono", rate=16000)
        with av.open(str(playback_mp3), "w") as out:
            ostream = out.add_stream("libmp3lame", rate=16000)
            ostream.layout = "mono"
            ostream.bit_rate = 64000
            for frame in inp.decode(stream):
                frame.pts = None
                for f in res16.resample(frame):
                    chunks.append(f.to_ndarray().reshape(-1))
                    for pkt in ostream.encode(f):
                        out.mux(pkt)
            for f in res16.resample(None):
                chunks.append(f.to_ndarray().reshape(-1))
                for pkt in ostream.encode(f):
                    out.mux(pkt)
            for pkt in ostream.encode(None):
                out.mux(pkt)
    if not chunks:
        raise ValueError("No audio found in file")
    pcm = np.concatenate(chunks).astype(np.float32) / 32768.0
    return pcm, len(pcm) / 16000.0
