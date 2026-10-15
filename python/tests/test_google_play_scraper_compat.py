"""Offline tests. Board rows are verbatim; malformed/absent cases are synthetic."""
import copy
import importlib.util
import inspect
import json
import os
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import google_play_scraper_compat as shim

FIXTURES = Path(__file__).parent / 'fixtures'
BOARD = json.loads((FIXTURES / 'play_board_exports.json').read_text())['runs']
DETAILS = BOARD['TQemqnIoWc1tZM7y5']['items']
SEARCH = BOARD['xXdaThOR8sRIwdnJF']['items']

class Client:
    def __init__(self, rows=SEARCH, run='dict'):
        self.rows = copy.deepcopy(rows)
        self.calls = []
        self.run = {'status':'SUCCEEDED','defaultDatasetId':'dataset'} if run == 'dict' else run
    def actor(self, actor):
        assert actor == shim.ACTOR
        return self
    def call(self, **kwargs):
        self.calls.append(kwargs)
        return self.run
    def dataset(self, dataset):
        assert dataset == 'dataset'
        return self
    def iterate_items(self):
        yield from self.rows

class AdapterTests(unittest.TestCase):
    def test_board_search_all_ten_rows(self):
        client=Client()
        result=shim.search('meditation',10,client=client)
        self.assertEqual(len(result),10)
        for raw,mapped in zip(SEARCH,result):
            self.assertEqual(set(mapped),set(shim.SEARCH_KEYS))
            self.assertEqual(mapped['appId'],raw['appId'])
            for old,new in [('appName','title'),('developer','developer'),('rating','score'),('installs','installs'),('price','price')]:
                self.assertEqual(mapped[new],raw[old])
        self.assertEqual(len(client.calls),1)
        self.assertEqual(client.calls[0]['run_input'],dict(stores=['google_play'],apps=[],searchTerms=['meditation'],maxResultsPerTerm=10,country='us',language='en'))
        self.assertEqual(str(client.calls[0]['max_total_charge_usd']),'0.1')
    def test_board_app_all_three_rows(self):
        for row in DETAILS:
            with self.subTest(row=row['appId']):
                client=Client(DETAILS)
                value=shim.app(row['appId'],client=client)
                self.assertEqual(set(value),set(shim.APP_KEYS))
                self.assertEqual(value['title'],row['appName'])
                self.assertEqual(value['histogram'],[row['histogram'][str(i)] for i in range(1,6)])
                self.assertEqual(value['version'],row['version'])
                self.assertEqual(value['minInstalls'],int(row['installs'].replace(',','').replace('+','')))
                self.assertEqual(len(client.calls),1)
                self.assertEqual(client.calls[0]['run_input']['apps'],['play:'+row['appId']])
    def test_missing_is_not_fabricated(self):
        row=dict(DETAILS[0],price=None,histogram=None,installs=None,updatedAt=None)
        v=shim.app(row['appId'],client=Client([row]))
        for k in ['free','histogram','minInstalls','realInstalls','updated','lastUpdatedOn','icon','description','sale','offersIAP','containsAds']:
            self.assertIsNone(v[k],k)
        for k in ['screenshots','categories','comments']:
            self.assertEqual(v[k],[])
    def test_paid_free_and_timestamp(self):
        v=shim.app(DETAILS[1]['appId'],client=Client(DETAILS))
        self.assertFalse(v['free'])
        self.assertEqual(v['price'],6.99)
        from datetime import datetime
        self.assertEqual(v['updated'],int(datetime.fromisoformat(DETAILS[1]['updatedAt'].replace('Z','+00:00')).timestamp()))
        self.assertEqual(v['lastUpdatedOn'],'Sep 25, 2026')
    def test_empty_search(self):
        self.assertEqual(shim.search('nothing',client=Client([])),[])
    def test_zero_no_token_or_run(self):
        for n in [0,-1]:
            with patch.dict(os.environ,{},clear=True):
                self.assertEqual(shim.search('',n),[])
    def test_default_limit_and_upper_cap(self):
        for n,limit in [(30,30),(500,200)]:
            c=Client();shim.search('meditation',n,client=c)
            self.assertEqual(c.calls[0]['run_input']['maxResultsPerTerm'],limit)
    def test_source_order_dedup_slice(self):
        c=Client(list(reversed(SEARCH))+[SEARCH[0]])
        v=shim.search('meditation',2,client=c)
        self.assertEqual([r['appId'] for r in v],[r['appId'] for r in SEARCH[:2]])
    def test_model_run(self):
        c=Client(run=SimpleNamespace(status='SUCCEEDED',default_dataset_id='dataset'))
        self.assertTrue(shim.search('meditation',client=c))
    def test_run_failure(self):
        for run in [None,{'status':'FAILED'},{'status':'TIMED-OUT'},{'status':'SUCCEEDED'}]:
            with self.subTest(run=run),self.assertRaises(RuntimeError):
                shim.search('meditation',client=Client(run=run))
    def test_actor_errors_not_silent_partial(self):
        for row in [dict(SEARCH[0],error='source refused'),{'success':False}]:
            with self.assertRaises(RuntimeError):
                shim.search('meditation',client=Client([SEARCH[1],row]))
    def test_wrong_identity(self):
        for change in [{'store':'app_store'},{'country':'de'},{'language':'de'},{'searchTerm':'other'}]:
            with self.assertRaises(RuntimeError):
                shim.search('meditation',client=Client([dict(SEARCH[0],**change)]))
        with self.assertRaises(RuntimeError):
            shim.app('com.whatsapp',client=Client(DETAILS))
    def test_missing_identity_rank(self):
        for change in [{'appId':None},{'rank':None},{'rank':True},{'rank':0}]:
            with self.assertRaises(RuntimeError):
                shim.search('meditation',client=Client([dict(SEARCH[0],**change)]))
    def test_bad_inputs_fail_before_call(self):
        for query in ['',None,'x'*201]:
            with self.assertRaises(ValueError):shim.search(query,client=Client())
        for n in [True,'1',1.5]:
            with self.assertRaises(TypeError):shim.search('meditation',n,client=Client())
        for app_id in ['',None,'123','https://play.google.com/store/apps/details?id=com.spotify.music']:
            with self.assertRaises(ValueError):shim.app(app_id,client=Client())
        for kwargs in [{'country':'usa'},{'lang':''},{'max_total_charge_usd':0},{'max_total_charge_usd':'NaN'},{'max_total_charge_usd':'Infinity'}]:
            with self.assertRaises(ValueError):shim.search('meditation',client=Client(),**kwargs)
    def test_locale_and_cap(self):
        c=Client([dict(SEARCH[0],country='gb',language='pt-BR')])
        shim.search('meditation',lang='pt-BR',country='GB',max_total_charge_usd='0.25',client=c)
        self.assertEqual(str(c.calls[0]['max_total_charge_usd']),'0.25')
        self.assertEqual(c.calls[0]['run_input']['country'],'gb')
    def test_missing_token(self):
        with patch.dict(os.environ,{},clear=True),self.assertRaisesRegex(RuntimeError,'APIFY_TOKEN'):
            shim.app('com.spotify.music')
    def test_no_mutation_or_shared_lists(self):
        before=copy.deepcopy(SEARCH)
        a=shim.search('meditation',client=Client());a[0]['screenshots'].append('x')
        b=shim.search('meditation',client=Client())
        self.assertEqual(b[0]['screenshots'],[]);self.assertEqual(SEARCH,before)
    def test_named_apps_local_capture(self):
        d=json.loads((FIXTURES/'play_named_apps_local.json').read_text())
        self.assertEqual(len(d['cases']),10)
        for case in d['cases']:
            with self.subTest(name=case['input']['searchTerms'][0]):
                c=Client(case['rows'])
                v=shim.search(case['input']['searchTerms'][0],1,client=c)
                self.assertEqual(v[0]['appId'],case['expected'])
                self.assertEqual(len(c.calls),1)

