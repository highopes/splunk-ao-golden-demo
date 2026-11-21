"""On-prem / Kubernetes regressions: backend profiles, in-cluster addresses, vLLM, Luna metrics, deploy tool."""
import asyncio
import importlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

ROOT = Path(__file__).resolve().parents[1]
ONPREM = {
    'backend_profile': 'imlab-onprem', 'galileo_console_url': 'https://console.ao.example',
    'galileo_api_key': 'fixture-only', 'openai_api_key': 'fixture-only',
    'agent_control_agent_name': 'fixture-agent', 'agent_control_api_key_header': 'Splunk-AO-API-Key',
}
IN_CLUSTER = {
    **ONPREM,
    'galileo_api_url': 'https://api.galileo.svc.cluster.local:8088',
    'galileo_ingest_url': 'https://ingest-service.galileo.svc.cluster.local:8081',
    'agent_control_url': 'http://agent-control.galileo.svc.cluster.local:8000',
}


class BackendProfileTests(unittest.TestCase):
    def test_onprem_derives_public_addresses_without_tenant_path(self):
        from setup_env import resolve_backend_settings
        backend = resolve_backend_settings(ONPREM)
        self.assertEqual(backend['api_url'], 'https://api.ao.example')
        self.assertEqual(backend['agent_control_url'], 'https://api.ao.example/agent-control')
        self.assertEqual(backend['demo_console_url'], 'https://console.ao.example')
        self.assertEqual(backend['rest_base_url'], 'https://api.ao.example')
        self.assertEqual(backend['ingest_url'], '')
        self.assertEqual(resolve_backend_settings({**ONPREM, 'agent_control_api_key_header': ''})['control_header'], 'Splunk-AO-API-Key')

    def test_in_cluster_addresses_override_and_console_only_for_links(self):
        from setup_env import setup_environment
        with patch('setup_env.toml.load', return_value=IN_CLUSTER), patch.dict(os.environ, {}), \
                patch('helpers.galileo_ingest.configure_ingest_url') as configure:
            setup_environment()
            self.assertEqual(os.environ['GALILEO_API_URL'], IN_CLUSTER['galileo_api_url'])
            self.assertEqual(os.environ['GALILEO_REST_BASE_URL'], IN_CLUSTER['galileo_api_url'])
            self.assertEqual(os.environ['AGENT_CONTROL_URL'], IN_CLUSTER['agent_control_url'])
            self.assertEqual(os.environ['GALILEO_INGEST_URL'], IN_CLUSTER['galileo_ingest_url'])
            self.assertEqual(os.environ['DEMO_CONSOLE_URL'], 'https://console.ao.example')
            self.assertEqual(os.environ['DEMO_BACKEND_PROFILE'], 'imlab-onprem')
        configure.assert_called_once_with(IN_CLUSTER['galileo_ingest_url'])

    def test_switching_profile_clears_stale_ingest_url(self):
        from setup_env import setup_environment
        splunkse = {**ONPREM, 'backend_profile': 'splunkse', 'galileo_console_url': 'https://console.multitenant.galileocloud.io',
                    'agent_control_api_key_header': 'Galileo-API-Key'}
        with patch('setup_env.toml.load', return_value=splunkse), patch.dict(os.environ, {'GALILEO_INGEST_URL': 'https://stale'}), \
                patch('helpers.galileo_ingest.configure_ingest_url') as configure:
            setup_environment()
            self.assertNotIn('GALILEO_INGEST_URL', os.environ)
            self.assertEqual(os.environ['GALILEO_REST_BASE_URL'], 'https://console.multitenant.galileocloud.io/api/galileo')
        configure.assert_called_once_with('')

    def test_invalid_profile_or_header_errors_do_not_echo_secrets(self):
        from setup_env import setup_environment
        for bad in ({**ONPREM, 'backend_profile': 'nope'}, {**ONPREM, 'agent_control_api_key_header': 'Authorization'},
                    {**ONPREM, 'backend_profile': 'splunkse'}):
            with self.subTest(bad=bad['backend_profile']), patch('setup_env.toml.load', return_value=bad), \
                    patch.dict(os.environ, {}), self.assertRaises(ValueError) as ctx:
                setup_environment()
            self.assertNotIn('fixture-only', str(ctx.exception))

    def test_control_header_default_follows_profile(self):
        from helpers.agent_control_helpers import _profile_default_control_header
        with patch.dict(os.environ, {'DEMO_BACKEND_PROFILE': 'imlab-onprem'}):
            self.assertEqual(_profile_default_control_header(), 'Splunk-AO-API-Key')
        with patch.dict(os.environ, {'DEMO_BACKEND_PROFILE': 'splunkse'}):
            self.assertEqual(_profile_default_control_header(), 'Galileo-API-Key')


