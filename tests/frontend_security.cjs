// Real Chromium, actual Jinja templates/scripts, all requests intercepted.
// PLAYWRIGHT_MODULE may point to an existing external Playwright installation.
const {test, before, after} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = process.env.ANIMEMAN_TEST_ROOT || path.resolve(__dirname, '..');
const python = process.env.ANIMEMAN_TEST_PYTHON || 'python3';
const rendered = spawnSync(python, ['-c', `from jinja2 import Environment, FileSystemLoader
import sys
env=Environment(loader=FileSystemLoader(sys.argv[1]),autoescape=True)
print(env.get_template('index.html').render(url_for=lambda endpoint,filename:'/static/'+filename))`, path.join(root, 'templates')], {encoding:'utf8'});
if (rendered.status !== 0) throw new Error(rendered.stderr);
let browser;
before(async()=> { browser = await chromium.launch({headless:true,
    ...(process.env.CHROMIUM_PATH ? {executablePath:process.env.CHROMIUM_PATH} : {}), args:['--no-sandbox']}); });
after(async()=> { await browser?.close(); });
const evil = `<img id="injected" src=x onerror="window.__xss++">`;
const tricky = `/源目录/双"单'\\反斜杠&实体&quot;<>.mkv`;
const title = `片名"'\\ &quot; 中文 ${evil}`;
const item = {src:tricky,src_name:title,target:'/library/'+tricky,target_exists:true,title,
    media_type:'movie',year:'2026',confidence:80,processed_time:1,cache_key:tricky,path:tricky,name:title,
    status:'success',parent_dir:title,grandparent_dir:'中文',tmdb_id:42};
const episode = {cache_key:tricky,episode:1,season:1,title, target_path:tricky,target_dir:'/library', processed_time:1};
const show = {tmdb_id:24,title,year:'2026',seasons:{1:{episodes:[episode]}}};
async function setup(t, overrides={}) {
    const page = await browser.newPage();
    page.setDefaultTimeout(5000);
    t.after(()=>page.close());
    const requests=[];
    page.on('dialog', dialog=>dialog.accept());
    await page.addInitScript(()=>{window.__xss=0; window.__alerts=[]; window.alert=s=>window.__alerts.push(s); window.confirm=()=>true;});
    await page.route('**/*', async route=>{
        const req=route.request(), url=new URL(req.url());
        if(url.origin!=='http://animeman.test') return route.abort();
        if(url.pathname==='/') return route.fulfill({contentType:'text/html',body:rendered.stdout});
        if(url.pathname.startsWith('/static/')) {
            const file=path.join(root,url.pathname);
            if(!file.startsWith(root+'/static/') || !fs.existsSync(file)) return route.abort();
            return route.fulfill({path:file});
        }
        if(!url.pathname.startsWith('/api/')) return route.abort();
        requests.push({url:url.pathname+url.search,method:req.method(),body:req.postDataJSON()});
        if (overrides[url.pathname]) return overrides[url.pathname](route,req);
        const data = {
            '/api/config':{source_folders:[],auth:{},ai_parser:{},ai_plot_enhance:{},tmdb_api:{}},
            '/api/status':{running:false,status:'completed',log:[]},
            '/api/offline/status':{},
            '/api/media/library':{movies:[],tv_shows:[]},
            '/api/processed_history':{history:[item]},
            '/api/processed_cache':{items:[item],total_pages:1},
            '/api/failed_cache/clusters':{clusters:[{folder:tricky,count:1,files:[item]}]},
            '/api/failed_cache':{failed:[{...item,reason:title}]},
            '/api/failed_cache/folder_details':{files:[item]},
            '/api/tmdb/search_proxy':{results:[{id:42,title,year:'2026',media_type:'tv',poster_url:`x" onerror="window.__xss++`,seasons_detail:[{season_number:1,episode_count:1,name:title}]}]},
            '/api/special_mappings':{mappings:[]},
            '/api/drives':[], '/api/subtitle/scan':{subtitles:[]},
        }[url.pathname] || {status:'success',processed:1,total:1};
        return route.fulfill({json:data});
    });
    await page.goto('http://animeman.test/');
    await page.evaluate(()=>{clearInterval(App.statusInterval);});
    return {page,requests};
}
async function safe(page, scope) {
    assert.equal(await page.locator(scope+' #injected').count(),0,'no injected elements');
    assert.equal(await page.evaluate(()=>window.__xss),0,'no injected event executed');
    assert.equal(await page.locator(scope+' [onclick], '+scope+' [onchange], '+scope+' [onerror]').count(),0,'no inline dynamic handlers');
}
async function requestBody(page, requests, endpoint, action) {
    const wait=page.waitForRequest(req=>new URL(req.url()).pathname===endpoint && req.method()==='POST');
    await action();
    return (await wait).postDataJSON();
}

