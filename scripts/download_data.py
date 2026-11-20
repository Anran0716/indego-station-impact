"""Download and verify the pinned public inputs without running the analysis."""

from pathlib import Path

from stimpact.download import download_inputs

if __name__ == "__main__":
    download_inputs(Path(__file__).resolve().parents[1])
