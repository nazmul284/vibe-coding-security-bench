const $ = s => document.querySelector(s);
let token = sessionStorage.getItem('token'), notes = [], current = null, mode = 'login';

async function api(path, options={}) {
  const headers = {'Content-Type':'application/json', ...(options.headers||{})};
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(path, {...options, headers});
  const data = await res.json().catch(()=>({error:'Unexpected server response'}));
  if (!res.ok) throw new Error(data.error || 'Request failed');
  return data;
}
function message(el, text, good=false) { el.textContent=text; el.className=`message ${good?'good':'error'}`; }
function showApp() { $('#auth').classList.add('hidden'); $('#shared').classList.add('hidden'); $('#notes-app').classList.remove('hidden'); $('#logout').classList.remove('hidden'); loadNotes(); }
function showAuth() { $('#auth').classList.remove('hidden'); $('#notes-app').classList.add('hidden'); $('#logout').classList.add('hidden'); }
async function loadNotes(){ try { notes=await api('/api/notes'); renderList(); } catch(e) { logout(); } }
function renderList(){ const list=$('#note-list'); list.replaceChildren(); for(const n of notes){ const b=document.createElement('button'); b.className='note-item'+(current?.id===n.id?' selected':''); const h=document.createElement('strong'); h.textContent=n.title; const p=document.createElement('span'); p.textContent=n.body.slice(0,70)||'Empty note'; b.append(h,p); b.onclick=()=>selectNote(n); list.append(b); } }
function selectNote(n){ current=n; $('#empty').classList.add('hidden'); $('#note-form').classList.remove('hidden'); $('#title').value=n.title; $('#body').value=n.body; $('#share-box').classList.add('hidden'); $('#note-message').textContent=''; renderList(); }
function newNote(){ current=null; $('#empty').classList.add('hidden'); $('#note-form').classList.remove('hidden'); $('#title').value=''; $('#body').value=''; $('#share-box').classList.add('hidden'); $('#title').focus(); renderList(); }
function logout(){ token=null; notes=[]; current=null; sessionStorage.removeItem('token'); showAuth(); }

document.querySelectorAll('.tabs button').forEach(b=>b.onclick=()=>{ mode=b.dataset.mode; document.querySelectorAll('.tabs button').forEach(x=>x.classList.toggle('active',x===b)); $('#auth-form .primary').textContent=mode==='login'?'Log in':'Create account'; $('#password').autocomplete=mode==='login'?'current-password':'new-password'; $('#auth-message').textContent=''; });
$('#auth-form').onsubmit=async e=>{ e.preventDefault(); const data={email:$('#email').value,password:$('#password').value}; try { if(mode==='signup'){ await api('/api/signup',{method:'POST',body:JSON.stringify(data)}); mode='login'; document.querySelector('[data-mode="login"]').click(); message($('#auth-message'),'Account created. You can log in now.',true); } else { const r=await api('/api/login',{method:'POST',body:JSON.stringify(data)}); token=r.token; sessionStorage.setItem('token',token); showApp(); } } catch(err){ message($('#auth-message'),err.message); } };
$('#note-form').onsubmit=async e=>{ e.preventDefault(); try { const data={title:$('#title').value,body:$('#body').value}; const saved=await api(current?`/api/notes/${current.id}`:'/api/notes',{method:current?'PUT':'POST',body:JSON.stringify(data)}); current=saved; await loadNotes(); selectNote(saved); message($('#note-message'),'Saved',true); } catch(err){ message($('#note-message'),err.message); } };
$('#new-note').onclick=newNote; $('#logout').onclick=logout;
$('#delete').onclick=async()=>{ if(!current||!confirm('Delete this note permanently?')) return; try{ await api(`/api/notes/${current.id}`,{method:'DELETE'}); current=null; $('#note-form').classList.add('hidden'); $('#empty').classList.remove('hidden'); await loadNotes(); }catch(e){message($('#note-message'),e.message);} };
$('#share').onclick=async()=>{ if(!current){message($('#note-message'),'Save the note before sharing.');return;} try{ const r=await api(`/api/notes/${current.id}/share`,{method:'POST',body:'{}'}); const url=`${location.origin}/?share=${encodeURIComponent(r.share_token)}`; $('#share-url').textContent=url; $('#share-box').classList.remove('hidden'); }catch(e){message($('#note-message'),e.message);} };
$('#copy').onclick=async()=>{ await navigator.clipboard.writeText($('#share-url').textContent); $('#copy').textContent='Copied'; setTimeout(()=>$('#copy').textContent='Copy',1200); };

async function start(){ const share=new URLSearchParams(location.search).get('share'); if(share){ try{const n=await api(`/api/shared/${encodeURIComponent(share)}`); $('#auth').classList.add('hidden'); $('#shared').classList.remove('hidden'); $('#shared-title').textContent=n.title; $('#shared-body').textContent=n.body;}catch(e){message($('#auth-message'),'This share link is invalid or has expired.');} return;} token?showApp():showAuth(); }
start();
