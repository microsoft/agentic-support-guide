"""Export the dealer group evidence fixtures as documents for Foundry IQ.

Module 6 needs real files in blob storage to index. The in-repo fixtures
are the same evidence the agents already use, so grounding the agent on
these exports means the knowledge base and the coordinator see the same
facts.

Usage:
  python scripts/export_knowledge_docs.py
  python scripts/export_knowledge_docs.py --out evals/knowledge
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

DEFAULT_OUT = REPO_ROOT / "evals" / "knowledge"


async def _export(out_dir: Path) -> int:
    from app.evidence import EvidenceRequest, FixtureEvidenceRetriever
    from app.evidence.fixtures import list_available_dealer_groups
    from app.mock_data import CATEGORY_IDS

    retriever = FixtureEvidenceRetriever()
    out_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for group in list_available_dealer_groups():
        for category in CATEGORY_IDS:
            bundle = await retriever.retrieve(
                EvidenceRequest(
                    dealer_group_id=group,
                    category=category,
                    detected_need_hint="",
                )
            )
            if not bundle.citations:
                continue

            lines = [
                f"# {group} - {category}",
                "",
                "Dealer group: " + group,
                "Category: " + category,
                "",
                "> Synthetic data. Nothing here is a pricing, financing, credit,",
                "> compliance, safety, or staffing determination. A human reviews",
                "> every recommendation.",
                "",
            ]
            for c in bundle.citations:
                lines += [
                    f"## {c.source_title}",
                    "",
                    f"- Citation ID: {c.citation_id}",
                    f"- Dealer group: {c.dealer_group_id}",
                    f"- Source type: {c.source_type.value}",
                    f"- Section: {c.section_or_page}",
                    "",
                    c.evidence_summary,
                    "",
                ]

            path = out_dir / f"{group.lower()}-{category}.md"
            path.write_text("\n".join(lines), encoding="utf-8")
            written += 1

    print(f"Wrote {written} document(s) to {out_dir}")
    print("\nUpload with:")
    print("  az storage blob upload-batch \\")
    print("    --account-name <storage-account> \\")
    print("    --destination group-knowledge \\")
    print(f"    --source {out_dir.relative_to(REPO_ROOT)} \\")
    print("    --auth-mode login")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output directory.")
    args = parser.parse_args()
    return asyncio.run(_export(Path(args.out)))


if __name__ == "__main__":
    raise SystemExit(main())