test('history selection, correction and retry preserve special paths',async t=>{
    const {page,requests}=await setup(t);
    // History is a legacy module absent from index.html; use real DOM controls.
    await page.evaluate(()=>{
        const section=document.createElement('section');
        section.innerHTML='<select id="historySortSelect"><option value="processed_time_desc">时间</option></select><input type="checkbox" id="historySelectAll"><button id="historyBatchCorrectBtn"></button><span id="historySelectedCount"></span><table><tbody id="historyBody"></tbody></table>';
        document.body.append(section);
    });
    await page.addScriptTag({url:'/static/js/history.js'});
    await page.evaluate(()=>App.History.loadProcessedHistory());
    await safe(page,'#historyBody');
    assert.equal(await page.locator('#historyBody td').nth(1).getAttribute('title'),tricky);
    assert.equal(await page.locator('#historyBody td').nth(1).textContent(),title);
    await page.locator('.history-checkbox').check();
    await page.locator('#historyBody button').nth(1).click();
    assert.equal(await page.locator('#correctionSrcPath').inputValue(),tricky);
    assert.equal(await page.locator('#correctionFileName').getByText(title,{exact:false}).count(),1);
    await page.evaluate(()=>App.Correction.closeCorrectionModal());
    const body=await requestBody(page,requests,'/api/processed/retry',()=>page.locator('#historyBody button').first().click());
    assert.equal(body.src_path,tricky);
});

test('processed cache selection/correction/deletion preserve original path',async t=>{
    const {page,requests}=await setup(t);
    await page.evaluate(()=>App.ProcessedCache.viewProcessedCache());
    await page.locator('.processed-cache-checkbox').waitFor();
    await safe(page,'#processedCacheBody');
    assert.equal(await page.locator('.processed-cache-checkbox').getAttribute('data-src'),tricky);
    await page.locator('.processed-cache-checkbox').check();
    await page.locator('#processedCacheBody button.secondary').click();
    assert.equal(await page.locator('#correctionSrcPath').inputValue(),tricky);
    await page.evaluate(()=>App.Correction.closeCorrectionModal());
    const body=await requestBody(page,requests,'/api/processed_cache/delete',()=>page.locator('#processedCacheBody button.danger').click());
    assert.equal(body.src_path,tricky);
});

test('failed folder clustering passes raw folder/files to correction',async t=>{
    const {page}=await setup(t);
    await page.evaluate(()=>App.FailedCache.viewFailedCache());
    await page.locator('#failedCacheList button.success').waitFor();
    await safe(page,'#failedCacheList');
    await page.evaluate(()=>{App.BatchCorrection.openModal=(...args)=>window.__batch=args;});
    await page.locator('#failedCacheList button.success').click();
    const args=await page.evaluate(()=>window.__batch);
    assert.equal(args[0],tricky); assert.equal(args[1][0].path,tricky);
    await page.locator('#failedCacheList button').filter({hasText:'查看失败文件'}).click();
    await safe(page,'#failedCacheList');
    await page.locator('#failedCacheList button.warning').click();
    assert.equal(await page.locator('#correctionSrcPath').inputValue(),tricky);
});

