import argparse
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from linkedin_agent.config import PROJECT_ROOT
from linkedin_agent.graph import build_graph
from linkedin_agent.ideation.pipeline import run_ideation

OUTPUT_DIR = PROJECT_ROOT / "output"
OUTPUT_FILE = OUTPUT_DIR / "drafts.md"


def cmd_draft(args: argparse.Namespace) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    graph = build_graph()
    result = graph.invoke({"topic": args.topic})

    draft = result.get("draft", "ERROR: No draft generated")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"\n---\n## {timestamp}\n**Topic:** {args.topic}\n\n{draft}\n"

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "a") as f:
        f.write(entry)

    print(draft)


def cmd_ideate(args: argparse.Namespace) -> None:
    keywords = args.keywords
    result = run_ideation(keywords=keywords)

    ideas = result.get("generated_ideas", [])
    saved_ids = result.get("saved_ids", [])

    print(f"\n=== Ideation Summary ===")
    print(f"Ideas generated: {len(ideas)}")
    print(f"Saved to MongoDB: {len(saved_ids)}")
    print(f"Skipped (duplicates): {len(ideas) - len(saved_ids)}")
    print()

    for i, idea in enumerate(ideas, 1):
        title = idea.get("generated_idea", "Untitled")
        score = idea.get("score", "N/A")
        framework = idea.get("framework", "N/A")
        saved = "✅" if i <= len(saved_ids) else "⏭️"
        print(f"  {saved} {i}. [{score}] {framework} — {title}")

    print()


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")

    parser = argparse.ArgumentParser(description="LinkedIn Content Agent")
    sub = parser.add_subparsers(dest="command", required=True)

    draft_parser = sub.add_parser("draft", help="Generate a LinkedIn draft from a topic")
    draft_parser.add_argument("topic", type=str, help="The topic to write about")
    draft_parser.set_defaults(func=cmd_draft)

    ideate_parser = sub.add_parser("ideate", help="Run the idea generation pipeline")
    ideate_parser.add_argument(
        "--keywords", type=str, default=None,
        help="Niche keywords (overrides .env NICHE_KEYWORDS)",
    )
    ideate_parser.set_defaults(func=cmd_ideate)

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
