import io
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import app, initialize, analyze, parse_csv

CSV=b'id,type,vendor,amount,date,reference,status\n1,Invoice,A,100,2026-01-01,X,Paid\n2,Invoice,A,100,2026-01-02,X,Paid\n3,Invoice,B,900,2026-01-03,Y,Pending\n'
class OpsDetectTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        app.config['TESTING']=True
        app.config['DATABASE']=os.path.join(self.tmp.name,'test.sqlite3')
        initialize()
        self.client=app.test_client()
    def tearDown(self): self.tmp.cleanup()
    def test_import_and_findings(self):
        res=self.client.post('/api/import',data={'file':(io.BytesIO(CSV),'sample.csv')})
        self.assertEqual(res.status_code,200)
        self.assertEqual(res.json['imported'],3)
        self.assertGreaterEqual(res.json['findings'],2)
        summary=self.client.get('/api/summary').json
        self.assertEqual(summary['records'],3)
        self.assertTrue(any(f['rule']=='Duplicate reference' for f in summary['findings']))
    def test_status_and_audit(self):
        self.client.post('/api/import',data={'file':(io.BytesIO(CSV),'sample.csv')})
        fid=self.client.get('/api/summary').json['findings'][0]['id']
        self.assertEqual(self.client.patch(f'/api/findings/{fid}',json={'status':'Resolved'}).status_code,200)
        result=self.client.get('/api/summary').json
        self.assertEqual(result['audit'][0]['new_status'],'Resolved')
        self.assertEqual(self.client.patch(f'/api/findings/{fid}',json={'status':'NotReal'}).status_code,400)
    def test_invalid_csv_preserves_data(self):
        self.client.post('/api/import',data={'file':(io.BytesIO(CSV),'sample.csv')})
        res=self.client.post('/api/import',data={'file':(io.BytesIO(b'wrong,headers\na,b'),'bad.csv')})
        self.assertEqual(res.status_code,400)
        self.assertEqual(self.client.get('/api/summary').json['records'],3)
    def test_health_and_records(self):
        self.assertEqual(self.client.get('/api/health').json['status'], 'ok')
        self.client.post('/api/import',data={'file':(io.BytesIO(CSV),'sample.csv')})
        self.assertEqual(len(self.client.get('/api/records').json['records']), 3)
    def test_reject_non_csv(self):
        r=self.client.post('/api/import',data={'file':(io.BytesIO(CSV),'sample.txt')})
        self.assertEqual(r.status_code,400)
    def test_overdue_needs_due_date(self):
        row={'id':'x','type':'PO','vendor':'V','amount':10,'date':(date.today()-timedelta(days=100)).isoformat(),'reference':'PO-1','status':'Open','due_date':''}
        self.assertNotIn('Overdue purchase order',[r[0] for r in analyze([row])])
    def test_export(self):
        self.client.post('/api/import',data={'file':(io.BytesIO(CSV),'sample.csv')})
        r=self.client.get('/api/export')
        self.assertEqual(r.status_code,200)
        self.assertIn(b'Duplicate reference',r.data)
    def test_missing_field_and_overdue(self):
        rows=[{'id':'a','type':'PO','vendor':'','amount':None,'date':(date.today()-timedelta(days=3)).isoformat(),'reference':'PO-1','status':'Open','due_date':(date.today()-timedelta(days=1)).isoformat()}]
        rules=[x[0] for x in analyze(rows)]
        self.assertIn('Missing field',rules)
        self.assertIn('Overdue purchase order',rules)
if __name__=='__main__': unittest.main()