test('failed list and folder details are inert and keep correction paths',async t=>{
    const {page}=await setup(t);
    await page.evaluate(()=>App.FailedCache.viewFailedCache());
    await page.locator('#failedCacheList button.success').waitFor();
    await page.evaluate(()=>App.FailedCache.switchToListView());
    await safe(page,'#failedCacheList');
    await page.evaluate(folder=>App.FailedCache.showAllFilesInFolder(folder),tricky);
    await safe(page,'#failedCacheList');
    await page.locator('#failedCacheList td button').click();
    assert.equal(await page.locator('#correctionSrcPath').inputValue(),tricky);
});

for(const batch of [false,true]) test(`${batch?'batch':'single'} TMDB search treats title, attributes and selection as data`,async t=>{
    const {page,requests}=await setup(t);
    await page.evaluate(({tricky,title,batch})=>{
        if(batch) App.BatchCorrection.openModalWithFiles('folder',[{path:tricky,name:title}]);
        else App.Correction.openCorrectionModal(tricky,title);
    },{tricky,title,batch});
    const input=batch?'batchTmdbSearchInput':'tmdbSearchInput', scope=batch?'#batchTmdbResults':'#tmdbResultsBody';
    await page.locator('#'+input).fill('query');
    await page.evaluate(batch=>batch?App.BatchCorrection.searchTmdb():App.Correction.searchTmdbForCorrection(),batch);
    await safe(page,scope);
    assert.equal(await page.locator(scope+' img').getAttribute('src'),`x" onerror="window.__xss++`);
    await page.locator(scope+' button').click();
    assert.equal(await page.locator(batch?'#batchSelectedTmdbTitle':'#selectedTmdbTitle').textContent(),title);
    if(!batch) {
        const body=await requestBody(page,requests,'/api/failed_cache/correct',()=>page.evaluate(()=>App.Correction.executeCorrection()));
        assert.equal(body.src_path,tricky);
    }
});

test('media manager movie attributes preserve key and delete payload',async t=>{
    const {page,requests}=await setup(t,{'/api/media/library':route=>route.fulfill({json:{movies:[item],tv_shows:[show]}})});
    await page.evaluate(()=>App.MediaManager.refreshLibrary());
    await page.locator('#movieGrid .movie-card').waitFor();
    await safe(page,'#mediaLibraryManagerContainer');
    assert.equal(await page.locator('.movie-card').getAttribute('data-movie-key'),tricky);
    await page.locator('.movie-card input').check();
    const body=await requestBody(page,requests,'/api/media/delete',()=>page.locator('.movie-card .danger').click());
    assert.equal(body.src_path,tricky); assert.equal(body.delete_source,false);
});

test('media manager show/episode panels and popup do not parse titles',async t=>{
    const {page}=await setup(t,{'/api/media/library':route=>route.fulfill({json:{movies:[],tv_shows:[show]}})});
    await page.evaluate(()=>App.MediaManager.refreshLibrary());
    await page.locator('.season-toggle-btn').click();
    await page.locator('[data-action="toggleSeasonEpisodes"]').click();
    await safe(page,'#mediaLibraryManagerContainer');
    await page.locator('.episode-title-clickable').click();
    await safe(page,'#episodeDetailPopup');
    assert.ok((await page.locator('#episodeDetailPopup').textContent()).includes('双"单'));
});

test('media selector returns unmodified movie metadata with entity-like text',async t=>{
    const {page}=await setup(t,{'/api/media/library':route=>route.fulfill({json:{movies:[item],tv_shows:[show]}})});
    await page.evaluate(()=>App.MediaLibrary.showTargetSelector(value=>window.__selected=value));
    await safe(page,'#mediaLibraryContainer');
    await page.locator('.select-movie-btn').click();
    const selected=await page.evaluate(()=>window.__selected);
    assert.equal(selected.data.title,title); assert.equal(selected.data.cache_key,tricky);
});