@unittest.skipUnless(importlib.util.find_spec('google_play_scraper'),'optional 1.2.7 reference not installed')
class ReferenceTests(unittest.TestCase):
    def test_exact_keys_and_positional_parameters(self):
        import google_play_scraper as ref
        from google_play_scraper.constants.element import ElementSpecs
        self.assertEqual(set(shim.SEARCH_KEYS),set(ElementSpecs.SearchResult))
        self.assertEqual(set(shim.SEARCH_KEYS),set(ElementSpecs.SearchResultOnTop))
        self.assertEqual(set(shim.APP_KEYS),set(ElementSpecs.Detail)|{'appId','url'})
        for name in ['search','app']:
            old=list(inspect.signature(getattr(ref,name)).parameters.values())
            new=list(inspect.signature(getattr(shim,name)).parameters.values())[:len(old)]
            self.assertEqual([(p.name,p.default,p.kind) for p in old],[(p.name,p.default,p.kind) for p in new])

@unittest.skipUnless(importlib.util.find_spec('apify_client'),'optional SDK not installed')
class SDKTests(unittest.TestCase):
    def test_real_sdk_http_boundary_with_board_rows(self):
        # Synthetic API run envelope around verbatim board rows, never a live run.
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from threading import Thread
        from apify_client import ApifyClient
        requests=[]
        dataset_rows=list(SEARCH)
        run={'id':'run','actId':'actor','userId':'user','startedAt':'2026-10-08T10:15:36Z','status':'SUCCEEDED','meta':{'origin':'API'},'stats':{},'options':{'build':'latest','timeoutSecs':300,'memoryMbytes':512,'diskMbytes':1024},'buildId':'build','defaultKeyValueStoreId':'kv','defaultDatasetId':'dataset','defaultRequestQueueId':'rq'}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=self.rfile.read(int(self.headers.get('Content-Length','0')))
                request_input=json.loads(body)
                requests.append(('POST',self.path,request_input))
                dataset_rows[:]=DETAILS if request_input['apps'] else SEARCH
                self.respond({'data':run})
            def do_GET(self):
                requests.append(('GET',self.path,None))
                from urllib.parse import urlparse, parse_qs
                offset=int(parse_qs(urlparse(self.path).query).get('offset',['0'])[0])
                self.respond(dataset_rows[offset:offset+1000] if '/datasets/' in self.path else {'data':run},offset)
            def respond(self,body,offset=0):
                payload=json.dumps(body).encode();self.send_response(200)
                self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)))
                self.send_header('X-Apify-Pagination-Total',str(len(SEARCH)))
                self.send_header('X-Apify-Pagination-Offset',str(offset));self.send_header('X-Apify-Pagination-Limit','1000')
                self.send_header('X-Apify-Pagination-Count',str(len(body) if isinstance(body,list) else 0));self.send_header('X-Apify-Pagination-Desc','false')
                self.end_headers();self.wfile.write(payload)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            client=ApifyClient('offline',api_url='http://127.0.0.1:'+str(server.server_port))
            result=shim.search('meditation',10,client=client)
            self.assertEqual(len(result),10)
            posts=[r for r in requests if r[0]=='POST']
            self.assertEqual(len(posts),1);self.assertIn('maxTotalChargeUsd=0.1',posts[0][1])
            self.assertEqual(posts[0][2]['searchTerms'],['meditation'])
            details=shim.app('com.spotify.music',client=client)
            self.assertEqual(details['appId'],'com.spotify.music')
            self.assertEqual(details['ratings'],DETAILS[0]['ratingsCount'])
            posts=[r for r in requests if r[0]=='POST']
            self.assertEqual(len(posts),2)
            self.assertEqual(posts[1][2]['apps'],['play:com.spotify.music'])
        finally:
            server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
