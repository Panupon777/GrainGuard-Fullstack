'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const C=require('./site-context.js');
const live={authenticated:true,site:{id:'pumpkintec',name:'PumpkinTec',mode:'live',machine_count:1}};
const mock={authenticated:true,site:{id:'uengliangseng',name:'โรงสีไฟอึ้งเลี่ยงเส็ง',mode:'mock',machine_count:6}};

test('server-issued live site name replaces generic Pilot labels in either language',()=>{
  for(const language of ['th','en']){const c=C.context(live,language);assert.equal(c.name,'PumpkinTec');assert.equal(c.id,'pumpkintec');assert.equal(c.mock,false);assert.equal(c.modeLabel,'');}
});
test('mock site preserves its exact proper name while translating the MOCK disclosure',()=>{
  assert.equal(C.context(mock,'th').name,'โรงสีไฟอึ้งเลี่ยงเส็ง');
  assert.equal(C.context(mock,'en').name,'โรงสีไฟอึ้งเลี่ยงเส็ง');
  assert.equal(C.context(mock,'th').modeLabel,'MOCK · ข้อมูลจำลอง');
  assert.equal(C.context(mock,'en').modeLabel,'MOCK · Simulated data');
});
test('unauthenticated or absent site never adopts a supplied client identity',()=>{
  assert.equal(C.context({...mock,authenticated:false}).name,'GrainGuard');
  assert.equal(C.context(null).name,'GrainGuard');assert.equal(C.context({authenticated:true,site:null}).mock,false);
});
test('mock history, graph, record and footer descriptions explicitly disclose simulation',()=>{
  for(const key of ['historyHint','trend','trendHint','recordDesc','recordTitle','recordConfirm']){
    assert.match(C.label(mock,key,'en'),/mock|simulat/i);assert.match(C.label(mock,key,'th'),/จำลอง/);
  }
  assert.match(C.context(mock,'en').footerNote,/Not live/);assert.match(C.context(mock,'th').footerNote,/ไม่ใช่ข้อมูลเครื่องจริง/);
  assert.equal(C.label(live,'trend','en'),null);
});
test('persistent MOCK badge and footer escape server text and appear outside page-specific content',()=>{
  const source=fs.readFileSync(path.join(__dirname,'live-ui.js'),'utf8');
  const start=source.indexOf('function siteModeBadge()'),end=source.indexOf('\nfunction soundButton',start);
  assert.ok(start>=0&&end>start);
  const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const unsafe={...C.context(mock,'en'),name:'<script>bad</script>',modeLabel:'MOCK <bad>'};
  const context=vm.createContext({siteContext:()=>unsafe,esc,t:key=>key==='site'?unsafe.name:unsafe.footerNote,lastFetch:0});
  vm.runInContext(source.slice(start,end),context);
  assert.match(vm.runInContext('siteModeBadge()',context),/MOCK &lt;bad&gt;/);
  const footer=vm.runInContext('footerMarkup()',context);assert.doesNotMatch(footer,/<script>|pumpkintec/i);assert.match(footer,/&lt;script&gt;/);
  // The badge lives in the persistent header (shellHead), never inside page-specific content.
  assert.match(source,/function shellHead\(\)\{[\s\S]*?<div class="gg-head-l">[^\n]*\$\{siteModeBadge\(\)\}/);
});
test('desktop app icon embeds the exact supplied product PNG with a light backing tile',()=>{
  const svg=fs.readFileSync(path.join(__dirname,'assets/brand/grainguard-app.svg'),'utf8');
  const embedded=Buffer.from(svg.match(/data:image\/png;base64,([A-Za-z0-9+/=]+)/)[1],'base64');
  assert.deepEqual(embedded,fs.readFileSync(path.join(__dirname,'assets/brand/grainguard-product.png')));
  assert.match(svg,/<rect[^>]*rx="92"[^>]*fill="#ffffff"/);
});
test('tiny runtime brand derivatives are bounded while approved machine Login illustration is retained',()=>{
  for(const file of ['grainguard-product-96.webp','pumpkintec-team-48.webp'])assert.ok(fs.statSync(path.join(__dirname,'assets/brand',file)).size<10000);
  for(const file of ['local.html','online.html']){
    const html=fs.readFileSync(path.join(__dirname,'login',file),'utf8');
    assert.match(html,/class="brand-panel"><img src="assets\/grainguard-logo.webp"/);
    assert.match(html,/class="product-mark"/);assert.match(html,/By PumpkinTec/);assert.doesNotMatch(html,/pumpkintec-team/i);
  }
});
