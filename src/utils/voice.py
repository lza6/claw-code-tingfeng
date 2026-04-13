"""Voice - Audio input from Aider

Adapted from aider/voice.py
Provides: Audio recording and transcription via microphone
"""

import contextlib
import math
import os
import queue
import tempfile
import time


class SoundDeviceError(Exception):
    """Raised when sound device is not available."""
    pass


class Voice:
    """Voice input handler for audio recording and transcription."""

    max_rms = 0
    min_rms = 1e5
    pct = 0
    threshold = 0.15

    def __init__(self, audio_format="wav", device_name=None):
        self.audio_format = audio_format
        self.device_name = device_name
        self.sd = None
        self._check_dependencies()

    def _check_dependencies(self):
        """Check if required dependencies are available."""
        try:
            import soundfile as sf
        except (OSError, ModuleNotFoundError):
            raise SoundDeviceError("soundfile not installed")

        try:
            import sounddevice as sd
            self.sd = sd
        except (OSError, ModuleNotFoundError):
            raise SoundDeviceError("sounddevice not installed")

    def get_available_devices(self):
        """Get list of available audio input devices."""
        if not self.sd:
            return []
        try:
            devices = self.sd.query_devices()
            return [d for d in devices if d.get("max_input_channels", 0) > 0]
        except Exception:
            return []

    def callback(self, indata, frames, time_info, status):
        """Audio callback for recording."""
        import numpy as np

        rms = np.sqrt(np.mean(indata**2))
        self.max_rms = max(self.max_rms, rms)
        self.min_rms = min(self.min_rms, rms)

        rng = self.max_rms - self.min_rms
        if rng > 0.001:
            self.pct = (rms - self.min_rms) / rng
        else:
            self.pct = 0.5

        self.q.put(indata.copy())

    def get_prompt(self):
        """Get the recording prompt with progress bar."""
        num = 10
        if math.isnan(self.pct) or self.pct < self.threshold:
            cnt = 0
        else:
            cnt = int(self.pct * 10)

        bar = "░" * cnt + "█" * (num - cnt)
        dur = time.time() - self.start_time
        return f"Recording, press ENTER when done... {dur:.1f}sec {bar}"

    def record(self, sample_rate=16000):
        """Record audio from microphone and return the audio file path."""
        self.q = queue.Queue()
        temp_wav = tempfile.mktemp(suffix=".wav")

        # Get sample rate from device or use default
        try:
            if self.device_name:
                device_id = self._find_device_id(self.device_name)
            else:
                device_id = None

            if device_id is not None:
                device_info = self.sd.query_devices(device_id, "input")
                sample_rate = int(device_info.get("default_samplerate", sample_rate))
        except Exception:
            pass

        self.start_time = time.time()

        try:
            with self.sd.InputStream(
                samplerate=sample_rate,
                channels=1,
                callback=self.callback,
                device=device_id
            ):
                from prompt_toolkit.shortcuts import prompt
                prompt(self.get_prompt, refresh_interval=0.1)
        except Exception as e:
            raise SoundDeviceError(f"Error accessing audio: {e}")

        # Write recorded audio to file
        import soundfile as sf
        with sf.SoundFile(temp_wav, mode="x", samplerate=sample_rate, channels=1) as f:
            while not self.q.empty():
                f.write(self.q.get())

        return temp_wav

    def _find_device_id(self, device_name):
        """Find device ID by name."""
        devices = self.sd.query_devices()
        for i, device in enumerate(devices):
            if device_name in device.get("name", ""):
                return i
        return None

    def transcribe(self, audio_path, history=None, language=None):
        """Transcribe audio file using OpenAI Whisper."""
        try:
            from src.llm import litellm
        except ImportError:
            # Fallback to direct import
            try:
                import litellm
            except ImportError:
                return None

        with open(audio_path, "rb") as f:
            try:
                response = litellm.transcription(
                    model="whisper-1",
                    file=f,
                    prompt=history,
                    language=language
                )
                return response.text
            except Exception as e:
                print(f"Transcription error: {e}")
                return None

    def record_and_transcribe(self, history=None, language=None):
        """Record audio and transcribe in one step."""
        try:
            audio_path = self.record()
            if not audio_path:
                return None

            text = self.transcribe(audio_path, history, language)

            # Cleanup
            with contextlib.suppress(OSError):
                os.remove(audio_path)

            return text
        except SoundDeviceError as e:
            print(f"Sound device error: {e}")
            return None
        except KeyboardInterrupt:
            return None


def is_available():
    """Check if voice input is available."""
    try:
        Voice()
        return True
    except SoundDeviceError:
        return False


__all__ = [
    "SoundDeviceError",
    "Voice",
    "is_available",
]
