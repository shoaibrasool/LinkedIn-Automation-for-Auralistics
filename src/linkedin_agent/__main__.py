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

    initial_state = {
        "topic": args.topic,
        "search_results": "",
        "draft": None,
        "authenticity_result": None,
        "retry_count": 0,
        "flagged_for_manual": False,
        "authenticity_feedback": "",
    }

    graph = build_graph()
    result = graph.invoke(initial_state)

    draft = result.get("draft", "ERROR: No draft generated")
    authenticity_result = result.get("authenticity_result", {})
    flagged = result.get("flagged_for_manual", False)
    retry_count = result.get("retry_count", 0)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    auth_line = []
    if authenticity_result:
        passed = authenticity_result.get("passed", False)
        status = "PASSED" if passed else "FAILED"
        auth_line.append(f"\n**Authenticity:** {status}")
        if authenticity_result.get("banned_phrases_found"):
            auth_line.append(
                f"**Banned phrases:** {', '.join(authenticity_result['banned_phrases_found'][:3])}"
            )
        if not passed and authenticity_result.get("feedback"):
            auth_line.append(f"**Feedback:** {authenticity_result['feedback']}")
        if retry_count > 0:
            auth_line.append(f"**Retries:** {retry_count}")
        if flagged:
            auth_line.append("**⚠ Flagged for manual rewrite — hit max retries**")

    auth_section = "\n".join(auth_line) if auth_line else ""
    entry = f"\n---\n## {timestamp}\n**Topic:** {args.topic}\n{auth_section}\n\n{draft}\n"

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "a") as f:
        f.write(entry)

    print(draft)
    if auth_line:
        print()
        for line in auth_line:
            print(line)


def cmd_ideate(args: argparse.Namespace) -> None:
    keywords = args.keywords
    result = run_ideation(keywords=keywords)

    ideas = result.get("generated_ideas", [])
    saved_ids = result.get("saved_ids", [])

    print(f"\n=== Ideation Summary ===")
    print(f"Ideas generated: {len(ideas)}")
    print(f"Saved: {len(saved_ids)}")
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
