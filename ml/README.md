# dsa-coach models

Two models for dsa-coach, trained on public data and evaluated on data they never saw.

| Model | Question it answers | Shipped as |
|---|---|---|
| **Recall** | Will you still remember this problem at its next review? | LightGBM on review history + FSRS state |
| **Solve** | Will you solve this problem on your first try? | Online topic Elo |

## Recall model

**Data.** [anki-revlogs-10k](https://huggingface.co/datasets/open-spaced-repetition/anki-revlogs-10k)
(727M reviews from 10k Anki users). 400 users sampled, capped at 60k reviews each.
Its license allows personal research use and forbids redistribution, so only results and
trained weights are published, never the data.

**Target.** For each review at least a day after the previous one: remembered (any
rating but "again") or not.

**Features.** The card's history before the review (time since last review, number of
reviews, lapses, last and mean rating, card age), the user's running recall rate, and
the state FSRS with default parameters holds at that moment (retrievability, stability,
difficulty). Answer time is left out of the shipped model because dsa-coach does not
record it.

**Evaluation 1: users never seen.** Trained on 300 users, scored on the other 100.

| Model | AUC ↑ | Log-loss ↓ | ECE ↓ |
|---|---|---|---|
| FSRS, default parameters (dsa-coach before) | 0.744 | 0.348 | 0.008 |
| Recall model, shipped (no answer time) | **0.791** | **0.326** | **0.007** |

**Evaluation 2: against FSRS tuned to each user.** For 30 held-out users, FSRS is fitted
on the first half of the user's own reviews; every model is scored on the second half.

| Model | AUC ↑ | Log-loss ↓ | ECE ↓ | AUC, cards reviewed ≤ 2 times |
|---|---|---|---|---|
| FSRS, default parameters | 0.789 | 0.365 | 0.030 | 0.692 |
| FSRS, tuned on the user's first half | 0.840 | 0.327 | **0.013** | 0.798 |
| Recall model (never saw this user) | **0.849** | **0.323** | 0.024 | **0.824** |

The recall model ranks better than FSRS fitted to the user's own history while needing
none of it; tuned FSRS is better calibrated. dsa-coach uses the recall model from the
first review and can blend in tuned FSRS once a user has enough history.

**Caveats.** Flashcards, not DSA problems: how well this transfers is measured on users'
own reviews (the dashboard's calibration panel). The tuned-FSRS comparison covers 30
users.

## Solve model

**Data.**
- [Project CodeNet](https://github.com/IBM/Project_CodeNet) metadata: AtCoder and AIZU
  submissions with verdicts. AIZU is cut at the end of 2017: from 2018 CodeNet stops
  recording its failed submissions (acceptance jumps from 42-46% a year to 85-100%).
- Codeforces: a rating-stratified sample of users' full submission histories from the
  public API, plus problem ratings and tags.
- [AtCoder Problems](https://kenkoooo.com/atcoder/) difficulty estimates, matched to
  CodeNet problems by contest and title (1,116 of 1,519).

**Target.** Solved on the first try. "Ever solved" is 90-97% because people resubmit
until they pass, so it carries little signal; first-try is 56-72% and varies from 19%
to 90% across problems.

**Model.** Online Elo in logits (the Elo form of the Rasch model): P = sigmoid(bias +
skill[user] + mean topic skill[user, problem's topics] - difficulty[problem]). Topics
come from one shared list (`topics.py`) that maps each judge's tags. A problem's
difficulty starts from its judge's published Elo-style rating, at 15% of the raw Elo
scale (tuned; the full scale was far too extreme). Everything, including the base rate,
is learned online from earlier attempts only.

**Evaluation: leave one judge out.** Settings are tuned on the other judges, then the
held-out judge is replayed from scratch.

| Held-out judge | Model | AUC ↑ | Log-loss ↓ | ECE ↓ |
|---|---|---|---|---|
| AtCoder (5.6M) | Problem only | 0.765 | 0.528 | 0.029 |
| | LightGBM | 0.788 | 0.552 | 0.115 |
| | **Topic Elo** | **0.802** | **0.491** | **0.005** |
| AIZU (430k) | Problem only | 0.690 | 0.629 | 0.023 |
| | LightGBM | 0.728 | 0.601 | 0.009 |
| | **Topic Elo** | **0.729** | **0.600** | **0.008** |
| Codeforces (163k) | Problem only | 0.682 | 0.636 | 0.037 |
| | LightGBM | 0.698 | 0.725 | 0.191 |
| | **Topic Elo** | **0.699** | **0.624** | **0.020** |

Topic Elo ranks as well as LightGBM on every unseen judge and stays calibrated where
LightGBM does not, so it is what dsa-coach ships: a few kilobytes of parameters, updated
after every attempt. A two-number correction fitted on a judge's first 5% of attempts
(slope limited to 0.25-4) helps a little on Codeforces (ECE 0.020 → 0.013) and is kept
as an optional per-user step.

**Caveats.** LeetCode publishes no failed attempts, so the model cannot be evaluated on
LeetCode before use; leave-one-judge-out is the evidence that it transfers, and users'
own reviews check it after.

## Leakage found and fixed

Two early versions computed a judge's overall first-try rate from all of its attempts,
including later ones and the held-out judge's, and used it as Elo's starting bias and as
the smoothing prior. Both now start from a fixed prior and learn online. All numbers
above are from the fixed version.

## Reproduce

```bash
cd ml
uv sync
uv run python -m dsa_ml.collect_codeforces --users 2000   # ~2 h, resumable
# CodeNet metadata, AtCoder Problems JSON and anki-revlogs-10k go in data/raw/
uv run python -m dsa_ml.attempts
uv run python -m dsa_ml.features
uv run python -m dsa_ml.tune_elo          # solve model, leave-one-judge-out
uv run python -m dsa_ml.recall_features --users 400
uv run python -m dsa_ml.train_recall      # recall model, held-out users
uv run python -m dsa_ml.eval_recall_fsrs  # against FSRS tuned per user
```
