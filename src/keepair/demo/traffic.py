"""Scripted demo traffic: 500 simulated requests through the gateway.

The plan is built from a fixed seed, so every run sends the same requests in
the same order and gets the same decisions. Requests carry fixed idempotency
keys: sending the plan twice replays stored results and spends nothing more.
Use another --run to send it again as new requests.

Run with:  python -m keepair.demo.traffic
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from keepair.config import Settings
from keepair.demo.seed import _tree, agent_name, demo_token
from keepair.rng import DEMO_SEED, seeded_rng

TOTAL = 500
# Requested model names, with weights. Names use mixed case and aliases on purpose.
MODELS = (
    ("model-1", 30),
    ("va-fast", 25),
    ("vendor-a/model-2", 12),
    ("Vendor-A/Model-1", 8),
    ("vb-large", 6),  # alias of a model whose vendor is blocked
    ("vendor-b/model-1", 5),
    ("vendor-a/model-3", 6),  # blocked model
    ("vendor-a/model-9", 5),  # not registered
    ("vendor-c/new-model", 3),  # not registered
)
PROMPTS = (
    "Summarize the attached incident report in three bullet points.",
    "Classify this support ticket: the customer cannot reset a password.",
    "Draft a short reply that confirms the meeting for Tuesday.",
    "List the action items from these meeting notes.",
    "Translate the release note into plain language for customers.",
)
EXHAUSTING_AGENT = agent_name("Summaries EU")  # 0.15 EUR left on a hard limit
HELD_AGENT = agent_name("Research Agent")  # approval policy: requests are held


@dataclass(frozen=True, slots=True)
class Planned:
    index: int
    agent: str
    model: str
    prompt: str
    max_tokens: int


def _project_names() -> list[str]:
    org, _ = _tree()
    names: list[str] = []

    def walk(node) -> None:
        if node.kind == "PROJECT":
            names.append(node.name)
        for child in node.children:
            walk(child)

    walk(org)
    return names


def build_plan(seed_value: int = DEMO_SEED, total: int = TOTAL) -> list[Planned]:
    rng = seeded_rng(seed_value + 2)
    others = [
        a for a in map(agent_name, _project_names()) if a not in (EXHAUSTING_AGENT, HELD_AGENT)
    ]
    agents = [EXHAUSTING_AGENT] * 70 + [HELD_AGENT] * 12
    agents += [others[rng.randrange(len(others))] for _ in range(total - len(agents))]
    rng.shuffle(agents)
    names, weights = zip(*MODELS, strict=True)
    plan = []
    for index, agent in enumerate(agents[:total]):
        if agent == EXHAUSTING_AGENT:
            model, max_tokens = "model-1", 4096  # large estimate against a nearly empty budget
        else:
            model = rng.choices(names, weights=weights)[0]
            max_tokens = rng.choice((256, 512, 1024))
        prompt = f"{PROMPTS[rng.randrange(len(PROMPTS))]} (demo request {index})"
        plan.append(Planned(index, agent, model, prompt, max_tokens))
    return plan


Sender = Callable[[Planned, dict[str, str], dict], tuple[int, dict]]


def outcome_of(status: int, body: dict) -> str:
    if status == 200:
        return "ALLOWED"
    return body.get("error", {}).get("code", f"HTTP_{status}")


def run_plan(
    plan: list[Planned], send: Sender, run: str = "1", seed_value: int = DEMO_SEED
) -> list[str]:
    """Send the plan in order. Returns one outcome per request."""
    outcomes = []
    for item in plan:
        headers = {
            "Authorization": f"Bearer {demo_token(item.agent, seed_value)}",
            "Idempotency-Key": f"demo-{seed_value}-run{run}-{item.index}",
            "Content-Type": "application/json",
        }
        body = {
            "model": item.model,
            "messages": [{"role": "user", "content": item.prompt}],
            "max_tokens": item.max_tokens,
        }
        outcomes.append(outcome_of(*send(item, headers, body)))
    return outcomes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Send the scripted demo traffic to the gateway.")
    parser.add_argument("--gateway-url", default=Settings().gateway_url)
    parser.add_argument("--run", default="1", help="Run label. A new label sends new requests.")
    args = parser.parse_args(argv)

    with httpx.Client(base_url=args.gateway_url, timeout=30.0, trust_env=False) as client:

        def send(item: Planned, headers: dict[str, str], body: dict) -> tuple[int, dict]:
            response = client.post("/v1/chat/completions", headers=headers, json=body)
            return response.status_code, response.json()

        outcomes = run_plan(build_plan(), send, run=args.run)
    counts = Counter(outcomes)
    print(f"Sent {len(outcomes)} demo requests to {args.gateway_url} (run {args.run}):")
    for name, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {name:<24}{count:>5}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
