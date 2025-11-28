import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.api.endpoints.download import _is_under, _is_under_any
from werkzeug.utils import secure_filename


def test_is_under_basic():
    root = os.path.join(os.getcwd(), "DownloadRoot")
    sub = os.path.join(root, "subdir", "file.txt")
    os.makedirs(os.path.join(root, "subdir"), exist_ok=True)
    assert _is_under(root, sub) is True


def test_is_under_blocks_root_equal():
    root = os.path.join(os.getcwd(), "DownloadRoot")
    assert _is_under(root, root) is False


def test_is_under_prevents_escape_via_dotdot():
    root = os.path.join(os.getcwd(), "DownloadRoot")
    outside = os.path.join(root, "..", "evil.txt")
    assert _is_under(root, outside) is False


def test_is_under_any_basic():
    base = os.path.join(os.getcwd(), "DownloadRoot")
    tmp = os.path.join(os.getcwd(), "TempRoot")
    os.makedirs(base, exist_ok=True)
    os.makedirs(tmp, exist_ok=True)
    p = os.path.join(base, "a", "b", "c.txt")
    os.makedirs(os.path.join(base, "a", "b"), exist_ok=True)
    assert _is_under_any(p, [base, tmp]) is True


def test_secure_filename_sanitizes():
    raw = "../..\\evil/name.mp4"
    safe = secure_filename(raw)
    assert safe == "evil_name.mp4"

