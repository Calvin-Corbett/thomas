import { installFeature } from './chat_feature_fixture.mjs';
// Drive the shipped hydration wrapper and helper with delayed server replies.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
const htmlPath = process.argv[2], html = fs.readFileSync(htmlPath, 'utf8');
const helper = fs.readFileSync(path.join(path.dirname(htmlPath), 'js/chat_turn_flow.js'), 'utf8');
const checks = [];
async function fixture() {
  let answer, calls = 0, painted = 0;
  const messages = [{role:'user',text:'question',model:''},{role:'assistant',text:'answer',model:'luna'}];
  const chat = {id:'chat-A',sessionId:'session-A',model:'luna',msgs:messages};
  const state = {activeChat:'chat-A',sessionId:'session-A',messages:messages.map(m=>({...m})),streaming:false};
  const context = {window:{}, state, chatSelectionToken:1, msgRefs:[],
    fetch() { calls++; return new Promise(resolve=>{answer=resolve;}); },
    threadEl:{innerHTML:'kept',appendChild(){painted++;}},
    buildMessageNode:message=>({message}), syncView(){},syncDynamic(){},scrollEnd(){},
  };
  vm.createContext(context); vm.runInContext(helper,context);
  vm.runInContext(fs.readFileSync(path.join(path.dirname(htmlPath), 'js/chat_media_bridge.js'), 'utf8'), context);
  installFeature(context, htmlPath, 'history_view', ['mapRealMessages']);
  installFeature(context, htmlPath, 'session_restore', ['hydrateSelectedChat']);
  // Establish a rendered transcript through the same owned hydration path,
  // then exercise another response while that actual signature is retained.
  const prime = context.hydrateSelectedChat(chat, 1);
  answer({ok:true,json:async()=>({conversation:{messages:messages.map(m=>({role:m.role,content:m.text}))}})});
  await prime; calls=0; painted=0; context.threadEl.innerHTML='kept';
  return {context,state,chat,counts:()=>({calls,painted}),
    respond(messages) { answer({ok:true,json:async()=>({conversation:{messages}})}); },
    run:()=>context.hydrateSelectedChat(chat,1),
  };
}
const original = [{role:'user',content:'question'},{role:'assistant',content:'answer'}];
async function check(name,run) { await run(); checks.push(name); }
await check('matching saved transcript keeps existing message nodes',async()=>{
  const f=await fixture(), pending=f.run();f.respond(original);assert.equal(await pending,true);
  assert.equal(f.counts().painted,0);assert.equal(f.context.threadEl.innerHTML,'kept');
});
await check('new saved answer repaints the real mapped transcript',async()=>{
  const f=await fixture(),pending=f.run();f.respond([original[0],{role:'assistant',content:'saved answer'}]);
  assert.equal(await pending,true);assert.equal(f.state.messages[1].text,'saved answer');
  assert.equal(f.state.messages[1].model,'luna');assert.equal(f.counts().painted,2);
});
await check('late response cannot overwrite another selection',async()=>{
  const f=await fixture(),pending=f.run();f.context.chatSelectionToken=2;f.state.activeChat='chat-B';
  f.respond([original[0],{role:'assistant',content:'stale'}]);assert.equal(await pending,false);
  assert.equal(f.state.messages[1].text,'answer');assert.equal(f.counts().painted,0);
});
await check('late response cannot overwrite an in-flight reply',async()=>{
  const f=await fixture(),pending=f.run();f.state.streaming=true;f.respond(original);
  assert.equal(await pending,false);assert.equal(f.counts().painted,0);
});
await check('late response cannot overwrite a newer finished turn',async()=>{
  const f=await fixture(),pending=f.run();f.state.messages.push({role:'assistant',text:'newer finished turn'});
  f.respond(original);assert.equal(await pending,false);assert.equal(f.state.messages.length,3);
  assert.equal(f.counts().painted,0);
});
await check('replaced transcript stays owned by the newer local action',async()=>{
  const f=await fixture(),pending=f.run();f.state.messages=f.state.messages.slice();f.respond(original);
  assert.equal(await pending,false);assert.equal(f.counts().painted,0);
});
await check('fresh empty session avoids a guaranteed missing-session request',async()=>{
  const f=await fixture();f.chat.msgs=[];assert.equal(await f.run(),false);assert.equal(f.counts().calls,0);
});
console.log(JSON.stringify({passed:checks.length,checks}));
