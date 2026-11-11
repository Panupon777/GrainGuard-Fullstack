/* Presentation only. Hub/Node evidence and command authorization stay unchanged. */
(function(root){
 'use strict';
 const words={
  th:{overview:'ภาพรวมโรงสี',intro:'สถานะทุกเครื่อง ในจอเดียว',tracked:'เครื่องที่ติดตาม',all:'ทั้งหมด',attention:'ต้องตรวจ',offline:'ขาดข้อมูล',alarm:'Alarm การทำงาน',fault:'อุปกรณ์ขัดข้อง',faultAction:'ดูรหัสปัญหาและแจ้งช่าง',normal:'กำลังทำงาน',rest:'เครื่องพัก',learning:'เรียนรู้ / เฝ้าดู',unknown:'ยังยืนยันไม่ได้',empty:'ยังไม่ผูก Node',status:'สถานะโรงสี',system:'การเชื่อมต่อระบบ',issues:'จุดที่ต้องตรวจ',clear:'ไม่พบเหตุผิดปกติที่รายงาน',check:'ดูวิธีตรวจและรายละเอียด',guide:'คู่มือการใช้งาน',details:'รายละเอียด',care:'ดูแลตะแกรง',settings:'ตั้งค่าเครื่อง',signal:'สถานะสัญญาณ',add:'เพิ่มเครื่อง',fresh:'ข้อมูลล่าสุด',noMatch:'ไม่พบเครื่องตามตัวกรอง',noNodes:'ยังไม่มีเครื่องที่ติดตาม',addHint:'เพิ่มเครื่อง แล้วผูก Node ในตั้งค่าเครื่อง',discovered:'พบ Node ใหม่',manage:'จัดการ Node',loading:'กำลังรับข้อมูล',lost:'ติดต่อ Hub ไม่ได้',stale:'ข้อมูลจาก Hub ค้าง',retry:'ลองใหม่',lostHint:'ยังยืนยันสถานะเครื่องไม่ได้',sample:'ตัวอย่างในคอม · ไม่เชื่อมต่อ Pi',limit:'ตำแหน่งการ์ดคงที่ตาม Node',active:'ปัญหาที่ต้องตรวจสอบ',allMachines:'ทุกเครื่อง',noIssue:'ไม่พบปัญหาที่รายงานในเครื่องที่เลือก',steps:'ขั้นตอนตรวจเครื่อง',step1:'ตรวจชื่อเครื่องและหมายเลข Node',step2:'อ่านวิธีตรวจและรหัสปัญหา',step3:'ตรวจตามขั้นตอนของโรงสี',ack:'รับทราบ (ACK) คือยืนยันว่าเห็นเหตุแล้ว เหตุที่ยังเกิดอยู่จะยังแสดงต่อ',legend:'ความหมายของสถานะ',inspect:'ดูรายละเอียดเครื่อง',hub:'Hub ต้องตรวจ',hubHint:'ตรวจสถานะระบบและประวัติเหตุการณ์',legendAlarm:'ตรวจเครื่องตามขั้นตอนโรงสี',legendFault:'รวมข้อควรตรวจของระบบวัดและอุปกรณ์',legendOffline:'ตรวจไฟและเครือข่ายของ Node',legendLearning:'กำลังเรียนรู้หรือเฝ้าดูแบบเงียบ',legendRest:'เครื่องพัก แต่ Node ยังส่งข้อมูล',legendNormal:'เครื่องทำงานและ Node ส่งข้อมูล',showAll:'ดูทุกเครื่อง',codes:'รหัสที่รายงาน',quality:'ตัวเลขเป็นอัตราส่วน ไม่ใช่ dB หรือค่าการสั่นที่สอบเทียบ',history:'ประวัติเหตุการณ์',unknownCopy:'รอข้อมูลที่ยืนยันได้ก่อนประเมินสภาพเครื่อง'},
  en:{overview:'Mill overview',intro:'Every machine. One clear view.',tracked:'Tracked machines',all:'All',attention:'Needs attention',offline:'No data',alarm:'Operational alarm',fault:'Equipment fault',faultAction:'Review codes and contact a technician',normal:'Running',rest:'Idle',learning:'Learning / observing',unknown:'Unconfirmed',empty:'Unassigned',status:'Mill status',system:'System connection',issues:'Items to inspect',clear:'No reported abnormalities',check:'Open guidance and details',guide:'Operating guide',details:'Details',care:'Screen care',settings:'Machine settings',signal:'Signal status',add:'Add machine',fresh:'Last sample',noMatch:'No machines match this filter.',noNodes:'No tracked machines yet',addHint:'Add a machine, then assign its Node in settings.',discovered:'New Node discovered',manage:'Manage Nodes',loading:'Receiving data',lost:'Hub unreachable',stale:'Hub data is stale',retry:'Retry',lostHint:'Machine states cannot be confirmed.',sample:'Local sample · No Pi connection',limit:'Cards stay in Node order',active:'Issues to inspect',allMachines:'All machines',noIssue:'No reported issues for the selected machines.',steps:'Inspection steps',step1:'Match the machine and Node number.',step2:'Review the action and issue code.',step3:'Follow your mill’s inspection procedure.',ack:'Acknowledge (ACK) confirms you saw an event. An active event remains visible.',legend:'Status reference',inspect:'Open machine details',hub:'Hub needs inspection',hubHint:'Review system connection and event history.',legendAlarm:'Inspect the machine using mill procedures.',legendFault:'Includes equipment and sensor warnings.',legendOffline:'Check Node power and network.',legendLearning:'Baseline learning or quiet monitoring.',legendRest:'The machine is idle and the Node is online.',legendNormal:'The machine is running and the Node is online.',showAll:'Show all machines',codes:'Reported codes',quality:'Readings are ratios, not dB or calibrated vibration values.',history:'Event history',unknownCopy:'Wait for confirmed data before assessing the machine.'}
 };
 function context(c){const w={...words[c.lang==='en'?'en':'th']};if(c.mock)w.sample=c.lang==='en'?'MOCK · Simulated data, not live machine readings':'MOCK · ข้อมูลจำลอง ไม่ใช่ข้อมูลเครื่องจริง';return {...c,w};}
 // Regroup warnings in the UI without mutating the diagnostic evidence or its rank.
 function displayAssessment(assessment,lang){
  if(assessment.level!=='warning')return assessment;
  return {...assessment,level:'fault',title:words[lang==='en'?'en':'th'].fault};
 }
 function level(n,a){return a.level==='normal'&&n.status==='rest'?'rest':a.level;}
 function title(n,a,w){return a.level==='normal'&&n.status==='run'?w.normal:a.level==='normal'&&n.status==='rest'?w.rest:a.title;}
 function counts(c){
  const out={alarm:0,fault:0,offline:0,normal:0,rest:0,learning:0,unknown:0,empty:0};
  for(const n of c.nodes)out[level(n,displayAssessment(c.assess(n),c.lang))]++;
  return out;
 }
 const more={th:{slot:'ช่องว่าง',list:'ดูรายการ',recent:'เหตุการณ์ล่าสุด',viewAll:'ทั้งหมด',of:'จาก',machines:'เครื่อง',screen:'ตะแกรง',unack:'แจ้งเตือน · ยังไม่รับทราบ',acked:'รับทราบแล้ว · ยังเกิดอยู่',short:{alarm:'Alarm',fault:'ขัดข้อง',offline:'ขาดข้อมูล',learning:'เรียนรู้',rest:'พักเครื่อง',normal:'ทำงาน'}},
  en:{slot:'Empty slot',list:'View list',recent:'Recent events',viewAll:'All',of:'of',machines:'machines',screen:'Screen',unack:'Alarm · not acknowledged',acked:'Acknowledged · still active',short:{alarm:'Alarm',offline:'No data',learning:'Learning',rest:'Idle',normal:'Running'}}};
 const pad=n=>String(n).padStart(2,'0');
 // One card per tracked machine. Both sensor columns keep the same rows (light + name, number, graph area).
 function card(n,c){
  const {w,esc:e,icon}=c,m=more[c.lang==='en'?'en':'th'],a=displayAssessment(c.assess(n),c.lang),l=level(n,a),label=title(n,a,w);
  const unack=l==='alarm'&&!n.ack,acked=l==='alarm'&&!!n.ack,wear=c.wearOf?c.wearOf(n):null;
  const ack=unack&&c.isAdmin?`<button type="button" class="gg-ack" data-action="ack" data-id="${n.id}">${e(c.ackLabel||'ACK')}</button>`:'';
  const care=`<button type="button" class="gg-ibtn" data-action="node-maintenance" data-id="${n.id}" title="${e(w.care)}" aria-label="${e(w.care)}">${icon('screen')}</button>`;
  const set=c.isAdmin?`<button type="button" class="gg-ibtn" data-action="machine-settings" data-id="${n.id}" title="${e(w.settings)}" aria-label="${e(w.settings)}">${icon('settings')}</button>`:'';
  return `<article class="gg-tile${unack?' unack':acked?' acked':''}" data-level="${l}" data-node="${n.id}" data-ack="${!!n.ack}" aria-label="Node ${n.id} · ${e(c.name(n))} · ${e(label)}">
   <header class="gg-band"><span class="gg-bi">${icon(c.statusIcon(l))}</span>${a.needsAttention?`<button type="button" class="gg-blink" data-action="inspect" data-id="${n.id}" title="${e(a.summary)}">${e(unack?m.unack:acked?m.acked:label)}</button>`:`<span>${e(unack?m.unack:acked?m.acked:label)}</span>`}<span class="gg-band-act">${ack}${care}${set}</span></header>
   <div class="gg-body"><button type="button" class="gg-id" data-action="detail" data-id="${n.id}"><span class="gg-nno">${pad(n.id)}</span><span class="gg-nm">${e(c.name(n))}</span><span class="gg-fresh">${e(c.age(n))}</span></button>
   <div class="gg-reads">${c.readings(n,'a')}${c.readings(n,'b')}</div>
   <div class="gg-wear${wear>=90?' hi':''}"><span>${m.screen}</span><span class="gg-bar"><i style="width:${wear==null?0:Math.min(100,Math.max(0,wear))}%"></i></span><span class="num">${wear==null?'—':Math.round(wear)+'%'}</span></div></div>
  </article>`;
 }
 // Always the same 3 × 2 slots. "All" fills unused slots with a quiet add-machine slot; filters fill from the top-left.
 function cards(input){
  const c=context(input),m=more[c.lang==='en'?'en':'th'];let nodes=[...c.nodes].sort((a,b)=>a.id-b.id);
  if(c.filter==='attention')nodes=nodes.filter(n=>c.assess(n).needsAttention);
  if(c.filter==='offline')nodes=nodes.filter(n=>['offline','unknown'].includes(n.status));
  if(c.filter==='all'&&c.offlinePolicy==='group')nodes=nodes.filter(n=>n.status!=='offline');
  // New Nodes (discovery = "temporary") take free slots, each with its own Register button.
  const pend=[].concat(c.pendingCards()||[]).filter(Boolean);
  if(!c.nodes.length&&!pend.length)return `<div class="gg-ghost" style="grid-column:1/-1;grid-row:1/-1"><span>${c.icon('grid')}${c.w.noNodes}<small>${c.w.addHint}</small></span></div>`;
  const out=nodes.map(n=>card(n,c));
  out.push(...pend.slice(0,Math.max(0,6-out.length)));
  if(!out.length)return `<div class="gg-ghost"><span>${c.icon('check')}<small>${c.w.noMatch}</small></span></div>`;
  // Unused slots stay plain (no text, no button) so the 3 × 2 grid keeps its shape; adding a machine is the boxed button in the header.
  if(c.filter==='all')while(out.length<6)out.push(`<div class="gg-slot-empty" aria-hidden="true"></div>`);
  return out.join('');
 }
 function overview(input){
  const c=context(input),{w,esc:e,icon}=c,m=more[c.lang==='en'?'en':'th'],tot=counts(c),nodeIssues=c.nodes.filter(n=>c.assess(n).needsAttention).length,hubCodes=c.connected?(c.snapshot?.hub?.codes||[]):[],issues=nodeIssues+(hubCodes.length?1:0);
  const nAttention=c.nodes.filter(n=>c.assess(n).needsAttention).length,nOffline=c.nodes.filter(n=>['offline','unknown'].includes(n.status)).length;
  const filters=[['all','all',c.nodes.length],['attention','attention',nAttention],['offline','offline',nOffline]];
  const keys=['alarm','fault','offline','learning','rest','normal'];
  return `<div class="gg-ov"><section class="gg-ov-left" aria-label="${w.tracked}">
   <div class="gg-ov-head"><h2>${w.tracked} <span class="gg-muted num">${c.nodes.length}</span></h2><div class="gg-seg" role="group" aria-label="${w.tracked}">${filters.map(([v,k,num])=>`<button type="button" data-action="filter" data-value="${v}" aria-pressed="${c.filter===v}">${w[k]}<span class="gg-n">${num}</span></button>`).join('')}</div>${c.isAdmin?`<button type="button" class="gg-btn" data-action="add-machine">${icon('plus')}${w.add}</button>`:''}</div>
   <div id="machine-cards" class="gg-tiles" data-count="${c.nodes.length}">${cards(c)}</div><div id="offline-group">${c.offlineGroup()}</div></section>
   <aside class="gg-rail" aria-label="${w.status}">
    <section class="gg-card"><div class="gg-rhd"><span class="gg-att-n${issues?'':' zero'}">${c.connected?issues:'—'}</span><span class="gg-att-t">${!c.connected?w.unknown:issues?w.issues:w.clear}<small>${m.of} ${c.nodes.length} ${m.machines}</small></span><button type="button" class="gg-lnk" data-action="view-attention">${m.list}${icon('chevron')}</button></div>
     <div class="gg-cgrid">${keys.map(k=>`<div data-level="${k}" class="${tot[k]?'':'zero'}"><span>${(m.short[k]||w[k])}</span><strong>${tot[k]}</strong></div>`).join('')}</div>
     ${hubCodes.length?`<button type="button" class="gg-lnk" style="margin-top:12px" data-action="view-attention">${icon('alert')}${w.hub} · ${hubCodes.map(e).join(' · ')}</button>`:''}</section>
    <section class="gg-card"><div class="gg-rhd"><h3 class="gg-h3">${w.system}</h3>${c.fixture?`<span class="gg-mode" style="margin-left:auto">MOCK</span>`:''}</div>${c.sysGrid?c.sysGrid():''}${!c.connected&&c.started?`<div class="gg-rhd" style="margin-top:12px"><span class="gg-muted">${w.lostHint}</span><button type="button" class="gg-btn gg-sm" style="margin-left:auto" data-action="retry">${icon('link')}${w.retry}</button></div>`:''}</section>
    <section class="gg-card gg-feedcard"><div class="gg-rhd"><h3 class="gg-h3">${m.recent}</h3><button type="button" class="gg-lnk" data-action="nav" data-page="history">${m.viewAll}${icon('chevron')}</button></div><ol class="gg-feed">${c.feed?c.feed():''}</ol></section>
    ${c.pendingCount?`<button type="button" class="gg-btn" data-action="nav" data-page="settings" data-tab="pending">${icon('plus')}${w.discovered} (${c.pendingCount})</button>`:''}
   </aside></div>`;
 }
 // Alarms page (approved mock v15): equal cards for each active problem, then three equal help boxes.
 const gwords={th:{title:'แจ้งเตือนที่ยังเกิดอยู่',order:'เรียงตามความสำคัญ',since:'เริ่มเมื่อ',dur:'นานแล้ว',ackNo:'ยังไม่รับทราบ',ackYes:'รับทราบแล้ว',ackNone:'ไม่ต้องรับทราบ',view:'ดูเครื่อง',lights:'ความหมายของไฟสถานะ',green:'เขียว',yellow:'เหลือง',red:'แดง',grey:'เทา',greenT:'ทำงานปกติ ได้รับข้อมูล',yellowT:'อุปกรณ์ขัดข้อง ดูรหัสปัญหา',redT:'Alarm ต้องตรวจตอนนี้',greyT:'ปิดอยู่ หรือขาดข้อมูล',contact:'ติดต่อผู้ดูแล',contactT:'แจ้งชื่อเครื่อง, MAC, รหัสปัญหา และเวลาที่พบให้ผู้ดูแลโรงสี',min:'นาที',none:'ไม่มีรายการอื่น'},
  en:{title:'Active alarms',order:'Sorted by priority',since:'Started',dur:'Duration',ackNo:'Not acknowledged',ackYes:'Acknowledged',ackNone:'No acknowledgement needed',view:'View machine',lights:'What the lights mean',green:'Green',yellow:'Yellow',red:'Red',grey:'Grey',greenT:'Running, data received',yellowT:'Check needed, equipment fault',redT:'Alarm, inspect now',greyT:'Off or no data',contact:'Contact support',contactT:'Give the mill administrator the machine name, MAC, error code and time.',min:'min',none:'No other items'}};
 function guideIssue(c,node,assessment){
  const {w,esc:e,icon}=c,g=gwords[c.lang==='en'?'en':'th'];
  const a=displayAssessment(assessment,c.lang);
  const action=a.level==='fault'?(a.issues.length?w.faultAction:a.action):a.action;
  const diagnosis=a.level==='fault'&&a.issues.length?'':a.summary;
  const alarm=a.level==='alarm',unack=alarm&&!node.ack;
  const now=Number(c.snapshot?.now)||Date.now()/1000,since=Number(node.since)||0;
  const ack=alarm?(node.ack?`${icon('check')}${g.ackYes}`:g.ackNo):g.ackNone;
  return `<article class="guide-issue" data-level="${a.level}">
    <header class="gg-ac-band" data-ack="${unack?'no':'yes'}"><span class="gg-bi">${icon(c.statusIcon(a.level))}</span><span>${e(a.title)}</span><span class="gg-ac-ack">${ack}</span></header>
    <div class="gg-ac-body">
     <div class="guide-identity gg-id"><span class="gg-nno guide-node">${String(node.id).padStart(2,'0')}</span><h3 class="gg-nm">${e(c.name(node))}</h3></div>
     <div class="gg-reads">${c.readings?c.readings(node,'a')+c.readings(node,'b'):''}</div>
     <p class="gg-ac-what">${icon('help')}${e(action)}</p>
     <div class="gg-ac-time"><div><small>${g.since}</small><b class="num">${since&&c.clock?c.clock(since*1000):'—'}</b></div><div><small>${g.dur}</small><b class="num">${since?Math.max(0,Math.round((now-since)/60))+' '+g.min:'—'}</b></div></div>
     <div class="gg-ac-act">${unack&&c.isAdmin?`<button type="button" class="gg-btn gg-pri" data-action="ack" data-id="${node.id}">${icon('check')}${e(c.ackLabel||'ACK')}</button>`:''}<button type="button" class="gg-btn" data-action="detail" data-id="${node.id}">${g.view}</button></div>
    </div>
    <details class="guide-disclosure gg-disc" data-guide-disclosure="node-${node.id}">
      <summary>${w.diagnostics}${a.issues.length?` <span class="guide-code-count">${a.issues.length}</span>`:''}</summary>
      <div class="guide-disclosure-body">
        ${node.mac?`<p class="guide-mac">MAC ${e(node.mac)}</p>`:''}
        ${diagnosis?`<p>${e(diagnosis)}</p>`:''}
        ${a.issues.length?`<ul class="guide-codes">${a.issues.map(i=>`<li><code>${e(i.code)}</code><div><strong>${e(i.title)}</strong>${i.action&&i.action!==action?`<p>${e(i.action)}</p>`:''}</div></li>`).join('')}</ul>`:''}
        ${c.isAdmin!==false?`<button type="button" class="gg-btn gg-sm" data-action="machine-settings" data-id="${node.id}">${icon('settings')}${w.settings}</button>`:''}
      </div>
    </details>
   </article>`;
 }
 function guideReference(c,issues){
  const {w,icon,esc:e}=c,g=gwords[c.lang==='en'?'en':'th'];
  const lights=[['ok','green','greenT'],['warn','yellow','yellowT'],['bad','red','redT'],['off','grey','greyT']];
  const report=issues.map(({node,assessment})=>`#${node.id} · ${e(node.mac||'—')} · ${e((node.codes&&node.codes[0])||displayAssessment(assessment,c.lang).title)}${node.since&&c.clock?' · '+c.clock(node.since*1000):''}`).join('<br>')||'—';
  return `<div class="gg-hgrid">
    <section class="gg-card gg-hbox guide-reference" data-guide-disclosure="legend" aria-label="${w.legend}"><h2 class="gg-h3">${g.lights}</h2><div class="gg-leds">${lights.map(([cls,name,txt])=>`<div><i class="gg-led ${cls}"></i><b>${g[name]}</b><span>${g[txt]}</span></div>`).join('')}</div><p class="gg-hnote">${w.ack}</p></section>
    <section class="gg-card gg-hbox guide-quick-steps"><h2 class="gg-h3">${w.steps}</h2><ol class="gg-steps"><li><b>1</b>${w.step1}</li><li><b>2</b>${w.step2}</li><li><b>3</b>${w.step3}</li></ol><p class="gg-hnote">${w.quality}</p></section>
    <section class="gg-card gg-hbox"><h2 class="gg-h3">${g.contact}</h2><p class="gg-hnote">${g.contactT}</p><div class="gg-copybox num" tabindex="0">${report}</div></section>
   </div>`;
 }
 function guide(input){
  const c=context(input),{w,esc:e,icon}=c,g=gwords[c.lang==='en'?'en':'th'];
  w.diagnostics=c.lang==='en'?'Diagnostics':'รหัสและรายละเอียด';
  const items=c.attentionItems().filter(({node})=>!c.selected||node.id===c.selected);
  const hubCodes=c.connected?(c.snapshot?.hub?.codes||[]):[];
  const visibleIssues=c.connected?items.length+(hubCodes.length?1:0):0;
  let cards;
  if(!c.connected){
   const connectionLabel=w[c.connectionState==='stale'?'stale':c.started?'lost':'loading'];
   cards=`<div class="gg-ghost gg-wide" role="status"><span>${icon('unlink')}${connectionLabel}${c.started?`<button type="button" class="gg-btn" data-action="retry">${icon('link')}${w.retry}</button>`:''}</span></div>`;
  }else if(!visibleIssues){
   cards=`<div class="gg-ghost gg-wide"><span>${icon('check')}${w.noIssue}</span></div>`;
  }else{
   const list=items.map(({node,assessment})=>guideIssue(c,node,assessment));
   if(hubCodes.length)list.push(`<article class="guide-issue" data-level="fault">
    <header class="gg-ac-band"><span class="gg-bi">${icon(c.statusIcon('fault'))}</span><span>${w.fault}</span></header>
    <div class="gg-ac-body"><div class="guide-identity gg-id"><h3 class="gg-nm">${w.hub}</h3></div><p class="gg-ac-what">${icon('help')}${hubCodes.map(e).join(' · ')}</p><div class="gg-ac-act"><button type="button" class="gg-btn" data-action="nav" data-page="history">${icon('history')}${w.history}</button></div></div>
   </article>`);
   while(list.length%3)list.push(`<div class="gg-ghost"><span><small>${g.none}</small></span></div>`);
   cards=list.join('');
  }
  return `<div class="gg-pgh"><h1>${g.title}</h1><span class="num gg-muted">${visibleIssues}</span><span class="gg-muted gg-right">${g.order}</span>${c.selected?`<button type="button" class="gg-btn" data-action="guide-all">${icon('grid')}${w.showAll}</button>`:''}</div>
   <div class="gg-agrid guide-layout">${cards}</div>
   ${guideReference(c,c.connected?items:[])}`;
 }
 const api={overview,cards,guide,counts,displayAssessment};root.GGMonitorView=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