test('subtitle show display and execution keep text and raw paths',async t=>{
    const {page,requests}=await setup(t);
    await page.evaluate(({show,tricky,title})=>{
        App.scannedSubtitles=[{path:tricky,name:title}];
        App.MediaLibrary.showShowSelector=cb=>cb(show);
        App.SubtitleCenter.selectTargetShow();
        App.matchResults=[{subtitle:{path:tricky,name:title},best_match:{score:90,media:{media_type:'tv',title,season:1,episode:1,target_path:tricky,target_dir:'/library'}}}];
        App.SubtitleCenter.renderMatchTable();
    },{show,tricky,title});
    await safe(page,'#selectedShowDisplay'); await safe(page,'#subtitleMatchBody');
    assert.ok((await page.locator('#selectedShowDisplay').textContent()).includes(title));
    const body=await requestBody(page,requests,'/api/subtitle/execute',()=>page.locator('#subtitleMatchBody button.success').click());
    assert.equal(body.items[0].subtitle_path,tricky); assert.equal(body.items[0].target_media.target_path,tricky);
});

test('mapping fields are inert and edit restores exact keyword',async t=>{
    const {page}=await setup(t,{'/api/special_mappings':route=>route.fulfill({json:{mappings:[{keyword:title,tmdb_id:title,media_type:'tv',season:1,episode:1,enabled:true}]}})});
    await page.evaluate(()=>App.MappingRules.loadMappingRules());
    await safe(page,'#mappingRulesBody');
    await page.locator('#mappingRulesBody button.secondary').click();
    assert.equal(await page.locator('#mappingKeyword').inputValue(),title);
});

for(const status of [401,409,500]) test(`HTTP ${status} is a readable failure without reporting correction success`,async t=>{
    const {page}=await setup(t,{'/api/failed_cache/correct':route=>route.fulfill({status,json:{status:'success',message:title}})});
    await page.evaluate(({tricky,title})=>{App.Correction.openCorrectionModal(tricky,title);App.Correction.selectTmdbForCorrection(42,title,'movie');}, {tricky,title});
    await page.evaluate(()=>App.Correction.executeCorrection());
    const text=await page.locator('.app-toast').textContent();
    assert.match(text,new RegExp(status===401?'认证':status===409?'冲突':'服务器'));
    assert.doesNotMatch(text,/修正成功/);
    assert.equal(await page.locator('#correctionModal').evaluate(el=>el.style.display),'block');
    await safe(page,'.app-toast');
});

test('stream error containing HTML is only text (existing protection)',async t=>{
    const {page}=await setup(t,{'/api/ai/stream_enhance':route=>route.fulfill({contentType:'text/event-stream',body:'data: '+JSON.stringify({error:title})+'\n\n'})});
    await page.locator('#testTitle').fill('title'); await page.locator('#testPlot').fill('plot');
    await page.evaluate(()=>App.AIStream.startStreamEnhance());
    assert.equal(await page.locator('#streamOutput').textContent(),'错误: '+title);
    await safe(page,'#streamOutput');
});


test('processed batch deletion submits exactly the checked raw path',async t=>{
    const {page,requests}=await setup(t);
    await page.evaluate(()=>App.ProcessedCache.viewProcessedCache());
    await page.locator('.processed-cache-checkbox').check();
    await page.waitForFunction(()=>document.getElementById('selectedProcessedCount').textContent==='1');
    assert.equal(await page.locator('#selectedProcessedCount').textContent(),'1');
    const body=await requestBody(page,requests,'/api/processed_cache/batch_delete',()=>page.evaluate(()=>App.ProcessedCache.batchDeleteSelected()));
    assert.deepEqual(body.src_paths,[tricky]);
});

test('batch correction sends checked files without reinterpreting titles',async t=>{
    const {page,requests}=await setup(t);
    await page.evaluate(({tricky,title})=>App.BatchCorrection.openModalWithFiles('folder',[{path:tricky,name:title},{path:'/other.mkv',name:'other'}]),{tricky,title});
    await safe(page,'#batchFileList');
    await page.locator('#batchFileList input[data-index="1"]').uncheck();
    await page.evaluate(()=>App.BatchCorrection.selectTmdb(42,'Title','movie'));
    const body=await requestBody(page,requests,'/api/failed_cache/batch_correct',()=>page.evaluate(()=>App.BatchCorrection.execute()));
    assert.deepEqual(body.src_paths,[tricky]);
});

