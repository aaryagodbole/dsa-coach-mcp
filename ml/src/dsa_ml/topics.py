"""One topic list for every judge.

Each judge names topics its own way ("dp" on Codeforces, "dynamic-programming" on
LeetCode). Skills are tracked per common topic, so practice on one judge counts on
another. Tags with no entry here are ignored rather than guessed.
"""

from __future__ import annotations

# Common topic -> each judge's own tags for it.
TOPICS: dict[str, dict[str, tuple[str, ...]]] = {
    "math": {
        "codeforces": (
            "math",
            "number theory",
            "combinatorics",
            "probabilities",
            "matrices",
            "fft",
            "chinese remainder theorem",
        ),
        "leetcode": (
            "math",
            "number-theory",
            "combinatorics",
            "probability-and-statistics",
            "matrix",
        ),
    },
    "greedy": {"codeforces": ("greedy",), "leetcode": ("greedy",)},
    "dynamic programming": {
        "codeforces": ("dp",),
        "leetcode": ("dynamic-programming", "memoization", "bitmask"),
    },
    "graphs": {
        "codeforces": ("graphs", "shortest paths", "graph matchings", "flows", "2-sat"),
        "leetcode": (
            "graph",
            "shortest-path",
            "topological-sort",
            "eulerian-circuit",
            "minimum-spanning-tree",
            "strongly-connected-component",
            "biconnected-component",
        ),
    },
    "trees": {
        "codeforces": ("trees",),
        "leetcode": ("tree", "binary-tree", "binary-search-tree"),
    },
    "search": {
        "codeforces": ("dfs and similar",),
        "leetcode": ("depth-first-search", "breadth-first-search", "backtracking"),
    },
    "binary search": {
        "codeforces": ("binary search", "ternary search"),
        "leetcode": ("binary-search",),
    },
    "data structures": {
        "codeforces": ("data structures", "dsu"),
        "leetcode": (
            "stack",
            "queue",
            "heap-priority-queue",
            "union-find",
            "segment-tree",
            "binary-indexed-tree",
            "monotonic-stack",
            "monotonic-queue",
            "ordered-set",
            "linked-list",
            "trie",
            "hash-table",
            "design",
        ),
    },
    "strings": {
        "codeforces": ("strings", "hashing", "string suffix structures"),
        "leetcode": ("string", "string-matching", "rolling-hash", "suffix-array"),
    },
    "sorting": {
        "codeforces": ("sortings",),
        "leetcode": ("sorting", "counting-sort", "bucket-sort", "radix-sort", "merge-sort"),
    },
    "two pointers": {
        "codeforces": ("two pointers",),
        "leetcode": ("two-pointers", "sliding-window"),
    },
    "implementation": {
        "codeforces": ("implementation", "brute force"),
        "leetcode": ("simulation", "enumeration", "array"),
    },
    "constructive": {"codeforces": ("constructive algorithms",), "leetcode": ()},
    "bits": {"codeforces": ("bitmasks",), "leetcode": ("bit-manipulation",)},
    "geometry": {"codeforces": ("geometry",), "leetcode": ("geometry",)},
    "games": {"codeforces": ("games",), "leetcode": ("game-theory",)},
    "divide and conquer": {
        "codeforces": ("divide and conquer",),
        "leetcode": ("divide-and-conquer", "recursion"),
    },
    "prefix sums": {"codeforces": (), "leetcode": ("prefix-sum",)},
    "interactive": {"codeforces": ("interactive",), "leetcode": ("interactive",)},
}

NAMES = sorted(TOPICS)
_INDEX = {
    (judge, tag): NAMES.index(topic)
    for topic, judges in TOPICS.items()
    for judge, tags in judges.items()
    for tag in tags
}


def topic_ids(judge: str, tags: list[str]) -> list[int]:
    """The common topics a problem's own tags belong to, each once."""

    return sorted({_INDEX[(judge, t)] for t in tags if (judge, t) in _INDEX})
