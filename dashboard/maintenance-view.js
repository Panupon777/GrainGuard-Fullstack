/* Screen-care views for machine-slot history. No estimated service life or hardware writes. */
(function (root) {
  'use strict';
  const array = value => Array.isArray(value) ? value : [];
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const words = {
    th: {title:'ดูแลตะแกรง',intro:'เลือก Node เพื่อดูและบันทึกการดูแลตะแกรงของเครื่องนั้น',choose:'เลือกเครื่อง / Node',node:'Node',machine:'เครื่องขัด',current:'ตะแกรงรอบปัจจุบัน',since:'วันที่เริ่มรอบ',none:'ยังไม่มีบันทึกวันที่เปลี่ยน',implicit:'Hub กำหนดจุดเริ่มต้นจากข้อมูลระบบ ยังไม่ใช่บันทึกการเปลี่ยนที่ยืนยัน',records:'ประวัติการเปลี่ยนตะแกรง',count:'รายการ',date:'วันที่เปลี่ยน',reason:'เหตุผล',note:'หมายเหตุ',record:'บันทึกเปลี่ยนตะแกรง',detail:'ดูข้อมูล Node',scope:'ประวัตินี้ผูกกับช่องเครื่อง การย้ายหรือเปลี่ยน Node ไม่ได้ย้ายประวัติไปกับ MAC',mac:'MAC ที่ผูกอยู่ปัจจุบัน',unassigned:'ยังไม่ได้ผูก Node',noEntries:'ยังไม่มีประวัติการเปลี่ยนตะแกรงของเครื่องนี้',unavailable:'ยังโหลดประวัติการดูแลไม่ได้',noMachines:'ยังไม่มีเครื่องที่ติดตาม',emptyNote:'เพิ่มเครื่องจากตั้งค่าเพื่อเริ่มดูประวัติ',noEstimate:'ไม่มีการคาดการณ์วันหมดอายุจากข้อมูลที่ยังไม่ยืนยัน',broke:'ตะแกรงชำรุด',scheduled:'เปลี่ยนตามแผน',other:'อื่น ๆ',last:'เปลี่ยนล่าสุด',all:'ดูประวัติการดูแล',load:'เปิดหน้าดูแลตะแกรงเพื่อโหลดประวัติ',currentNode:'Node ปัจจุบัน',notKnown:'ไม่มีข้อมูล'},
    en: {title:'Screen care',intro:'Choose a Node to view and record care for its machine.',choose:'Machine / Node',node:'Node',machine:'Whitener',current:'Current screen cycle',since:'Cycle start date',none:'No replacement date recorded',implicit:'Hub inferred this start from system data; it is not a confirmed replacement record.',records:'Screen replacement history',count:'records',date:'Replacement date',reason:'Reason',note:'Note',record:'Record replacement',detail:'View Node details',scope:'Records belong to the machine slot. Moving or replacing a Node does not transfer this history with its MAC.',mac:'Currently assigned MAC',unassigned:'No Node assigned',noEntries:'No screen replacements recorded for this machine.',unavailable:'Maintenance history could not be loaded.',noMachines:'No tracked machines',emptyNote:'Add a machine in Settings to view its records.',noEstimate:'No remaining-life estimate is shown without verified data.',broke:'Screen broke',scheduled:'Scheduled replacement',other:'Other',last:'Last replacement',all:'View screen-care history',load:'Open Screen care to load its records.',currentNode:'Current Node',notKnown:'No data'}
  };
  const idOf = node => Number(node && (node.id ?? node.n));
  const nameOf = (node,t) => node && (node.name || node.label) || `${t.machine} ${idOf(node)}`;
  function model(life, node) {
    const id = idOf(node);
    const machine = array(life && life.machines).find(item => Number(item.n) === id) || null;
    const entries = array(machine && machine.entries).slice().sort((a,b) => (Number(b.ts)||0)-(Number(a.ts)||0));
    return {id, machine, entries, latest:entries[0] || null, loaded:!!life};
  }
  function dateLabel(ts, fallback, lang) {
    if (typeof ts === 'number' && Number.isFinite(ts) && ts > 0) {
      return new Date(ts * 1000).toLocaleDateString(lang === 'th' ? 'th-TH' : 'en-GB', {year:'numeric',month:'short',day:'numeric',timeZone:'Asia/Bangkok'});
    }
    return typeof fallback === 'string' && fallback.trim() ? fallback : '—';
  }
  const button = (label,action,id,cls='') => `<button type="button" class="button ${cls}" data-action="${action}" data-id="${id}">${esc(label)}</button>`;
  function summary({life,node,lang='th'}) {
    if (!node) return '';
    const t=words[lang] || words.th, m=model(life,node);
    const last = m.latest ? dateLabel(m.latest.ts,m.latest.date,lang) : '—';
    return `<section class="panel node-maintenance-summary"><div class="section-head"><div><p class="eyebrow">${esc(t.currentNode)} ${m.id}</p><h2>${esc(t.title)}</h2></div>${button(t.all,'maintenance-select',m.id)}</div><div class="info-row"><span>${esc(t.last)}</span><strong>${esc(last)}</strong></div><p class="settings-copy">${esc(!m.loaded?t.load:m.entries.length?t.scope:t.noEntries)}</p><div class="toolbar">${button(t.record,'record',m.id)}</div></section>`;
  }
  // Screen care (approved mock v15): equal wear tiles for every tracked machine, then the selected machine.
  // Shows the Hub's own wear figure and cycle facts only; no invented remaining-life estimate.
  const MORE = {th:{used:'ใช้ไปแล้ว',runH:'ชั่วโมงเดินเครื่องรอบนี้',days:'จำนวนวันรอบนี้',start:'เริ่มรอบ',slot:'ช่องว่าง',cycles:'รอบที่ผ่านมา',cycle:'รอบ',current:'กำลังใช้',h:'ชม.',d:'วัน',near:'ใกล้ครบอายุ ควรเตรียมเปลี่ยน',noWear:'ยังไม่มีข้อมูลการสึก'},
                en:{used:'Used',runH:'Run hours this cycle',days:'Days this cycle',start:'Cycle start',slot:'Empty slot',cycles:'Past cycles',cycle:'Cycle',current:'In use',h:'h',d:'days',near:'Near end of life, prepare a replacement',noWear:'No wear data yet'}};
  function render({life,nodes=[],selectedId,lang='th',canManage=false,icon=null}) {
    const t=words[lang] || words.th, x=MORE[lang==='en'?'en':'th'], available=array(nodes), ic=n=>icon?icon(n):'';
    if (!available.length) return `<div class="gg-pgh"><h1>${esc(t.title)}</h1></div><div class="gg-ghost gg-wide"><span>${esc(t.noMachines)}<small>${esc(t.emptyNote)}</small></span></div>`;
    const node=available.find(item=>idOf(item)===Number(selectedId)) || available[0];
    const m=model(life,node), machine=m.machine, st=machine && machine.state || null;
    const reasonOf = entry => t[entry.reason] || (lang==='th' && entry.reason_th) || entry.reason || t.other;
    const start = dateLabel(machine && machine.start_ts,machine && machine.start_date,lang);
    const pct = v => typeof v==='number' && Number.isFinite(v) ? Math.max(0,Math.min(100,v)) : null;
    const num = (v,d=0) => typeof v==='number' && Number.isFinite(v) ? v.toFixed(d) : '—';
    const tiles = available.map(item=>{const im=model(life,item),p=pct(im.machine && im.machine.state && im.machine.state.used_pct);
      return `<button type="button" class="gg-wtile${idOf(item)===m.id?' on':''}${p>=90?' hi':''}" data-action="maintenance-select" data-id="${idOf(item)}" aria-pressed="${idOf(item)===m.id}"><span class="gg-wt-id"><b class="num">${String(idOf(item)).padStart(2,'0')}</b>${esc(nameOf(item,t))}</span><span class="gg-wt-pct num">${p==null?'—':Math.round(p)+'%'}</span><span class="gg-bar"><i style="width:${p||0}%"></i></span><small>${im.entries.length} ${esc(t.count)}</small></button>`;});
    while (tiles.length < 6) tiles.push(`<div class="gg-wtile gg-wghost"><small>${esc(x.slot)}</small></div>`);
    const used=pct(st && st.used_pct);
    const cycles=array(machine && machine.cycles).slice().reverse();
    return `<div class="gg-pgh"><h1>${esc(t.title)}</h1><span class="gg-muted">${esc(t.scope)}</span></div>
     <div class="gg-wgrid">${tiles.join('')}</div>
     <div class="gg-sgrid2">
      <section class="gg-card gg-sdetail"><div class="gg-rhd"><h2><span class="num">${String(m.id).padStart(2,'0')}</span>${esc(nameOf(node,t))}</h2>${used>=90?`<span class="gg-chip" data-level="fault">${ic('alert')}${esc(x.near)}</span>`:''}${canManage?`<button type="button" class="gg-btn gg-pri" data-action="record" data-id="${m.id}">${ic('plus')}${esc(t.record)}</button>`:''}</div>
       ${!m.loaded?`<p class="gg-alert">${esc(t.unavailable)}</p>`:''}${machine && machine.implicit_start?`<p class="gg-hnote">${esc(t.implicit)}</p>`:''}
       <div class="gg-stats4"><div><small>${esc(x.used)}</small><b class="num${used>=90?' hi':''}">${used==null?'—':Math.round(used)+'%'}</b><span class="gg-bar"><i style="width:${used||0}%"></i></span></div><div><small>${esc(x.runH)}</small><b class="num">${num(st && st.run_h,1)}</b></div><div><small>${esc(x.days)}</small><b class="num">${num(st && st.days,1)}</b></div><div><small>${esc(x.start)}</small><b>${esc(start==='—'?t.notKnown:start)}</b></div></div>
       ${st && st.stage_th && lang==='th'?`<p class="gg-hnote">${esc(st.stage_th)}</p>`:''}
       <div class="gg-cyc"><h3 class="gg-h3">${esc(x.cycles)}</h3>${cycles.length?cycles.slice(0,4).map((c,i)=>`<div class="gg-hrow"><span class="gg-hn">${esc(x.cycle)} ${cycles.length-i}</span><b>${esc(c.start_date||'—')} → ${esc(c.end_date||x.current)}</b><small class="num">${num(c.days,1)} ${esc(x.d)} · ${num(c.run_h,1)} ${esc(x.h)}</small>${c.outcome_th||c.outcome?`<small>${esc(lang==='th'?c.outcome_th||c.outcome:c.outcome)}</small>`:''}</div>`).join(''):`<div class="gg-hrow"><span class="gg-hn">${esc(x.cycle)} 1</span><b>${esc(start==='—'?t.notKnown:start)} → ${esc(x.current)}</b><small>${esc(used==null?x.noWear:'')}</small></div>`}</div>
       <div class="gg-rhd gg-foot"><span class="gg-muted">${esc(t.mac)} <b class="num">${esc(node.mac || t.unassigned)}</b></span><button type="button" class="gg-btn" data-action="detail" data-id="${m.id}">${esc(t.detail)}</button></div>
      </section>
      <section class="gg-card gg-shist"><div class="gg-rhd"><h3 class="gg-h3">${esc(t.records)}</h3><span class="gg-muted gg-right">${m.entries.length} ${esc(t.count)}</span></div>
       ${m.entries.length?m.entries.slice(0,6).map(entry=>`<div class="gg-hrow"><span class="gg-hn">${ic('screen')}</span><b>${esc(dateLabel(entry.ts,entry.date,lang))}</b><small>${esc(reasonOf(entry))}${entry.note?' · '+esc(entry.note):''}</small></div>`).join(''):`<div class="gg-chart-msg gg-static">${esc(m.loaded?t.noEntries:t.unavailable)}</div>`}
      </section></div>`;
  }
  const api={render,summary,model,dateLabel};
  root.GGMaintenanceView=api;
  if (typeof module==='object' && module.exports) module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
