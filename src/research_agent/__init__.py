"""Research Agent MVP package."""

from research_agent.config import load_environment

load_environment()

from research_agent.pipeline import ResearchPipeline

__all__ = ["ResearchPipeline"]
