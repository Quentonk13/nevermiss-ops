#!/usr/bin/env python3
"""
Facebook Source — Lead Pipeline
Monitors contractor Facebook groups for missed call complaints, phone system
questions, and overwhelmed-with-work posts. Uses Groq/Llama to classify post
relevance. Extracts poster name + business info, flags as "warm_intent".

Target groups: HVAC, plumber, electrician, general contractor groups.
"""

import json
import os
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone, timedelta
from typing import Optional

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.abspath(os.path.join(SKILL_DIR, "..", ".."))
CONFIG_PATH = os.path.join(SKILL_DIR, "config.json")
LOG_PATH = os.path.join(PROJECT_ROOT, "data", "system_log.jsonl")
FACEBOOK_GROUPS_PATH = os.path.join(SKILL_DIR, "facebook_groups.json")

# Estimated token costs for Groq Llama 3.1 70B
GROQ_COST_PER_1K_INPUT = 0.00059
GROQ_COST_PER_1K_OUTPUT = 0.00079
AVG_INPUT_TOKENS_PER_CLASSIFICATION = 350
AVG_OUTPUT_TOKENS_PER_CLASSIFICATION = 50


def _log(action: str, lead_id: Optional[str], result: str, details: str,
         llm_used: str = "none", tokens: int = 0, cost: float = 0.00):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "skill": "lead-pipeline",
        "action": action,
        "lead_id": lead_id,
        "result": result,
        "details": details,
        "llm_used": llm_used,
        "tokens_estimated": tokens,
        "cost_estimated": cost,
    }
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _load_config() -> dict:
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def _load_facebook_groups() -> list:
    """
    Load the list of monitored Facebook group IDs and metadata.
    Returns a list of dicts with group_id, name, vertical, etc.
    If the file doesn't exist, return an empty list (groups must be configured).
    """
    if not os.path.exists(FACEBOOK_GROUPS_PATH):
        return []
    with open(FACEBOOK_GROUPS_PATH, "r") as f:
        return json.load(f)


def _facebook_graph_request(endpoint: str, params: dict,
                            access_token: str) -> Optional[dict]:
    """Make a GET request to the Facebook Graph API."""
    params["access_token"] = access_token
    query_string = urllib.parse.urlencode(params)
    url = f"https://graph.facebook.com/v19.0/{endpoint}?{query_string}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        if e.fp:
            body = e.fp.read().decode("utf-8", errors="replace")
        _log("facebook_api_error", None, "failure",
             f"HTTP {e.code} on {endpoint}: {body}")
        return None
    except urllib.error.URLError as e:
        _log("facebook_api_error", None, "failure",
             f"URL error on {endpoint}: {e.reason}")
        return None
    except Exception as e:
        _log("facebook_api_error", None, "failure",
             f"Unexpected error on {endpoint}: {str(e)}")
        return None


