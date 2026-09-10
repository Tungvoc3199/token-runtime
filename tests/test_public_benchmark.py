import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
CORPUS = REPO / "benchmarks" / "public-corpus"
RUNNER = REPO / "benchmarks" / "run_rd0b_offline.py"
FROZEN = REPO / "benchmarks" / "results" / "public-v1.json"


def run_public_benchmark(destination: Path) -> dict[str, object]:
    subprocess.run(
        ["python3", str(RUNNER), str(CORPUS), "--output", str(destination)],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(REPO / "src")},
    )
    return json.loads(destination.read_text(encoding="utf-8"))


class PublicBenchmarkTests(unittest.TestCase):
    def test_public_benchmark_is_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            first_path = Path(tmp) / "first.json"
            second_path = Path(tmp) / "second.json"
            first = run_public_benchmark(first_path)
            second = run_public_benchmark(second_path)
            self.assertEqual(first_path.read_bytes(), second_path.read_bytes())
            self.assertEqual(first, second)
            self.assertTrue(first["all_protected_fidelity"])
            self.assertTrue(first["all_recoverable"])
            self.assertEqual(first["corpus_cases"], 6)
            self.assertEqual(first_path.read_bytes(), FROZEN.read_bytes())

    def test_public_manifest_is_lexically_ordered_and_complete(self):
        manifest = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
        files = [item["file"] for item in manifest["trajectories"]]
        self.assertEqual(files, sorted(files))
        self.assertEqual(len(files), 6)
        for name in files:
            self.assertTrue((CORPUS / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
