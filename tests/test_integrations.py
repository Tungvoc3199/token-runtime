import tempfile
import unittest
from pathlib import Path

from token_runtime.integrations import (
    apply_plan,
    detect_integrations,
    plan_install,
    restore_plan,
    uninstall_integration,
)


class IntegrationTests(unittest.TestCase):
    def test_detects_codex_config_and_generic_openai_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".codex").mkdir()
            (root / ".codex" / "config.toml").write_text(
                'model = "gpt-example"\n', encoding="utf-8"
            )
            (root / ".env").write_text(
                "OPENAI_API_KEY=sentinel\n", encoding="utf-8"
            )
            found = detect_integrations(root)
            self.assertEqual({item.kind for item in found}, {"codex", "openai_env"})

    def test_codex_plan_changes_only_single_provider_base_url_and_restores_byte_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / ".codex" / "config.toml"
            config.parent.mkdir()
            original = (
                b'model = "x"\n'
                b'[model_providers.router9]\n'
                b'name = "ExampleRouter"\n'
                b'base_url = "http://127.0.0.1:20128/v1"\n'
                b'wire_api = "responses"\n'
            )
            config.write_bytes(original)
            integration = detect_integrations(root)[0]
            plan = plan_install(integration, gateway_url="http://127.0.0.1:8788/v1")
            self.assertEqual(plan.mode, "managed_toml")
            self.assertEqual(plan.target_path, config)
            self.assertTrue(plan.safe_to_apply)
            apply_plan(plan, apply=True)
            changed = config.read_bytes()
            self.assertIn(b'base_url = "http://127.0.0.1:8788/v1"', changed)
            self.assertIn(b'name = "ExampleRouter"', changed)
            restore_plan(plan, apply=True)
            self.assertEqual(config.read_bytes(), original)

    def test_codex_uninstall_refuses_config_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / ".codex" / "config.toml"
            config.parent.mkdir()
            config.write_text('[model_providers.router9]\nbase_url = "http://127.0.0.1:20128/v1"\n')
            integration = detect_integrations(root)[0]
            plan = plan_install(integration, gateway_url="http://127.0.0.1:8788/v1")
            apply_plan(plan, apply=True)
            config.write_text(config.read_text() + '# user change\n')
            before = config.read_bytes()
            result = uninstall_integration(integration, apply=True)
            self.assertFalse(result.changed)
            self.assertEqual(result.reason, "target_drift")
            self.assertEqual(config.read_bytes(), before)

    def test_codex_multiple_providers_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / ".codex" / "config.toml"
            config.parent.mkdir()
            config.write_text(
                '[model_providers.a]\nbase_url = "http://a/v1"\n'
                '[model_providers.b]\nbase_url = "http://b/v1"\n'
            )
            integration = detect_integrations(root)[0]
            plan = plan_install(integration, gateway_url="http://127.0.0.1:8788/v1")
            self.assertFalse(plan.safe_to_apply)
            self.assertEqual(plan.reason, "ambiguous_codex_provider")
            before = config.read_bytes()
            result = apply_plan(plan, apply=True)
            self.assertFalse(result.changed)
            self.assertEqual(config.read_bytes(), before)

    def test_env_dry_run_does_not_mutate_and_apply_restore_is_byte_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_path = root / ".env"
            original = b"OPENAI_API_KEY=sentinel\nCUSTOM=1\n"
            env_path.write_bytes(original)
            integration = detect_integrations(root)[0]
            plan = plan_install(integration, gateway_url="http://127.0.0.1:8788/v1")
            preview = apply_plan(plan, apply=False)
            self.assertTrue(preview.changed)
            self.assertEqual(env_path.read_bytes(), original)
            apply_plan(plan, apply=True)
            changed = env_path.read_bytes()
            self.assertIn(b"TOKEN MANAGED", changed)
            self.assertIn(b"OPENAI_BASE_URL=http://127.0.0.1:8788/v1", changed)
            self.assertNotEqual(changed, original)
            restore_plan(plan, apply=True)
            self.assertEqual(env_path.read_bytes(), original)

    def test_env_plan_refuses_unmanaged_existing_base_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_path = root / ".env"
            original = b"OPENAI_BASE_URL=https://custom.example/v1\n"
            env_path.write_bytes(original)
            integration = detect_integrations(root)[0]
            plan = plan_install(integration, gateway_url="http://127.0.0.1:8788/v1")
            self.assertFalse(plan.safe_to_apply)
            result = apply_plan(plan, apply=True)
            self.assertFalse(result.changed)
            self.assertEqual(env_path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()


class PersistentUninstallTests(unittest.TestCase):
    def test_uninstall_removes_only_token_managed_env_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_path = root / ".env"
            original = b"OPENAI_API_KEY=sentinel\nCUSTOM=1\n"
            env_path.write_bytes(original)
            integration = detect_integrations(root)[0]
            plan = plan_install(integration, gateway_url="http://127.0.0.1:8788/v1")
            apply_plan(plan, apply=True)
            result = uninstall_integration(integration, apply=True)
            self.assertTrue(result.changed)
            self.assertEqual(env_path.read_bytes(), original)

    def test_uninstall_codex_managed_provider_restores_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / ".codex" / "config.toml"
            config.parent.mkdir()
            original = b'[model_providers.router9]\nbase_url = "http://127.0.0.1:20128/v1"\n'
            config.write_bytes(original)
            integration = detect_integrations(root)[0]
            plan = plan_install(integration, gateway_url="http://127.0.0.1:8788/v1")
            apply_plan(plan, apply=True)
            result = uninstall_integration(integration, apply=True)
            self.assertTrue(result.changed)
            self.assertEqual(config.read_bytes(), original)
            self.assertFalse((root / ".token" / "integrations" / "codex.json").exists())

    def test_uninstall_restores_env_without_trailing_newline_byte_exactly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_path = root / ".env"
            original = b"OPENAI_API_KEY=sentinel"
            env_path.write_bytes(original)
            integration = detect_integrations(root)[0]
            plan = plan_install(integration, gateway_url="http://127.0.0.1:8788/v1")
            apply_plan(plan, apply=True)
            uninstall_integration(integration, apply=True)
            self.assertEqual(env_path.read_bytes(), original)
            metadata = root / ".token" / "integrations" / "openai_env.json"
            self.assertFalse(metadata.exists())