class RestHelperTests(unittest.TestCase):
    def _call(self, env):
        from helpers import galileo_api_helpers as helpers
        post = MagicMock(); post.return_value.json.return_value = {'projects': [{'name': 'p', 'id': 'pid'}]}
        get = MagicMock(); get.return_value.json.return_value = [{'name': 's', 'id': 'sid'}]
        with patch.dict(os.environ, env), patch.object(helpers.requests, 'post', post), patch.object(helpers.requests, 'get', get):
            self.assertEqual(helpers.get_galileo_project_id('p'), 'pid')
            self.assertEqual(helpers.get_galileo_log_stream_id('pid', 's'), 'sid')
        return post.call_args, get.call_args

    def test_onprem_calls_api_directly(self):
        post, get = self._call({'GALILEO_API_KEY': 'fixture-only', 'GALILEO_CONSOLE_URL': 'https://console.ao.example',
                                'GALILEO_REST_BASE_URL': 'https://api.galileo.svc.cluster.local:8088'})
        self.assertTrue(post.args[0].startswith('https://api.galileo.svc.cluster.local:8088/public/v2/projects/paginated'))
        self.assertEqual(get.args[0], 'https://api.galileo.svc.cluster.local:8088/v2/projects/pid/log_streams')
        self.assertNotIn('origin', post.kwargs['headers'])

    def test_splunkse_keeps_console_proxy(self):
        console = 'https://console.multitenant.galileocloud.io'
        post, get = self._call({'GALILEO_API_KEY': 'fixture-only', 'GALILEO_CONSOLE_URL': console,
                                'GALILEO_REST_BASE_URL': f'{console}/api/galileo'})
        self.assertTrue(post.args[0].startswith(f'{console}/api/galileo/public/v2/projects/paginated'))
        self.assertEqual(get.args[0], f'{console}/api/galileo/v2/projects/pid/log_streams')
        self.assertEqual(post.kwargs['headers']['origin'], console)


class IngestUrlTests(unittest.TestCase):
    def tearDown(self):
        from helpers.galileo_ingest import configure_ingest_url
        configure_ingest_url(None)
        importlib.import_module('galileo.logger.logger')._ingest_service_cache.clear()

    def test_probe_and_native_writes_use_ingest_url_updates_stay_on_api(self):
        from helpers.galileo_ingest import configure_ingest_url
        from galileo.traces import IngestTraces
        from galileo import GalileoLogger
        logger_module = importlib.import_module('galileo.logger.logger')
        ingest = 'https://ingest-service.galileo.svc.cluster.local:8081'
        self.assertTrue(configure_ingest_url(ingest + '/'))
        response = MagicMock(is_success=True)
        with patch.object(logger_module.httpx, 'get', return_value=response) as get, \
                patch.object(logger_module.GalileoPythonConfig, 'get', return_value=MagicMock(extra_headers=None)):
            self.assertTrue(GalileoLogger._is_ingest_service_available())
        self.assertEqual(get.call_args.args[0], f'{ingest}/ingest/healthz')

        client = IngestTraces(project_id='00000000-0000-0000-0000-000000000001',
                              base_url='https://api.galileo.svc.cluster.local:8088', api_key='fixture-only')
        http = MagicMock(); http.post = AsyncMock(return_value=MagicMock(json=lambda: {}, raise_for_status=lambda: None))
        http.patch = AsyncMock(return_value=MagicMock(json=lambda: {}, raise_for_status=lambda: None))
        client._thread_local.client = http
        request = MagicMock(); request.traces = []; request.model_dump.return_value = {}
        asyncio.run(client.ingest_traces(request))
        self.assertTrue(http.post.call_args.args[0].startswith(f'{ingest}/ingest/traces/'))
        update = MagicMock(trace_id='t1'); update.model_dump.return_value = {}
        asyncio.run(client.update_trace(update))
        self.assertTrue(http.patch.call_args.args[0].startswith('https://api.galileo.svc.cluster.local:8088/v2/projects/'))
        self.assertEqual(client.base_url, 'https://api.galileo.svc.cluster.local:8088')

    def test_unconfigured_keeps_sdk_default(self):
        from helpers.galileo_ingest import configure_ingest_url, current_ingest_url
        from galileo import GalileoLogger
        logger_module = importlib.import_module('galileo.logger.logger')
        self.assertFalse(configure_ingest_url(''))
        self.assertIsNone(current_ingest_url())
        config = MagicMock(api_url='https://api.ao.example', extra_headers=None)
        with patch.object(logger_module.httpx, 'get', return_value=MagicMock(is_success=False)) as get, \
                patch.object(logger_module.GalileoPythonConfig, 'get', return_value=config):
            self.assertFalse(GalileoLogger._is_ingest_service_available())
        self.assertEqual(get.call_args.args[0], 'https://api.ao.example/ingest/healthz')