test('season selection and inversion keep the episode key for batch deletion',async t=>{
    const {page,requests}=await setup(t,{'/api/media/library':route=>route.fulfill({json:{movies:[],tv_shows:[show]}})});
    await page.evaluate(()=>App.MediaManager.refreshLibrary());
    await page.locator('.season-toggle-btn').click();
    await page.locator('.season-row button').filter({hasText:'全选'}).click();
    assert.equal(await page.locator('#mediaSelectedCount').textContent(),'1');
    await page.locator('.season-row button').filter({hasText:'反选'}).click();
    assert.equal(await page.locator('#mediaSelectedCount').textContent(),'0');
    await page.locator('.season-row button').filter({hasText:'全选'}).click();
    const body=await requestBody(page,requests,'/api/media/batch_delete',()=>page.evaluate(()=>App.MediaManager.batchDeleteSelected()));
    assert.deepEqual(body.src_paths,[tricky]); assert.equal(body.delete_source,false);
});

test('browser directory navigation and selection preserve punctuation and entities',async t=>{
    const {page}=await setup(t,{
        '/api/drives':route=>route.fulfill({json:[{path:tricky,name:title}]}),
        '/api/browse':(route,req)=>{
            assert.equal(new URL(req.url()).searchParams.get('path'),tricky);
            return route.fulfill({json:{current:tricky,dirs:[],parent:null}});
        }
    });
    await page.evaluate(()=>App.Browse.openBrowser('source'));
    await page.locator('#dirList li').waitFor();
    await safe(page,'#dirList');
    assert.equal(await page.locator('#dirList li').textContent(),'📁 '+title);
    await page.locator('#dirList li').click();
    await page.waitForFunction(value=>App.currentBrowsePath===value,tricky);
    await page.evaluate(()=>App.Browse.selectCurrentPath());
    assert.equal(await page.locator('#sourceFoldersInput').inputValue(),tricky);
});

test('mapping edit/save passes the literal keyword and has no injected nodes',async t=>{
    const {page}=await setup(t,{'/api/special_mappings':(route,req)=>route.fulfill({json:req.method()==='GET'?{
        mappings:[{keyword:title,tmdb_id:42,media_type:'tv',season:0,episode:1,enabled:true}]}:{status:'success'}})});
    await page.evaluate(()=>App.MappingRules.loadMappingRules());
    await page.locator('#mappingRulesBody button.secondary').click();
    const wait=page.waitForRequest(req=>new URL(req.url()).pathname==='/api/special_mappings'&&req.method()==='PUT');
    await page.evaluate(()=>App.MappingRules.saveMappingRule());
    assert.equal((await wait).postDataJSON().rule.keyword,title);
    await safe(page,'#mappingRulesBody');
});

test('subtitle processed and force-match labels are literal text',async t=>{
    const {page}=await setup(t);
    await page.evaluate(({tricky,title})=>{
        App.matchResults=[{subtitle:{path:tricky,name:title,processed_info:{title,media_type:'movie',year:title,target_exists:true,target:tricky}},best_match:null}];
        App.SubtitleCenter.renderMatchTable();
        App.MediaLibrary.showTargetSelector=cb=>cb({type:'movie',data:{title,year:title}});
        App.SubtitleCenter.selectForceMatchShow();
    },{tricky,title});
    await safe(page,'#subtitleMatchBody'); await safe(page,'#forceMatchShowDisplay');
    assert.ok((await page.locator('#forceMatchShowDisplay').textContent()).includes(title));
});

for(const kind of ['html','network']) test(`${kind} error messages render without injected markup`,async t=>{
    const {page}=await setup(t,{'/api/failed_cache/folder_details':route=>route.fulfill({status:500,contentType:'text/html',body:evil})});
    if(kind==='network') await page.evaluate(message=>{window.fetch=async()=>{throw new Error(message);};},title);
    await page.evaluate(folder=>App.FailedCache.showAllFilesInFolder(folder),tricky);
    await safe(page,'#failedCacheList'); await safe(page,'.app-toast');
    assert.match(await page.locator('#failedCacheList').textContent(),kind==='html'?/服务器.*HTTP 500/:/网络请求失败/);
});

