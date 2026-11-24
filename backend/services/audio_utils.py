import audioop
import io
import wave


def create_wav_from_mulaw(mulaw_bytes: bytes, sample_rate: int = 8000) -> bytes:
    """
    Converts raw 8-bit mu-law PCM from Twilio to a valid 16-bit PCM WAV file.
    Sarvam AI STT requires a valid WAV file.
    """
    # Convert mu-law to 16-bit linear PCM
    pcm_bytes = audioop.ulaw2lin(mulaw_bytes, 2)

    # Write to a WAV container in memory
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2) # 16-bit
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_bytes)

    return buf.getvalue()

def create_mulaw_from_wav(wav_bytes: bytes) -> bytes:
    """
    Converts a standard WAV file from Sarvam AI TTS to raw 8-bit mu-law for Twilio.
    """
    buf = io.BytesIO(wav_bytes)
    try:
        with wave.open(buf, 'rb') as wav_file:
            channels = wav_file.getnchannels()
            sampwidth = wav_file.getsampwidth()
            framerate = wav_file.getframerate()
            frames = wav_file.readframes(wav_file.getnframes())
    except wave.Error:
        # If it's not a valid WAV, just return empty
        return b""

    # Convert stereo to mono if needed
    if channels == 2:
        frames = audioop.tomono(frames, sampwidth, 1, 1)

    # Convert to 16-bit if it's 8-bit or 24-bit/32-bit (rare but possible)
    if sampwidth != 2:
        # Simplified: If not 16-bit, audioop lin2lin can convert
        frames = audioop.lin2lin(frames, sampwidth, 2)

    # Convert sample rate to 8000 Hz for Twilio
    if framerate != 8000:
        frames, _ = audioop.ratecv(frames, 2, 1, framerate, 8000, None)

    # Finally, convert to mu-law
    return audioop.lin2ulaw(frames, 2)
