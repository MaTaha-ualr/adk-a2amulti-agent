
from google.adk.agents import Agent
from google.adk.agents.remote_a2a_agent import (
    AGENT_CARD_WELL_KNOWN_PATH,
    RemoteA2aAgent,
)
from google.adk.live import CascadeLive, GeminiSTT, GeminiTTS
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools import AgentTool

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import os

from dotenv import load_dotenv
import python_weather
from newsapi import NewsApiClient


# Uvicorn imports this package directly, so load its .env file here; existing
# process environment variables keep precedence over values stored in the file.
load_dotenv(Path(__file__).with_name(".env"), override=False)


# TOOL 1: GET CURRENT TIME
def get_current_time(timezone_name: str) -> dict:
    """Returns the current local time for an IANA timezone.

    Args:
        timezone_name: A valid IANA timezone identifier.
            Examples: 'America/Chicago', 'Europe/Berlin',
            'Asia/Tokyo'.
    """
    try:
        tz = ZoneInfo(timezone_name)
        now = datetime.now(tz)

        return {
            "status": "success",
            "timezone": timezone_name,
            "time": now.strftime("%I:%M %p"),
            "date": now.strftime("%Y-%m-%d")
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


# TOOL 2: GET CURRENT WEATHER
async def get_current_weather(location: str) -> dict:
    """Fetches current weather information for a location.

    Args:
        location: A specific city, state/region, and country.
            Examples: 'Little Rock, Arkansas, USA',
            'Berlin, Germany', 'Tokyo, Japan'.
    """
    try:
        async with python_weather.Client(
            unit=python_weather.IMPERIAL
        ) as client:

            weather = await client.get(location)

            return {
                "status": "success",
                "location": weather.location,
                "region": weather.region,
                "country": weather.country,
                "temperature_f": weather.temperature,
                "feels_like_f": weather.feels_like,
                "description": weather.description,
                "humidity_percent": weather.humidity,
                "wind_speed_mph": weather.wind_speed,
                "observation_time": weather.datetime.isoformat()
            }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


# TOOL 3: GET TOP NEWS HEADLINES
def get_top_news(query: str, country: str = "us") -> dict:
    """Fetches recent news headlines matching a topic.

    Args:
        query: Topic or keywords to search for.
        country: Two-letter country code for top headlines, such as 'us'.
    """
    api_key = os.getenv("NEWSAPI_API_KEY")
    if not api_key:
        return {
            "status": "error",
            "message": "Set NEWSAPI_API_KEY in my_agent/.env to use news search."
        }

    try:
        client = NewsApiClient(api_key=api_key)
        response = client.get_top_headlines(
            q=query,
            language="en",
            page_size=10
        )
        if response.get("status") != "ok":
            return {
                "status": "error",
                "message": response.get("message", "NewsAPI request failed.")
            }

        articles = [
            {
                "title": article.get("title"),
                "source": (article.get("source") or {}).get("name"),
                "description": article.get("description"),
                "url": article.get("url"),
                "published_at": article.get("publishedAt")
            }
            for article in response.get("articles", [])
        ]
        return {"status": "success", "articles": articles}
    except Exception as error:
        return {"status": "error", "message": str(error)}


# Category requests use NewsAPI's category filter instead of treating the
# category label as a keyword query, which can correctly return zero matches.
def get_top_headlines_by_category(category: str, country: str = "us") -> dict:
    """Fetches current top headlines in a category for a country.

    Args:
        category: NewsAPI category such as 'technology', 'business', or 'sports'.
        country: Two-letter country code, such as 'us'.
    """
    api_key = os.getenv("NEWSAPI_API_KEY")
    if not api_key:
        return {
            "status": "error",
            "message": "Set NEWSAPI_API_KEY in my_agent/.env to use news search.",
        }

    try:
        client = NewsApiClient(api_key=api_key)
        response = client.get_top_headlines(
            country=country,
            category=category,
            page_size=5,
        )
        if response.get("status") != "ok":
            return {
                "status": "error",
                "message": response.get("message", "NewsAPI request failed."),
            }

        articles = [
            {
                "title": article.get("title"),
                "source": (article.get("source") or {}).get("name"),
                "description": article.get("description"),
                "url": article.get("url"),
                "published_at": article.get("publishedAt"),
            }
            for article in response.get("articles", [])
        ]
        return {"status": "success", "articles": articles}
    except Exception as error:
        return {"status": "error", "message": str(error)}


def _agent_card_url(environment_variable: str, default_url: str) -> str:
    """Resolve a specialist's published Agent Card endpoint."""
    base_url = os.getenv(environment_variable, default_url).rstrip("/")
    return f"{base_url}{AGENT_CARD_WELL_KNOWN_PATH}"


# The live voice gateway calls this text-only A2A router. That router owns
# specialist selection and hands control to the dedicated A2A agents.
a2a_router_agent = RemoteA2aAgent(
    name="a2a_router",
    description=(
        "Routes the user's complete request to the correct specialist: "
        "information, greeting, or farewell."
    ),
    agent_card=_agent_card_url(
        "A2A_ROUTER_URL", "http://127.0.0.1:8010"
    ),
    use_legacy=False,
)


# ROOT VOICE GATEWAY
# It has no specialist skills of its own. The text router and specialist
# capabilities are in a separate A2A service, so this live path never tries to
# run RemoteA2aAgent as a live sub-agent.
root_agent = Agent(
    # ADK's documented cascade adds streaming speech to this gateway.
    # https://github.com/google/adk-docs/blob/main/docs/live/architectures/cascade.md
    model=CascadeLive(
        model=LiteLlm(
            model="ollama_chat/qwen3.5:4b",
            reasoning_effort="none",
        ),
        stt=GeminiSTT(),
        tts=GeminiTTS(speech_config="Kore"),
    ),
    name="root_agent",
    description=(
        "Voice and text gateway that forwards requests to the A2A router and "
        "speaks its response. It does not answer requests itself."
    ),
    instruction=(
        "You are only a voice and text gateway. For every user message, call "
        "the a2a_router tool exactly once with the complete request. Do not "
        "speak before the tool returns. Do not answer, classify, expand, or "
        "add facts yourself. After the router returns, relay the complete "
        "response faithfully. Do not summarize, omit facts, add unsolicited "
        "information, or add a new greeting. Never reveal internal reasoning."
    ),
    # AgentTool invokes the text router through run_async. The text router
    # performs A2A handoffs to dedicated specialist agents. See:
    # https://github.com/google/adk-docs/blob/main/docs/tools-custom/function-tools.md#agent-tool
    tools=[AgentTool(agent=a2a_router_agent)],
)


