import argparse
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from linkedin_agent.config import PROJECT_ROOT
from linkedin_agent.graph import build_graph

OUTPUT_DIR = PROJECT_ROOT / "output"
OUTPUT_FILE = OUTPUT_DIR / "drafts.md"


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")

    parser = argparse.ArgumentParser(description="Generate a LinkedIn draft from a topic")
    parser.add_argument("topic", type=str, help="The topic to write about")
    args = parser.parse_args()

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


if __name__ == "__main__":
    main()