for(const status of [401,409,500]) test(`stream HTTP ${status} is checked before consuming content`,async t=>{
    const {page}=await setup(t,{'/api/ai/stream_enhance':route=>route.fulfill({status,contentType:'text/event-stream',body:'data: '+JSON.stringify({content:evil})+'\n\n'})});
    await page.locator('#testTitle').fill('title'); await page.locator('#testPlot').fill('plot');
    await page.evaluate(()=>App.AIStream.startStreamEnhance());
    assert.match(await page.locator('#streamOutput').textContent(),new RegExp(status===401?'认证':status===409?'冲突':'服务器'));
    assert.equal(await page.locator('#stream-card button.primary').isDisabled(),false);
    await safe(page,'#streamOutput');
});

test('offline counters treat malformed returned values as text',async t=>{
    const {page}=await setup(t,{'/api/offline/status':route=>route.fulfill({json:{total_folders:evil,cached_folders:title}})});
    await page.evaluate(()=>App.OfflinePreparser.refreshStatus());
    await safe(page,'#offlineScanStatus'); await safe(page,'#offlineCacheStatus');
    assert.ok((await page.locator('#offlineScanStatus').textContent()).includes(evil));
});

test('pagination buttons use listeners and keep normal navigation',async t=>{
    const {page}=await setup(t,{'/api/processed_cache':route=>route.fulfill({json:{items:[item],total_pages:2}})});
    await page.evaluate(()=>App.ProcessedCache.viewProcessedCache());
    await page.locator('#processedCachePagination button').first().waitFor();
    await safe(page,'#processedCachePagination');
    const wait=page.waitForRequest(req=>new URL(req.url()).pathname==='/api/processed_cache'&&new URL(req.url()).searchParams.get('page')==='2');
    await page.locator('#processedCachePagination button').nth(2).click();
    await wait;
    await page.waitForFunction(()=>document.getElementById('processedCachePagination').textContent.includes('第 2 / 2 页'));
});

test('full log popup contains literal text and no injected elements',async t=>{
    const {page}=await setup(t,{'/api/log':route=>route.fulfill({json:{log:title}})});
    const opened=page.waitForEvent('popup');
    await page.evaluate(()=>App.Task.viewFullLog());
    const popup=await opened;
    t.after(()=>popup.close());
    await popup.waitForLoadState();
    assert.equal(await popup.locator('pre').textContent(),title);
    assert.equal(await popup.locator('#injected').count(),0);
});

test('forbidden parent navigation still returns to allowed roots',async t=>{
    const {page}=await setup(t,{
        '/api/drives':route=>route.fulfill({json:[{path:'/allowed',name:'Allowed'}]}),
        '/api/browse':route=>route.fulfill({status:403,json:{error:'Forbidden path'}})
    });
    await page.evaluate(()=>{App.currentBrowsePath='/forbidden';});
    await page.evaluate(()=>App.Browse.goUp());
    assert.equal(await page.evaluate(()=>App.currentBrowsePath),'');
    assert.equal(await page.locator('#dirList li').textContent(),'📁 Allowed');
});

test('movie/TV with the same TMDB ID request distinct typed posters in both library views',async t=>{
    const movie={...item,tmdb_id:7,poster_url:'/media_poster/7'};
    const tv={...show,tmdb_id:7,poster_url:'/media_poster/7'};
    const {page}=await setup(t,{'/api/media/library':route=>route.fulfill({json:{movies:[movie],tv_shows:[tv]}})});
    await page.evaluate(()=>App.MediaManager.refreshLibrary());
    assert.equal(await page.locator('#movieGrid img').getAttribute('src'),'/media_poster/movie/7');
    assert.equal(await page.locator('#showGrid img').getAttribute('src'),'/media_poster/tv/7');
    await page.evaluate(()=>App.MediaLibrary.showTargetSelector(()=>{}));
    assert.equal(await page.locator('#mediaLibraryContainer .movie-item img').getAttribute('src'),'/media_poster/movie/7');
    assert.equal(await page.locator('#mediaLibraryContainer .show-poster').getAttribute('src'),'/media_poster/tv/7');
    assert.equal(await page.evaluate(()=>App.poster(App.mediaPosterUrl('tv',null)).hasAttribute('src')),false);
});
