const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

test('manual confirmation is displayed without inventing an algorithm percentage', async()=>{
    class Element {
        constructor(tag = 'div') { this.tagName = tag.toUpperCase(); this.style = {}; this.dataset = {}; this.children = []; this.value = 'processed_time_desc'; this._text = ''; }
        append(...children) { this.children.push(...children); }
        appendChild(child) { this.append(child); return child; }
        replaceChildren(...children) { this.children = children; this._text = ''; }
        addEventListener() {}
        get textContent() { return this._text + this.children.map(c => typeof c === 'string' ? c : c.textContent).join(''); }
        set textContent(value) { this._text = String(value ?? ''); this.children = []; }
        get innerHTML() { return this.textContent; }
        set innerHTML(value) { this.textContent = value; }
    }
    const nodes = new Map();
    const element = id => {
        if (!nodes.has(id)) nodes.set(id, new Element());
        return nodes.get(id);
    };
    const item = {src:'/source/input.mkv',src_name:'input.mkv',target:'/movies/Manual.mkv',
        title:'Manual',media_type:'movie',confidence:null,confirmed_by_user:true,
        path:'/source/input.mkv',name:'input.mkv',status:'success'};
    const app = {escapeHtml:v=>String(v??''),showToast:()=>{}};
    const context = vm.createContext({window:{App:app,addEventListener:()=>{}},App:app,console,
        document:{getElementById:element,createElement:tag=>new Element(tag),querySelectorAll:()=>[],addEventListener:()=>{}},
        fetch:async()=>({ok:true,json:async()=>({history:[item],items:[item],files:[item],total_pages:1})})});
    for (const name of ['app.js','history.js','processedCache.js','failedCache.js'])
        vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/js',name),'utf8'),context);
    await app.History.loadProcessedHistory();
    app.ProcessedCache.viewProcessedCache();
    await app.FailedCache.showAllFilesInFolder('/source');
    for (const id of ['historyBody','processedCacheBody','failedCacheList']) {
        assert.match(element(id).innerHTML,/人工指定/);
        assert.doesNotMatch(element(id).innerHTML,/(?:100|0|null)%/);
    }
});

test('recognition score labels distinguish legacy, manual, zero and evidence', ()=>{
    const app={};
    const context=vm.createContext({window:{App:app,addEventListener:()=>{}},App:app,console,
        document:{addEventListener:()=>{}}});
    vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/js/app.js'),'utf8'),context);
    const manual=app.recognitionScore({confirmed_by_user:true,confidence:100});
    assert.match(manual.label,/人工指定/);assert.doesNotMatch(manual.label,/100/);
    assert.match(app.recognitionScore({score_origin:'manual_mapping',confidence:100}).label,/人工指定/);
    assert.match(app.recognitionScore({confidence:0}).label,/旧评分.*0/);
    assert.match(app.recognitionScore({}).label,/未评分/);
    const current=app.recognitionScore({confidence:75,score_origin:'automatic',score_evidence:['标题匹配'],score_conflicts:['多个候选']});
    assert.match(current.label,/匹配评分.*75/);
    assert.match(current.detail,/标题匹配/);assert.match(current.detail,/多个候选/);
    assert.doesNotMatch(current.label+current.detail,/准确率/);
});
