"""Online topic Elo: the solve-probability model dsa-coach ships.

P(first-try solve) = sigmoid(bias + skill[user] + mean(topic_skill[user, t] for t in
problem's topics) - difficulty[problem])

It is the Elo form of the Rasch model (Pelánek), extended with a skill per common topic
in the spirit of multidimensional Elo and Performance Factor Analysis. Everything is
learned online, one attempt at a time, so each prediction uses only earlier attempts:
the platform's base rate (bias) too, which a new platform cannot know in advance.

A problem's difficulty starts from its judge's published rating where one exists. Both
Codeforces and AtCoder publish Elo-style ratings, where a 400-point gap is a factor of
10 in odds, so ``rating * ln(10) / 400`` puts them on the model's logit scale.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

ELO_TO_LOGIT = math.log(10) / 400


@dataclass(frozen=True)
class Settings:
    k_user: float = 0.4
    k_topic: float = 0.2
    k_problem: float = 0.05
    k_bias: float = 0.002
    # How strongly a published rating is believed, in attempts' worth of evidence, and
    # how it maps to the model's scale (1.0 = the judge's own Elo scale).
    prior_attempts: float = 20.0
    prior_scale: float = 1.0
    # Starting base rate for a platform nothing is known about: the training judges'.
    start_rate: float = 0.65


def run(
    users: np.ndarray,
    problems: np.ndarray,
    problem_topics: list[list[int]],
    y: np.ndarray,
    rating: np.ndarray,
    settings: Settings = Settings(),
) -> dict[str, np.ndarray]:
    """Replay attempts in time order and predict each before seeing its outcome.

    users, problems: integer codes per attempt. problem_topics: each problem code's
    common topic ids. rating: each problem code's published rating, NaN if none."""

    s = settings
    n_users = users.max() + 1
    known = ~np.isnan(rating)
    center = np.nanmedian(rating) if known.any() else 0.0
    difficulty = np.where(known, s.prior_scale * ELO_TO_LOGIT * (rating - center), 0.0)
    seen_problem = np.where(known, s.prior_attempts, 0.0)
    skill = np.zeros(n_users)
    seen_user = np.zeros(n_users)
    topic_skill: dict[tuple[int, int], float] = {}
    bias = math.log(s.start_rate / (1 - s.start_rate))

    pred = np.empty(len(y))
    skill_at = np.empty(len(y))
    topic_at = np.empty(len(y))
    diff_at = np.empty(len(y))
    for i in range(len(y)):
        u, q = users[i], problems[i]
        topics = problem_topics[q]
        t_skill = sum(topic_skill.get((u, t), 0.0) for t in topics) / len(topics) if topics else 0.0
        z = bias + skill[u] + t_skill - difficulty[q]
        p = 1.0 / (1.0 + math.exp(-z))
        pred[i], skill_at[i], topic_at[i], diff_at[i] = p, skill[u], t_skill, difficulty[q]

        err = y[i] - p
        # Larger steps while a user or problem is new, so few attempts still move it.
        skill[u] += s.k_user * err / (1 + 0.05 * seen_user[u])
        for t in topics:
            topic_skill[(u, t)] = topic_skill.get((u, t), 0.0) + s.k_topic * err / len(topics)
        difficulty[q] -= max(s.k_problem, 1.0 / (1 + seen_problem[q])) * err
        bias += s.k_bias * err
        seen_user[u] += 1
        seen_problem[q] += 1
    return {"p": pred, "skill": skill_at, "topic_skill": topic_at, "difficulty": diff_at}
