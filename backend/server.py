"""Small shared annotation API. Independent SQLite database; no training or game input."""
import contextlib,hashlib,json,mimetypes,os,secrets,shutil,sqlite3,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote,urlsplit

ROOT=Path(__file__).resolve().parent
DATABASE=Path(os.environ.get('ANNOTATION_DATABASE',ROOT/'runtime/progress.sqlite3'))
SEED=Path(os.environ.get('ANNOTATION_SEED',ROOT/'seed.json'))
ORIGIN=os.environ.get('ANNOTATION_ORIGIN','http://127.0.0.1:8080').rstrip('/')
STATIC=Path(os.environ['ANNOTATION_STATIC_ROOT']).resolve() if os.environ.get('ANNOTATION_STATIC_ROOT') else None
LABELS=['background','ham','milk','pot','potato','sauce','cucumber','meat','udon','noodles','plum','egg','brownegg','kamaboko','cereal','onion','panko','pepper','spider','flour','sausage','ricebowl','plate','ricepack','scallion','shrimp','curry','seaweed','glove','moyashi','tuna','uncertain']

@contextlib.contextmanager
def connect():
    db=sqlite3.connect(DATABASE,timeout=5,isolation_level=None);db.row_factory=sqlite3.Row
    db.execute('PRAGMA busy_timeout=5000');db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA synchronous=FULL')
    try:yield db
    finally:db.close()

def initialize():
    DATABASE.parent.mkdir(parents=True,exist_ok=True)
    with connect() as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript('''
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS participants(token_hash TEXT PRIMARY KEY,name TEXT NOT NULL,expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS samples(id TEXT PRIMARY KEY,position INTEGER UNIQUE NOT NULL,record TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS annotations(id TEXT PRIMARY KEY REFERENCES samples(id),label TEXT NOT NULL,author TEXT NOT NULL,updated INTEGER NOT NULL,protected INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS leases(id TEXT PRIMARY KEY REFERENCES samples(id),owner TEXT NOT NULL,expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL,label TEXT NOT NULL,author TEXT NOT NULL,updated INTEGER NOT NULL);
        ''')
        if db.execute('SELECT COUNT(*) FROM samples').fetchone()[0]:return
        seed=json.loads(SEED.read_text(encoding='utf-8'))
        db.execute('BEGIN IMMEDIATE')
        try:
            db.execute('INSERT INTO metadata VALUES(?,?)',('dataset_sha256',seed['dataset_sha256']))
            db.executemany('INSERT INTO samples VALUES(?,?,?)',[(s['id'],i,json.dumps(s)) for i,s in enumerate(seed['samples'])])
            for id,a in seed['annotations'].items():
                if a.get('human_annotated') and a.get('visible') in LABELS:
                    db.execute('INSERT INTO annotations VALUES(?,?,?,?,1)',(id,a['visible'],'prior_human',int(time.time())))
            db.commit()
        except BaseException:db.rollback();raise

def stats(db):
    counts=dict(db.execute('SELECT label,COUNT(*) FROM annotations GROUP BY label').fetchall())
    return {'total':db.execute('SELECT COUNT(*) FROM samples').fetchone()[0],
        'confirmed':sum(v for k,v in counts.items() if k!='uncertain'),'uncertain':counts.get('uncertain',0),
        'counts':counts,'revision':db.execute('SELECT COALESCE(MAX(sequence),0) FROM events').fetchone()[0]}

