import unittest
from pathlib import Path


class GovernanceTests(unittest.TestCase):
    def test_claim_registry_has_required_fields(self):
        text = Path("docs/CLAIMS.md").read_text()
        for field in ("Evidence", "Scope", "Limitations", "Allowed wording"):
            self.assertIn(field, text)

    def test_threat_model_names_core_trust_boundaries(self):
        text = Path("docs/THREAT-MODEL.md").read_text()
        for term in ("client", "TOKEN gateway", "upstream", "recovery store"):
            self.assertIn(term, text)

    def test_release_process_has_promotion_ladder(self):
        text = Path("docs/RELEASE-PROCESS.md").read_text()
        for term in (
            "private RC",
            "deterministic export",
            "runtime digest equivalence",
            "owner-approved release",
        ):
            self.assertIn(term, text)

    def test_lessons_ledger_has_permanent_fields(self):
        text = Path("docs/engineering/LESSONS.md").read_text()
        for field in (
            "Incident",
            "Root cause",
            "Why gate missed it",
            "Permanent prevention",
            "Regression test",
        ):
            self.assertIn(field, text)

    def test_public_contribution_bridge_is_explicit(self):
        text = Path("CONTRIBUTING.md").read_text()
        self.assertIn("private canonical", text)
        self.assertIn("public pull request", text)
        self.assertIn("canonical verification", text)

    def test_github_governance_requires_main_protection(self):
        text = Path("docs/GITHUB-GOVERNANCE.md").read_text()
        for rule in (
            "block force-push",
            "block deletion",
            "require CI",
            "pull request",
        ):
            self.assertIn(rule, text)


if __name__ == "__main__":
    unittest.main()
