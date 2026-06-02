import os
import tempfile
import unittest
from pathlib import Path

from agent.runtime.factory import load_llm_client


class AgentLlmConfigTests(unittest.TestCase):
    def test_load_llm_client_reads_dotenv_file(self):
        old_env = dict(os.environ)
        try:
            os.environ.clear()
            with tempfile.TemporaryDirectory() as temp_dir:
                env_path = Path(temp_dir) / ".env"
                env_path.write_text(
                    "\n".join(
                        [
                            "WEREWOLF_LLM_API_KEY=v2-dotenv-key",
                            "WEREWOLF_LLM_BASE_URL=https://v2-dotenv.test/api/v1",
                            "WEREWOLF_LLM_MODEL=v2/model",
                            "WEREWOLF_LLM_TIMEOUT=11",
                            "WEREWOLF_LLM_TEMPERATURE=0.3",
                        ]
                    ),
                    encoding="utf-8",
                )

                client = load_llm_client(env_path=env_path)

            self.assertEqual(client.api_key, "v2-dotenv-key")
            self.assertEqual(client.base_url, "https://v2-dotenv.test/api/v1")
            self.assertEqual(client.model, "v2/model")
            self.assertEqual(client.timeout, 11)
            self.assertEqual(client.temperature, 0.3)
        finally:
            os.environ.clear()
            os.environ.update(old_env)

    def test_environment_values_override_dotenv_file(self):
        old_env = dict(os.environ)
        try:
            os.environ.clear()
            with tempfile.TemporaryDirectory() as temp_dir:
                env_path = Path(temp_dir) / ".env"
                env_path.write_text(
                    "\n".join(
                        [
                            "WEREWOLF_LLM_API_KEY=v2-dotenv-key",
                            "WEREWOLF_LLM_MODEL=v2-dotenv/model",
                        ]
                    ),
                    encoding="utf-8",
                )
                os.environ["WEREWOLF_LLM_API_KEY"] = "v2-real-env-key"
                os.environ["WEREWOLF_LLM_MODEL"] = "v2-real-env/model"

                client = load_llm_client(env_path=env_path)

            self.assertEqual(client.api_key, "v2-real-env-key")
            self.assertEqual(client.model, "v2-real-env/model")
        finally:
            os.environ.clear()
            os.environ.update(old_env)


if __name__ == "__main__":
    unittest.main()
