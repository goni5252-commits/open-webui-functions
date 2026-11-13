"""Hydrogen model discovery and real SDK configuration; no paid API calls."""
import logging
import unittest
from unittest.mock import Mock
try:
    from google.genai import types
except ImportError:
    types = None
from test_conversation_images import Gemini


@unittest.skipIf(types is None, "google-genai is required for SDK configuration checks")
class HydrogenTests(unittest.TestCase):
    def setUp(self):
        self.pipe = object.__new__(Gemini)
        self.pipe.valves = Gemini.Valves()
        self.pipe.log = logging.getLogger('hydrogen-test')
        self.pipe._model_cache = None
        self.pipe._model_cache_time = 0

    def config(self, body=None, model='gemini-4-hydrogen'):
        return self.pipe._configure_generation(body or {}, None, {}, model_id=model)

    def test_supported_levels_and_legacy_budget_omitted(self):
        for level in ('low', 'medium', 'high', 'xhigh'):
            with self.subTest(level=level):
                cfg = self.config({'reasoning_effort': level, 'thinking_budget': 0,
                                   'temperature': .2, 'top_p': .3, 'top_k': 5})
                self.assertEqual(cfg.thinking_config.thinking_level.value.lower(), level)
                self.assertIsNone(cfg.thinking_config.thinking_budget)
                self.assertTrue(all(getattr(cfg, key) is None for key in ('temperature', 'top_p', 'top_k')))

    def test_minimal_normalized_and_manual_override(self):
        self.assertEqual(self.config({'reasoning_effort': 'minimal'}).thinking_config.thinking_level.value.lower(), 'low')
        self.pipe.valves.THINKING_LEVEL = 'xhigh'
        self.assertEqual(self.config().thinking_config.thinking_level.value.lower(), 'xhigh')
        self.assertEqual(self.config({'reasoning_effort': 'medium'}).thinking_config.thinking_level.value.lower(), 'medium')

    def test_default_preserves_provider_thinking_and_no_image_generation(self):
        cfg = self.config()
        self.assertIsNone(cfg.thinking_config.thinking_level)
        self.assertIsNone(cfg.thinking_config.thinking_budget)
        self.assertFalse(self.pipe._check_image_generation_support('gemini-4-hydrogen'))
        self.assertFalse(self.pipe._is_auto_thinking_candidate_model('gemini-4-hydrogen'))

    def test_discovery_with_saved_valves_and_whitelist(self):
        self.pipe.valves.MODEL_ADDITIONAL = 'gemini-3.7-flash'
        client = Mock()
        client.models.list.return_value = []
        self.pipe._get_client = lambda: client
        models = self.pipe.get_google_models(force_refresh=True)
        self.assertEqual(sum(m['id'] == 'gemini-4-hydrogen' for m in models), 1)
        self.pipe.valves.MODEL_WHITELIST = 'gemini-3.7-flash'
        self.assertNotIn('gemini-4-hydrogen', [m['id'] for m in self.pipe.get_google_models(force_refresh=True)])
        self.pipe.valves.MODEL_WHITELIST = 'gemini-4-hydrogen'
        client.models.list.return_value = [types.Model(name='models/gemini-4-hydrogen', supported_actions=['generateContent'])]
        self.assertEqual(len(self.pipe.get_google_models(force_refresh=True)), 1)

    def test_prefix_and_older_model_compatibility(self):
        self.assertEqual(self.pipe._prepare_model_id('google_gemini.gemini-4-hydrogen'), 'gemini-4-hydrogen')
        self.assertEqual(self.config({'reasoning_effort': 'xhigh'}, 'gemini-3.8-flash').thinking_config.thinking_level.value.lower(), 'high')
        self.assertEqual(self.config({'thinking_budget': 1024}, 'gemini-2.5-flash').thinking_config.thinking_budget, 1024)
