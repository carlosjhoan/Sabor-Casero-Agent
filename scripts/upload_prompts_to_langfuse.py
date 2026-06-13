"""
One-shot script: upload all prompt templates to Langfuse Prompt Management.

Reads paths from ``settings.prompt_fallback_map``, converts {variable} →
{{variable}} for mustache compatibility, and creates prompts in Langfuse.

Usage:
    .venv/Scripts/python scripts/upload_prompts_to_langfuse.py
    .venv/Scripts/python scripts/upload_prompts_to_langfuse.py --dry-run

Requires ``.env`` with ``LANGFUSE_PUBLIC_KEY``, ``LANGFUSE_SECRET_KEY``.
"""

import argparse
import os
import re
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def convert_variables(text: str) -> str:
    """Convert {variable} → {{variable}} for mustache compatibility.

    Uses negative lookbehind/lookahead to avoid breaking ``{{...}}`` blocks
    that are already escaped (e.g. JSON examples in few-shot prompts).
    """
    return re.sub(r"(?<!\{)\{(\w+)\}(?!\})", r"{{\1}}", text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload prompts to Langfuse")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be uploaded without making API calls",
    )
    args = parser.parse_args()

    # ── Source of truth: settings.prompt_fallback_map ────────────────
    from src.config.environment import settings as cfg

    fallback_map = cfg.prompt_fallback_map

    # ── Propagate Langfuse credentials to os.environ ────────────────
    os.environ.setdefault("LANGFUSE_PUBLIC_KEY", cfg.langfuse_public_key)
    os.environ.setdefault("LANGFUSE_SECRET_KEY", cfg.langfuse_secret_key)
    os.environ.setdefault("LANGFUSE_HOST", cfg.langfuse_host)

    if args.dry_run:
        print("=" * 60)
        print("  DRY RUN — no API calls will be made")
        print("=" * 60)
    else:
        from langfuse import Langfuse
        langfuse = Langfuse()

    errors = 0

    for name, rel_path in fallback_map.items():
        full_path = os.path.join(PROJECT_ROOT, rel_path)

        if not os.path.exists(full_path):
            print(f"⚠️  {name} — file not found: {rel_path}")
            errors += 1
            continue

        with open(full_path, "r", encoding="utf-8") as f:
            raw = f.read()

        converted = convert_variables(raw)

        if args.dry_run:
            print(f"\n{'─' * 60}")
            print(f"  Prompt: {name}")
            print(f"  File:   {rel_path}")
            print(f"  Size:   {len(raw)} chars → {len(converted)} chars")
            print(f"  Sample: {converted[:80].strip()}...")
            continue

        prompt = langfuse.create_prompt(
            name=name,
            prompt=converted,
            labels=["production"],
        )
        print(f"✅  {name} — v{prompt.version} ({len(converted)} chars)")

    if args.dry_run:
        print(f"\n{'=' * 60}")
        print(f"  Source: settings.prompt_fallback_map")
        print(f"  Prompts: {len(fallback_map)}")
        print(f"  Run without --dry-run to upload.")
    elif errors:
        print(f"\n{'=' * 60}")
        print(f"  Done with {errors} error(s).")
    else:
        print(f"\n{'=' * 60}")
        print(f"  All {len(fallback_map)} prompts uploaded successfully.")
        print(f"  The PromptManager will now fetch them from Langfuse.")


if __name__ == "__main__":
    main()
