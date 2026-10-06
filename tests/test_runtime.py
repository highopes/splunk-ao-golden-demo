"""Local regressions; fixtures never claim cloud evaluator/control acceptance."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from domain_manager import DomainManager
from helpers.llm_utils import configured_providers
from helpers.pgvector_utils import get_postgres_connection_string
from helpers.sql_utils import execute_sql
from helpers.agent_control_helpers import make_controlled_tool
from helpers.agent_control_helpers import init_agent_control
from agent_control import ControlViolationError, ControlSteerError
from experiments.experiment_helpers import read_dataset_csv, create_experiment_function
from galileo import GalileoLogger
from helpers.hallucination_helpers import log_hallucination_for_domain
from chaos_engine import ChaosEngine
from chaos_wrapper import wrap_tools_with_chaos

ROOT = Path(__file__).resolve().parents[1]


class RuntimeTests(unittest.TestCase):
    def test_simplified_secrets_derive_services_and_domain_routing(self):
        from setup_env import setup_environment, _derive_galileo_api_url, _derive_agent_control_url
        cfg=DomainManager().load_domain_config('healthcare').config
        minimal={'backend_profile':'splunkse','galileo_console_url':'https://console.multitenant.galileocloud.io',
            'galileo_api_key':'fixture-only','openai_api_key':'fixture-only',
            'agent_control_agent_name':'fixture-agent','agent_control_api_key_header':'Galileo-API-Key'}
        with patch('setup_env.toml.load',return_value=minimal), patch.dict(os.environ,{'GALILEO_API_URL':'stale','AGENT_CONTROL_URL':'stale','GALILEO_PROJECT':'stale','GALILEO_LOG_STREAM':'stale'}):
            setup_environment('healthcare',cfg)
            self.assertEqual(os.environ['GALILEO_API_URL'],'https://api.multitenant.galileocloud.io')
            self.assertEqual(os.environ['AGENT_CONTROL_URL'],'https://console.multitenant.galileocloud.io/api/agent-control')
            self.assertEqual(os.environ['DEMO_CONSOLE_URL'],'https://console.multitenant.galileocloud.io/splunkse')
            self.assertEqual(os.environ['GALILEO_PROJECT'],cfg['galileo']['project'])
            self.assertEqual(os.environ['GALILEO_LOG_STREAM'],'healthcare')
            self.assertEqual(os.environ['AGENT_CONTROL_API_KEY'],'fixture-only')
            self.assertEqual(os.environ['AGENT_CONTROL_RUNTIME_AUTH_MODE'],'jwt')
        self.assertEqual(_derive_galileo_api_url('https://console.example','https://api.override/'),'https://api.override')
        self.assertEqual(_derive_agent_control_url('https://console.example','https://control.override/'),'https://control.override')

    def test_placeholder_keys_are_not_providers(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY':'YOUR_OPENAI_API_KEY', 'AWS_BEARER_TOKEN_BEDROCK':'YOUR_BEDROCK_API_KEY', 'OLLAMA_BASE_URL':''}):
            self.assertEqual(configured_providers(), [])

    def test_database_password_special_characters(self):
        from sqlalchemy.engine import make_url
        with patch.dict(os.environ, {'POSTGRES_PASSWORD':'test-only:@/#%!?'}):
            self.assertEqual(make_url(get_postgres_connection_string()).password, 'test-only:@/#%!?')

    def test_domain_contracts_and_datasets(self):
        dm=DomainManager()
        self.assertEqual(dm.list_domains(), ['bank','healthcare','insurance','restaurant'])
        for name in dm.list_domains():
            cfg=dm.load_domain_config(name)
            schema=json.loads(Path(cfg.tools_dir,'schema.json').read_text())
            self.assertEqual(cfg.config['domain']['name'],name)
            self.assertEqual(set(cfg.config['tools']), {x['name'] for x in schema})
            self.assertGreater(len(read_dataset_csv(cfg.dataset_file)),0)

    def test_dataset_bad_headers_and_empty_cells_fail(self):
        for content in ('question,answer\na,b\n','input,output\na,\n'):
            with tempfile.NamedTemporaryFile(mode='w', suffix='.csv') as handle:
                handle.write(content); handle.flush()
                with self.assertRaises(ValueError): read_dataset_csv(handle.name)

    def test_write_sql_blocked_before_database_connection(self):
        queries=['DELETE FROM healthcare_patient', 'SELECT 1; DELETE FROM healthcare_patient',
            'WITH d AS (DELETE FROM healthcare_patient RETURNING *) SELECT * FROM d',
            'SELECT * INTO stolen FROM healthcare_patient', 'DROP TABLE healthcare_patient',
            'UPDATE healthcare_patient SET patient_id=\'X\'', 'EXPLAIN ANALYZE DELETE FROM healthcare_patient']
        with patch('helpers.sql_utils.create_engine', side_effect=AssertionError('DB must not be reached')):
            for sql in queries:
                with self.subTest(sql=sql):
                    self.assertTrue(execute_sql(sql)['blocked_by_local_safety'])

    def test_control_deny_prevents_tool_body(self):
        calls=[]
        async def body(sql: str): calls.append(sql); return 'executed'
        def deny_decorator(**_kwargs):
            def decorate(_func):
                async def denied(*args,**kwargs):
                    raise ControlViolationError(control_name='block-harmful-sql')
                return denied
            return decorate
        with patch('helpers.agent_control_helpers.control', deny_decorator):
            fn=make_controlled_tool(body,'delete_patient_record')
            result=json.loads(asyncio.run(fn('DELETE FROM healthcare_patient')))
        self.assertTrue(result['blocked_by_agent_control'])
        self.assertEqual(calls,[])

    def test_runnable_config_stays_local_to_tool_control(self):
        observed=[]
        framework_config={'callbacks':object()}
        async def search(query: str, config=None):
            self.assertIs(config,framework_config)
            return query
        def json_control(**_kwargs):
            def decorate(fn):
                async def checked(*args,**kwargs):
                    observed.append(json.dumps(kwargs))
                    return await fn(*args,**kwargs)
                return checked
            return decorate
        with patch('helpers.agent_control_helpers.control',json_control):
            fn=make_controlled_tool(search,'retrieval_step')
            self.assertEqual(asyncio.run(fn(query='Lisinopril',config=framework_config)),'Lisinopril')
        self.assertEqual(observed,['{"query": "Lisinopril"}'])

    def test_control_init_requires_server_registration_readback(self):
        logger=MagicMock()
        with patch.dict(os.environ,{'AGENT_CONTROL_URL':'https://example.invalid','AGENT_CONTROL_AGENT_NAME':'fixture-registration','GALILEO_API_KEY':'fixture-only'}), patch('helpers.agent_control_helpers.get_log_stream'), patch('helpers.agent_control_helpers.agent_control.init'), patch('helpers.agent_control_helpers.agent_control.AgentControlClient',side_effect=RuntimeError('unreachable')):
            self.assertFalse(init_agent_control(logger,'fixture-project','fixture-stream',force=True))

    def test_synthetic_hallucination_serializes_real_sdk_trace(self):
        batches=[]
        logger=GalileoLogger(ingestion_hook=batches.append)
        cfg=DomainManager().load_domain_config('healthcare').config
        self.assertTrue(log_hallucination_for_domain('healthcare',cfg,existing_logger=logger))
        data=json.dumps(batches[0].model_dump(mode='json'))
        self.assertIn('10-40 mg',data)
        self.assertIn('100mg',data)
        self.assertIn('synthetic_demo',data)
        logger.terminate()

    def test_rag_disconnect_hits_primary_domain_search(self):
        chaos=ChaosEngine(); chaos.enable_rag_chaos()
        calls=[]
        async def search_medicine_qa(query): calls.append(query); return 'context'
        with patch('chaos_wrapper.get_chaos_engine',return_value=chaos):
            fn=wrap_tools_with_chaos([search_medicine_qa])[0]
            result=json.loads(asyncio.run(fn('Lisinopril')))
        self.assertEqual(result['error_type'],'rag_failure')
        self.assertEqual(result['retrieved_documents'],[])
        self.assertEqual(calls,[])
        self.assertEqual(chaos.rag_chaos_count,1)

    def test_instability_and_rate_limit_do_not_reach_tool(self):
        for mode,code in (('enable_tool_instability','503'), ('enable_rate_limit_chaos','429')):
            chaos=ChaosEngine(); getattr(chaos,mode)()
            async def get_patient_info(patient_id): raise AssertionError('must not call backend')
            with patch('chaos_wrapper.get_chaos_engine',return_value=chaos):
                fn=wrap_tools_with_chaos([get_patient_info])[0]
                result=json.loads(asyncio.run(fn('P001')))
            self.assertEqual(result['status_code'],code)
            self.assertTrue(result['chaos_injected'])

    def test_sloppiness_always_changes_a_numeric_result(self):
        chaos=ChaosEngine(); chaos.enable_sloppiness()
        with patch('chaos_engine.random.randint',return_value=1):
            self.assertNotEqual(chaos.transpose_numbers('count=1'),'count=1')
        self.assertEqual(chaos.sloppiness_count,1)

    def test_experiment_keeps_sdk_trace_open_and_routes_logger(self):
        logger=MagicMock(); logger.current_parent.return_value=object()
        factory=MagicMock(); factory.create_agent.return_value.process_query.return_value='answer'
        with patch('experiments.experiment_helpers.galileo_context.get_logger_instance',return_value=logger), patch('experiments.experiment_helpers.GalileoCallback'):
            result=create_experiment_function('healthcare',factory,llm_provider='hosted')({'input':'test'})
        self.assertEqual(result,'answer')
        self.assertIs(factory.create_agent.call_args.kwargs['galileo_logger'],logger)
        self.assertFalse(factory.create_agent.return_value.manage_trace_lifecycle)
        logger.conclude.assert_not_called()
        logger.flush.assert_not_called()


if __name__=='__main__': unittest.main()
