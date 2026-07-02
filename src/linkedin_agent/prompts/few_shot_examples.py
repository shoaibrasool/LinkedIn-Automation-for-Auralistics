FEW_SHOT_EXAMPLES = [
    # Example 1: Technical teardown / build-in-public
    """We spent 3 weeks integrating GPT-4 for a client's document pipeline.

Not because it was hard. Because every "simple" RAG tutorial skips the part where your data isn't a clean PDF.

Real world:
- Emails with inconsistent formatting
- Scanned invoices with OCR errors
- Tables that don't parse unless you write custom extractors

We ended up building a 3-stage pipeline:
1. Classify document type first (don't assume)
2. Route to specialized parser per type
3. Use GPT-4 only for the ambiguous edge cases (about 15% of documents)

The result: 94% accuracy instead of the 60% we got from a generic RAG approach.

Cost dropped 4x because we stopped sending every document through the LLM.

What's the messiest data type you've had to wrangle? Mine's hand-written invoices.""",

    # Example 2: Client problem / opinionated
    """A prospect asked us to build them a chatbot last week.

I said no. Not because we couldn't. Because a chatbot wasn't the problem.

Their real problem: support tickets were piling up because their knowledge base was a graveyard of outdated Notion docs.

A chatbot trained on bad data is just a faster way to give wrong answers.

We spent the first month:
- Auditing what actually breaks in their product
- Writing 12 canonical responses for the top 80% of issues
- Building a simple intent classifier (not an LLM, just a classifier)

Then we added an LLM on top for the remaining 20% that needs reasoning.

The chatbot works now because we fixed the input before obsessing over the output.

Most AI projects fail at the data layer. Most consultants won't tell you that because it's not sexy to say "your docs need cleaning."

When was the last time you audited what your AI actually consumes?""",

    # Example 3: Industry hot take
    """Everyone's jumping on the "AI agent" bandwagon.

I've seen 5 demo videos this week of agents that "autonomously" book meetings.

None of them handle the edge case where the restaurant is closed on Tuesdays.

Here's what nobody shows you:
- Agents hallucinating confirmation numbers
- Agents booking the wrong timezone (3x in one demo)
- Agents getting stuck in loops when a human says "actually, let me check"

The demos work. The production deployments don't.

We're bullish on agents long-term. But if you're shipping an "agent" today that touches a customer's money or calendar, you're going to have a bad time.

Start with tools that suggest. Let humans approve. You'll move slower and win faster.

What's the worst agent demo you've seen? I'll go first: one that ordered 47 pizzas.""",

    # Example 4: Founder lesson
    """I spent 2 months building a feature nobody asked for.

We were building an AI dashboard for a client. I got carried away with the visualization layer.

Beautiful charts. Real-time updates. Interactive filters.

The client asked for one thing: a CSV export button that works consistently.

I gave them a tableau competitor.

The feature they actually used was a simple table with search. That's it.

What I learned:
- Ask "what's the one thing" before writing any code
- Ship the boring thing first
- Pretty dashboards don't close deals, reliable outputs do

We stripped 80% of the UI and delivered 2 weeks early. Client was thrilled.

What feature did you over-engineer while the simple thing sat undone?""",
]