def _groq_classify_post(post_text: str, groq_api_key: str,
                        model: str, config: dict) -> dict:
    """
    Use Groq/Llama to classify a Facebook post for missed-call relevance.
    Returns: {"relevant": True/False, "confidence": float, "reasoning": str}
    """
    intent_keywords = config["sources"]["facebook"].get("intent_keywords", [])
    keywords_str = ", ".join(intent_keywords)

    system_prompt = (
        "You are a lead qualification classifier for a missed-call prevention service "
        "targeting home service contractors. Your job is to determine if a Facebook "
        "group post indicates the poster is experiencing missed calls, phone overwhelm, "
        "or needs a phone answering solution.\n\n"
        "Respond ONLY with valid JSON in this exact format:\n"
        '{"relevant": true or false, "confidence": 0.0 to 1.0, "reasoning": "one sentence"}\n\n'
        f"Relevant signals include: {keywords_str}\n\n"
        "A post is relevant if the contractor is complaining about missed calls, asking "
        "about phone systems or answering services, mentioning being too busy to answer "
        "phones, or expressing frustration about lost leads from unanswered calls."
    )

    user_prompt = f"Classify this post:\n\n{post_text[:1500]}"

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.0,
        "max_tokens": 150,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {groq_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    est_input_tokens = AVG_INPUT_TOKENS_PER_CLASSIFICATION
    est_output_tokens = AVG_OUTPUT_TOKENS_PER_CLASSIFICATION
    est_total_tokens = est_input_tokens + est_output_tokens
    est_cost = (
        (est_input_tokens / 1000) * GROQ_COST_PER_1K_INPUT
        + (est_output_tokens / 1000) * GROQ_COST_PER_1K_OUTPUT
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            response_data = json.loads(resp.read().decode("utf-8"))

        content = response_data["choices"][0]["message"]["content"]
        usage = response_data.get("usage", {})
        actual_tokens = usage.get("total_tokens", est_total_tokens)
        actual_input = usage.get("prompt_tokens", est_input_tokens)
        actual_output = usage.get("completion_tokens", est_output_tokens)
        actual_cost = (
            (actual_input / 1000) * GROQ_COST_PER_1K_INPUT
            + (actual_output / 1000) * GROQ_COST_PER_1K_OUTPUT
        )

        result = json.loads(content)
        _log("facebook_classify_post", None, "success",
             f"Post classified: relevant={result.get('relevant', False)}, "
             f"confidence={result.get('confidence', 0)}",
             llm_used="groq", tokens=actual_tokens, cost=round(actual_cost, 6))
        return {
            "relevant": bool(result.get("relevant", False)),
            "confidence": float(result.get("confidence", 0)),
            "reasoning": result.get("reasoning", ""),
            "tokens_used": actual_tokens,
            "cost": actual_cost,
        }
    except urllib.error.HTTPError as e:
        body = ""
        if e.fp:
            body = e.fp.read().decode("utf-8", errors="replace")
        _log("facebook_groq_error", None, "failure",
             f"Groq HTTP {e.code}: {body}",
             llm_used="groq", tokens=0, cost=0.00)
        return {"relevant": False, "confidence": 0, "reasoning": "LLM error",
                "tokens_used": 0, "cost": 0}
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        _log("facebook_groq_parse_error", None, "failure",
             f"Failed to parse Groq response: {str(e)}",
             llm_used="groq", tokens=est_total_tokens, cost=round(est_cost, 6))
        return {"relevant": False, "confidence": 0, "reasoning": "Parse error",
                "tokens_used": est_total_tokens, "cost": est_cost}
    except Exception as e:
        _log("facebook_groq_error", None, "failure",
             f"Unexpected Groq error: {str(e)}",
             llm_used="groq", tokens=0, cost=0.00)
        return {"relevant": False, "confidence": 0, "reasoning": "Unexpected error",
                "tokens_used": 0, "cost": 0}


def _keyword_prefilter(post_text: str, config: dict) -> bool:
    """
    Fast keyword pre-filter before sending to LLM.
    Returns True if the post contains any intent keywords.
    This saves LLM calls by filtering out obviously irrelevant posts.
    """
    intent_keywords = config["sources"]["facebook"].get("intent_keywords", [])
    text_lower = post_text.lower()
    for keyword in intent_keywords:
        if keyword.lower() in text_lower:
            return True
    return False


def _extract_business_info_from_profile(poster_data: dict) -> dict:
    """
    Extract business information from a Facebook poster's profile data.
    Returns dict with available fields.
    """
    name = poster_data.get("name", "")
    # Facebook Graph API may return work info if permissions allow
    work = poster_data.get("work", [])
    company_name = ""
    role = ""
    if work and isinstance(work, list) and len(work) > 0:
        employer = work[0].get("employer", {})
        company_name = employer.get("name", "")
        position = work[0].get("position", {})
        role = position.get("name", "")

    # Try the about/bio fields
    about = poster_data.get("about", "")
    bio = poster_data.get("bio", "")

    return {
        "contact_name": name,
        "company_name": company_name,
        "contact_role": role,
        "about": about,
        "bio": bio,
    }


def _infer_vertical_from_group(group_data: dict) -> str:
    """Infer the vertical from the Facebook group's name/description."""
    name = group_data.get("name", "").lower()
    description = group_data.get("description", "").lower()
    combined = f"{name} {description}"

    vertical_keywords = {
        "HVAC": ["hvac", "heating", "cooling", "air conditioning", "ac repair"],
        "plumbing": ["plumb", "plumber", "plumbing", "pipe", "drain"],
        "electrical": ["electric", "electrician", "electrical", "wiring"],
        "general_contractor": ["general contractor", "gc ", "remodel", "renovation",
                               "construction", "builder"],
        "roofing": ["roof", "roofing", "roofer"],
    }
    for vertical, keywords in vertical_keywords.items():
        for kw in keywords:
            if kw in combined:
                return vertical
    return "general_contractor"


def run_facebook_source() -> list:
    """
    Execute the Facebook source pipeline.
    Monitors contractor groups for missed-call complaints and phone system questions.
    Uses Groq/Llama to classify post relevance.
    Returns a list of raw lead dicts flagged as warm_intent.
    """
    config = _load_config()
    fb_config = config["sources"]["facebook"]
    access_token = os.environ.get(fb_config["api_key_env"], "")
    if not access_token:
        _log("facebook_source_start", None, "failure",
             f"Missing API key: {fb_config['api_key_env']} env var not set")
        return []

    groq_api_key = os.environ.get(config["llm"]["api_key_env"], "")
    if not groq_api_key:
        _log("facebook_source_start", None, "failure",
             "Missing GROQ_API_KEY env var for post classification")
        return []

    groq_model = config["llm"].get("model", "llama-3.1-70b-versatile")
    lookback_hours = fb_config.get("post_lookback_hours", 4)
    since_timestamp = int(
        (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).timestamp()
    )

    _log("facebook_source_start", None, "success",
         f"Starting Facebook source run. Lookback: {lookback_hours}h")

    groups = _load_facebook_groups()
    if not groups:
        _log("facebook_source_no_groups", None, "skipped",
             "No Facebook groups configured. Add groups to facebook_groups.json")
        return []

    leads = []
    total_posts_scanned = 0
    total_posts_prefiltered = 0
    total_posts_classified = 0
    total_posts_relevant = 0
    total_tokens = 0
    total_cost = 0.0

    for group in groups:
        group_id = group.get("group_id", "")
        group_name = group.get("name", "unknown")
        if not group_id:
            continue

        # Fetch recent posts from the group
        feed_data = _facebook_graph_request(
            f"{group_id}/feed",
            {
                "fields": "id,message,from,created_time,updated_time",
                "since": str(since_timestamp),
                "limit": "100",
            },
            access_token,
        )
        if not feed_data or "data" not in feed_data:
            _log("facebook_group_fetch_failed", None, "failure",
                 f"Failed to fetch posts from group {group_name} ({group_id})")
            continue

        posts = feed_data["data"]
        total_posts_scanned += len(posts)
        group_vertical = _infer_vertical_from_group(group)

        for post in posts:
            message = post.get("message", "")
            if not message or len(message) < 20:
                continue

            # Stage 1: Keyword pre-filter (free, no LLM cost)
            if not _keyword_prefilter(message, config):
                continue
            total_posts_prefiltered += 1

            # Stage 2: LLM classification (Groq/Llama)
            classification = _groq_classify_post(
                message, groq_api_key, groq_model, config
            )
            total_posts_classified += 1
            total_tokens += classification.get("tokens_used", 0)
            total_cost += classification.get("cost", 0)

            if not classification["relevant"] or classification["confidence"] < 0.6:
                continue
            total_posts_relevant += 1

            # Extract poster info
            poster_raw = post.get("from", {})
            poster_id = poster_raw.get("id", "")
            poster_name = poster_raw.get("name", "")

            # Attempt to fetch poster's profile for business info
            business_info = {"contact_name": poster_name, "company_name": "",
                             "contact_role": "", "about": "", "bio": ""}
            if poster_id:
                profile_data = _facebook_graph_request(
                    poster_id,
                    {"fields": "name,about,work"},
                    access_token,
                )
                if profile_data:
                    business_info = _extract_business_info_from_profile(profile_data)
                    if not business_info["contact_name"]:
                        business_info["contact_name"] = poster_name

            # Build lead record -- warm_intent flagged
            lead = {
                "company_name": business_info.get("company_name", ""),
                "contact_name": business_info.get("contact_name", poster_name),
                "contact_role": business_info.get("contact_role", ""),
                "email": "",
                "phone": "",
                "website": "",
                "has_website": False,
                "vertical": group_vertical,
                "tier": 1 if group_vertical in config["verticals"]["tier_1"] else (
                    2 if group_vertical in config["verticals"]["tier_2"] else 3
                ),
                "city": "",
                "state": "",
                "source": "facebook",
                "source_intent": "warm_intent",
                "estimated_employee_count": None,
                "website_has_chat": None,
                "website_has_calltracking": None,
                "google_rating": None,
                "google_review_count": None,
                "yelp_response_indicator": None,
                "facebook_post_id": post.get("id", ""),
                "facebook_poster_id": poster_id,
                "facebook_group_id": group_id,
                "facebook_group_name": group_name,
                "facebook_post_snippet": message[:500],
                "classification_confidence": classification["confidence"],
                "classification_reasoning": classification["reasoning"],
            }
            leads.append(lead)

            _log("facebook_lead_found", None, "success",
                 f"Warm intent lead from {group_name}: {poster_name}. "
                 f"Confidence: {classification['confidence']:.2f}. "
                 f"Reasoning: {classification['reasoning']}",
                 llm_used="groq",
                 tokens=classification.get("tokens_used", 0),
                 cost=round(classification.get("cost", 0), 6))

    _log("facebook_source_complete", None, "success",
         f"Facebook source complete. Scanned {total_posts_scanned} posts, "
         f"pre-filtered {total_posts_prefiltered}, classified {total_posts_classified}, "
         f"found {total_posts_relevant} relevant. {len(leads)} leads extracted. "
         f"Tokens: {total_tokens}, Cost: ${total_cost:.4f}",
         llm_used="groq", tokens=total_tokens, cost=round(total_cost, 6))
    return leads


if __name__ == "__main__":
    results = run_facebook_source()
    print(json.dumps({"leads_found": len(results), "leads": results}, indent=2))
