const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function setup() {
    const nodes = new Map();
    const element = id => {
        if (!nodes.has(id)) nodes.set(id, {style:{}, disabled:false, innerHTML:'', textContent:''});
        return nodes.get(id);
    };
    const requests = [];
    let status = {running:true, status:'running', task_id:'current', progress:1, total:3, log:[]};
    const app = {renderLogs:()=>{}, showToast:()=>{}};
    const context = vm.createContext({App:app, window:{App:app}, document:{getElementById:element},
        console, alert:()=>{}, setTimeout:()=>1, clearTimeout:()=>{}, setInterval:()=>1, clearInterval:()=>{},
        fetch: async (url, options) => {
            requests.push({url,options});
            if (url.startsWith('/api/stop')) status = {...status, status:'stopping'};
            return {ok:true, json: async ()=>url.startsWith('/api/stop') ? {status:'stopping'} : structuredClone(status)};
        }});
    vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/js/app.js'),'utf8'),context);
    vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/js/task.js'),'utf8'),context);
    app.showToast = () => {};
    return {app,element,requests,setStatus(value){status=value;}};
}

test('stopping remains busy and repeated stop clicks never force-reset', async()=>{
    const {app,element,requests,setStatus} = setup();
    await app.Task.updateStatus();
    await app.Task.stopTask();
    await app.Task.stopTask();
    assert.equal(element('runBtn').disabled,true);
    assert.ok(requests.some(r=>r.url==='/api/stop?task_id=current'));
    assert.ok(requests.every(r=>!r.url.includes('force=1')));
    setStatus({running:true,status:'stopping',task_id:'current',progress:1,total:3,log:[]});
    await app.Task.updateStatus();
    assert.equal(element('runBtn').disabled,true);
    assert.equal(element('stopBtn').disabled,true);
    assert.match(element('statusText').textContent,/停止/);
});

test('terminal status preserves counts and renders messages as text', async()=>{
    const {app,element,setStatus} = setup();
    setStatus({running:false,status:'cancelled',task_id:'current',progress:1,total:3,
        message:'<img src=x onerror=bad()>',result:{success:1,failed:0},log:[]});
    await app.Task.updateStatus();
    assert.equal(element('runBtn').disabled,false);
    assert.match(element('statusText').textContent,/取消/);
    assert.match(element('statusText').textContent,/1/);
    assert.equal(element('statusText').innerHTML,'');
    assert.equal(element('progressFill').style.width,'33%');
});
