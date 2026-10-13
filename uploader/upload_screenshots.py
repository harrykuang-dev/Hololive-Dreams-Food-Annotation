"""Owner-operated resumable upload of original screenshots. No password persistence."""
import hashlib,json,os,queue,re,sys,threading,time,tkinter as tk
from pathlib import Path
from tkinter import ttk,filedialog,messagebox
import paramiko

ROOT=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent
REMOTE=r'''
import hashlib,json,os,pwd,re,shutil,subprocess
from pathlib import Path
os.nice(10)
root=Path('/srv/cooking-annotation');directory=root/'site/screenshots';statefile=root/'runtime/screenshot-upload-state.json'
def filename(value):
    if not re.fullmatch(r'[a-f0-9]{64}\.(jpg|png)',value):raise ValueError('Invalid screenshot name')
    return directory/value
def state():
    return json.loads(statefile.read_text()) if statefile.exists() else {'completed':{}}
def save(value):
    temp=statefile.with_suffix('.tmp');temp.write_text(json.dumps(value));temp.chmod(0o600);os.replace(temp,statefile)
def verified(item,cache):
    path=filename(item['name'])
    if not path.is_file() or path.stat().st_size!=item['bytes']:return False
    stat=path.stat();known=cache['completed'].get(item['name'])
    if known and known.get('mtime_ns')==stat.st_mtime_ns and known.get('sha256')==item['sha256']:return True
    with path.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
    if digest!=item['sha256']:return False
    cache['completed'][item['name']]={'sha256':digest,'mtime_ns':stat.st_mtime_ns};return True
def operate(p):
    if p['action']=='setup':
        metadata_script=r"""import json,sqlite3
from pathlib import Path
def update(p):
    db=sqlite3.connect('file:/data/progress.sqlite3?mode=rw',uri=True,timeout=30)
    actual=db.execute('SELECT value FROM metadata WHERE key=?',('dataset_sha256',)).fetchone()[0]
    if actual!=p['dataset_sha256']:raise ValueError('Dataset fingerprint mismatch; no changes made')
    priority=list(dict.fromkeys(p['samples'][r[0]]['screenshot'].split('/')[-1] for r in db.execute('SELECT s.id FROM samples s LEFT JOIN annotations a ON s.id=a.id WHERE a.id IS NULL ORDER BY s.position') if r[0] in p['samples']))
    backup=Path('/data/screenshot-records-before.json')
    if not backup.exists():backup.write_text(json.dumps(dict(db.execute('SELECT id,record FROM samples').fetchall())));backup.chmod(0o600)
    db.execute('BEGIN IMMEDIATE')
    try:
        for id,extra in p['samples'].items():
            row=db.execute('SELECT record FROM samples WHERE id=?',(id,)).fetchone()
            if not row:raise ValueError('Unknown sample ID')
            record=json.loads(row[0])
            if any(record.get(k)!=v for k,v in extra.items()):
                record.update(extra);db.execute('UPDATE samples SET record=? WHERE id=?',(json.dumps(record),id))
        db.commit()
    except BaseException:db.rollback();raise
    finally:db.close()
    print(json.dumps({'priority':priority}))
"""
        data={'dataset_sha256':p['dataset_sha256'],'samples':p['samples']}
        metadata_script+='\nupdate(json.loads('+repr(json.dumps(data))+'))\n'
        operation=subprocess.run(['docker','exec','-i','cooking-annotation','python','-'],input=metadata_script,capture_output=True,text=True,timeout=180)
        if operation.returncode:raise RuntimeError(operation.stderr.strip().splitlines()[-1] if operation.stderr.strip() else 'Metadata update failed')
        priority=json.loads(operation.stdout)['priority']
        directory.mkdir(exist_ok=True);owner=pwd.getpwnam('ubuntu');os.chown(directory,owner.pw_uid,owner.pw_gid);directory.chmod(0o755)
        notes=[]
        for name,update in p['site'].items():
            if name not in ('index.html','app.js','style.css'):raise ValueError('Unexpected website file')
            path=root/'site'/name;current=hashlib.sha256(path.read_bytes()).hexdigest();desired=update['content'].encode('utf-8')
            digest=hashlib.sha256(desired).hexdigest()
            if current==digest:continue
            if current!=update['previous_sha256']:
                notes.append(name+': kept newer website version');continue
            backup=root/'runtime'/('screenshot-before-'+name)
            if not backup.exists():shutil.copyfile(path,backup);backup.chmod(0o600)
            temp=path.with_name(name+'.screenshot-update');temp.write_bytes(desired);temp.chmod(0o644);os.replace(temp,path)
        cache=state();done=[item['name'] for item in p['files'] if verified(item,cache)];save(cache)
        done_set=set(done);needed=sum(item['bytes'] for item in p['files'] if item['name'] not in done_set)
        disk=shutil.disk_usage(root)
        if disk.free<needed+512*1024**2:raise ValueError('Insufficient server disk space for remaining screenshots')
        return {'completed':done,'disk_total':disk.total,'disk_free':disk.free,'notes':notes,'priority':priority}
    if p['action']=='verify':
        cache=state();completed=[];failed=[]
        for item in p['files']:
            final=filename(item['name']);part=final.with_name(final.name+'.part')
            if part.exists():
                with part.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
                if part.stat().st_size==item['bytes'] and digest==item['sha256']:
                    part.chmod(0o644);os.replace(part,final)
                else:part.unlink();failed.append(item['name']);continue
            if verified(item,cache):completed.append(item['name'])
            else:failed.append(item['name'])
        save(cache);return {'completed':completed,'failed':failed}
    raise ValueError('Unknown operation')
'''