class HermesParserTests(unittest.TestCase):
    def test_single_and_multiple_tool_calls(self):
        from helpers.hermes_chat import parse_hermes_tool_calls
        text, calls = parse_hermes_tool_calls('<tool_call>\n{"name": "get_patient_info", "arguments": {"patient_id": "P001"}}\n</tool_call>')
        self.assertEqual(text, '')
        self.assertEqual([(c['name'], c['args']) for c in calls], [('get_patient_info', {'patient_id': 'P001'})])
        self.assertTrue(calls[0]['id'].startswith('call_'))
        text, calls = parse_hermes_tool_calls('Checking.\n<tool_call>{"name":"a","arguments":"{\\"x\\": 1}"}</tool_call>\n<tool_call>{"name":"b","arguments":{}}</tool_call>')
        self.assertEqual(text, 'Checking.')
        self.assertEqual([(c['name'], c['args']) for c in calls], [('a', {'x': 1}), ('b', {})])
        self.assertNotEqual(calls[0]['id'], calls[1]['id'])

    def test_broken_json_is_kept_verbatim_and_plain_text_unchanged(self):
        from helpers.hermes_chat import parse_hermes_tool_calls
        broken = '<tool_call>{"name": "a", "arguments": {</tool_call>'
        self.assertEqual(parse_hermes_tool_calls(broken), (broken, []))
        self.assertEqual(parse_hermes_tool_calls('Lisinopril: 10-40 mg once daily.'), ('Lisinopril: 10-40 mg once daily.', []))

    def test_think_residue_is_removed(self):
        from helpers.hermes_chat import parse_hermes_tool_calls
        self.assertEqual(parse_hermes_tool_calls('<think>\n\n</think>\n\nAnswer.')[0], 'Answer.')
        self.assertEqual(parse_hermes_tool_calls('reasoning...</think>\nAnswer.')[0], 'Answer.')

    def test_parsed_before_callbacks_and_request_format(self):
        from helpers.hermes_chat import HermesToolCallChatOpenAI
        from langchain_openai import ChatOpenAI
        raw = AIMessage(content='<tool_call>{"name": "get_patient_info", "arguments": {"patient_id": "P001"}}</tool_call>',
                        response_metadata={'finish_reason': 'stop'})
        llm = HermesToolCallChatOpenAI(model='Qwen/Qwen3-14B-FP8', base_url='http://vllm.invalid/v1', api_key='EMPTY')
        self.assertTrue(llm.disable_streaming)
        with patch.object(ChatOpenAI, '_agenerate', AsyncMock(return_value=ChatResult(generations=[ChatGeneration(message=raw)]))):
            result = asyncio.run(llm.ainvoke([HumanMessage(content='Show me data for patient P001.')]))
        self.assertEqual(result.content, '')
        self.assertEqual(result.tool_calls[0]['name'], 'get_patient_info')
        self.assertEqual(result.response_metadata['finish_reason'], 'tool_calls')
        call_id = result.tool_calls[0]['id']
        payload = llm._get_request_payload([HumanMessage(content='q'), result,
                                            ToolMessage(content='{"name": "John"}', tool_call_id=call_id)])
        self.assertEqual(payload['extra_body']['chat_template_kwargs'], {'enable_thinking': False})
        assistant, tool = payload['messages'][1], payload['messages'][2]
        self.assertEqual(assistant['tool_calls'][0]['function']['name'], 'get_patient_info')
        self.assertEqual(json.loads(assistant['tool_calls'][0]['function']['arguments']), {'patient_id': 'P001'})
        self.assertEqual((tool['role'], tool['tool_call_id']), ('tool', call_id))


