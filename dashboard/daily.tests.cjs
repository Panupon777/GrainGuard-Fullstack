const test=require('node:test');
const assert=require('node:assert/strict');
const D=require('./daily-view.js');
const daily={today:'2026-11-11',days:[
 {date:'2026-11-10',rows:[{node:1,run_min:120,rest_min:0,alarm_count:0,alarm_min:0,offline_min:0,uptime_pct:100,health_incidents:0}]},
 {date:'2026-11-11',rows:[{node:1,run_min:90,rest_min:30,alarm_count:2,alarm_min:5,offline_min:0,uptime_pct:99,health_incidents:1},{node:2,run_min:0,rest_min:0,offline_min:0,alarm_count:0,uptime_pct:0,health_incidents:0}]}]};
test('daily rows, run-hour series and mill totals use only Hub rows',()=>{
 const rows=D.dayRows(daily,'2026-11-11');
 assert.equal(rows.get(1).alarm_count,2);assert.deepEqual(D.series(daily,1),[2,1.5]);assert.deepEqual(D.series(daily,3),[null,null]);
 assert.deepEqual(D.totals(rows,[1,2,3]),{run_h:1.5,alarm_count:2,alarm_min:5,health_incidents:1});
 assert.equal(D.level(rows.get(1)),'bad');assert.equal(D.level(rows.get(2)),'off');assert.equal(D.level(undefined),'off');
});
test('error codes are counted from history without double-counting active ones',()=>{
 const errors={history:[{code:'E301',n:6,label:'Mill 6',th:'offline',open:true},{code:'E301',n:6,label:'Mill 6',open:false},{code:'E199',n:5,label:'Mill 5'}],
  active:[{code:'E301',n:6,label:'Mill 6'},{code:'E104',n:2,label:'Mill 2',th:'noise'}]};
 const c=D.codeCounts(errors);
 assert.deepEqual(c.map(x=>[x.code,x.count]),[['E301',2],['E104',1],['E199',1]]);
 assert.deepEqual(c[0].where,['Mill 6']);
});
test('page renders a full 3 × 2 grid and escapes machine names',()=>{
 const html=D.render({daily,errors:{history:[],active:[]},nodes:[{id:1,name:'<b>Mill</b>'}],lang:'en'});
 assert.equal((html.match(/class="gg-dcard"/g)||[]).length,1);assert.equal((html.match(/class="gg-ghost"/g)||[]).length,5);
 assert.match(html,/&lt;b&gt;Mill/);assert.doesNotMatch(html,/<b>Mill<\/b>/);assert.match(html,/Today · so far/);
 assert.match(D.render({daily:null,lang:'en',failed:true}),/Could not load the Hub summary/);
});
