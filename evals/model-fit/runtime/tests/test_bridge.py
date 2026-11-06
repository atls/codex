import json
from pathlib import Path
import os
import subprocess
import unittest

SUITE = Path(__file__).resolve().parents[2]


class OfficialProviderBridgeTests(unittest.TestCase):
    def test_official_python_provider_functions_preserve_response_and_cumulative_usage(
        self,
    ):
        script = """
import {loadApiProvider} from 'promptfoo';
import {resolve} from 'node:path';
const file=resolve('corpus/provider.py');
const context={vars:{active_profile:{model:'fixture',effort:'medium',speed:null},task_context:'fixture'}};
const options={env:{OPENAI_API_KEY:'',CODEX_API_KEY:''},options:{config:{mode:'stock-control',execution:{}}}};
let provider=await loadApiProvider(`file://${file}:prepare`,options);
let result;
try {result=await provider.callApi('task',context);} finally {await provider.cleanup?.();}
if(result.error)throw new Error(result.error);
const prepared=JSON.parse(result.output);
provider=await loadApiProvider(`file://${file}:finalize`,options);
try {result=await provider.callApi(JSON.stringify({prepared,execution:{output:'retained answer',raw:{tokenUsage:{total:{totalTokens:3,inputTokens:2,outputTokens:1},last:{totalTokens:1}}}}}),context);} finally {await provider.cleanup?.();}
console.log(JSON.stringify({output:result.output,total:result.tokenUsage?.total,preflight:result.metadata?.corpusStages.preflight.status,error:result.error}));
"""
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=SUITE,
            env=os.environ | {"PROMPTFOO_DISABLE_TELEMETRY": "1"},
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(
            response,
            {"output": "retained answer", "total": 3, "preflight": "not-invoked"},
        )
