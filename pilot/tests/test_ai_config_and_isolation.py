"""Env-driven configuration, plus proof the AI package stays isolated from existing Engine 6."""
import ast
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from vm1.ai import (
    AIConfigError, CloudflareWorkersAIProvider, GroqProvider, MockProvider, provider_from_env,
)
from vm1.ai.cloudflare import DEFAULT_BASE_URL as CF_URL
from vm1.ai.groq import DEFAULT_BASE_URL as GROQ_URL

PKG = Path(__file__).resolve().parent.parent / "vm1"
AI_PKG = PKG / "ai"
TOKEN = "sekrit-token-123"


class ProviderFromEnvTests(unittest.TestCase):
    def test_nothing_is_selected_by_default(self):
        with self.assertRaisesRegex(AIConfigError, "ENGINE6_AI_PROVIDER is not set"):
            provider_from_env({})
        with self.assertRaisesRegex(AIConfigError, "unknown ENGINE6_AI_PROVIDER"):
            provider_from_env({"ENGINE6_AI_PROVIDER": "openai"})

    def test_mock_needs_no_keys(self):
        for value in ("mock", " MOCK "):
            self.assertIsInstance(provider_from_env({"ENGINE6_AI_PROVIDER": value}), MockProvider)

    def test_cloudflare_from_env(self):
        env = {"ENGINE6_AI_PROVIDER": "cloudflare", "CLOUDFLARE_ACCOUNT_ID": "acc1",
               "CLOUDFLARE_API_TOKEN": TOKEN, "CLOUDFLARE_AI_MODEL": "@cf/test/m"}
        p = provider_from_env(env)
        self.assertIsInstance(p, CloudflareWorkersAIProvider)
        self.assertEqual((p.account_id, p.model, p.base_url), ("acc1", "@cf/test/m", CF_URL))
        p = provider_from_env({**env, "CLOUDFLARE_AI_BASE_URL": "https://gw.example.test/x/"})
        self.assertEqual(p.base_url, "https://gw.example.test/x")

    def test_groq_from_env(self):
        env = {"ENGINE6_AI_PROVIDER": "groq", "GROQ_API_KEY": TOKEN, "GROQ_MODEL": "m"}
        p = provider_from_env(env)
        self.assertIsInstance(p, GroqProvider)
        self.assertEqual((p.model, p.base_url, p.response_mode, p.strict_schema), ("m", GROQ_URL, "json_object", False))
        p = provider_from_env({**env, "GROQ_RESPONSE_MODE": "json_schema", "GROQ_STRICT_SCHEMA": "TRUE",
                               "GROQ_BASE_URL": "https://gw.example.test/g"})
        self.assertEqual((p.response_mode, p.strict_schema, p.base_url),
                         ("json_schema", True, "https://gw.example.test/g"))

    def test_missing_variables_are_named_but_values_never_leak(self):
        with self.assertRaises(AIConfigError) as cm:
            provider_from_env({"ENGINE6_AI_PROVIDER": "cloudflare", "CLOUDFLARE_API_TOKEN": TOKEN})
        text = str(cm.exception)
        self.assertIn("CLOUDFLARE_ACCOUNT_ID", text)
        self.assertIn("CLOUDFLARE_AI_MODEL", text)
        self.assertNotIn("CLOUDFLARE_API_TOKEN", text)
        self.assertNotIn(TOKEN, text)
        with self.assertRaisesRegex(AIConfigError, "GROQ_API_KEY, GROQ_MODEL"):
            provider_from_env({"ENGINE6_AI_PROVIDER": "groq", "GROQ_API_KEY": "  "})

    def test_invalid_values_are_config_errors_without_leaking(self):
        base = {"ENGINE6_AI_PROVIDER": "groq", "GROQ_API_KEY": TOKEN, "GROQ_MODEL": "m"}
        for extra in ({"GROQ_RESPONSE_MODE": "xml"}, {"GROQ_STRICT_SCHEMA": "maybe"},
                      {"GROQ_BASE_URL": "http://insecure.example.test"}):
            with self.subTest(extra=extra), self.assertRaises(AIConfigError) as cm:
                provider_from_env({**base, **extra})
            self.assertNotIn(TOKEN, str(cm.exception))

    def test_environment_is_read_at_call_time_not_import_time(self):
        with mock.patch.dict(os.environ, {"ENGINE6_AI_PROVIDER": "mock"}, clear=True):
            self.assertIsInstance(provider_from_env(), MockProvider)
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(AIConfigError):
                provider_from_env()


class IsolationTests(unittest.TestCase):
    FORBIDDEN = {"smtplib", "imaplib", "poplib", "email", "googleapiclient", "google", "sendgrid", "mailgun",
                 "requests", "urllib3", "aiohttp", "httpx", "openai", "anthropic", "groq", "cloudflare"}

    @staticmethod
    def imports(path: Path):
        """Yield (top-level module, is_relative) for every import in a source file."""
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    yield alias.name, False
            elif isinstance(node, ast.ImportFrom):
                yield (node.module or ""), node.level > 0

    def test_ai_package_uses_only_stdlib_and_itself(self):
        files = sorted(AI_PKG.glob("*.py"))
        self.assertGreaterEqual(len(files), 8)
        for path in files:
            for module, relative in self.imports(path):
                top = module.split(".")[0]
                with self.subTest(file=path.name, module=module):
                    if relative:
                        continue
                    self.assertIn(top, sys.stdlib_module_names)
                    self.assertNotIn(top, self.FORBIDDEN)

    def test_ai_package_never_reaches_outside_itself(self):
        for path in AI_PKG.glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and node.level > 1:
                    self.fail(f"{path.name} imports from outside vm1.ai")
                if isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "").startswith("vm1"):
                    self.fail(f"{path.name} imports vm1 absolutely")

    def test_existing_modules_do_not_import_the_ai_package(self):
        for path in sorted(PKG.glob("*.py")):
            for module, relative in self.imports(path):
                with self.subTest(file=path.name, module=module):
                    self.assertFalse(
                        (relative and module.split(".")[0] == "ai") or module.startswith("vm1.ai"),
                        f"{path.name} imports the AI package",
                    )

    def test_no_provider_keys_are_hardcoded(self):
        for path in AI_PKG.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for marker in ("gsk_", "Bearer sk-", "cfut_"):
                self.assertNotIn(marker, text, f"{path.name} looks like it embeds a credential")

    def test_importing_the_package_does_no_network_or_env_io_in_a_fresh_interpreter(self):
        # Pre-import the stdlib modules the package needs (CPython's own `re` reads an env var at
        # import) so the traps below only observe vm1.ai's own import-time behaviour.
        stdlib = sorted({m for p in AI_PKG.glob("*.py") for m, rel in self.imports(p) if m and not rel})
        code = (
            "import os, socket, sys\n"
            f"for m in {stdlib!r}: __import__(m)\n"
            "def boom(*a, **k): raise AssertionError('network attempted at import')\n"
            "socket.socket.connect = boom; socket.getaddrinfo = boom; socket.create_connection = boom\n"
            "class Env(dict):\n"
            "    def __getitem__(self, k): raise AssertionError('env read at import')\n"
            "    def get(self, *a, **k): raise AssertionError('env read at import')\n"
            "os.environ = Env()\n"
            f"sys.path.insert(0, {str(PKG.parent)!r})\n"
            "import vm1.ai\n"
            "print('imported', len(vm1.ai.__all__))\n"
        )
        proc = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("imported", proc.stdout)


if __name__ == "__main__":
    unittest.main()
