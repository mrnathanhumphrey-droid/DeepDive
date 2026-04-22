"""
Fetch and classify tweets from verified news accounts.
Budget-capped at $2.00 per run (configurable via --budget or TWITTER_BUDGET_CAP env var).

Usage:
    python scripts/classify_tweets.py                        # All accounts, 7 days, $2 cap
    python scripts/classify_tweets.py --hours 48             # Last 48 hours
    python scripts/classify_tweets.py --accounts Reuters AP  # Specific accounts
    python scripts/classify_tweets.py --max 50               # Max per account
    python scripts/classify_tweets.py --budget 1.00          # $1 budget cap
"""
import sys, os, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.twitter_fetch_agent import TwitterFetchAgent


def main():
    parser = argparse.ArgumentParser(description="Fetch and classify tweets (budget-capped)")
    parser.add_argument("--accounts", nargs="+", default=None,
                        help="Specific account usernames to fetch from")
    parser.add_argument("--max", type=int, default=25,
                        help="Max tweets per account (default: 25)")
    parser.add_argument("--hours", type=int, default=168,
                        help="Hours to look back (default: 168 = 7 days)")
    parser.add_argument("--budget", type=float, default=2.00,
                        help="Max budget in USD (default: $2.00)")
    parser.add_argument("--output", type=str, default=None,
                        help="Output JSON file path")
    args = parser.parse_args()

    agent = TwitterFetchAgent(budget_cap=args.budget)
    accts = args.accounts or agent.ALL_ACCOUNTS

    # Pre-flight cost estimate
    estimated_tweets = len(accts) * args.max
    estimated_twitter = estimated_tweets * 0.005 + len(accts) * 0.01
    estimated_haiku = estimated_tweets * 0.3 * 0.0003
    estimated_total = estimated_twitter + estimated_haiku

    print(f"=== TWEET CLASSIFICATION PIPELINE ===")
    print(f"Accounts: {len(accts)}")
    print(f"Max per account: {args.max}")
    print(f"Window: {args.hours} hours")
    print(f"Budget cap: ${args.budget:.2f}")
    print(f"")
    print(f"--- COST ESTIMATE ---")
    print(f"Est. tweets: {estimated_tweets}")
    print(f"Est. Twitter API: ${estimated_twitter:.2f}")
    print(f"Est. Anthropic:   ${estimated_haiku:.4f}")
    print(f"Est. total:       ${estimated_total:.2f}")
    if estimated_total > args.budget:
        safe_per = int((args.budget - len(accts) * 0.01) / (len(accts) * 0.005))
        print(f"WARNING: Estimate exceeds budget. Reducing to ~{safe_per}/account")
        args.max = max(safe_per, 10)
    print(f"")

    data = agent.fetch_and_classify(
        accounts=args.accounts,
        max_per_account=args.max,
        hours_back=args.hours,
    )

    total = data["total"]
    modes = data["modes"]
    domains = data["domains"]
    cost = data["cost"]

    print(f"=== RESULTS ===")
    print(f"Tweets classified: {total}")
    print(f"Detection rate: {data['detection_rate']:.0%}")
    print()
    print("--- MODE DISTRIBUTION ---")
    for m in ["breaking", "current", "recent", "general"]:
        c = modes.get(m, 0)
        pct = c * 100 // max(total, 1)
        print(f"  {m.upper():10} {c:4} ({pct}%)")
    print()
    print("--- DOMAIN DISTRIBUTION ---")
    for d in sorted(domains.keys(), key=lambda x: -domains[x]):
        c = domains[d]
        pct = c * 100 // max(total, 1)
        print(f"  {d:15} {c:4} ({pct}%)")
    print()
    print("--- COST REPORT ---")
    print(f"  Twitter reads:     {cost['twitter_reads']:4}  (${cost['twitter_cost']:.3f})")
    print(f"  User lookups:      {cost['user_lookups']:4}  (included above)")
    print(f"  Haiku calls:       {cost['haiku_calls']:4}  (${cost['anthropic_cost']:.4f})")
    print(f"  TOTAL COST:              ${cost['total_cost']:.3f} / ${cost['budget_cap']:.2f}")
    print(f"  Budget remaining:        ${cost['remaining']:.3f}")
    print()

    print(f"{'ACCOUNT':<18} {'TIER':<14} {'MODE':>8} {'DOMAIN':>12} {'TWEET TEXT'}")
    print("=" * 120)
    for t in data["tweets"]:
        cls = t["classification"]
        text = t["text"].replace("\n", " ")[:60]
        print(f"{t['author_username']:<18} {t.get('tier','?'):<14} "
              f"{cls['mode'].upper():>8} {cls['domain']:>12} {text}")

    filepath = agent.export_dataset(data, args.output)
    print(f"\nDataset saved to: {filepath}")


if __name__ == "__main__":
    main()
