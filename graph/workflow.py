"""
graph/workflow.py — Full AI Sales Agent LangGraph pipeline

Flow:
    search → evaluate_search → [retry | scrape | END(fail)]
    scrape → evaluate_scrape → [retry | analyze | END(fail)]
    analyze → evaluate_analyze → [retry | ppt | ppt(accept_anyway)]
    ppt → email → approval (interrupt) → [send | END(rejected)]
    send → END

Usage (run pipeline, pauses at approval):

    from graph.workflow import build_pipeline, run_pipeline, resume_pipeline

    # Start
    thread_id = run_pipeline("KFintech")

    # ... user reviews in UI, then approves or rejects ...

    # Resume after approval
    result = resume_pipeline(
        thread_id=thread_id,
        decision={"status": "approved", "email_draft": {...}},
    )

Usage (FastAPI approval endpoint):

    from langgraph.types import Command
    result = pipeline.invoke(
        Command(resume={"status": "approved", "email_draft": edited_draft}),
        config={"configurable": {"thread_id": job_id}},
    )
"""

import sys
import os

# Ensure repo root and dev1_research are importable
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEV1_DIR = os.path.join(_REPO_ROOT, "dev1_research")
for _p in [_REPO_ROOT, _DEV1_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from graph.state import PipelineState
from graph.dev2_nodes import ppt_node, email_node, approval_node, send_node

# Dev1 nodes — imported from dev1_research/graph_nodes.py
from graph_nodes import (
    search_node,
    evaluate_search_node,
    route_after_search,
    scrape_node,
    evaluate_scrape_node,
    route_after_scrape,
    analyze_node,
    evaluate_analyze_node,
    route_after_analyze,
)


# ── routing ───────────────────────────────────────────────────────────────────

def route_after_approval(state: PipelineState) -> str:
    if state.get("approval_status") == "approved":
        return "send"
    return "end"


# ── graph builder ─────────────────────────────────────────────────────────────

def build_pipeline(checkpointer=None) -> "CompiledStateGraph":
    """
    Build and compile the full pipeline graph.

    Args:
        checkpointer: LangGraph checkpointer for persistence.
                      Defaults to MemorySaver (in-memory, resets on restart).
                      Swap for AsyncPostgresSaver for production.
    """
    graph = StateGraph(PipelineState)

    # ── Dev1 nodes ────────────────────────────────────────────────────────
    graph.add_node("search", search_node)
    graph.add_node("evaluate_search", evaluate_search_node)
    graph.add_node("scrape", scrape_node)
    graph.add_node("evaluate_scrape", evaluate_scrape_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("evaluate_analyze", evaluate_analyze_node)

    # ── Dev2 nodes ────────────────────────────────────────────────────────
    graph.add_node("ppt", ppt_node)
    graph.add_node("email", email_node)
    graph.add_node("approval", approval_node)
    graph.add_node("send", send_node)

    # ── entry ─────────────────────────────────────────────────────────────
    graph.set_entry_point("search")

    # ── Dev1 edges ────────────────────────────────────────────────────────
    graph.add_edge("search", "evaluate_search")
    graph.add_conditional_edges(
        "evaluate_search", route_after_search,
        {"retry": "search", "continue": "scrape", "fail": END},
    )

    graph.add_edge("scrape", "evaluate_scrape")
    graph.add_conditional_edges(
        "evaluate_scrape", route_after_scrape,
        {"retry": "scrape", "continue": "analyze", "fail": END},
    )

    graph.add_edge("analyze", "evaluate_analyze")
    graph.add_conditional_edges(
        "evaluate_analyze", route_after_analyze,
        {"retry": "analyze", "continue": "ppt", "accept_anyway": "ppt"},
    )

    # ── Dev2 edges ────────────────────────────────────────────────────────
    graph.add_edge("ppt", "email")
    graph.add_edge("email", "approval")     # approval uses interrupt() inside
    graph.add_conditional_edges(
        "approval", route_after_approval,
        {"send": "send", "end": END},
    )
    graph.add_edge("send", END)

    cp = checkpointer or MemorySaver()
    return graph.compile(checkpointer=cp)


# ── singleton instance ────────────────────────────────────────────────────────

# Import this in FastAPI routes:
#   from graph.workflow import pipeline
pipeline = build_pipeline()


# ── convenience wrappers ──────────────────────────────────────────────────────

def run_pipeline(company_name: str, thread_id: str | None = None) -> str:
    """
    Start the pipeline for a company. Runs until the approval interrupt.

    Returns the thread_id to use when resuming after approval.
    """
    import uuid
    tid = thread_id or uuid.uuid4().hex[:12]
    config = {"configurable": {"thread_id": tid}}

    initial_state: PipelineState = {
        "company_name": company_name,
        "search_attempts": 0,
        "scrape_attempts": 0,
        "analyze_attempts": 0,
        "quality_notes": [],
    }

    # invoke() will pause at approval_node's interrupt() and return
    pipeline.invoke(initial_state, config=config)
    return tid


def resume_pipeline(thread_id: str, decision: dict) -> dict:
    """
    Resume the pipeline after the human approval step.

    Args:
        thread_id: returned by run_pipeline()
        decision:  {"status": "approved", "email_draft": {...}}
                   or {"status": "rejected"}

    Returns the final state.
    """
    config = {"configurable": {"thread_id": thread_id}}
    return pipeline.invoke(Command(resume=decision), config=config)
