const annMsg=document.querySelector('#ann-message');
function formAnnouncement(){
  const v=id=>document.querySelector(id).value.trim();
  return {announcement_id:v('#ann-id'),carrier:v('#ann-carrier'),destination:v('#ann-dest'),
    published_at:v('#ann-published'),stop_at:v('#ann-stop'),resume_at:v('#ann-resume'),reason:v('#ann-reason')};
}
async function postJSON(url,body){
  const res=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data=await res.json();
  if(!res.ok)throw new Error(data.message||'请求失败');
  return data;
}
async function loadAnnouncements(){
  const res=await fetch('/api/announcements');const data=await res.json();
  const list=document.querySelector('#ann-list');
  list.innerHTML=data.announcements.map(a=>{
    const cls=a.status==='active'?'ok':(a.status==='revoked'?'no':'muted');
    return `<div class="reason"><b class="badge ${cls}">${a.status}</b>${a.announcement_id} · ${a.carrier} · ${a.destination}`+
      `<small>发布 ${a.published_at[5:16]}｜停运 ${a.stop_at[5:16]} → 恢复 ${a.resume_at[5:16]}｜${a.reason}`+
      (a.superseded_by?`｜被 v${a.superseded_by} 替换`:'')+`</small></div>`;
  }).join('')||'<div class="empty">暂无公告。</div>';
  document.querySelector('#ann-count').textContent=data.announcements.filter(a=>a.status==='active').length+' 条有效';
}
document.querySelector('#ann-register').addEventListener('click',async()=>{
  annMsg.textContent='提交中…';
  try{await postJSON('/api/announcements',formAnnouncement());annMsg.textContent='已登记，请重建批次后重算。';
    document.querySelector('#retry').click();}
  catch(e){annMsg.textContent=e.message;}
});
document.querySelector('#ann-revoke').addEventListener('click',async()=>{
  annMsg.textContent='撤销中…';
  const id=document.querySelector('#ann-recheck-id').value.trim();
  const version=Number(document.querySelector('#ann-recheck-version').value);
  try{
    await postJSON(`/api/announcements/${id}/recheck`,{version,action:'revoke',announcement:{}});
    annMsg.textContent='已撤销，旧版保留可查。';document.querySelector('#retry').click();
  }catch(e){annMsg.textContent=e.message;}
});
document.querySelector('#ann-recheck').addEventListener('click',async()=>{
  annMsg.textContent='修订中…';
  const id=document.querySelector('#ann-recheck-id').value.trim();
  const version=Number(document.querySelector('#ann-recheck-version').value);
  try{
    const data=await postJSON(`/api/announcements/${id}/recheck`,{version,action:'replace',announcement:formAnnouncement()});
    annMsg.textContent=`已生成 v${data.versions.length}，旧版保留。`;document.querySelector('#retry').click();
  }catch(e){annMsg.textContent=e.message;}
});
loadAnnouncements();
