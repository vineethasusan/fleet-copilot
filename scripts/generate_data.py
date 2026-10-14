"""CLI wrapper: python scripts/generate_data.py --out data/fleet.db --seed 42"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fleet_copilot.synthetic import build  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Generate the synthetic fleet database")
    ap.add_argument("--out", default="data/fleet.db")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--scale", type=float, default=1.0, help="Multiply fleet sizes")
    a = ap.parse_args()
    print(build(Path(a.out), a.seed, a.scale))
