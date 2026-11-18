import threading
from concurrent.futures import ThreadPoolExecutor

import av
import numpy as np
import pytest

from vox import audioio


@pytest.fixture
def stereo():
    t = np.arange(44100, dtype=np.float64) / 44100
    return np.stack([0.32 * np.sin(2 * np.pi * hz * t) for hz in (440, 1331)], axis=1).astype("f4")


@pytest.mark.parametrize(
    "fmt,depth", [("wav", 16), ("wav", 24), ("wav", 32), ("flac", 16), ("flac", 24)]
)
@pytest.mark.parametrize("rate", audioio.OUTPUT_RATES)
def test_pcm(tmp_path, stereo, fmt, depth, rate):
    out = tmp_path / f"原始录音.{fmt}"
    audioio.encode(out, stereo, 44100, depth, output_rate=rate)
    result, info = audioio.decode(out)
    assert (info["sample_rate"], info["bit_depth"], info["channels"]) == (rate, depth, 2)
    assert result.shape == stereo.shape
    # Conversion filters need a handful of samples to settle at each edge.
    assert np.max(abs(result[100:-100] - stereo[100:-100])) < 0.0001


@pytest.mark.parametrize("fmt,rate", [("mp3", 44100), ("aac", 96000), ("m4a", 48000)])
def test_lossy(tmp_path, stereo, fmt, rate):
    out = tmp_path / ("输出." + fmt)
    audioio.encode(out, stereo, 44100, output_rate=rate)
    result, info = audioio.decode(out)
    assert info["sample_rate"] == rate
    assert info["bit_depth"] is None
    # Raw ADTS has no encoder-delay metadata; M4A does.
    if fmt == "aac":
        assert abs(len(result) - len(stereo)) < 2048
    else:
        assert result.shape == stereo.shape
        assert np.corrcoef(result[:, 1], stereo[:, 1])[0, 1] > 0.99
    for ch, hz in enumerate((440, 1331)):
        middle = result[3000:32000, ch]
        measured = np.argmax(abs(np.fft.rfft(middle * np.hanning(len(middle))))) * 44100 / len(middle)
        assert abs(measured - hz) < 2


@pytest.mark.parametrize("fmt,codec,rate", [("ogg", "libopus", 48000), ("aiff", "pcm_s16be", 44100)])
def test_external_layouts(tmp_path, stereo, fmt, codec, rate):
    out = tmp_path / ("音轨." + fmt)
    with av.open(str(out), "w") as container:
        stream = container.add_stream(codec, rate=rate)
        stream.layout = "mono"
        frame = av.AudioFrame.from_ndarray(
            stereo[:, 0].copy().reshape(1, -1), format="flt", layout="mono"
        )
        frame.sample_rate = 44100
        for packet in [*stream.encode(frame), *stream.encode(None)]:
            container.mux(packet)
    pcm, info = audioio.decode(out)
    assert info["channels"] == 1
    assert len(pcm) == 44100
    assert np.array_equal(pcm[:, 0], pcm[:, 1])
    assert 0.3 < np.max(pcm) < 0.35


def test_disk_backed_decode(tmp_path, stereo, monkeypatch):
    monkeypatch.setattr(audioio, "_SPOOL_BYTES", 4096)
    out = tmp_path / "长轨.wav"
    audioio.encode(out, stereo, 44100, 32)
    pcm, _ = audioio.decode(out)
    assert isinstance(pcm, np.memmap)
    assert np.array_equal(pcm, stereo)


def test_no_replace_and_cleanup(tmp_path, stereo):
    out = tmp_path / "录音.wav"
    out.write_bytes(b"original")
    with pytest.raises(FileExistsError):
        audioio.encode(out, stereo, 44100)
    assert out.read_bytes() == b"original"
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(InterruptedError):
        audioio.decode(out, cancelled)
    with pytest.raises(InterruptedError):
        audioio.encode(tmp_path / "导出.wav", stereo, 44100, cancel=cancelled)
    broken = stereo.copy()
    broken[-5, 0] = np.nan
    with pytest.raises(ValueError):
        audioio.encode(tmp_path / "导出.wav", broken, 44100)
    assert list(tmp_path.iterdir()) == [out]


def test_two_writers(tmp_path, stereo):
    path = tmp_path / "同名.wav"

    def attempt():
        try:
            audioio.encode(path, stereo, 44100)
            return True
        except FileExistsError:
            return False

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(lambda _: attempt(), range(2))) == [False, True]
    assert audioio.decode(path)[0].shape == stereo.shape


def test_channels_and_codec_limits(tmp_path, stereo):
    out = tmp_path / "mono.wav"
    audioio.encode(out, stereo, 44100, 32, channels=1)
    mono, info = audioio.decode(out)
    assert np.allclose(mono[:, 0], stereo.mean(axis=1))
    assert info["channels"] == 1
    with pytest.raises(ValueError):
        audioio.encode(tmp_path / "不支持.mp3", stereo, 44100, output_rate=96000)
