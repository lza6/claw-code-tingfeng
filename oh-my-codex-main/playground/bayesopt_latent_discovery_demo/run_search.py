from __future__ import annotations

import argparse
import json

from optimizer import load_config, run_search


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=None)
    args = parser.parse_args()

    config = load_config(args.config)
    result = run_search(config)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
