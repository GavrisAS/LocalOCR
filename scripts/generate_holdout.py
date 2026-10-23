"""Generate private seeded images and canonical synthetic gold for local qualification."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from localocr.synthetic import generate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=713091)
    parser.add_argument("--count", type=int, default=8)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    manifest = []
    for index in range(args.count):
        case = generate(args.seed + index, simple=index < 2)
        name = f"synthetic-{index + 1:02d}.png"
        case.image.save(args.output / name)
        manifest.append(
            {
                "file": name,
                "seed": case.seed,
                "style": case.style,
                "rotation": case.rotation,
                "gold": asdict(case.gold),
            }
        )
    (args.output / "gold.json").write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
