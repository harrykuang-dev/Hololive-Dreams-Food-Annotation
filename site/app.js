const names={ham:'火腿',milk:'牛奶',pot:'帶柄麵鍋',potato:'馬鈴薯',sauce:'醬汁瓶',cucumber:'小黃瓜',meat:'肉盒',udon:'白色烏龍麵',noodles:'黃色麵塊',plum:'梅子',egg:'白雞蛋',brownegg:'棕雞蛋',kamaboko:'魚板',cereal:'麥片盒',onion:'洋蔥',panko:'麵包粉',pepper:'紅辣椒',spider:'蜘蛛盒',flour:'麵粉',sausage:'香腸',ricebowl:'碗裝白飯',plate:'盤裝白飯',ricepack:'粉紅飯盒',scallion:'蔥',shrimp:'炸蝦',curry:'咖哩壺',seaweed:'海苔',glove:'手套／手掌盤',moyashi:'豆芽罐',tuna:'鮪魚罐',background:'背景／空白',uncertain:'不確定'};
const $=id=>document.getElementById(id), config=await fetch('config.json').then(r=>r.json());
const prefix='food500-shared-v1-', read=(key,fallback=null)=>{try{return JSON.parse(localStorage.getItem(prefix+key))??fallback}catch{return fallback}};
const write=(key,value)=>localStorage.setItem(prefix+key,JSON.stringify(value));
let token=read('token'),name=read('name'),sample=null,lastSaved=null,busy=false;
function status(text){$('status').textContent=text}
function progress(s){$('completed').textContent=`已確認：${s.confirmed.toLocaleString()}／${s.total.toLocaleString()}`;$('remaining').textContent=`未標：${(s.total-s.confirmed-s.uncertain).toLocaleString()}　不確定：${s.uncertain.toLocaleString()}`}
function lock(value){busy=value;const pending=!!read('pending');document.querySelectorAll('.choices button').forEach(b=>b.disabled=value||!sample||pending);$('undo').disabled=value||!lastSaved||pending;$('next').disabled=value||pending}
async function api(path,payload){
 if(!config.api_base)throw new Error('共享服務尚未接通');
 const response=await fetch(config.api_base.replace(/\/$/,'')+path,{method:payload?'POST':'GET',headers:{'Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{})},...(payload?{body:JSON.stringify(payload)}:{})});
 const data=await response.json();if(!response.ok){if(response.status===401){token=null;write('token',null);$('join').hidden=false;$('workspace').hidden=true}const error=new Error(data.error||'連線失敗');error.status=response.status;throw error}
 $('connection').textContent='已連線';return data;
}
function show(s){
 sample=s;$('workspace').hidden=!s;
 if($('fullshot-view')){$('fullshot-view').hidden=true;$('fullshot-image').removeAttribute('src');$('fullshot').disabled=!s?.screenshot;}
 if(!s){status('目前沒有可領取的圖片。可能已標完，或正在由其他人標註。');return}
 for(const k of ['crop','context']){if(!/^(crops|contexts)\/[a-f0-9]{24}\.(png|jpg)$/.test(s[k]))throw new Error('圖片路徑無效');$(k).src=s[k]}
 $('sample-id').textContent='圖片：'+s.id;$('participant').textContent='標註者：'+name;
 lock(false);status('選擇紅圈中心的食物。每次選擇立即同步。');
}
$('fullshot')?.addEventListener('click',()=>{
 if(!sample?.screenshot||!/^screenshots\/[a-f0-9]{64}\.(jpg|png)$/.test(sample.screenshot))return;
 const point=sample.screenshot_point_percent;if(!Array.isArray(point)||point.length!==2||point.some(v=>!Number.isFinite(v)||v<0||v>100)){status('完整截圖點位資料無效');return}
 const id=sample.id;$('fullshot-status').textContent='正在載入完整原始截圖…';$('fullshot-view').hidden=false;
 $('fullshot-point').style.left=point[0]+'%';$('fullshot-point').style.top=point[1]+'%';$('fullshot-link').href=sample.screenshot;
 $('fullshot-image').onload=()=>{if(sample?.id===id)$('fullshot-status').textContent='原始尺寸：'+sample.screenshot_size.join(' × ')+'；圖片未重新壓縮。'};
 $('fullshot-image').onerror=()=>{if(sample?.id===id){$('fullshot-status').textContent='這張完整截圖尚未上傳完成，稍後可再按一次載入。'}};
 $('fullshot-image').src=sample.screenshot;
});
async function claim(){if(busy)return;lock(true);try{const d=await api('/api/claim',{});progress(d.stats);show(d.sample)}catch(e){status(e.message);$('connection').textContent='連線中斷'}finally{lock(false)}}
async function sendPending(){
 const pending=read('pending');if(!pending)return true;
 try{const d=await api('/api/label',pending);progress(d.stats);write('pending',null);$('pending-conflict').hidden=true;return true}catch(e){if(e.status===409)$('pending-conflict').hidden=false;throw e}
}
async function choose(label){
 if(busy||!sample)return;
 try{write('pending',{id:sample.id,label})}catch{status('本機保存不可用，尚未提交，請檢查瀏覽器儲存設定。');return}
 lock(true);try{await sendPending();lastSaved=sample;sample=null;status('已同步：'+names[label])}catch(e){status(e.message+'；選擇已留在本機，重新連線後再提交。');$('connection').textContent='待同步';lock(false);return}
 lock(false);await claim();
}
for(const [label,text]of Object.entries(names)){if(['background','uncertain'].includes(label))continue;const button=document.createElement('button');button.className='food';button.type='button';const icon=document.createElement('img');icon.src='icons/'+label+'.png';icon.alt='';const caption=document.createElement('span');caption.textContent=text;button.append(icon,caption);button.addEventListener('click',()=>choose(label));$('foods').append(button)}
$('background').onclick=()=>choose('background');$('uncertain').onclick=()=>choose('uncertain');$('next').onclick=claim;
$('join-form').onsubmit=async e=>{e.preventDefault();try{const d=await api('/api/join',{name:$('name').value});token=d.token;name=d.name;write('token',token);write('name',name);$('join').hidden=true;await sendPending();await claim()}catch(error){status(error.message)}};
$('keep-pending').onclick=async()=>{const pending=read('pending');if(!pending)return;const url=URL.createObjectURL(new Blob([JSON.stringify({dataset_id:config.dataset_id,pending},null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='unsynced-annotation.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);write('pending',null);$('pending-conflict').hidden=true;lock(false);await claim()};
$('retry').onclick=async()=>{try{await sendPending();await claim()}catch(e){status(e.message)}};
$('undo').onclick=async()=>{if(busy||!lastSaved)return;lock(true);try{const d=await api('/api/undo',{id:lastSaved.id});lastSaved=null;progress(d.stats);show(d.sample);status('已撤銷，請重新選擇。')}catch(e){status(e.message)}finally{lock(false)}};
$('export').onclick=async()=>{try{const d=await api('/api/export');const url=URL.createObjectURL(new Blob([JSON.stringify(d,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='shared-annotations.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}catch(e){status(e.message)}};
window.addEventListener('keydown',e=>{if(e.code==='Space'&&!['INPUT','TEXTAREA'].includes(document.activeElement.tagName)){e.preventDefault();choose('uncertain')}});
if(config.api_base){
 const base=new URL(config.api_base);if(base.protocol!=='https:'&&!['127.0.0.1','localhost'].includes(base.hostname))throw new Error('共享連線必須使用HTTPS');
 if(token){try{await sendPending();await claim()}catch(e){status(e.message)}}else{$('join').hidden=false;$('name').value=name||'';$('connection').textContent='尚未加入';status('請填寫標註者 ID。')}
 setInterval(async()=>{if(!token||busy)return;try{progress(await api('/api/stats'))}catch{$('connection').textContent='連線中斷'}},5000);
 setInterval(()=>{if(sample&&!busy)claim()},300000);
}else{$('connection').textContent='尚未接通';status('共享服務尚未接通，請等待部署完成。')}