class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup();self.connection.settimeout(15)
    def log_message(self,*args):pass
    def reply(self,status,value):
        body=json.dumps(value,ensure_ascii=False).encode()
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        if self.headers.get('Origin')==ORIGIN:self.send_header('Access-Control-Allow-Origin',ORIGIN)
        self.send_header('Vary','Origin');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def do_OPTIONS(self):
        if self.headers.get('Origin')!=ORIGIN:return self.reply(403,{'error':'來源不允許'})
        self.send_response(204);self.send_header('Access-Control-Allow-Origin',ORIGIN)
        self.send_header('Access-Control-Allow-Headers','Authorization, Content-Type')
        self.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS');self.send_header('Access-Control-Max-Age','600');self.end_headers()
    def identity(self,db):
        token=self.headers.get('Authorization','').removeprefix('Bearer ')
        key=hashlib.sha256(token.encode()).hexdigest()
        r=db.execute('SELECT name FROM participants WHERE token_hash=? AND expires>?',(key,int(time.time()))).fetchone()
        return (key,r['name']) if r else None
    def payload(self):
        length=int(self.headers.get('Content-Length','0'))
        if length<1 or length>8192:raise ValueError('請求大小無效')
        value=json.loads(self.rfile.read(length))
        if not isinstance(value,dict):raise ValueError('無效請求')
        return value
    def do_GET(self):
        path=urlsplit(self.path).path
        if not path.startswith('/api/') and STATIC:
            target=(STATIC/unquote(path).lstrip('/')).resolve()
            if target==STATIC:target=STATIC/'index.html'
            if not target.is_relative_to(STATIC) or not target.is_file():return self.reply(404,{'error':'找不到圖片或網頁'})
            self.send_response(200);self.send_header('Content-Type',mimetypes.guess_type(target.name)[0] or 'application/octet-stream')
            self.send_header('Content-Length',str(target.stat().st_size));self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Cache-Control','public, max-age=86400' if target.suffix in ('.png','.jpg') else 'no-store')
            self.end_headers()
            with target.open('rb') as source:shutil.copyfileobj(source,self.wfile)
            return
        if path=='/api/health':return self.reply(200,{'status':'ok','service':'cooking-annotation'})
        with connect() as db:
            if not self.identity(db):return self.reply(401,{'error':'請先加入標註'})
            if path=='/api/stats':return self.reply(200,stats(db))
            if path=='/api/export':
                rows=db.execute('SELECT a.id,a.label,COALESCE(p.name,a.author) AS author,a.updated FROM annotations a LEFT JOIN participants p ON p.token_hash=a.author').fetchall()
                return self.reply(200,{'dataset_sha256':db.execute('SELECT value FROM metadata WHERE key=?',('dataset_sha256',)).fetchone()[0],
                    'annotations':{r['id']:{'visible':r['label'],'human_annotated':True,'origin':'shared/'+r['author'],'updated':r['updated']} for r in rows}})
        self.reply(404,{'error':'找不到介面'})
    def do_POST(self):
        if self.headers.get('Origin') not in (None,ORIGIN):return self.reply(403,{'error':'來源不允許'})
        try:
            p=self.payload();path=urlsplit(self.path).path;now=int(time.time())
            with connect() as db:
                if path=='/api/join':
                    name=p.get('name','')
                    if not isinstance(name,str) or not 1<=len(name.strip())<=40:raise ValueError('請填寫40字內的標註者 ID')
                    token=secrets.token_urlsafe(32);key=hashlib.sha256(token.encode()).hexdigest()
                    db.execute('INSERT INTO participants VALUES(?,?,?)',(key,name.strip(),now+30*86400))
                    return self.reply(200,{'token':token,'name':name.strip(),'stats':stats(db)})
                person=self.identity(db)
                if not person:return self.reply(401,{'error':'請重新加入標註'})
                key,name=person
                if path=='/api/claim':
                    db.execute('BEGIN IMMEDIATE')
                    db.execute('DELETE FROM leases WHERE expires<=?',(now,))
                    held=db.execute('SELECT s.record FROM samples s JOIN leases l ON s.id=l.id WHERE l.owner=? ORDER BY s.position LIMIT 1',(key,)).fetchone()
                    if held:
                        db.execute('UPDATE leases SET expires=? WHERE owner=?',(now+900,key));db.commit()
                        return self.reply(200,{'sample':json.loads(held['record']),'stats':stats(db)})
                    row=db.execute('SELECT s.id,s.record FROM samples s LEFT JOIN annotations a ON s.id=a.id LEFT JOIN leases l ON s.id=l.id WHERE a.id IS NULL AND l.id IS NULL ORDER BY s.position LIMIT 1').fetchone()
                    if row:db.execute('INSERT INTO leases VALUES(?,?,?)',(row['id'],key,now+900))
                    db.commit();return self.reply(200,{'sample':json.loads(row['record']) if row else None,'stats':stats(db)})
                if path=='/api/label':
                    id=p.get('id');label=p.get('label')
                    if not isinstance(id,str) or label not in LABELS:raise ValueError('無效標籤')
                    db.execute('BEGIN IMMEDIATE')
                    existing=db.execute('SELECT label,author,protected FROM annotations WHERE id=?',(id,)).fetchone()
                    if existing:
                        db.rollback()
                        if not existing['protected'] and existing['author']==key and existing['label']==label:return self.reply(200,{'saved':True,'stats':stats(db)})
                        return self.reply(409,{'error':'這張已被保存，沒有覆蓋原標註'})
                    lease=db.execute('SELECT owner,expires FROM leases WHERE id=?',(id,)).fetchone()
                    if not lease or lease['owner']!=key or lease['expires']<=now:
                        db.rollback();return self.reply(409,{'error':'領取已過期，請重新領取'})
                    db.execute('INSERT INTO annotations VALUES(?,?,?,?,0)',(id,label,key,now))
                    db.execute('INSERT INTO events(id,label,author,updated) VALUES(?,?,?,?)',(id,label,name,now))
                    db.execute('DELETE FROM leases WHERE id=?',(id,));db.commit()
                    return self.reply(200,{'saved':True,'stats':stats(db)})
                if path=='/api/undo':
                    id=p.get('id')
                    if not isinstance(id,str):raise ValueError('無效圖片')
                    db.execute('BEGIN IMMEDIATE')
                    previous=db.execute('SELECT label,author,updated,protected FROM annotations WHERE id=?',(id,)).fetchone()
                    if not previous or previous['protected'] or previous['author']!=key or previous['updated']<now-300:
                        db.rollback();return self.reply(409,{'error':'只能撤銷自己五分鐘內的標註'})
                    db.execute('DELETE FROM annotations WHERE id=?',(id,))
                    db.execute('INSERT INTO events(id,label,author,updated) VALUES(?,?,?,?)',(id,'__undo__:'+previous['label'],name,now))
                    db.execute('DELETE FROM leases WHERE owner=?',(key,))
                    db.execute('INSERT OR REPLACE INTO leases VALUES(?,?,?)',(id,key,now+900));db.commit()
                    row=db.execute('SELECT record FROM samples WHERE id=?',(id,)).fetchone()
                    return self.reply(200,{'sample':json.loads(row['record']),'stats':stats(db)})
                return self.reply(404,{'error':'找不到介面'})
        except (ValueError,TypeError,json.JSONDecodeError):self.reply(400,{'error':'請求內容無效'})
        except sqlite3.Error:self.reply(503,{'error':'資料庫暫時忙碌，選擇尚未保存，請重試'})

if __name__=='__main__':
    initialize();server=ThreadingHTTPServer((os.environ.get('ANNOTATION_HOST','127.0.0.1'),int(os.environ.get('ANNOTATION_PORT','18765'))),Handler)
    server.daemon_threads=True
    try:server.serve_forever()
    finally:server.server_close()
