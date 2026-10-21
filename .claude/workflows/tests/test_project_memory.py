import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC=importlib.util.spec_from_file_location('pm',Path(__file__).parents[2]/'skills/project-memory/scripts/project_memory.py')
pm=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(pm)


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.memory=pm.Memory(self.root)
        self.path=self.root/'proof.json';self.path.write_text(json.dumps({'status':'verified','count':2}))

    def candidate(self, statement='Two independent checks passed', key='checks'):
        return self.memory.propose(key,'lesson',statement,['harness','验收'],[self.memory.evidence('proof.json','/count')])

    def test_candidate_not_retrieved(self):
        self.candidate();self.assertEqual(self.memory.query('harness'),[])

    def test_review_then_retrieve(self):
        r=self.candidate();self.memory.review(r['id'],'approve','reviewer','supported in this fixture')
        self.assertEqual(self.memory.query('harness')[0]['id'],r['id'])

    def test_stale_evidence_excluded(self):
        r=self.candidate();self.memory.review(r['id'],'approve','reviewer','supported')
        self.path.write_text('{"count":3}')
        self.assertEqual(self.memory.query('harness'),[])
        self.assertFalse(self.memory.inspect()[0]['evidence_valid'])

    def test_no_duplicate(self):
        self.assertEqual(self.candidate()['id'],self.candidate()['id'])
        self.assertEqual(len(self.memory.read()['records']),1)

    def test_conflict_not_overwrite(self):
        r=self.candidate();self.memory.review(r['id'],'approve','reviewer','supported')
        other=self.candidate('Different scoped conclusion')
        self.assertEqual(self.memory.review(other['id'],'approve','reviewer','requires resolution')['status'],'conflict')
        self.assertEqual(len(self.memory.query('harness')),1)

    def test_missing_or_mismatch_rejected(self):
        evidence=self.memory.evidence('proof.json','/count');evidence['value']=99
        with self.assertRaises(ValueError):self.memory.propose('x','fact','test',['x'],[evidence])
        with self.assertRaises(ValueError):self.memory.evidence('../outside','')

    def test_retired_not_retrieved(self):
        r=self.candidate();self.memory.review(r['id'],'approve','reviewer','supported')
        self.memory.retire(r['id'],'obsolete');self.assertEqual(self.memory.query('harness'),[])

    def test_failed_run_not_harvested(self):
        for run in [{'done':False},{'done':True,'status':'verified','final_checks':[{'exit_code':1}]}]:
            with self.assertRaises(ValueError):self.memory.harvest(run)
        self.assertFalse(self.memory.file.exists())

    def test_success_harvest_is_idempotent(self):
        run={'done':True,'status':'verified','final_checks':[{'exit_code':0}]}
        r=self.memory.harvest(run);self.assertEqual(r['status'],'accepted')
        self.assertEqual(r['id'],self.memory.harvest(run)['id'])
        self.assertEqual(len(self.memory.query('harness')),1)

    def test_short_term_separate(self):
        self.memory.checkpoint({'status':'stopped','error':'timeout','task':{'requirement':'private text','scope':['a']}})
        record=json.loads((self.memory.directory/'current-task.json').read_text())
        self.assertNotIn('private text',json.dumps(record))
        self.assertEqual(self.memory.query('timeout'),[])

    def test_budget(self):
        r=self.candidate();self.memory.review(r['id'],'approve','reviewer','supported')
        self.assertEqual(self.memory.query('harness',budget=10),[])

    def test_corrupt_store_not_overwritten(self):
        self.memory.directory.mkdir(parents=True);self.memory.file.write_text('BROKEN')
        with self.assertRaises(ValueError):self.candidate()
        self.assertEqual(self.memory.file.read_text(),'BROKEN')


if __name__=='__main__':unittest.main()
