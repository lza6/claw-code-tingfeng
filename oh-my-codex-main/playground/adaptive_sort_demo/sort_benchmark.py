from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

CONFIG_PATH = Path(__file__).with_name('config.json')


@dataclass
class Metrics:
    comparisons: int = 0
    moves: int = 0

    def score(self) -> float:
        return self.comparisons + 0.35 * self.moves


class Ops:
    def __init__(self) -> None:
        self.metrics = Metrics()

    def compare(self, a: int, b: int) -> int:
        self.metrics.comparisons += 1
        return (a > b) - (a < b)

    def move(self, count: int = 1) -> None:
        self.metrics.moves += count


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text())


def insertion_sort(values: list[int], ops: Ops) -> list[int]:
    arr = values[:]
    for i in range(1, len(arr)):
        key = arr[i]
        ops.move()
        j = i - 1
        while j >= 0 and ops.compare(arr[j], key) > 0:
            arr[j + 1] = arr[j]
            ops.move()
            j -= 1
        arr[j + 1] = key
        ops.move()
    return arr


def merge_sort(values: list[int], ops: Ops) -> list[int]:
    if len(values) <= 1:
        return values[:]
    mid = len(values) // 2
    left = merge_sort(values[:mid], ops)
    right = merge_sort(values[mid:], ops)
    out: list[int] = []
    i = j = 0
    while i < len(left) and j < len(right):
        if ops.compare(left[i], right[j]) <= 0:
            out.append(left[i])
            ops.move()
            i += 1
        else:
            out.append(right[j])
            ops.move()
            j += 1
    if i < len(left):
        out.extend(left[i:])
        ops.move(len(left) - i)
    if j < len(right):
        out.extend(right[j:])
        ops.move(len(right) - j)
    return out


def counting_sort(values: list[int], min_value: int, max_value: int, ops: Ops) -> list[int]:
    offset = min_value
    counts = [0] * (max_value - min_value + 1)
    ops.move(len(counts))
    for value in values:
        counts[value - offset] += 1
        ops.move()
    out: list[int] = []
    for index, count in enumerate(counts):
        if count:
            value = index + offset
            out.extend([value] * count)
            ops.move(count)
    return out


def longest_non_decreasing_run(values: list[int]) -> int:
    if not values:
        return 0
    best = current = 1
    for idx in range(1, len(values)):
        if values[idx - 1] <= values[idx]:
            current += 1
        else:
            best = max(best, current)
            current = 1
    return max(best, current)


def hybrid_sort(values: list[int], config: dict, ops: Ops) -> list[int]:
    params = dict(config.get('params', {}))
    insertion_threshold = int(params.get('insertion_threshold', 12))
    run_detection_min = int(params.get('run_detection_min', 10))
    counting_span_limit = int(params.get('counting_span_limit', 128))

    if len(values) <= insertion_threshold:
        return insertion_sort(values, ops)
    if values:
        min_value = min(values)
        max_value = max(values)
        if max_value - min_value <= counting_span_limit:
            return counting_sort(values, min_value, max_value, ops)
    if longest_non_decreasing_run(values) >= run_detection_min:
        return insertion_sort(values, ops)
    return merge_sort(values, ops)


def baseline_sort(values: list[int], _config: dict, ops: Ops) -> list[int]:
    return merge_sort(values, ops)


def build_cases() -> list[tuple[str, list[int], float]]:
    cases: list[tuple[str, list[int], float]] = []
    sizes = [32, 64, 96]
    for n in sizes:
        cases.append((f'random-{n}', [((i * 37 + 11) % 101) for i in range(n)], 1.0))
        cases.append((f'reverse-{n}', list(range(n, 0, -1)), 1.1))
        cases.append((f'nearly-sorted-{n}', [i if i % 9 else max(0, i - 3) for i in range(n)], 1.2))
        cases.append((f'duplicates-{n}', [((i * 7) % 8) for i in range(n)], 1.3))
        cases.append((f'low-cardinality-{n}', [((i * 13 + 5) % 16) for i in range(n)], 1.15))
    return cases


def evaluate_algorithm(algorithm: Callable[[list[int], dict, Ops], list[int]], config: dict) -> dict:
    total = 0.0
    per_case = []
    for name, values, weight in build_cases():
        ops = Ops()
        out = algorithm(values, config, ops)
        if out != sorted(values):
            raise AssertionError(f'incorrect sort output for {name}')
        weighted = weight * ops.metrics.score()
        total += weighted
        per_case.append({'case': name, 'weighted_cost': weighted})
    return {'total_cost': total, 'cases': per_case}


def run_config(config: dict) -> dict:
    algorithm_name = config.get('algorithm', 'hybrid_sort')
    if algorithm_name == 'hybrid_sort':
        result = evaluate_algorithm(hybrid_sort, config)
    elif algorithm_name == 'baseline_sort':
        result = evaluate_algorithm(baseline_sort, config)
    else:
        raise ValueError(f'unsupported algorithm: {algorithm_name}')
    result['algorithm'] = algorithm_name
    return result


def main() -> None:
    print(json.dumps(run_config(load_config())))


if __name__ == '__main__':
    main()
