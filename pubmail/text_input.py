"""Explicitly bounded model evidence; original source remains untouched."""
from .io import Error


def bounded_message(m, c):
    limit = c.get("limits", {}).get("body_characters", 24000)
    if c.get("agent_chain", {}).get("enabled"):
        limit = min(limit, c["agent_chain"].get("review_packet", {}).get("max_excerpt_characters", 6000))
    if type(limit) is not int or limit < 1:
        raise Error("Text character limits must be positive integers")
    body = m.get("body", "")
    result = dict(m, body=body[:limit])
    result["text_trimmed"] = bool(m.get("truncated") or m.get("text_trimmed") or len(body) > limit)
    if result["text_trimmed"]:
        for key in ("image_alts", "visual_titles"):
            result[key] = [title for title in m.get(key, []) if title in result["body"]]
    return result
