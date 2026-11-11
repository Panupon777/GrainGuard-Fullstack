const test=require('node:test');
const assert=require('node:assert/strict');
const M=require('./model.js');
const rawNode=(n,extra={})=>({n,mac:`aabbccddee${String(n).padStart(2,'0')}`,label:`Mill ${n}`,cls:'ok',state:'RUN',last_state:'RUN',last_seen_s:1,ratio:1.02,ratio_b:.98,chb:true,spark:[0,null,1.02],...extra});
const snapshot=()=>({now:1000,nodes:[rawNode(1),{n:2,mac:null,cls:'empty',state:'EMPTY'},{n:3,mac:null,cls:'empty',state:'EMPTY'}],new:[]});
test('default tracks only one slot while preserving the Hub payload',()=>{
 const snap=snapshot(),before=JSON.stringify(snap);const nodes=M.normalizeSnapshot(snap);
 assert.equal(nodes.length,1);assert.equal(nodes[0].id,1);assert.equal(nodes[0].raw,snap.nodes[0]);
 assert.equal(nodes[0].status,'run');assert.equal(JSON.stringify(snap),before);
});
test('Admin-selected slots determine cards without fabricated registered Nodes',()=>{
 const nodes=M.normalizeSnapshot(snapshot(),[1,2,2,-1,'3']);
 assert.equal(nodes.length,2);assert.equal(nodes[1].status,'empty');assert.equal(nodes[1].mac,null);
 assert.deepEqual(M.counts(nodes),{total:2,registered:1,run:1,rest:0,alarm:0,warn:0,attention:0,offline:0,empty:1,learn:0,unknown:0});
 assert.equal(M.counts({nodes}).total,2);
});
test('real zero ratios, voltage, and temperature are preserved',()=>{
 const nodes=M.normalizeSnapshot({nodes:[rawNode(1,{cls:'warn',state:'FAULT',ratio:0,ratio_b:0,vin:0,tc:0})]});
 assert.equal(nodes[0].a,0);assert.equal(nodes[0].b,0);assert.equal(nodes[0].vin,0);assert.equal(nodes[0].tc,0);
 assert.equal(nodes[0].status,'warn');assert.equal(nodes[0].dataAvailable,true);
});
test('missing data and disabled channel B do not appear as numeric zero',()=>{
 const n=M.normalizeSnapshot({nodes:[rawNode(1,{ratio:undefined,ratio_b:2,chb:false})]})[0];
 assert.equal(n.a,null);assert.equal(n.b,null);assert.equal(n.chb,false);assert.equal(n.dataAvailable,false);
});
test('Hub-classified offline retains identity but suppresses cached readings',()=>{
 const raw=rawNode(1,{cls:'offline',state:'OFFLINE',last_seen_s:20});
 const n=M.normalizeSnapshot({nodes:[raw]})[0];
 assert.equal(n.id,1);assert.equal(n.mac,raw.mac);assert.equal(n.status,'offline');
 assert.equal(n.a,null);assert.equal(n.b,null);assert.deepEqual(n.spark,[]);assert.equal(n.raw.ratio,1.02);
});
test('lost Hub is unknown, not evidence that an individual Node is offline',()=>{
 const nodes=M.normalizeSnapshot(snapshot(),[1],Date.now()-2000,false);
 assert.equal(nodes[0].status,'unknown');assert.equal(nodes[0].reason,'hub_lost');
 assert.equal(nodes[0].a,null);assert.equal(nodes[0].b,null);assert.equal(M.counts(nodes).offline,0);assert.equal(M.counts(nodes).unknown,1);
});
test('data age increments from browser receipt without inventing a Hub status',()=>{
 const n=M.normalizeSnapshot(snapshot(),[1],Date.now()-3500)[0];
 assert.ok(n.age>=4.5&&n.age<5);assert.equal(n.status,'run');
 const missing=M.normalizeSnapshot({nodes:[rawNode(1,{last_seen_s:null})]})[0];assert.equal(missing.age,null);
});
test('REST, CAL and SHADOW match the original Hub UI behavior',()=>{
 assert.equal(M.normalizeSnapshot({nodes:[rawNode(1,{last_state:'REST'})]})[0].status,'rest');
 assert.equal(M.normalizeSnapshot({nodes:[rawNode(1,{cls:'cal',state:'CAL'})]})[0].status,'learn');
 assert.equal(M.normalizeSnapshot({nodes:[rawNode(1,{cls:'shadow',alarm_shadow:true})]})[0].status,'learn');
 assert.equal(M.normalizeSnapshot({nodes:[rawNode(1,{last_state:'?',state:'?'})]})[0].status,'unknown');
});
test('ack from telemetry does not resolve an active alarm',()=>{
 const n=M.normalizeSnapshot({nodes:[rawNode(1,{cls:'alarm',ack:1,alarm_active:true})]})[0];
 assert.equal(n.ack,true);assert.equal(n.status,'alarm');assert.equal(n.alarm_active,true);
});
test('history uses actual timestamps, preserves zero/null gaps and sorts buckets',()=>{
 const payload={points:[{t:20,ratio:0,ratio_max:0,ratio_b:null,cnt:2},{t:10,ratio:null,ratio_b:1.1,ratio_b_max:1.2},{t:'invalid',ratio:99}]};
 const before=JSON.stringify(payload);const points=M.normalizeHistory(payload);
 assert.deepEqual(points.map(p=>[p.ts,p.a,p.b,p.aMax,p.bMax]),[[10,null,1.1,null,1.2],[20,0,null,0,null]]);
 assert.equal(points[1].count,2);assert.equal(JSON.stringify(payload),before);assert.deepEqual(M.normalizeHistory(null),[]);
});
test('search can find a real MAC and grouped offline Nodes remain counted',()=>{
 const nodes=M.normalizeSnapshot({nodes:[rawNode(1),rawNode(2,{cls:'offline'})]},[1,2]);
 assert.equal(M.visible(nodes,'aabbccddee01').length,1);assert.equal(M.visible({nodes,policy:{offline:'group'}}).length,1);
 assert.equal(M.counts(nodes).offline,1);
});
test('moved Node follows its new machine number and vacated slot has no phantom identity or readings',()=>{
 const liveMac='020000000002',oldMac='020000000001';
 const before={nodes:[rawNode(1,{mac:oldMac,label:'Old offline machine',cls:'offline',state:'OFFLINE'}),rawNode(2,{mac:liveMac,label:'Receiver at machine 2'})]};
 const previous=M.normalizeSnapshot(before,[2]);assert.equal(previous[0].id,2);assert.equal(previous[0].mac,liveMac);
 const after={nodes:[rawNode(1,{mac:liveMac,label:'Receiver at machine 1'}),{n:2,mac:null,label:'ขัด 2',cls:'empty',state:'EMPTY'}]};
 const tracked=M.normalizeSnapshot(after,[1]);assert.equal(tracked.length,1);assert.equal(tracked[0].id,1);assert.equal(tracked[0].n,1);
 assert.equal(tracked[0].mac,liveMac);assert.equal(tracked[0].name,'Receiver at machine 1');assert.notEqual(tracked[0].mac,oldMac);
 const vacated=M.normalizeSnapshot(after,[2])[0];assert.equal(vacated.status,'empty');assert.equal(vacated.mac,null);
 assert.equal(vacated.a,null);assert.equal(vacated.b,null);assert.equal(vacated.fw,null);assert.deepEqual(vacated.codes,[]);
});
test('an explicit empty tracked list stays empty after delete rather than restoring initial machine one',()=>{
 const nodes=M.normalizeSnapshot(snapshot(),[]);assert.deepEqual(nodes,[]);assert.equal(M.counts(nodes).total,0);
 assert.equal(M.counts(nodes).registered,0);assert.deepEqual(M.visible(nodes),[]);
 assert.equal(M.normalizeSnapshot(snapshot()).length,1); // Only omitted configuration uses the initial default.
});
test('Piezo sparkline and alarm channel come only from the Hub and only when valid',()=>{
 const n=M.normalizeSnapshot({nodes:[rawNode(1,{spark_b:[1.1,null,1.4],alarm_active:true,alarm_ch:'B'})]})[0];
 assert.deepEqual(n.sparkB,[1.1,null,1.4]);assert.equal(n.alarmCh,'B');
 const off=M.normalizeSnapshot({nodes:[rawNode(1,{chb:false,spark_b:[1.1],alarm_active:false,alarm_ch:'A'})]})[0];
 assert.deepEqual(off.sparkB,[]);assert.equal(off.alarmCh,null);
 const bad=M.normalizeSnapshot({nodes:[rawNode(1,{alarm_active:true,alarm_ch:'X'})]})[0];assert.equal(bad.alarmCh,null);
 const lost=M.normalizeSnapshot({nodes:[rawNode(1,{spark_b:[1.2]})]},[1],Date.now(),false)[0];assert.deepEqual(lost.sparkB,[]);
});
