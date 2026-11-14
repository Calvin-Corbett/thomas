"""Persona validation sweep — 6 personas x 20 complex tasks each (120 total).

Runs every task prompt through the REAL backend card-titler (derive_active_goal,
the single source of the task-card title on every chat path incl. gpt-5.5) and
records the title. Emits JSON for a critical-analysis pass. This is the feasible,
backend-true version of Calvin's "run several personas through real tasks and
cynically analyze the card name / replies" — at the function that actually names
the card, across all 120 tasks, deterministically.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from thomas.marketplace.observability.task_ledger import derive_active_goal

# 6 personas. Tasks are deliberately MORE than "make me a file": multi-part,
# real-life/real-eng, phrased in each persona's natural voice.
PERSONAS: dict[str, list[str]] = {
    "grandma_50": [
        "Hi Thomas, can you help me make a printable birthday invitation for my grandson's 7th birthday with a dinosaur theme?",
        "I'd like to organize all my handwritten recipes into a little cookbook I can print and give to the family at Christmas",
        "Could you build me a simple photo website so I can share pictures of the grandkids with relatives who live far away?",
        "Help me write a heartfelt 60th anniversary letter to my husband that mentions how we met at the county fair",
        "Can you set up a budget spreadsheet that tracks my monthly bills, groceries, and medicine costs and warns me if I overspend?",
        "I want to plan a family reunion for 30 people in July — help me make a checklist, a menu, and a schedule",
        "My computer is running slow, can you figure out what's wrong and fix it so it's faster?",
        "Help me write a polite but firm email to my insurance company disputing a $400 charge they shouldn't have made",
        "Can you make me a large-print weekly medication schedule I can stick on the fridge?",
        "I'd like to start a little blog about gardening — can you set it up and write the first post about growing tomatoes?",
        "Help me research the best and safest used car under $15,000 for someone who mostly drives to church and the store",
        "Can you make a digital photo slideshow with music for my granddaughter's graduation party?",
        "Help me figure out how to lower my electric bill — look at what's using the most power and give me a plan",
        "I want to write my life story for the grandkids — help me outline the chapters and start the first one about growing up on the farm",
        "Can you build a simple form so my church group can sign up to bring food to the potluck?",
        "Help me compare three Medicare supplement plans and tell me which is best for my situation",
        "Make me a printable chore chart with stickers for when the grandkids visit",
        "Can you help me sell my late husband's tools online — write the listings and price them fairly?",
        "I keep forgetting birthdays — set up something that reminds me a week before each family member's birthday",
        "Help me plan and budget a 10-day road trip to see the national parks with my sister",
    ],
    "girl_10": [
        "make me a game where a cat jumps over boxes and gets points pleaseee",
        "can you make a quiz about horses for me and my friends to play",
        "i want a poster about saving the ocean for my school project with cool facts",
        "build a drawing app where i can paint with rainbow colors and save my pictures",
        "help me write a story about a dragon who is scared of flying",
        "make a website about my pet hamster named Nibbles with pictures",
        "can you make flashcards to help me learn my times tables up to 12",
        "i want a secret diary on the computer that needs a password to open",
        "make a spinning wheel that picks which chore i have to do",
        "help me make a birthday card for my mom that has a popup heart",
        "can you build a maze game where you have to find the cheese",
        "make a list of fun science experiments i can do at home with stuff in the kitchen",
        "help me make a comic strip about a superhero who can talk to animals",
        "i want a countdown to my birthday that shows how many days are left",
        "make a music thing where i can press keys and it plays sounds",
        "help me plan a lemonade stand — how much should i sell it for to make money",
        "can you make a memory matching game with emojis",
        "i want to learn to code, can you teach me to make something move on the screen",
        "make a chart to track how many books i read this summer",
        "help me write a funny speech for class about why dogs are better than cats",
    ],
    "woman_25": [
        "Can you set up a budget tracker that categorizes my monthly spending and shows where my money actually goes?",
        "I need a portfolio website to show off my photography with a gallery and a contact form",
        "Help me plan a 7-day trip to Japan with a day-by-day itinerary, budget, and must-see spots",
        "Draft a resignation letter that stays professional and warm since I actually like my boss",
        "Build me a habit tracker app where I can check off water, gym, and reading every day",
        "Help me negotiate my salary — research the market rate for a UX designer in Austin and write my talking points",
        "Can you make a meal-prep plan for the week that's high-protein, under $60 of groceries, and a shopping list?",
        "I'm starting an Etsy shop for handmade jewelry — help me name it, write the listings, and plan the launch",
        "Help me build a personal finance dashboard that pulls in my spending and shows trends over time",
        "Write me a dating profile that's funny and authentic, not cringey",
        "Help me plan my friend's bachelorette weekend in Nashville — itinerary, budget split, and a group poll",
        "Can you build a simple CRM to track the freelance clients I'm pitching and follow-ups?",
        "Help me study for the GRE — make me a 6-week plan and quiz me on vocab",
        "I want to start investing — explain index funds simply and help me set up a beginner portfolio plan",
        "Build a wedding planning spreadsheet with budget, guest list, vendor tracker, and timeline",
        "Help me write and design a one-page resume tailored to a product design role",
        "Can you make an app that splits group expenses with my roommates and tracks who owes what?",
        "Help me plan a content calendar for my Instagram for the next month with post ideas and captions",
        "I need to file my taxes as a freelancer — walk me through it and build a deductions tracker",
        "Help me launch a small newsletter — set up the signup, write the welcome email, and a first issue",
    ],
    "engineer_junior": [
        "Fix the race condition in the websocket reconnect logic that drops messages on flaky networks",
        "Refactor the auth middleware to support token refresh without breaking existing sessions",
        "Investigate why the CI build is flaky on the integration tests and propose a fix",
        "Implement a rate limiter for the public API using a token-bucket algorithm",
        "build me a CLI that converts CSV files to parquet with a progress bar and schema inference",
        "Add OpenTelemetry tracing across the request path and export to the collector",
        "Write integration tests for the payment webhook handler including the failure paths",
        "Set up a pre-commit config with ruff, mypy, and a secret scanner for this repo",
        "Debug why the Docker image is 2GB and slim it down with a multi-stage build",
        "Implement optimistic locking on the orders table to prevent double-processing",
        "Migrate the REST endpoints to use Pydantic v2 models and fix the validation errors",
        "Profile the slow /search endpoint and bring p99 latency under 200ms",
        "Add a GitHub Action that runs the test matrix across Python 3.10-3.12 and posts coverage",
        "Implement graceful shutdown so in-flight requests finish before the server exits",
        "Write a database migration that backfills the new tenant_id column without downtime",
        "Set up structured JSON logging with request IDs propagated through async tasks",
        "Build a feature flag system with percentage rollouts and a kill switch",
        "Fix the memory leak in the background worker that grows unbounded over 24h",
        "Add idempotency keys to the checkout API so retries don't double-charge",
        "Implement cursor-based pagination on the activity feed to replace offset pagination",
    ],
    "engineer_senior": [
        "Design and implement a saga pattern for the distributed order/payment/inventory workflow with compensating transactions",
        "Audit the codebase for SSRF, injection, and auth-bypass vulnerabilities and fix the real ones",
        "Introduce a read-replica routing layer so read-heavy queries don't hit the primary",
        "Refactor the monolith's billing module into a separately deployable service with a clean contract",
        "Build a backpressure-aware ingestion pipeline that handles 10x traffic spikes without dropping events",
        "Implement zero-downtime blue-green deploys with automated rollback on health-check failure",
        "Design an event-sourced audit log with snapshotting and replay for the compliance team",
        "Add end-to-end encryption for messages with key rotation and forward secrecy",
        "Build a multi-region active-active setup with conflict resolution for the user store",
        "Instrument and fix the N+1 query storm in the dashboard that's melting the database",
        "Implement a circuit breaker and bulkhead isolation around the flaky third-party fraud API",
        "Design a schema-migration strategy for the 200M-row events table with no read downtime",
        "Build a deterministic replay test harness for the matching engine to catch nondeterminism",
        "Harden the CI/CD pipeline: signed commits, provenance attestation, and dependency pinning",
        "Implement adaptive concurrency limits on the gateway based on observed latency",
        "Design a tenant isolation model that prevents noisy-neighbor and data-leak across customers",
        "Replace the cron-based job runner with a durable workflow engine and exactly-once semantics",
        "Build a cost-attribution system that tags cloud spend by team and surfaces anomalies",
        "Implement a write-ahead caching layer with invalidation that survives a cache-cluster restart",
        "Lead the migration from REST to gRPC for the internal services with a compatibility shim",
    ],
    "man_50_hobbyist": [
        "Help me build a smart-home dashboard that shows my thermostat, cameras, and energy use in one place",
        "I restore old cars — build me an inventory app to track parts, costs, and which project each goes to",
        "Help me plan and budget a backyard deck build with a materials list and a cut diagram",
        "Set up a home media server and organize my movie and music collection so it streams to the TV",
        "Help me write a business plan for a part-time woodworking side business",
        "Build me a fishing log that tracks spot, weather, bait, and what I caught, with charts",
        "Help me research and pick a 3D printer under $800 for making model train parts",
        "Make a workout and nutrition plan for a 50-year-old who wants to get back in shape safely",
        "Help me build a simple website for my church's volunteer scheduling",
        "I want to learn guitar — build me a practice tracker and a 12-week beginner plan",
        "Help me automate my sprinkler system based on the weather forecast",
        "Build a tool that compares prices across stores for the lumber I buy regularly",
        "Help me digitize and organize 40 years of family slides and photos",
        "Plan a cross-country motorcycle trip with routes, stops, and a packing list",
        "Help me set up a small home network with a guest wifi and parental controls",
        "Build a budget and timeline for renovating my basement into a workshop",
        "Help me write my retirement-readiness plan — what I need saved and when I can retire",
        "Make a maintenance schedule app for my truck, mower, and generator with reminders",
        "Help me start a YouTube channel about car restoration — gear list, first video script, channel plan",
        "Build a tool to track my home-brewing batches: recipe, gravity readings, and tasting notes",
    ],
}

_FILLER_STARTS = ("hi ", "hey ", "hello ", "can you", "could you", "please ", "i want", "i need", "i'd like", "i would", "help me make", "help me write", "help me plan", "help me build", "i'm ", "make me", "build me")


def main() -> None:
    rows = []
    for persona, tasks in PERSONAS.items():
        for i, task in enumerate(tasks):
            title = derive_active_goal(task, current_goal="")
            low = title.lower()
            rows.append(
                {
                    "persona": persona,
                    "idx": i,
                    "task": task,
                    "card_title": title,
                    "word_count": len(title.split()),
                    "starts_with_filler": low.startswith(_FILLER_STARTS),
                    "is_fallback": title == "New task",
                }
            )
    total = len(rows)
    filler = sum(1 for r in rows if r["starts_with_filler"])
    fallback = sum(1 for r in rows if r["is_fallback"])
    long = sum(1 for r in rows if r["word_count"] > 11)
    print(json.dumps({
        "total_tasks": total,
        "personas": list(PERSONAS.keys()),
        "summary": {
            "filler_titles": filler,
            "fallback_titles": fallback,
            "overlong_titles(>11w)": long,
        },
        "rows": rows,
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