class VllmProviderTests(unittest.TestCase):
    def test_vllm_is_optional_chat_provider_with_hosted_embeddings(self):
        from helpers.llm_utils import (configured_providers, default_provider, get_chat_model,
                                       resolve_embedding_provider, set_llm_provider, reset_llm_provider)
        from helpers.hermes_chat import HermesToolCallChatOpenAI
        env = {'OPENAI_API_KEY': 'fixture-only-key', 'VLLM_BASE_URL': 'http://vllm.invalid/v1', 'OLLAMA_BASE_URL': '',
               'AWS_BEARER_TOKEN_BEDROCK': '', 'EMBEDDING_PROVIDER': ''}
        with patch.dict(os.environ, env):
            self.assertEqual(configured_providers(), ['hosted', 'vllm'])
            self.assertEqual(default_provider(), 'hosted')
            token = set_llm_provider('vllm')
            try:
                self.assertEqual(resolve_embedding_provider(), 'hosted')
            finally:
                reset_llm_provider(token)
            llm = get_chat_model('Qwen/Qwen3-14B-FP8', provider='vllm', name='Healthcare Assistant')
        self.assertIsInstance(llm, HermesToolCallChatOpenAI)
        self.assertEqual(llm.openai_api_base, 'http://vllm.invalid/v1')

    def test_domain_info_lists_vllm_models(self):
        from domain_manager import DomainManager
        with patch.dict(os.environ, {'VLLM_DEFAULT_CHAT_MODEL': 'Qwen/Qwen3-14B-FP8'}):
            info = DomainManager().get_domain_info('healthcare')
        self.assertEqual(info['vllm_default_model'], 'Qwen/Qwen3-14B-FP8')
        self.assertEqual(info['vllm_models'][0], 'Qwen/Qwen3-14B-FP8')


class LunaMetricTests(unittest.TestCase):
    def test_profile_and_domain_metric_selection(self):
        from domain_manager import DomainManager
        from experiments.experiment_helpers import DEFAULT_METRICS, resolve_experiment_metrics
        dm = DomainManager()
        healthcare, cisco = dm.load_domain_config('healthcare').config, dm.load_domain_config('cisco_se').config
        self.assertEqual(resolve_experiment_metrics(healthcare, 'splunkse'), DEFAULT_METRICS)
        onprem = [m.name for m in resolve_experiment_metrics(healthcare, 'imlab-onprem')]
        self.assertIn('context_adherence_luna', onprem)
        self.assertIn('prompt_injection_luna', onprem)
        self.assertEqual([m.name for m in resolve_experiment_metrics(cisco, 'splunkse')], ['ground_truth_adherence', 'context_adherence'])
        self.assertEqual([m.name for m in resolve_experiment_metrics(cisco, 'imlab-onprem')], ['ground_truth_adherence', 'context_adherence_luna'])
        with self.assertRaises(ValueError):
            resolve_experiment_metrics({'experiments': {'metrics': ['no_such_metric']}}, 'splunkse')

    def test_exporter_prefers_luna_variant_on_onprem_only(self):
        from experiments.cisco_se_economics import CONTEXT_ADHERENCE_ALIASES, find_metric
        record = {'metric_info': {'m1': {'metric_key_alias': 'context_adherence'}, 'm2': {'metric_key_alias': 'context_adherence_luna'}}}
        self.assertEqual(find_metric(record, CONTEXT_ADHERENCE_ALIASES, prefer_luna=True)[0], 'm2')
        self.assertEqual(find_metric(record, CONTEXT_ADHERENCE_ALIASES, prefer_luna=False)[0], 'm1')
        with patch.dict(os.environ, {'DEMO_BACKEND_PROFILE': 'imlab-onprem'}):
            self.assertEqual(find_metric(record, CONTEXT_ADHERENCE_ALIASES)[0], 'm2')


