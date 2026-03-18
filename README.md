# GitHUB daily

A GitHub Actions based repo scout that opens a daily issue with four buckets:

- Breakouts: repos spiking now
- Sustained movers: repos with healthy medium-term momentum
- Durable greats: repos with long-term trust and ongoing maintenance
- Watchlist hits: repos relevant to your chosen themes

## What it does

Every day the workflow:

1. Pulls GitHub Trending to capture what is hot now.
2. Uses the GitHub Search API to find repositories across your chosen themes.
3. Scores candidates on momentum, maintenance, quality, and relevance.
4. Writes a Markdown report.
5. Opens a dated GitHub issue in this repo.

## Why this design

Trending alone is noisy. All-time stars alone is stale. This project combines short-term momentum, medium-term persistence, long-term durability, and your own work relevance.

## Setup

### 1. Create a new GitHub repo

Create an empty repository, for example `github-daily`.

### 2. Upload these files

Push this folder into that repo.

### 3. Add optional secrets

No secret is required if you are fine with low-rate API usage.

Recommended:

- `GH_PAT`: a GitHub personal access token with `public_repo` or `repo` scope, used for higher API limits and issue creation via the API.

The built-in `GITHUB_TOKEN` is also used inside Actions for issue creation.

### 4. Customize the watchlist

Edit `config.json` and change:

- `watch_queries`
- `languages`
- `topics`
- `exclude_terms`
- `max_results_per_bucket`

### 5. Enable Actions

Go to the Actions tab and enable workflows.

## Schedule

The default workflow runs daily at 03:40 UTC and can also be run manually.

## Output

Each run creates a new issue with a title like:

`GitHUB daily - 2026-03-18`

## Notes

- GitHub stars are a weak signal by themselves. This project uses them only as one component.
- Trending is scraped from the public GitHub Trending page because GitHub does not provide an official Trending API endpoint. The page remains publicly accessible. citeturn774439search0
- GitHub Search and repository metadata come from the GitHub API and docs. citeturn774439search1turn774439search10

## Suggested operating model

Read the issue in this order:

1. Breakouts for early discovery
2. Sustained movers for likely usefulness
3. Durable greats for quiet infrastructure
4. Watchlist hits for direct work leverage

Then star, test, or ignore.
