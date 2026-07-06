from pydantic import BaseModel, Field


class ScoreCard(BaseModel):
    originality: int = Field(ge=1, le=5, description="Is this a fresh perspective or a recycled take?")
    value_to_reader: int = Field(ge=1, le=5, description="How useful is this insight to the target audience?")
    authority_fit: int = Field(ge=1, le=5, description="Does the idea demonstrate real, hands-on experience?")
    icp_relevance: int = Field(
        ge=1, le=5,
        description="How relevant is this to the ideal customer profile "
                    "(builders, founders, technical operators)?",
    )
    sales_potential: int = Field(
        ge=1, le=5,
        description="Does this naturally lead into Auralistic AI's services "
                    "(AI consulting, RAG, automation)?",
    )
    reasoning: str = Field(description="Brief justification for each score dimension")


SCORING_SYSTEM_PROMPT = (
    "You are a harsh editor, not a cheerleader. Your job is to critically "
    "evaluate a raw LinkedIn post idea against a strict rubric.\n\n"
    "For each of the 5 dimensions below, assign a score of 1-5 where:\n"
    "1 = Very weak / absent\n"
    "2 = Below average\n"
    "3 = Average / acceptable\n"
    "4 = Good / above average\n"
    "5 = Excellent / strong\n\n"
    "Dimensions:\n"
    "1. originality — Is this a fresh perspective or a recycled take? "
    "Penalize generic hot-takes.\n"
    "2. value_to_reader — How useful is this insight to operators, "
    "builders, and founders? Does it teach something actionable?\n"
    "3. authority_fit — Does the idea demonstrate real, hands-on "
    'experience? Anti-example: "AI is changing everything" with no '
    "specific personal story or technical detail.\n"
    "4. icp_relevance — How relevant is this to Auralistic AI's ICP: "
    "technical founders, AI builders, SaaS operators who care about "
    "RAG, automation, and practical LLM deployment?\n"
    "5. sales_potential — Does this naturally create curiosity about "
    "Auralistic AI's services (AI consulting, RAG systems, workflow "
    'automation)? A score of 5 means the reader walks away thinking '
    '"I need help with this."\n\n'
    "After assigning scores, write a short reasoning string explaining "
    "the breakdown — especially any 1s or 2s.\n\n"
    "Return a JSON object with exactly these fields: originality, "
    "value_to_reader, authority_fit, icp_relevance, sales_potential, "
    "reasoning."
)