class UploadApp:
    def __init__(self):
        self.window=tk.Tk();self.window.title('完整截圖上傳器');self.window.geometry('700x500')
        self.window.option_add('*Font',('Microsoft JhengHei',10))
        self.events=queue.Queue();self.stop=threading.Event();self.key=None;self.loaded_key_path=None;self.busy=False
        self.plan=json.loads((ROOT/'upload-plan.json').read_text(encoding='utf-8'))
        self.site=json.loads((ROOT/'site-update.json').read_text(encoding='utf-8'))
        frame=ttk.Frame(self.window,padding=24);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='完整截圖上傳',font=('Microsoft JhengHei',19,'bold')).pack(anchor='w')
        self.total=sum(f['bytes'] for f in self.plan['files'])
        ttk.Label(frame,text=f"{len(self.plan['samples']):,} 張標註，共用 {len(self.plan['files']):,} 張原始截圖（{self.total/1024**3:.2f} GiB）。\n保留原始畫質；可暫停、關閉後接續，已驗證的圖片不會重傳。").pack(anchor='w',pady=12)
        ttk.Label(frame,text='SSH 私鑰檔案').pack(anchor='w')
        row=ttk.Frame(frame);row.pack(fill='x',pady=5)
        self.keypath=tk.StringVar(value=self.plan['key_path']);ttk.Entry(row,textvariable=self.keypath).pack(side='left',fill='x',expand=True)
        ttk.Button(row,text='選擇檔案',command=self.browse).pack(side='right',padx=6)
        ttk.Label(frame,text='私鑰解鎖密碼（不保存；僅在本機解鎖）').pack(anchor='w',pady=(8,0))
        self.password=ttk.Entry(frame,show='●');self.password.pack(fill='x',pady=5)
        self.progress=ttk.Progressbar(frame,maximum=self.total);self.progress.pack(fill='x',pady=(16,8))
        self.disk=tk.StringVar(value='啟動後會確認伺服器實際磁碟容量及可用空間。')
        ttk.Label(frame,textvariable=self.disk,foreground='#666',wraplength=640).pack(anchor='w',pady=(0,8))
        self.status=tk.StringVar(value='尚未開始。填寫解鎖密碼後，按「開始／接續上傳」。')
        ttk.Label(frame,textvariable=self.status,wraplength=640).pack(anchor='w')
        buttons=ttk.Frame(frame);buttons.pack(fill='x',pady=16)
        self.start=ttk.Button(buttons,text='開始／接續上傳',command=self.submit);self.start.pack(side='left')
        self.pause=ttk.Button(buttons,text='暫停（保留進度）',command=self.stop.set,state='disabled');self.pause.pack(side='left',padx=12)
        ttk.Label(frame,text='目的地：label.kurumimarket.store　｜　上傳完成後重新整理標註網頁',foreground='#666').pack(anchor='w')
        self.window.protocol('WM_DELETE_WINDOW',self.close);self.window.after(150,self.poll)
        try:(ROOT/'startup-status.json').write_text(json.dumps({'status':'ready','pid':os.getpid(),'images':len(self.plan['files']),'samples':len(self.plan['samples']),'upload_started':False}),encoding='utf-8')
        except OSError:pass
    def browse(self):
        if self.busy:return
        path=filedialog.askopenfilename(title='選擇你的 SSH 私鑰')
        if path:self.keypath.set(path);self.key=None
    def emit(self,message,done=None):self.events.put((message,done))
    def command(self,client,payload):
        script=REMOTE+'\nprint(json.dumps(operate(json.loads('+repr(json.dumps(payload,ensure_ascii=False))+'))))\n'
        stdin,stdout,stderr=client.exec_command('sudo -n python3 -',timeout=180)
        stdin.write(script);stdin.flush();stdin.channel.shutdown_write()
        output=stdout.read().decode('utf-8');error=stderr.read().decode('utf-8');code=stdout.channel.recv_exit_status()
        if code:raise RuntimeError(error.strip().splitlines()[-1] if error.strip() else '伺服器操作未完成')
        return json.loads(output)
    def submit(self):
        if self.busy:return
        self.busy=True;self.stop.clear();self.start.configure(state='disabled');self.pause.configure(state='normal')
        secret=self.password.get();self.password.delete(0,'end');path=self.keypath.get()
        threading.Thread(target=self.upload,args=(path,secret),daemon=True).start();secret=None
    def upload(self,keypath,secret):
        client=paramiko.SSHClient()
        try:
            self.emit('正在解鎖與連線…')
            if self.key is None or self.loaded_key_path!=keypath:
                self.key=paramiko.Ed25519Key.from_private_key_file(keypath,password=secret or None);self.loaded_key_path=keypath
            secret=None;client.load_host_keys(str(ROOT/'known-hosts'));client.set_missing_host_key_policy(paramiko.RejectPolicy())
            client.connect(self.plan['host'],username=self.plan['username'],pkey=self.key,allow_agent=False,look_for_keys=False,timeout=15,auth_timeout=15)
            client.get_transport().set_keepalive(30)
            public=[{k:f[k] for k in ('name','sha256','bytes')} for f in self.plan['files']]
            self.emit('正在確認資料集、磁碟餘量與已上傳圖片；既有標註不會改動…')
            result=self.command(client,{'action':'setup','dataset_sha256':self.plan['dataset_sha256'],'samples':self.plan['samples'],'files':public,'site':self.site})
            completed=set(result['completed']);done=sum(f['bytes'] for f in self.plan['files'] if f['name'] in completed)
            self.emit(f"伺服器磁碟 {result['disk_total']/1024**3:.1f} GiB，可用 {result['disk_free']/1024**3:.1f} GiB。",done)
            self.events.put(('__disk__',f"伺服器磁碟 {result['disk_total']/1024**3:.1f} GiB，可用 {result['disk_free']/1024**3:.1f} GiB"))
            started=time.monotonic();transferred=0;batch=[];last_tick=0
            priority={name:i for i,name in enumerate(result['priority'])}
            with client.open_sftp() as sftp:
                for f in sorted(self.plan['files'],key=lambda item:priority.get(item['name'],len(priority))):
                    if self.stop.is_set():break
                    if f['name'] in completed:continue
                    source=Path(f['local'])
                    if not source.is_file():raise FileNotFoundError('找不到原始截圖：'+str(source))
                    with source.open('rb') as local:
                        if hashlib.file_digest(local,'sha256').hexdigest()!=f['sha256']:raise ValueError('原始截圖內容已改變，停止以免上傳錯圖')
                        local.seek(0);remote='/srv/cooking-annotation/site/screenshots/'+f['name']+'.part'
                        try:offset=sftp.stat(remote).st_size
                        except FileNotFoundError:offset=0
                        if offset>f['bytes']:raise ValueError('暫存圖片大小異常')
                        local.seek(offset)
                        with sftp.open(remote,'ab' if offset else 'wb') as target:
                            target.set_pipelined(True)
                            sent=offset
                            while not self.stop.is_set():
                                chunk=local.read(128*1024)
                                if not chunk:break
                                target.write(chunk);sent+=len(chunk);transferred+=len(chunk)
                                now=time.monotonic()
                                if now-last_tick>=1:
                                    last_tick=now;speed=max(0,transferred/max(now-started,.01));remaining=max(0,self.total-done-sent)
                                    eta=f'，約剩 {remaining/max(speed,1)/3600:.1f} 小時' if speed>0 else ''
                                    self.emit(f"{len(completed):,}／{len(public):,} 張已驗證　{(done+sent)/1024**3:.2f}／{self.total/1024**3:.2f} GiB　{speed/1024**2:.2f} MiB/s{eta}",done+sent)
                        if sent==f['bytes']:batch.append({k:f[k] for k in ('name','sha256','bytes')});done+=f['bytes']
                        if len(batch)>=8:
                            checked=self.command(client,{'action':'verify','files':batch})
                            if checked['failed']:raise ValueError('圖片校驗未通過，請按接續重傳該圖片')
                            completed.update(checked['completed']);batch=[]
                if batch:
                    checked=self.command(client,{'action':'verify','files':batch})
                    if checked['failed']:raise ValueError('圖片校驗未通過，請按接續重傳該圖片')
                    completed.update(checked['completed'])
            if self.stop.is_set():self.emit('已暫停。完整圖片和未完成的片段均已保留，下次可接續。',done)
            elif len(completed)==len(public):self.emit('全部截圖上傳並校驗完成。重新整理標註網頁，即可點「載入完整截圖」。',self.total)
            else:raise RuntimeError('仍有未驗證的圖片，請接續上傳')
        except Exception as error:self.emit('未完成：'+str(error)+'。已上傳內容保留，可再次接續。')
        finally:secret=None;client.close();self.events.put(('__idle__',None))
    def poll(self):
        while not self.events.empty():
            message,done=self.events.get()
            if message=='__disk__':self.disk.set(done)
            elif message=='__idle__':
                self.busy=False;self.start.configure(state='normal');self.pause.configure(state='disabled')
            else:
                self.status.set(message)
                if done is not None:self.progress['value']=done
        self.window.after(150,self.poll)
    def close(self):
        self.stop.set();self.key=None;self.window.destroy()

if __name__=='__main__':
    try:app=UploadApp();app.window.mainloop()
    except Exception as error:
        window=tk.Tk();window.withdraw();messagebox.showerror('無法開啟上傳器',str(error));window.destroy()
