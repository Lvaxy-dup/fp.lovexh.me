"""Short SQLite transactions serialize edits; model/network calls never hold a lock."""
from contextlib import contextmanager
import json
import sqlite3
import threading
import uuid
import secrets
import hashlib
from datetime import datetime, timezone
from .config import RUNTIME
from .profile import profile_defaults


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path=None):
        self.path = path or RUNTIME / 'travel.db'
        self.lock = threading.RLock()
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, owner TEXT NOT NULL, body TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS profiles (owner TEXT PRIMARY KEY, body TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS browser_sessions (token_hash TEXT PRIMARY KEY, owner TEXT NOT NULL)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        try:
            db.execute('PRAGMA journal_mode=WAL')
            with db:
                yield db
        finally:
            db.close()

    def create_browser_session(self, owner):
        token=secrets.token_hex(32)
        with self.lock, self.connect() as db:
            db.execute('INSERT INTO browser_sessions VALUES (?,?)', (hashlib.sha256(token.encode()).hexdigest(),owner))
        return token

    def browser_session_owner(self, token):
        with self.connect() as db:
            row=db.execute('SELECT owner FROM browser_sessions WHERE token_hash=?',
                           (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        return row[0] if row else None

    def get_profile(self, owner):
        with self.connect() as db:
            row=db.execute('SELECT body FROM profiles WHERE owner=?',(owner,)).fetchone()
        return profile_defaults(json.loads(row[0]) if row else {})

    def save_profile(self, owner, profile):
        profile=profile_defaults(profile)
        with self.lock, self.connect() as db:
            db.execute('INSERT INTO profiles(owner,body) VALUES(?,?) ON CONFLICT(owner) DO UPDATE SET body=excluded.body',
                       (owner,json.dumps(profile,ensure_ascii=False)))
        return profile

    def create(self, owner, title='新的出差'):
        data = {'id': uuid.uuid4().hex, 'title': title, 'created': now(), 'updated': now(), 'revision': 0,
                'forms': {k: {'values': {}, 'meta': {}, 'expenses': {}, 'questions': []} for k in ('application','reimbursement')},
                'materials': [], 'messages': [], 'events': [], 'agent': {'status':'idle','form':None}, 'pipeline': {'status':'idle','message':'导入材料后，点击填写当前表单。','completed':[],'forms':[]}, 'generation_requests': [], 'audit': []}
        with self.lock, self.connect() as db:
            db.execute('INSERT INTO records VALUES (?,?,?)', (data['id'], owner, json.dumps(data, ensure_ascii=False)))
        return data

    def get(self, owner, record):
        with self.connect() as db:
            row = db.execute('SELECT body FROM records WHERE id=? AND owner=?', (record, owner)).fetchone()
        if not row:
            raise KeyError('记录不存在')
        return json.loads(row[0])

    def list(self, owner):
        with self.connect() as db:
            rows = db.execute('SELECT body FROM records WHERE owner=?', (owner,)).fetchall()
        values = [json.loads(r[0]) for r in rows]
        return sorted([{'id':d['id'],'title':d['title'],'updated':d['updated']} for d in values],key=lambda d:d['updated'],reverse=True)

    def change(self, owner, record, fn):
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT body FROM records WHERE id=? AND owner=?', (record,owner)).fetchone()
            if not row: raise KeyError('记录不存在')
            data = json.loads(row[0])
            result = fn(data)
            data['revision'] += 1
            data['updated'] = now()
            db.execute('UPDATE records SET body=? WHERE id=?', (json.dumps(data,ensure_ascii=False),record))
        return data, result

    def delete(self, owner, record, before_delete):
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT body FROM records WHERE id=? AND owner=?',(record,owner)).fetchone()
            if not row:raise KeyError('记录不存在')
            before_delete(json.loads(row[0]))
            db.execute('DELETE FROM records WHERE id=? AND owner=?',(record,owner))

    def event(self, owner, record, event):
        def write(d):
            event['id'] = (d['events'][-1]['id'] + 1) if d['events'] else 1
            event['time'] = now()
            d['events'].append(event)
            d['events'] = d['events'][-150:]
        return self.change(owner,record,write)[0]

    def recover(self):
        with self.lock, self.connect() as db:
            for rid, raw in db.execute('SELECT id,body FROM records').fetchall():
                d=json.loads(raw)
                if d.get('pipeline',{}).get('status')=='running':
                    d['pipeline'].update(status='error',message='服务已重启，已保存内容保留，可点击重新填写。')
                if d['agent']['status']=='running':
                    d['agent']['status']='error'
                    d['agent']['message']='服务已重启，已保存内容可继续，请重新发送消息。'
                for m in d['materials']:
                    if m['status'] in ('queued','running'):
                        m['status']='error'; m['error']='服务已重启，请点击重新识别。'
                db.execute('UPDATE records SET body=? WHERE id=?',(json.dumps(d,ensure_ascii=False),rid))
