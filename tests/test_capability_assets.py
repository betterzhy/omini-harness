from __future__ import annotations

from pathlib import Path


def test_repository_contains_exact_bootstrap_seed_set():
    from evolution_harness.loader import load_capabilities

    root = Path(__file__).parents[1]
    capabilities = load_capabilities(root)
    ids = {c.id for c in capabilities}
    assert ids == {
        "principle:agent-design:canonical-capability-not-runtime-prompt",
        "principle:agent-design:project-truth-over-generic-guidance",
        "principle:agent-design:closure-requires-authority",
        "framework:agent-design:authority-analysis",
        "framework:agent-design:lifecycle-analysis",
        "skill:agent-design:design-closure-assessment",
        "skill:agent-design:baseline-finalization",
        "skill:agent-design:next-topic-routing",
        "skill:agent-design:architecture-review",
        "workflow:agent-design:design-discussion",
    }


def test_seed_assets_validate_against_kind_schema_and_have_content():
    from evolution_harness.loader import load_capabilities
    from evolution_harness.schema import SchemaStore

    root = Path(__file__).parents[1]
    store = SchemaStore(root)
    for capability in load_capabilities(root):
        store.validate(f"design/schemas/{capability.kind.lower()}.schema.json", capability.asset)
        assert capability.content_path.exists()
        assert capability.content.strip()


def test_semantic_body_stays_markdown_not_structured_as_megapayload():
    from evolution_harness.loader import load_capabilities

    root = Path(__file__).parents[1]
    by_id = {c.id: c for c in load_capabilities(root)}
    skill = by_id["skill:agent-design:architecture-review"].asset
    framework = by_id["framework:agent-design:authority-analysis"].asset
    principle = by_id["principle:agent-design:project-truth-over-generic-guidance"].asset
    assert "procedure" not in skill["skill"]
    assert "questions" not in framework["framework"]
    assert "rationale" not in principle["principle"]


def test_bootstrap_seed_provenance_is_source_referenced_not_source_copied():
    from evolution_harness.loader import load_capabilities

    root = Path(__file__).parents[1]
    for capability in load_capabilities(root):
        for source in capability.asset["provenance"]:
            assert source["reference"]
            assert "fullTranscript" not in source
            assert "messages" not in source
