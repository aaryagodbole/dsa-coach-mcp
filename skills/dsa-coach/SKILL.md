---
name: dsa-coach
description: "Coaches DSA and coding-interview practice with the dsa-coach MCP server. Use when the user talks about LeetCode, Codeforces or any other judge, asks what to practise or revise, reports solving or failing a problem, or wants to see their progress or recurring mistakes."
license: MIT
compatibility: "Needs the dsa-coach MCP server (uvx dsa-coach-mcp). Optional: a browser MCP server for platforms without an adapter."
---

# DSA coach

The dsa-coach tools return data, not decisions. Reading that data and deciding what is
weak, what comes next and how to say it is your job; never invent a tag, level, problem
or platform the tools did not give you.

## Planning practice

1. Call `list_platforms` once to learn each platform's tags and levels.
2. Call `get_profile`, with their handle, for every platform the user named whose
   `source` is `platform`. A `reported` platform has no adapter, so neither
   `get_profile` nor `search_problems` can read it: plan from its recorded reviews
   (`progress`, `mistake_patterns`) and tell the user it cannot be searched.
3. Combine what you read with `mistake_patterns`: the topics they solve least and the
   mistakes they repeat are where practice pays off.
4. For the same platforms as step 2, call `search_problems` with tags and levels taken
   from steps 1-3, and `exclude_solved_by` set to their handle there. If nothing
   matches, widen one filter at a time and say so.
5. For each problem, say which weakness or past mistake it targets.

## After the user solves or retries a problem

On a platform with an adapter, first call `review_evidence` with the user's handle: it
reads the rating from their submissions since the last review, which is more reliable
than their own estimate. Tell them the suggestion and its reason; they may overrule it.
If it suggests nothing, ask them.

Call `log_review` with the platform, the problem id and how it went:

- `again`: could not solve it
- `hard`: solved it, but with real difficulty or hints
- `good`: solved it after some thought
- `easy`: solved it at once

Record every mistake they mention in `mistakes`. Before choosing a `kind`, call
`mistake_kinds` and reuse an existing label whenever it describes the same mistake;
create a new label only for a genuinely new kind of mistake, in a few plain words. Keep
the `note` in the user's own words.

If they did not say how it went, ask before logging; a wrong rating skews every later
revision.

## Platforms without an adapter

Platforms `list_platforms` shows with `source` `platform` are read from their APIs. The
first time the user reviews a problem from any other platform, read the problem page,
with a browser MCP server if one is connected, then call `record_problem` with its URL,
title, the tags the page shows and its stated difficulty, and use the `platform` and
`problem_id` it returns for `log_review`. Record it only that once: later reviews pass
the same `platform` and `problem_id` to `log_review`, which reads the recorded problem.
Both come from the URL as `record_problem` describes, so the page need not be read
again. Never record a problem from memory or a guessed URL.

## Revision

- `revisions_due` lists what to revise now, least likely to be remembered first.
- For a quiz, use the `revision_quiz` prompt, or follow it: for each due problem read
  its past mistakes with `list_mistakes` (`platform` and `problem_id`), ask one question
  at a time without giving the answer, then log the result.
- `show_dashboard` shows progress, due revisions and a mistake heatmap; in hosts that
  support MCP Apps it renders as an interactive view.
- After a few hundred reviews, `personalize_schedule` fits the schedule to how fast this
  user forgets. If it reports too little history, say so and carry on.

## Do not

- Do not call tools for general DSA questions that are not about the user's own
  practice; answer those directly.
- Do not log a review the user did not report.
