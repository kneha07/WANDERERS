// WANDERERS local server smoke/security tests (Node.js 18+).
// Run from repository root: node --test test/server.test.js
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const net = require('node:net');
let child, base;
async function port() { return new Promise((resolve,reject)=>{const s=net.createServer();s.once('error',reject);s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p));});}); }
async function request(path, options) { return fetch(base + path, options); }
before(async () => {
  const p=await port(); base=`http://127.0.0.1:${p}`;
  child=spawn(process.execPath,['server.js'],{env:{...process.env,PORT:String(p)},stdio:'ignore'});
  for(let i=0;i<60;i++){if(child.exitCode!==null)throw new Error('server exited');try{const r=await request('/api/health');if(r.ok)return;}catch{} await new Promise(r=>setTimeout(r,100));}
  throw new Error('server failed to start');
});
after(()=>{if(child)child.kill();});
test('health endpoint responds',async()=>{const r=await request('/api/health');assert.equal(r.status,200);assert.equal(await r.text(),'ok');});
test('missing static file returns 404',async()=>{const r=await request('/not-a-real-file.txt');assert.equal(r.status,404);});
test('malformed JSON returns client error',async()=>{const r=await request('/api/ask',{method:'POST',headers:{'content-type':'application/json'},body:'{' });assert.equal(r.status,400);});
test('rejects unsafe target identifier',async()=>{const r=await request('/api/ask',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({target:'../secret',question:'What is this?'})});assert.equal(r.status,400);});
test('rejects empty question',async()=>{const r=await request('/api/ask',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({target:'wise0855',question:'  '})});assert.equal(r.status,400);});
test('rejects question longer than 500 characters',async()=>{const r=await request('/api/ask',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({target:'wise0855',question:'x'.repeat(501)})});assert.equal(r.status,400);});
test('rejects invalid URL encoding without crashing',async()=>{const r=await request('/%ZZ');assert.ok(r.status>=400&&r.status<500);});
test('static files cannot reach a sibling folder whose name starts with "app"',async()=>{
  const fs=require('node:fs'),path=require('node:path'),dir=path.join(__dirname,'..',`app_qa_${process.pid}`);
  fs.mkdirSync(dir,{recursive:true});fs.writeFileSync(path.join(dir,'secret.txt'),'secret');
  try{for(const u of[`/..%2fapp_qa_${process.pid}/secret.txt`,`/..%2F..%2F${path.basename(path.join(__dirname,'..'))}%2Fapp_qa_${process.pid}%2Fsecret.txt`]){const r=await request(u);assert.ok(r.status===403||r.status===404,`${u} -> ${r.status}`);assert.notEqual(await r.text(),'secret');}}
  finally{fs.rmSync(dir,{recursive:true,force:true});}
});
test('unknown target does not leak filesystem path',async()=>{const r=await request('/api/ask',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({target:'nonexistent_target_999',question:'What is this?'})});assert.equal(r.status,404);const msg=await r.text();assert.doesNotMatch(msg,/ENOENT|\/Users\/|\/home\/|\\\\/);});

// Another website must not reach /api/ask (it runs claude -p): cross-site POST and DNS rebinding (foreign Host).
const http = require('node:http');
function raw(path, headers, body) {
  return new Promise((ok, bad) => {
    const u = new URL(base + path);
    const r = http.request({ host: u.hostname, port: u.port, path, method: body ? 'POST' : 'GET', headers }, (res) => { res.resume(); ok(res.statusCode); });
    r.on('error', bad); r.end(body);
  });
}
const ASK = JSON.stringify({ target: 'nonexistent_target_999', question: 'hi' });
test('rejects a POST from another website', async () => {
  assert.equal(await raw('/api/ask', { origin: 'https://evil.example', 'content-type': 'text/plain' }, ASK), 403);
});
test('rejects a foreign Host header (DNS rebinding)', async () => {
  assert.equal(await raw('/api/health', { host: 'attacker.example:' + new URL(base).port }), 403);
  assert.equal(await raw('/api/ask', { host: 'localhost.attacker.example' }, ASK), 403);
});
test('accepts a POST from its own page', async () => {
  assert.equal(await raw('/api/ask', { origin: base, 'content-type': 'application/json' }, ASK), 404);
});
