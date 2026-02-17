const scopes = ["profile","api","logins","legal","medical","billing","misc"];
function el(id){ return document.getElementById(id); }
function setPill(id, text, cls){ const p=el(id); p.textContent=text; p.className="pill "+(cls||""); }
async function getJSON(url){ const r=await fetch(url); return await r.json(); }
async function postJSON(url, body){ const r=await fetch(url,{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(body)}); return await r.json(); }

function buildScopeChecks(){
  const wrap = el("scopes"); wrap.innerHTML="";
  for (const s of scopes){
    const lab=document.createElement("label"); lab.className="pill"; lab.style.cursor="pointer";
    const cb=document.createElement("input"); cb.type="checkbox"; cb.value=s; cb.checked=(s==="api"||s==="profile"); cb.style.marginRight="8px";
    lab.appendChild(cb); lab.appendChild(document.createTextNode(s)); wrap.appendChild(lab);
  }
  el("scopeSel").innerHTML=scopes.map(s=>`<option value="${s}">${s}</option>`).join("");
}

async function refresh(){
  const st=await getJSON("/api/status");
  if (!st.ok){ setPill("statusPill","Error","bad"); return; }
  setPill("statusPill", st.locked ? "VAULT LOCKED 🔒" : "VAULT UNLOCKED 🔓", st.locked ? "bad" : "ok");
  setPill("scopePill", "Scopes: "+(st.scopes?.length?st.scopes.join(", "):"(none)"), "");
  setPill("expPill", st.expiresAt ? ("Expires: "+st.expiresAt) : "", "");
  const lst=await getJSON("/api/list");
  if (lst.ok){
    const tbody=el("metaTable"); tbody.innerHTML="";
    for (const m of lst.metas){
      const tr=document.createElement("tr");
      tr.innerHTML=`<td><code>${m.ref}</code></td><td>${m.scope}</td><td>${m.sensitivity}</td><td>${m.label}</td><td>${m.updatedAt}</td>`;
      tbody.appendChild(tr);
    }
    setPill("listMsg", `Loaded ${lst.metas.length} secrets`, "ok");
  }
}

buildScopeChecks();
refresh();
el("btnRefresh").onclick=refresh;

el("btnInit").onclick=async()=>{
  const pw=el("initPw").value;
  const r=await postJSON("/api/init",{password:pw});
  setPill("initMsg", r.ok?"Initialized":("Error: "+r.error), r.ok?"ok":"bad");
  el("initPw").value=""; refresh();
};

el("btnUnlock").onclick=async()=>{
  const pw=el("unlockPw").value;
  const ttlMinutes=Number(el("ttl").value||30);
  const inactivityMinutes=Number(el("idle").value||10);
  const checks=[...el("scopes").querySelectorAll("input[type=checkbox]")];
  const chosen=checks.filter(c=>c.checked).map(c=>c.value);
  const r=await postJSON("/api/unlock",{password:pw,ttlMinutes,inactivityMinutes,scopes:chosen});
  setPill("unlockMsg", r.ok?"Unlocked":("Error: "+r.error), r.ok?"ok":"bad");
  el("unlockPw").value=""; refresh();
};

el("btnLock").onclick=async()=>{
  const r=await postJSON("/api/lock",{});
  setPill("unlockMsg", r.ok?"Locked":("Error: "+r.error), r.ok?"ok":"bad");
  refresh();
};

el("btnPut").onclick=async()=>{
  const scope=el("scopeSel").value;
  const sensitivity=el("sensSel").value;
  const name=el("nameSel").value.trim();
  const label=el("labelSel").value.trim();
  const secret=el("secretVal").value;
  const ref=`vault://${scope}/${name}`;
  const r=await postJSON("/api/put",{ref,scope,sensitivity,label,secret});
  setPill("putMsg", r.ok?`Saved ${ref}`:("Error: "+r.error), r.ok?"ok":"bad");
  el("secretVal").value=""; refresh();
};

el("btnToolAdd").onclick=async()=>{
  const toolId=el("toolId").value.trim();
  const allowedScopes=el("toolScopes").value.split(",").map(s=>s.trim()).filter(Boolean);
  const r=await postJSON("/api/tool-add",{toolId,allowedScopes});
  setPill("toolMsg", r.ok?(`Tool added. HMAC key: ${r.data.hmacKey}`):("Error: "+r.error), r.ok?"ok":"bad");
};

el("btnMint").onclick=async()=>{
  const ref=el("confRef").value.trim();
  const purpose=el("confPurpose").value.trim();
  const r=await postJSON("/api/mint-confirm",{ref,purpose});
  el("confOut").value = r.ok ? r.token : ("Error: "+r.error);
};
