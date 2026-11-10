"""A2A service apps for the router and its three specialist agents."""

import os

from google.adk.agents import Agent
from google.adk.agents.remote_a2a_agent import (
    AGENT_CARD_WELL_KNOWN_PATH,
    RemoteA2aAgent,
)
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools import AgentTool

from .agent import (
    get_current_time,
    get_current_weather,
    get_top_headlines_by_category,
    get_top_news,
)


def agent_card_url(environment_variable: str, default_url: str) -> str:
    """Builds a remote agent card URL from its service base URL."""
    service_url = os.getenv(environment_variable, default_url).rstrip("/")
    return f"{service_url}{AGENT_CARD_WELL_KNOWN_PATH}"


# This service is the only agent that owns live-data tools.
information_service_agent = Agent(
    model=LiteLlm(model="ollama_chat/qwen3.5:4b", reasoning_effort="none"),
    name="information_agent",
    description="Answers current time, weather, and news questions using tools.",
    instruction=(
        "You handle requests for current time, weather, and news. "
        "Use the appropriate tool for every live fact; never guess.\n\n"
        "For time, use the correct IANA timezone. For weather, identify the "
        "city, region, and country; ask for clarification if genuinely "
        "ambiguous. For a NewsAPI category such as technology, business, or "
        "sports, use get_top_headlines_by_category. For a keyword/topic search, "
        "use get_top_news. If multiple live facts are requested, use every "
        "relevant tool. Wait for tool results before answering. If a tool fails, "
        "report the error briefly and do not retry with guessed arguments. Keep "
        "the answer concise and factual."
    ),
    tools=[
        get_current_time,
        get_current_weather,
        get_top_news,
        get_top_headlines_by_category,
    ],
)


# AgentTool returns the remote information result to this greeting agent, so
# it can compose one greeting-plus-answer. A plain greeting does not call it.
information_for_greeting = RemoteA2aAgent(
    name="information_agent",
    description="Looks up current time, weather, or news when requested.",
    agent_card=agent_card_url(
        "INFORMATION_AGENT_URL", "http://127.0.0.1:8001"
    ),
    use_legacy=False,
)

greeting_service_agent = Agent(
    # This role must call the remote information tool for mixed requests, so it
    # uses the tool-calling model; LFM remains on the tool-free farewell role.
    model=LiteLlm(model="ollama_chat/qwen3.5:4b", reasoning_effort="none"),
    name="greeting_agent",
    description="Responds to greetings and can answer a factual question in the same message.",
    instruction=(
        "You are a friendly greeting specialist. For a simple greeting, "
        "welcome the user briefly and do not call another agent. If the user "
        "also asks about current time, weather, or news, you MUST call the "
        "information_agent tool with the factual question before answering. "
        "Then respond with a brief greeting and its result. Never invent, "
        "estimate, or claim to have fetched a live fact without the tool result. "
        "Do not narrate your routing, tool-use process, or private reasoning."
    ),
    tools=[AgentTool(agent=information_for_greeting)],
)


farewell_service_agent = Agent(
    model=LiteLlm(model="ollama_chat/lfm2.5:8b"),
    name="farewell_agent",
    description="Responds to simple thanks and goodbyes.",
    instruction=(
        "For a simple thank-you or goodbye, reply with a friendly, brief "
        "sign-off. Do not answer factual questions or call another agent."
    ),
)


# The text-only router owns specialist selection. Because it runs through
# run_async, its A2A specialists can use the standard ADK transfer flow.
information_for_router = RemoteA2aAgent(
    name="information_agent",
    description=(
        "Answers current time, weather, and news questions using live-data tools."
    ),
    agent_card=agent_card_url(
        "INFORMATION_AGENT_URL", "http://127.0.0.1:8001"
    ),
    use_legacy=False,
)

greeting_for_router = RemoteA2aAgent(
    name="greeting_agent",
    description=(
        "Handles greetings and greeting-plus-fact requests. It consults the "
        "information agent when a live fact is requested."
    ),
    agent_card=agent_card_url(
        "GREETING_AGENT_URL", "http://127.0.0.1:8002"
    ),
    use_legacy=False,
)

farewell_for_router = RemoteA2aAgent(
    name="farewell_agent",
    description="Handles simple thanks and goodbyes.",
    agent_card=agent_card_url(
        "FAREWELL_AGENT_URL", "http://127.0.0.1:8003"
    ),
    use_legacy=False,
)

router_service_agent = Agent(
    model=LiteLlm(
        model="ollama_chat/qwen3.5:4b",
        reasoning_effort="none",
    ),
    name="router_agent",
    description=(
        "Routes each request to the information, greeting, or farewell A2A agent."
    ),
    instruction=(
        "You are only a dispatcher. Do not answer factual questions yourself "
        "or narrate your classification. For each request, choose the best "
        "matching specialist and transfer control to that agent. Do not write "
        "response text before or after the hand-off.\n\n"
        "ROUTING:\n"
        "1. A greeting that also asks a live factual question goes to "
        "greeting_agent; it will call information_agent as needed.\n"
        "2. A current-time, weather, or news question without a greeting "
        "goes to information_agent.\n"
        "3. A greeting alone goes to greeting_agent.\n"
        "4. A simple thank-you or goodbye goes to farewell_agent.\n"
        "5. A factual question with a thank-you or goodbye goes to "
        "information_agent.\n"
        "6. For requests outside these capabilities, briefly explain the "
        "available capabilities without answering the request."
    ),
    sub_agents=[
        information_for_router,
        greeting_for_router,
        farewell_for_router,
    ],
)


# Each app publishes a generated Agent Card and handles A2A requests on its
# own local port. Port 8010 avoids the existing non-A2A listener on local 8000.
information_a2a_app = to_a2a(
    information_service_agent, host="127.0.0.1", port=8001
)
greeting_a2a_app = to_a2a(
    greeting_service_agent, host="127.0.0.1", port=8002
)
farewell_a2a_app = to_a2a(
    farewell_service_agent, host="127.0.0.1", port=8003
)
router_a2a_app = to_a2a(
    router_service_agent, host="127.0.0.1", port=8010
)
