"""Pick tool-capable OpenRouter models from the live catalogue, one per provider.

Model IDs change every few weeks, so hard-coded presets go stale. `auto:N` asks OpenRouter
what exists today and picks N models from different providers for diverse testers.
"""

import re

PREFERRED_PROVIDERS = ["anthropic", "openai", "google", "x-ai", "moonshotai", "z-ai", "deepseek", "qwen",
                       "mistralai", "meta-llama", "minimax", "amazon", "cohere", "microsoft", "nvidia"]
SMALL_VARIANT = re.compile(r"(mini|nano|lite|tiny|small|haiku|\b[1-9]b\b|-[1-9]b|flash-8b|air)", re.IGNORECASE)


def candidates(models, *, vision=False, budget=False, max_prompt_price=None, min_context=64000):
    found = []
    for model in models:
        model_id = model.get("id", "")
        parameters = set(model.get("supported_parameters") or [])
        architecture = model.get("architecture") or {}
        outputs = architecture.get("output_modalities") or ["text"]
        inputs = architecture.get("input_modalities") or ["text"]
        if "tools" not in parameters or "text" not in outputs or ":" in model_id or "/" not in model_id:
            continue
        if vision and "image" not in inputs:
            continue
        if (model.get("context_length") or 0) < min_context:
            continue
        pricing = model.get("pricing") or {}
        try:
            price = float(pricing.get("prompt") or 0) * 1e6
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue  # free endpoints are heavily rate-limited
        if max_prompt_price is not None and price > max_prompt_price:
            continue
        small = bool(SMALL_VARIANT.search(model_id.split("/", 1)[1]))
        if small and not budget:
            continue
        found.append({"id": model_id, "provider": model_id.split("/", 1)[0], "created": model.get("created") or 0,
                      "price": price, "vision": "image" in inputs})
    return found


def pick_models(models, count=3, **filters):
    """The newest suitable model from each provider, preferred providers first."""
    budget = filters.get("budget", False)
    best = {}
    for item in candidates(models, **filters):
        current = best.get(item["provider"])
        if budget:
            better = current is None or item["price"] < current["price"]
        else:
            better = current is None or item["created"] > current["created"]
        if better:
            best[item["provider"]] = item
    ranked = sorted(best.values(), key=lambda item: (
        PREFERRED_PROVIDERS.index(item["provider"]) if item["provider"] in PREFERRED_PROVIDERS else 99,
        -item["created"]))
    return [item["id"] for item in ranked[:max(1, count)]]


def parse_auto(text):
    """'auto', 'auto:4', 'auto-vision:2', 'auto-budget:3' -> (count, filters) or None."""
    match = re.fullmatch(r"auto(-vision|-budget)?(?::(\d+))?", text.strip())
    if not match:
        return None
    variant = match.group(1) or ""
    return int(match.group(2) or 3), {"vision": variant == "-vision", "budget": variant == "-budget"}