class LlmControlInputTests(unittest.TestCase):
    def test_llm_control_input_is_latest_human_turn(self):
        from langchain_core.messages import SystemMessage
        from agent_control.control_decorators import _create_evaluation_payload
        from agent_frameworks.langgraph.agent import latest_user_text
        call = {'name': 'get_patient_info', 'args': {'patient_id': 'P001'}, 'id': 'c1', 'type': 'tool_call'}
        msgs = [SystemMessage(content='You are an assistant. Always use tools.'), HumanMessage(content='Show me data for patient P001.'),
                AIMessage(content='', tool_calls=[call]), ToolMessage(content='{"phone": "+1-555"}', tool_call_id='c1')]
        self.assertEqual(latest_user_text(msgs), 'Show me data for patient P001.')
        retry = msgs + [AIMessage(content='draft'), HumanMessage(content='Please revise your answer.')]
        self.assertEqual(latest_user_text(retry), 'Please revise your answer.')

        async def _invoke_llm(input: str, msgs):
            return None
        payload = _create_evaluation_payload(_invoke_llm, (latest_user_text(msgs), msgs), {}, step_name='Healthcare Assistant')
        self.assertEqual((payload['type'], payload['input']), ('llm', 'Show me data for patient P001.'))


class CheckDemoTests(unittest.TestCase):
    def test_preflight_runs_to_missing_secrets_without_crashing(self):
        spec = importlib.util.spec_from_file_location('check_demo', ROOT / 'scripts/check_demo.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as root, patch.object(module, 'ROOT', Path(root)), \
                patch('sys.argv', ['check_demo.py', '--in-cluster']), patch('builtins.print'):
            self.assertEqual(module.main(), 1)


class SecretsToolTests(unittest.TestCase):
    def setUp(self):
        path = ROOT / 'deploy/k8s/scripts/secrets_tool.py'
        if not path.is_file():
            self.skipTest('deploy/ tooling is not part of the app image')
        spec = importlib.util.spec_from_file_location('secrets_tool', path)
        self.tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.tool)

    def test_k8s_table_is_removed_from_app_secret(self):
        text = ('backend_profile = "imlab-onprem"\n# comment\npostgres_password = "pw"\n\n'
                '# Deployment settings\n[k8s]\nnamespace = "sao-golden"\nbasic_auth_password = "pw2"\n')
        stripped = self.tool.strip_k8s_table(text)
        self.assertNotIn('[k8s]', stripped)
        self.assertNotIn('pw2', stripped)
        self.assertIn('postgres_password = "pw"', stripped)

    def test_k8s_table_removed_anywhere_and_ambiguous_text_rejected(self):
        stripped = self.tool.strip_k8s_table('[k8s]\nnamespace = "x"\n[other]\nkey = "v"\n')
        self.assertEqual(stripped, '[other]\nkey = "v"\n')
        with self.assertRaises(self.tool.ToolError):
            self.tool.strip_k8s_table('note = """\n[k8s]\n"""\nkey = "v"\n')

    def test_check_and_secret_commands_never_print_to_terminal(self):
        with tempfile.NamedTemporaryFile('w', suffix='.toml', delete=False) as handle:
            handle.write('backend_profile = "imlab-onprem"\ngalileo_console_url = "https://console.ao.example"\n'
                         'galileo_api_key = ""\n[k8s]\nnamespace = "sao-golden"\nbasic_auth_password = "secret-pw"\n')
        try:
            data = self.tool.load(Path(handle.name))
            lines = dict(line.split(': ') for line in self.tool.check(data))
            self.assertEqual(lines['galileo_api_key'], 'EMPTY')
            self.assertEqual(lines['k8s.basic_auth_password'], 'set')
            self.assertEqual(lines['k8s.app_host'], 'MISSING')
            with patch('sys.stdout') as stdout:
                stdout.isatty.return_value = True
                with self.assertRaises(self.tool.ToolError):
                    self.tool.main(['--file', handle.name, 'k8s-secret', 'basic_auth_password'])
                with self.assertRaises(self.tool.ToolError):
                    self.tool.main(['--file', handle.name, 'k8s', 'basic_auth_password'])
            self.assertFalse(any('secret-pw' in str(c) for c in stdout.mock_calls))
        finally:
            os.unlink(handle.name)


if __name__ == '__main__':
    unittest.main()
