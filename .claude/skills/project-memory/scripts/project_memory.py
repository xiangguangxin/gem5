#!/usr/bin/env python3
"""Evidence-backed project memory. JSON storage with atomic writes and a POSIX lock."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import re
import tempfile
import os


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def pointer(doc, path):
    if path == '':
        return doc
    if not isinstance(path, str) or not path.startswith('/'):
        raise ValueError('Evidence must use a JSON pointer')
    for part in path[1:].split('/'):
        part = part.replace('~1', '/').replace('~0', '~')
        doc = doc[int(part)] if isinstance(doc, list) else doc[part]
    return doc


class Memory:
    def __init__(self, root, directory=None):
        self.root = Path(root).resolve()
        self.directory = Path(directory).resolve() if directory else self.root/'.claude/memory'
        self.file = self.directory/'records.json'

    @contextmanager
    def transaction(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory/'.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = self.read()
            yield data
            self.atomic(self.file, data)

    def read(self):
        if not self.file.exists():
            return {'version':1, 'records':[], 'audit':[]}
        data = json.loads(self.file.read_text())
        if data.get('version') != 1 or not isinstance(data.get('records'), list):
            raise ValueError('Invalid memory store; do not overwrite')
        return data

    @staticmethod
    def atomic(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=path.parent, prefix='.memory-')
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(data,f,ensure_ascii=False,indent=2)
                f.write('\n'); f.flush(); os.fsync(f.fileno())
            os.replace(name,path)
        finally:
            if os.path.exists(name): os.unlink(name)

    def source(self, relative):
        p = (self.root/relative).resolve()
        if Path(relative).is_absolute() or p == self.root or self.root not in p.parents:
            raise ValueError('Evidence must be a project-relative file')
        return p

    def evidence(self, relative, at):
        p = self.source(relative)
        raw=p.read_bytes()
        return {'path':relative,'sha256':digest(raw),'pointer':at,'value':pointer(json.loads(raw),at)}

    def valid(self, record):
        try:
            return bool(record['evidence']) and all(
                self.evidence(e['path'],e['pointer']) == e for e in record['evidence'])
        except (OSError,ValueError,KeyError,TypeError,IndexError):
            return False

    def propose(self, key, kind, statement, tags, evidence, scope='project'):
        if kind not in ('fact','decision','lesson') or not all(isinstance(x,str) and x.strip() for x in (key,statement,scope)):
            raise ValueError('Valid key, scope, kind and statement required')
        if len(statement)>2000 or not evidence or not isinstance(tags,list) or any(not isinstance(t,str) for t in tags):
            raise ValueError('Bounded statement, tags and evidence required')
        r={'key':key,'scope':scope,'kind':kind,'statement':statement,'tags':tags,'evidence':evidence}
        if not self.valid(r): raise ValueError('Missing, changed or mismatched evidence')
        ident=digest(json.dumps(r,sort_keys=True,ensure_ascii=False).encode())[:20]
        with self.transaction() as data:
            existing=next((x for x in data['records'] if x['id']==ident),None)
            if existing:return existing
            r.update(id=ident,status='candidate',created=now(),updated=now(),review=None)
            data['records'].append(r)
            data['audit'].append({'at':now(),'id':ident,'event':'proposed'})
        return r

    def review(self, ident, verdict, reviewer, reason):
        if verdict not in ('approve','reject') or not reviewer.strip() or not reason.strip():
            raise ValueError('Review requires verdict, reviewer and reason')
        with self.transaction() as data:
            r=next(x for x in data['records'] if x['id']==ident)
            if r['status'] not in ('candidate','conflict'):raise ValueError('Only candidates/conflicts can be reviewed')
            if not self.valid(r):raise ValueError('Evidence is stale or missing')
            conflicts=[x for x in data['records'] if x['status']=='accepted' and x['scope']==r['scope'] and x['key']==r['key'] and x['id']!=ident]
            r['status']='rejected' if verdict=='reject' else ('conflict' if conflicts else 'accepted')
            r['review']={'reviewer':reviewer,'reason':reason,'verdict':verdict,'at':now()}
            r['updated']=now()
            data['audit'].append({'at':now(),'id':ident,'event':r['status'],'reason':reason})
        return r

    def retire(self, ident, reason):
        if not reason.strip():raise ValueError('Retirement reason required')
        with self.transaction() as data:
            r=next(x for x in data['records'] if x['id']==ident)
            r.update(status='retired',updated=now())
            data['audit'].append({'at':now(),'id':ident,'event':'retired','reason':reason})
        return r

    def query(self, query, limit=5, budget=5000):
        if not query.strip() or limit<1 or budget<1:return []
        tokens=set(re.findall(r'[a-z0-9_-]+|[\u4e00-\u9fff]',query.lower()))
        matches=[]
        for r in self.read()['records']:
            if r['status']!='accepted' or not self.valid(r):continue
            hay=(r['key']+' '+r['statement']+' '+' '.join(r['tags'])).lower()
            score=sum(t in hay for t in tokens)
            if score:matches.append((score,r['updated'],r))
        chosen=[];size=0
        for _,_,r in sorted(matches,key=lambda x:(x[0],x[1]),reverse=True):
            item={k:r[k] for k in ('id','kind','statement','evidence','review')}
            encoded=json.dumps(item,ensure_ascii=False)
            if size+len(encoded)>budget:continue
            chosen.append(item);size+=len(encoded)
            if len(chosen)>=limit:break
        return chosen

    def inspect(self):
        return [{**r,'evidence_valid':self.valid(r)} for r in self.read()['records']]

    def harvest(self, run):
        # Only canonical host fields create automatic facts. No prose is promoted here.
        if run.get('done') is not True or run.get('status')!='verified':
            raise ValueError('Only verified runs can be harvested')
        checks=run.get('final_checks')
        if not checks or any(not isinstance(c,dict) or c.get('exit_code')!=0 for c in checks):
            raise ValueError('Verified run lacks successful host checks')
        receipt={'done':True,'status':'verified','final_exit_codes':[c['exit_code'] for c in checks],
                 'initial_snapshot':run.get('initial_snapshot',{}),'final_snapshot':run.get('final_snapshot',{}),
                 'phase_verdicts':[{ 'phase':x.get('phase'), 'verdict':x.get('result',{}).get('verdict')} for x in run.get('history',run.get('phases',[]))]}
        raw=json.dumps(receipt,sort_keys=True,ensure_ascii=False).encode();rid=digest(raw)[:20]
        path=self.directory/'evidence'/f'{rid}.json'
        self.atomic(path,receipt)
        relative=str(path.relative_to(self.root))
        r=self.propose('run/'+rid,'fact',f'运行记录 {rid}：宿主记录为 verified；{len(checks)} 条最终验收命令退出码均为 0。仅适用于该次记录，不代表所有任务正确。',
                       ['harness','verified','验收'],[self.evidence(relative,'/status'),self.evidence(relative,'/final_exit_codes')])
        if r['status']=='candidate':r=self.review(r['id'],'approve','host-field-validator','Statement is generated only from verified host status and exit-code fields; no semantic claims inferred.')
        return r

    def checkpoint(self, run):
        item={'updated':now(),'status':run.get('status'),'done':run.get('done',False),
              'task_scope':run.get('task',{}).get('scope',[]),
              'requirement_sha256':digest(run.get('task',{}).get('requirement','').encode()),
              'completed_phases':[x.get('phase') for x in run.get('history',[]) if x.get('status')=='completed'],
              'error':run.get('error'), 'next_step':'inspect evidence; no automatic resume'}
        self.atomic(self.directory/'current-task.json',item)
        return item


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[4])
    sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('query');a.add_argument('text')
    sub.add_parser('inspect')
    a=sub.add_parser('harvest');a.add_argument('run',type=Path)
    a=sub.add_parser('propose');a.add_argument('proposal',type=Path)
    a=sub.add_parser('review');a.add_argument('id');a.add_argument('--verdict',choices=['approve','reject'],required=True);a.add_argument('--reviewer',required=True);a.add_argument('--reason',required=True)
    a=sub.add_parser('retire');a.add_argument('id');a.add_argument('--reason',required=True)
    args=p.parse_args();m=Memory(args.root)
    if args.command=='query':result=m.query(args.text)
    elif args.command=='inspect':result=m.inspect()
    elif args.command=='harvest':result=m.harvest(json.loads(args.run.read_text()))
    elif args.command=='propose':result=m.propose(**json.loads(args.proposal.read_text()))
    elif args.command=='review':result=m.review(args.id,args.verdict,args.reviewer,args.reason)
    else:result=m.retire(args.id,args.reason)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
