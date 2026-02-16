from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from core.config import Config

HUGGINGFACE_PROGRESS_PERCENT_PATTERN = re.compile(r"(\d{1,3}(?:\.\d+)?)%")


def parse_huggingface_progress_percent(output: str) -> float | None:
    matches = HUGGINGFACE_PROGRESS_PERCENT_PATTERN.findall(output or "")
    if not matches:
        return None
    try:
        value = float(matches[-1])
    except ValueError:
        return None
    return max(0.0, min(100.0, value))


def vllm_local_model_container_path(model_dir_name: str) -> str:
    root = Path(Config.VLLM_LOCAL_CUSTOM_MODELS_DIR).as_posix().rstrip("/")
    return f"{root}/{model_dir_name}"


def vllm_local_model_directory(model_dir_name: str) -> Path:
    custom_root = Path(Config.VLLM_LOCAL_CUSTOM_MODELS_DIR).resolve()
    return (custom_root / model_dir_name).resolve()


def model_directory_has_downloaded_contents(model_dir: Path) -> bool:
    if not model_dir.exists():
        return False
    if (model_dir / "model.json").is_file():
        return True
    try:
        next(model_dir.iterdir())
        return True
    except (OSError, StopIteration):
        return False


def run_huggingface_model_download(
    model_id: str,
    model_dir_name: str,
    *,
    token: str = "",
    model_container_path: str,
    progress_callback=None,
) -> None:
    def _emit(
        summary: str,
        *,
        phase: str,
        percent: float | None = None,
        raw_line: str = "",
    ) -> None:
        if progress_callback is None:
            return
        payload: dict[str, object] = {"summary": summary, "phase": phase}
        if percent is not None:
            payload["percent"] = percent
        if raw_line:
            payload["raw_line"] = raw_line
        progress_callback(payload)

    models_root = Path(Config.VLLM_LOCAL_CUSTOM_MODELS_DIR).resolve()
    model_target = vllm_local_model_directory(model_dir_name)
    try:
        model_target.relative_to(models_root)
    except ValueError as exc:
        raise ValueError(
            "Requested HuggingFace model directory is outside configured custom models root."
        ) from exc
    models_root.mkdir(parents=True, exist_ok=True)
    model_target.mkdir(parents=True, exist_ok=True)

    python_bin = "python3"
    _emit("Checking HuggingFace download dependencies.", phase="preparing", percent=2.0)
    check_hf = subprocess.run(
        [python_bin, "-c", "import huggingface_hub"],
        capture_output=True,
        text=True,
    )
    if check_hf.returncode != 0:
        venv_dir = models_root / ".download-venv"
        venv_python = venv_dir / "bin" / "python"
        if not venv_python.exists():
            _emit("Creating download virtualenv.", phase="preparing", percent=4.0)
            subprocess.run(
                [python_bin, "-m", "venv", str(venv_dir)],
                check=True,
                capture_output=True,
                text=True,
            )
        _emit("Installing huggingface_hub in local virtualenv.", phase="preparing", percent=8.0)
        subprocess.run(
            [str(venv_python), "-m", "pip", "install", "--upgrade", "pip", "huggingface_hub"],
            check=True,
            capture_output=True,
            text=True,
        )
        python_bin = str(venv_python)

    download_code = (
        "import os\n"
        "from huggingface_hub import snapshot_download\n"
        "snapshot_download("
        "repo_id=os.environ['MODEL_ID'], "
        "local_dir=os.environ['MODEL_TARGET_DIR'], "
        "token=(os.environ.get('HF_TOKEN') or os.environ.get('HUGGING_FACE_HUB_TOKEN'))"
        ")\n"
    )
    env = os.environ.copy()
    env.update(
        {
            "MODEL_ID": model_id,
            "MODEL_TARGET_DIR": str(model_target),
        }
    )
    if token:
        env["HF_TOKEN"] = token
    command = [python_bin, "-u", "-c", download_code]
    _emit(f"Downloading {model_id} from HuggingFace.", phase="downloading", percent=10.0)
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        bufsize=1,
        env=env,
    )
    captured_lines: list[str] = []
    assert process.stdout is not None
    buffer = ""
    while True:
        chunk = process.stdout.read(1)
        if chunk == "":
            if process.poll() is not None:
                break
            continue
        if chunk not in {"\n", "\r"}:
            buffer += chunk
            continue
        line = buffer.strip()
        buffer = ""
        if not line:
            continue
        captured_lines.append(line)
        if len(captured_lines) > 200:
            captured_lines.pop(0)
        raw_percent = parse_huggingface_progress_percent(line)
        if raw_percent is not None:
            effective_percent = 10.0 + (raw_percent * 0.85)
            _emit(
                f"{model_id} download {raw_percent:.0f}%",
                phase="downloading",
                percent=effective_percent,
                raw_line=line,
            )
            continue
        lowered = line.lower()
        if "file" in lowered or "download" in lowered:
            _emit(
                line[:240],
                phase="downloading",
                raw_line=line,
            )
    trailing_line = buffer.strip()
    if trailing_line:
        captured_lines.append(trailing_line)
        if len(captured_lines) > 200:
            captured_lines.pop(0)
    return_code = process.wait()
    if return_code != 0:
        captured_output = "\n".join(captured_lines)
        raise subprocess.CalledProcessError(
            return_code,
            command,
            output=captured_output,
            stderr=captured_output,
        )

    _emit("Writing local model manifest.", phase="finalizing", percent=97.0)
    manifest = {
        "name": model_id.split("/")[-1] or model_id,
        "model": model_container_path,
        "description": f"Downloaded from {env['MODEL_ID']} by provider settings action.",
    }
    (model_target / "model.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    _emit("Download complete.", phase="succeeded", percent=100.0)


def summarize_subprocess_error(exc: subprocess.CalledProcessError) -> str:
    detail = (exc.stderr or exc.stdout or "").strip()
    if detail:
        return detail.splitlines()[-1]
    return "See server logs for details."
