import logging
from io import BytesIO
import wave

from google.cloud import storage

from .settings import BUCKET_NAME
from .utils import unmarshal

client = storage.Client()

bucket = client.get_bucket(BUCKET_NAME)

if not bucket.exists():
    logging.error("There's no GCS Bucket to upload to")


def upload_audio(path: str, data: str):
    """Upload wav file from marshalled string data"""
    blob = bucket.blob(path)
    blob.upload_from_string(
        data=unmarshal(data),
        content_type="audio/wav",
    )


def get_audio(filepath: str) -> bytes:
    """Download wav file from prompts folder"""
    # prompts/default/hogehoge.wav
    blob = bucket.blob(filepath)
    if not blob.exists():
        logging.error("No prompts for %s", f"{filepath}.wav")

    audio = blob.download_as_bytes()
    return audio


def concatenate_audio(*filepaths: str) -> bytes:
    """Synthesize multiple audio files with same params"""
    outfile = BytesIO()

    with wave.open(outfile, "wb") as out_wf:
        for filepath in filepaths:
            infile = get_audio(filepath)
            with wave.open(BytesIO(infile), "rb") as in_wf:
                if outfile.getvalue() == b"":
                    out_wf.setparams(in_wf.getparams())  # pylint: disable=no-member
                frames = in_wf.readframes(in_wf.getnframes())
                out_wf.writeframes(frames)  # pylint: disable=no-member

    return outfile.getvalue()


def get_uri(path: str) -> (str, str):
    blob = bucket.blob(path)
    if not blob.exists():
        logging.error("GCS Blob (%s) doesn't exist", path)
    uri = f"gs://{BUCKET_NAME}/{blob.name}"
    return uri, blob.public_url
