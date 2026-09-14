'use strict';
// One workspace, reusing the existing forms and their verified save handlers.
const workspace = {tab:'agenda', range:'today', layout:'list', person:'', origin:null};
const originalShowView = showView;
const conciergeRoot = $('concierge-view');
const originalAsk = $('concierge-form').closest('section');
const originalReview = $('concierge-preview').closest('section');
const inbox = document.querySelector('.concierge-inbox');
conciergeRoot.classList.add('unified-concierge');
const tabs = element('nav',undefined,'workspace-tabs'); tabs.setAttribute('aria-label','Concierge workspace');
const panes = {};
for (const [key,label] of [['agenda','Today'],['ask','Add'],['attention','Requests'],['history','History'],['settings','Settings']]) {
  const button=element('button',label,'secondary'); button.type='button'; button.dataset.tab=key;
  button.addEventListener('click',()=>openWorkspace(key)); tabs.append(button);
  panes[key]=element('section'); panes[key].id='workspace-'+key; panes[key].hidden=true;
}
conciergeRoot.replaceChildren(tabs,...Object.values(panes));
panes.ask.append(originalAsk, originalReview); panes.attention.append(inbox);
$('concierge-inbox-heading').textContent='Needs attention';
inbox.querySelector('.eyebrow').hidden=true;
inbox.querySelector('p.optional').textContent='Answer missing details here. Drafts save automatically; nothing is booked until you add it.';
const requesterLabel=element('label','Who is asking?'); const requester=element('select'); requester.id='workspace-requester'; requester.required=true; requesterLabel.append(requester);
$('concierge-form').prepend(requesterLabel);
$('concierge-form').querySelector('button[type=submit]').textContent='Organize this';
const quick=element('div',undefined,'actions');
for(const [label,action] of [['Add a task',()=>openActivity('new-task')],['Add an appointment',()=>openActivity('new-event')]]) {
 const b=element('button',label,'secondary'); b.type='button';b.onclick=action;quick.append(b);
}
originalAsk.append(quick);
$('show-tasks').hidden=true; $('show-calendar').hidden=true;
$('show-concierge').textContent='Concierge'; $('show-concierge').parentElement.prepend($('show-concierge'));
$('tasks-view').hidden=true; $('calendar-view').hidden=true;
// Profile/contact editing has one home. Keep the old contact form hidden for compatibility.
panes.settings.append(document.querySelector('.panel.family'));
$('alert-contacts-form').closest('section').hidden=true;
function settingsGroup(label,node){const box=element('details',undefined,'panel');box.append(element('summary',label),node);panes.settings.append(box);}
settingsGroup('Connected calendars and who receives each schedule', document.querySelector('.calendar-assignments'));
settingsGroup('Calendar connection help', document.querySelector('.calendar-help'));
settingsGroup('Home, travel buffers and commute schedules',document.querySelector('.departure-settings'));
settingsGroup('Weather preferences',document.querySelector('.weather-settings'));
settingsGroup('Morning briefings', $('morning-briefing-form').closest('section'));
settingsGroup('Automatic calendar reminders', $('calendar-alert-rule-form').closest('section'));
for(const [id,label] of [['departures-view','Edit home or commute settings'],['weather-view','Edit weather preferences'],['alerts-view','Edit contacts and notification preferences']]){
 const b=element('button',label,'secondary'); b.type='button';b.onclick=()=>openWorkspace('settings');$(id).prepend(b);
}
const controls=element('div',undefined,'filters');
function selectControl(label,id,options){const l=element('label',label),s=element('select');s.id=id;for(const [v,t]of options)s.add(new Option(t,v));l.append(s);controls.append(l);return s;}
const range=selectControl('When','agenda-range',[['today','Today'],['tomorrow','Tomorrow'],['week','Next 7 days'],['all','Next 14 days']]);
const person=selectControl('Who','agenda-person',[['','Everyone']]);
const layout=selectControl('View','agenda-layout',[['list','List'],['calendar','Calendar']]);
const refreshAgenda=element('button','Refresh agenda','secondary'); refreshAgenda.type='button';refreshAgenda.onclick=async()=>{refreshAgenda.disabled=true;try{await Promise.all([load(),loadCalendar()]);}finally{refreshAgenda.disabled=false;}}; controls.append(refreshAgenda);
panes.agenda.append(element('h2','Our agenda'),controls,$('calendar-zone'),$('calendar-message'),$('calendar-sources'),$('calendar-conflicts'));
const agendaList=element('div');agendaList.id='agenda-list';const unscheduled=element('div');unscheduled.id='agenda-unscheduled';panes.agenda.append(agendaList,unscheduled);
for(const input of [range,person,layout])input.onchange=()=>renderAgenda();
function dateKey(value){return new Intl.DateTimeFormat('en-CA',{timeZone:regional.timezone,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));}
function addDays(key,n){const d=new Date(key+'T12:00:00Z');d.setUTCDate(d.getUTCDate()+n);return d.toISOString().slice(0,10);}
function eventPeople(e){return (state.assignments?.calendars||[]).find(c=>c.key===e.calendar_key)?.member_ids||[];}
function syncPeople(){
 for(const sel of [person,requester]){const old=sel.value;sel.replaceChildren(new Option(sel===person?'Everyone':'Choose a family member',''));for(const m of state.members)sel.add(new Option(m.name,String(m.id)));sel.value=old;}
}
function agendaCard(item){
 const card=element('article',undefined,'task agenda-item');
 card.append(element('span',item.kind==='task'?'Task':'Appointment','badge'),element('h3',item.title));
 card.append(element('p',item.kind==='task'?(item.due_at?`Due ${new Intl.DateTimeFormat(regional.locale,{dateStyle:'medium',timeStyle:'short',timeZone:regional.timezone}).format(new Date(item.due_at))}`:'No date set'):formatEventTime(item,regional.timezone)));
 card.append(element('p',item.kind==='task'?(item.assigned_to_name||'Unassigned'):`${item.calendar} · ${sourceLabels[item.source]}`,'optional'));
 const b=element('button','View details','secondary');b.type='button';b.onclick=()=>openActivity(item.kind,item);card.append(b);return card;
}
window.renderAgenda=function(){
 syncPeople();
 const today=dateKey(new Date()), first=range.value==='tomorrow'?addDays(today,1):today;
 const days=range.value==='week'?7:range.value==='all'?14:1,last=addDays(first,days);
 const member=person.value;
 const tasks=state.tasks.filter(t=>t.status!=='completed'&&(!member||String(t.assigned_to)===member)).map(t=>({...t,kind:'task'}));
 const events=(state.calendarData?.events||[]).filter(e=>!member||eventPeople(e).includes(Number(member))).map(e=>({...e,kind:'event'}));
 const rows=[...tasks.filter(t=>t.due_at&&dateKey(t.due_at)<last&&(dateKey(t.due_at)>=first||(first===today&&new Date(t.due_at)<new Date()))),...events.filter(e=>{const start=e.all_day?e.start:dateKey(e.start), end=e.all_day?e.end:dateKey(e.end);return start<last&&(e.all_day?end>first:end>=first);})].sort((a,b)=>(a.due_at||a.start).localeCompare(b.due_at||b.start));
 agendaList.replaceChildren();agendaList.className=layout.value==='calendar'?'agenda-grid':'';
 if(layout.value==='calendar'){
  for(let i=0;i<days;i++){const day=addDays(first,i),column=element('section',undefined,'agenda-day');column.append(element('h3',new Intl.DateTimeFormat(regional.locale,{weekday:'short',month:'short',day:'numeric',timeZone:'UTC'}).format(new Date(day+'T12:00:00Z'))));
   const daily=rows.filter(e=>{if(e.kind==='task')return dateKey(e.due_at)===day||(i===0&&dateKey(e.due_at)<first);const start=e.all_day?e.start:dateKey(e.start),end=e.all_day?e.end:dateKey(e.end);return start<=day&&(e.all_day?end>day:end>=day);});
   column.append(...daily.map(agendaCard));if(!daily.length)column.append(element('p','No scheduled items','optional'));agendaList.append(column);}
 }else{agendaList.append(...rows.map(agendaCard));if(!rows.length)agendaList.append(element('p','No scheduled items in this view.','empty'));}
 unscheduled.replaceChildren(element('h3','Unscheduled'),...tasks.filter(t=>!t.due_at).map(agendaCard));
 if(!tasks.some(t=>!t.due_at))unscheduled.append(element('p','No undated tasks.','optional'));
 if(member)unscheduled.append(element('p','Appointments are filtered using calendar assignments in Family settings. Unassigned calendars appear under Everyone.','optional'));
};
window.loadAllRequests=async function(status){let rows=[];for(let offset=0;;offset+=100){const batch=await api(`/concierge/inbox?status=${status}&limit=100&offset=${offset}`);rows.push(...batch);if(batch.length<100)return rows;}};
const historyRequests=element('div');
const historyRefresh=element('button','Refresh history','secondary');historyRefresh.type='button';historyRefresh.onclick=loadWorkspaceHistory;
panes.history.append(element('h2','History'),historyRefresh,element('h3','Saved drafts and resolved requests'),historyRequests);
const oldArchive=$('calendar-archive').closest('details');panes.history.append(oldArchive);
const completed=element('div');panes.history.append(element('h3','Completed tasks'),completed);
async function loadWorkspaceHistory(){
 historyRefresh.disabled=true;
 try{const [handled,dismissed]=await Promise.all([loadAllRequests('handled'),loadAllRequests('dismissed')]);historyRequests.replaceChildren();const dismissedBox=element('details');dismissedBox.append(element('summary',`Dismissed requests (${dismissed.length})`));
 for(const item of [...handled,...dismissed].sort((a,b)=>b.received_at.localeCompare(a.received_at))){const card=element('article',undefined,'task');card.append(element('h3',item.plan.title||item.request_text),element('p',`${item.member_name} · ${item.status==='dismissed'?'Dismissed':'Saved / resolved request'}`));
 card.append(element('p',item.plan.saved_task_id?'Task created':item.plan.saved_calendar_uid?`${Object.keys(item.plan.calendar_receipts||{}).length} appointment(s) added to iCloud`:'Saved request only; this status does not confirm a booking or delivery.','optional'));
 const b=element('button','Reopen request','secondary');b.type='button';b.onclick=async()=>{await api(`/concierge/inbox/${item.id}`,{method:'PATCH',body:JSON.stringify({status:'pending'})});activeConciergeInboxId=item.id;activeConciergeRequester=item.member_name;$('concierge-text').value=item.request_text;openWorkspace('ask');await previewConcierge(null,null,null,false,item.plan);};card.append(b);(item.status==='dismissed'?dismissedBox:historyRequests).append(card);}
 if(!historyRequests.children.length)historyRequests.append(element('p','No saved requests yet.'));if(dismissed.length)historyRequests.append(dismissedBox);
 completed.replaceChildren(...state.tasks.filter(t=>t.status==='completed').map(t=>agendaCard({...t,kind:'task'})));
 }catch(e){historyRequests.replaceChildren(element('p',e.message,'error'));}finally{historyRefresh.disabled=false;}
}
// Shared activity panel: task actions, appointment edits and per-event travel controls.
const dialog=element('dialog');dialog.id='activity-dialog';const close=element('button','Close','secondary');close.type='button';close.onclick=()=>dialog.close();
const detailTitle=element('h2','Activity details');detailTitle.id='activity-title';dialog.setAttribute('aria-labelledby','activity-title');const body=element('div');dialog.append(close,detailTitle,body);document.body.append(dialog);
const taskEditor=$('task-form').closest('section'),calendarEditor=$('icloud-editor');
function parkEditors(){taskEditor.hidden=true;calendarEditor.hidden=true;document.querySelector('main').append(taskEditor,calendarEditor);}
parkEditors();dialog.addEventListener('close',parkEditors);
async function openActivity(kind,item){
 parkEditors();body.replaceChildren();detailTitle.textContent=item?.title||'Add an activity';if(!dialog.open)dialog.show();
 if(kind==='new-task'){$('task-form').reset();taskEditor.hidden=false;body.append(taskEditor);return;}
 if(kind==='new-event'){calendarEditor.hidden=false;calendarEditor.open=true;body.append(calendarEditor);await loadIcloudCalendars();$('icloud-new').click();return;}
 body.append(agendaCardSummary(item,kind));
 if(kind==='task'){
  for(const status of item.status==='completed'?['pending']:['in_progress','completed']){const b=element('button',labels[status],'secondary');b.type='button';b.onclick=async()=>{b.disabled=true;try{const updated=await api(`/tasks/${item.id}`,{method:'PATCH',body:JSON.stringify({status})});state.tasks=state.tasks.map(t=>t.id===updated.id?updated:t);renderTasks();dialog.close();}catch(e){body.append(element('p',e.message,'error'));b.disabled=false;}};body.append(b);}
 }else{
  if(item.source==='icloud'&&!item.all_day){const b=element('button','Edit appointment','secondary');b.type='button';b.onclick=async()=>{calendarEditor.hidden=false;body.append(calendarEditor);await openIcloudEvent(item.id);};body.append(b);}
  const travel=element('details');travel.append(element('summary','Transportation and traffic alerts'));body.append(travel);
  travel.addEventListener('toggle',async()=>{if(!travel.open||travel.dataset.loaded)return;travel.dataset.loaded='true';travel.append(element('p','Loading travel details…'));await loadDeparturePlanner();const row=[...$('departure-event-list').children].find(r=>r.dataset.eventId===item.id);travel.lastChild.remove();travel.append(row||element('p','Travel controls require a timed upcoming appointment and a configured home address.'));});
 }
}
function agendaCardSummary(item,kind){const box=element('div');box.append(element('p',kind==='task'?labels[item.status]:formatEventTime(item,regional.timezone)));if(item.description)box.append(element('p',item.description));if(item.location)box.append(element('p',item.location));if(kind==='task')box.append(element('p',`Assigned to ${item.assigned_to_name||'no one'} · Repeat: ${item.repeat_interval||'none'} · Reminder: ${item.reminder_minutes_before==null?'Off':item.reminder_minutes_before+' minutes before'}`));else box.append(element('p',`Saved in ${item.calendar} (${sourceLabels[item.source]}).`));return box;}
window.openWorkspace=function(tab='agenda'){
 workspace.tab=tab;originalShowView('concierge');
 for(const [key,pane]of Object.entries(panes))pane.hidden=key!==tab;
 for(const b of tabs.children)b.setAttribute('aria-pressed',String(b.dataset.tab===tab));
 history.replaceState(null,'','#concierge/'+tab);document.querySelector('h1').textContent='Your family, organized';document.title='Family Agent · Concierge';
 if(tab==='agenda'){renderAgenda();if(!calendarLoaded)loadCalendar();}
 if(tab==='history')loadWorkspaceHistory();
 if(tab==='settings'){loadCalendar();loadDeparturePlanner();loadWeather();loadAlerts();}
};
showView=function(view){if(['tasks','calendar','concierge'].includes(view)){openWorkspace(view==='concierge'?'ask':'agenda');return;}originalShowView(view);};
// Capture website submissions before the legacy preview-only handler.
let webRequestId=crypto.randomUUID();
$('concierge-text').addEventListener('input',()=>{webRequestId=crypto.randomUUID();});
$('concierge-form').addEventListener('submit',async event=>{
 event.preventDefault();event.stopImmediatePropagation();const button=event.submitter;button.disabled=true;$('concierge-status').textContent='Organizing and saving your request…';
 try{const item=await api('/concierge/requests',{method:'POST',body:JSON.stringify({text:$('concierge-text').value.trim(),member_id:Number(requester.value),request_id:webRequestId})});activeConciergeInboxId=item.id;activeConciergeRequester=item.member_name;await previewConcierge(null,null,null,false,item.plan);await loadConciergeInbox();}
 catch(e){$('concierge-status').textContent=e.message;}finally{button.disabled=false;}
},true);
// Opening an inbox request also reveals the shared review area.
inbox.addEventListener('click',event=>{if(event.target.closest('button')?.textContent==='Open this plan')openWorkspace('ask');});
const oldPreview=previewConcierge;
previewConcierge=async function(...args){await oldPreview(...args);const plan=args[4];if(plan?.request_type==='calendar'){
 const entries=plan.calendar_events?.length?plan.calendar_events:[{title:plan.title,start_time:plan.time}];
 entries.forEach((entry,index)=>{if(plan.calendar_receipts?.[String(index)])return;const b=element('button',`Add to calendar: ${entry.title||plan.title}`,'secondary');b.type='button';b.onclick=async()=>{if(plan.missing_fields?.length){$('concierge-status').textContent='Please complete: '+plan.missing_fields.join(', ');return;}const current=(plan.calendar_events||[])[index]||{title:plan.title,start_time:plan.time};Object.assign(entry,current);await openActivity('new-event');window.calendarRequestOrigin=activeConciergeInboxId!==null?{id:activeConciergeInboxId,index}:null;$('icloud-title').value=entry.title||plan.title||'';$('icloud-start').value=plan.date&&entry.start_time?`${plan.date}T${entry.start_time}`:'';$('icloud-end').value=plan.date&&entry.end_time?`${plan.date}T${entry.end_time}`:'';if(plan.repeat_interval==='weekly'){$('icloud-repeat').value='weekly';$('icloud-repeat').dispatchEvent(new Event('change'));}$('icloud-description').value=`For: ${plan.primary_member||''}. Drop-off: ${plan.driver||'not set'}. Pickup: ${plan.pickup_by||'not set'}. Notify requested: ${(plan.notification_members||[]).join(', ')||'none'}.`;$('icloud-message').textContent='Review all details and choose the calendar. Saving creates the appointment; notifications are configured separately.';};$('concierge-preview').append(b);});
 }};
window.addEventListener('hashchange',()=>{const [view,tab]=location.hash.slice(1).split('/');if(view==='concierge')openWorkspace(tab||'agenda');else showView(view||'concierge');});
regionalReady.then(()=>{renderAgenda();const [view,tab]=location.hash.slice(1).split('/');if(!view||['tasks','calendar','concierge'].includes(view))openWorkspace(tab||'agenda');});
// The same task form serves create and edit, retaining reminder validation on the server.
let editingTaskId=null;
const activityBase=openActivity;
openActivity=async function(kind,item){
 window.calendarRequestOrigin=null;editingTaskId=null;$('task-form').querySelector('button[type=submit]').textContent='Add task';
 await activityBase(kind,item);
 if(kind==='task'){
  const edit=element('button','Edit task details','secondary');edit.type='button';edit.onclick=()=>{
   editingTaskId=item.id;taskEditor.hidden=false;body.append(taskEditor);
   $('title').value=item.title;$('description').value=item.description||'';$('assignee').value=item.assigned_to||'';
   $('task-due-at').value=item.due_at?browserDate(item.due_at):'';$('task-repeat').value=item.repeat_interval||'none';$('task-reminder').value=item.reminder_minutes_before??'';
   $('task-form').querySelector('button[type=submit]').textContent='Save task changes';
  };body.append(edit);
 }
};
$('task-form').addEventListener('submit',async event=>{
 if(editingTaskId===null)return;
 event.preventDefault();event.stopImmediatePropagation();const button=event.submitter;button.disabled=true;
 try{const due=$('task-due-at').value,reminder=$('task-reminder').value;
 const updated=await api(`/tasks/${editingTaskId}`,{method:'PUT',body:JSON.stringify({title:$('title').value,description:$('description').value||null,assigned_to:$('assignee').value||null,due_at:due?new Date(due).toISOString():null,repeat_interval:$('task-repeat').value,reminder_minutes_before:reminder===''?null:Number(reminder)})});
 state.tasks=state.tasks.map(t=>t.id===updated.id?updated:t);renderTasks();notice('Task changes saved.');dialog.close();
 }catch(e){body.append(element('p',e.message,'error'));}finally{button.disabled=false;}
},true);
const activityWithEditing=openActivity;
openActivity=async function(kind,item){
 await activityWithEditing(kind,item);
 if(!item)return;
 const delivery=element('details');delivery.append(element('summary','Reminder delivery status'));body.append(delivery);
 delivery.addEventListener('toggle',async()=>{
  if(!delivery.open||delivery.dataset.loaded)return;delivery.dataset.loaded='true';
  try{const rows=await api('/concierge/activity-alerts?'+(kind==='task'?'task_id=':'event_id=')+encodeURIComponent(item.id));
   delivery.append(element('p','Shows linked task and appointment reminders. Traffic checks have their own status above. “Sent” means Messages accepted the alert; it does not confirm that someone read it.','optional'));
   for(const r of rows)delivery.append(element('p',`${r.member_name} · ${r.status} · ${new Date(r.scheduled_for).toLocaleString()}`));
   if(!rows.length)delivery.append(element('p','No linked reminders recorded.'));
  }catch(e){delivery.append(element('p',e.message,'error'));delete delivery.dataset.loaded;}
 });
};

window.activityTaskSaved=()=>{if(dialog.open)dialog.close();};

// Today-first navigation: one row, with occasional tools under More.
const primaryNav=document.querySelector('.view-nav');
const moreMenu=element('details',undefined,'concierge-more');moreMenu.append(element('summary','More'));
for(const key of ['departures','weather','alerts','events'])moreMenu.append($('show-'+key));
for(const [key,label]of [['history','History'],['settings','Settings']]){const b=element('button',label,'secondary');b.type='button';b.onclick=()=>{moreMenu.open=false;openWorkspace(key);};moreMenu.append(b);}
const hiddenNav=element('div');hiddenNav.hidden=true;hiddenNav.append($('show-concierge'),$('show-tasks'),$('show-calendar'));primaryNav.append(hiddenNav);
for(const b of [...tabs.children])if(['ask','history','settings'].includes(b.dataset.tab))b.hidden=true;
const scheduleButton=element('button','Schedule','secondary');scheduleButton.type='button';scheduleButton.dataset.tab='schedule';scheduleButton.onclick=()=>openWorkspace('schedule');tabs.insertBefore(scheduleButton,tabs.children[1]);
primaryNav.append(tabs,moreMenu);
const todayTop=element('section',undefined,'today-composer');conciergeRoot.insertBefore(todayTop,conciergeRoot.firstChild);
todayTop.append(originalAsk);
originalAsk.querySelector('.eyebrow').hidden=true;originalAsk.querySelector('h2').textContent='What can I help your family with?';originalAsk.querySelector('p.optional').hidden=true;
$('concierge-text').rows=2;$('concierge-text').placeholder='e.g. Team practice Wednesday at 3:30 for Alex';
$('concierge-form').querySelector('button[type=submit]').textContent='Continue';
requesterLabel.classList.add('requester-choice');
const identityDetails=element('details');identityDetails.append(element('summary','Requesting for…'),requesterLabel);$('concierge-form').prepend(identityDetails);
requester.addEventListener('change',()=>{identityDetails.querySelector('summary').textContent=requester.selectedOptions[0]?.textContent||'Requesting for…';identityDetails.open=false;});
// Requester is required and must be explicitly chosen; open that choice when missing.
requester.addEventListener('invalid',()=>{identityDetails.open=true;});
quick.hidden=true;
const manual=element('details',undefined,'manual-add');manual.append(element('summary','Or add details yourself'),quick);quick.hidden=false;originalAsk.append(manual);
const daySummary=element('p','', 'day-summary');todayTop.prepend(daySummary);
const attentionBanner=element('button',undefined,'attention-banner');attentionBanner.type='button';attentionBanner.hidden=true;attentionBanner.onclick=()=>openWorkspace('attention');todayTop.append(attentionBanner);
const baseInboxRender=renderConciergeInbox;
renderConciergeInbox=function(items){baseInboxRender(items);attentionBanner.hidden=!items.length;attentionBanner.textContent=`${items.length} request${items.length===1?' needs':'s need'} your attention →`;const b=[...tabs.children].find(x=>x.dataset.tab==='attention');b.textContent=items.length?`Requests (${items.length})`:'Requests';};
const cleanOpenBase=openWorkspace;
openWorkspace=function(tab='agenda'){
 const isSchedule=tab==='schedule';cleanOpenBase(isSchedule?'agenda':tab);
 todayTop.hidden=tab!=='agenda';
 if(tab==='ask'&&!$('concierge-preview').querySelector('.concierge-plan, .inline-answer, button')&&$('concierge-preview').textContent.includes('will appear')){todayTop.hidden=false;panes.ask.hidden=true;}
 if(tab==='agenda'){range.value='today';layout.value='list';}
 if(isSchedule){range.value='week';layout.value='calendar';history.replaceState(null,'','#concierge/schedule');}
 controls.hidden=!isSchedule;
 panes.agenda.querySelector('h2').textContent=isSchedule?'Your schedule':'Today';
 for(const b of tabs.children)b.setAttribute('aria-pressed',String(b.dataset.tab===tab||(tab==='ask'&&b.dataset.tab==='agenda')));
 document.querySelector('h1').textContent=tab==='agenda'?'A little more together.':isSchedule?'Your family’s schedule':tab==='attention'?'Let’s finish these plans':tab==='settings'?'Family settings':tab==='history'?'History':'Let’s organize it';
 if(tab==='agenda'||isSchedule)renderAgenda();
};
const oldMainShow=showView;
showView=function(view){moreMenu.open=false;if(view==='concierge'){openWorkspace('agenda');return;}oldMainShow(view);};
const sourceDetails=element('details',undefined,'sync-details');sourceDetails.append(element('summary','Calendar connection status'),$('calendar-sources'),$('calendar-zone'));panes.settings.append(sourceDetails);
$('calendar-message').classList.add('calendar-status-short');
const compactAgendaBase=agendaCard;
agendaCard=function(item){const card=element('article',undefined,'agenda-row');const button=element('button',undefined,'agenda-open');button.type='button';
 const when=item.kind==='task'?(item.due_at?new Intl.DateTimeFormat(regional.locale,{hour:'numeric',minute:'2-digit',timeZone:regional.timezone}).format(new Date(item.due_at)):'To do'):item.all_day?'All day':new Intl.DateTimeFormat(regional.locale,{hour:'numeric',minute:'2-digit',timeZone:regional.timezone}).format(new Date(item.start));
 const text=element('span');text.append(element('strong',item.title),element('small',item.kind==='task'?item.assigned_to_name||'Unassigned':[item.calendar,item.location].filter(Boolean).join(' · ')));
 const timeLabel=element('span',when,'agenda-row-time');if(item.kind!=='task'&&!item.all_day)timeLabel.append(element('small','to '+new Intl.DateTimeFormat(regional.locale,{hour:'numeric',minute:'2-digit',timeZone:regional.timezone}).format(new Date(item.end))));button.append(timeLabel,text);button.onclick=()=>openActivity(item.kind,item);card.append(button);return card;};
const compactRenderBase=renderAgenda;
renderAgenda=function(){compactRenderBase();$('calendar-conflicts').hidden=!(state.calendarData?.conflicts||[]).length;
 const errors=(state.calendarData?.sources||[]).some(s=>s.status==='error');$('calendar-message').hidden=!errors&&!$('calendar-message').textContent.includes('failed');
 const next=(state.calendarData?.events||[]).filter(e=>!e.all_day&&new Date(e.start)>new Date()).sort((a,b)=>a.start.localeCompare(b.start))[0];
 const weather=daySummary.dataset.weather||'';daySummary.textContent=[weather,next?`Next: ${next.title} · ${formatEventTime(next,regional.timezone)}`:''].filter(Boolean).join(' · ');
 unscheduled.hidden=!state.tasks.some(t=>t.status!=='completed'&&!t.due_at);
};
// Optional event fields stay behind a single disclosure.
const eventOptions=element('details',undefined,'event-options');eventOptions.append(element('summary','More options'));
for(const id of ['icloud-repeat','icloud-repeat-until','icloud-description'])eventOptions.append($(id).closest('label'));
$('icloud-event-form').insertBefore(eventOptions,$('icloud-event-form').querySelector('button'));
const taskOptions=element('details',undefined,'event-options');taskOptions.append(element('summary','More options'));
for(const id of ['description','task-repeat','task-reminder'])taskOptions.append($(id).closest('label'));
$('task-form').insertBefore(taskOptions,$('task-form').querySelector('button'));
const compactPreviewBase=previewConcierge;
previewConcierge=async function(...args){await compactPreviewBase(...args);openWorkspace('ask');
 const preview=$('concierge-preview'),plan=args[4];
 preview.querySelectorAll('.safe-preview').forEach(n=>n.hidden=true);
 if(plan?.question_field)preview.querySelectorAll('.review-warning').forEach(n=>n.hidden=true);
 originalReview.querySelector('.eyebrow').hidden=true;originalReview.querySelector('h2').textContent='Review your plan';
 if(plan?.question_field){const prompt=element('p',plan.reply_text||'A few details are missing.');const answer=element('input');answer.placeholder='Your answer';answer.setAttribute('aria-label','Answer the missing detail');const reply=element('button','Continue');reply.type='button';
 const f=element('form',undefined,'inline-answer');answer.required=true;f.append(prompt,answer,reply);reply.type='submit';let answerId=crypto.randomUUID();answer.oninput=()=>{answerId=crypto.randomUUID();};f.onsubmit=async event=>{event.preventDefault();reply.disabled=true;try{const r=await api(`/concierge/inbox/${activeConciergeInboxId}/reply`,{method:'POST',body:JSON.stringify({text:answer.value,message_guid:answerId})});await previewConcierge(null,null,null,false,r.item.plan);}catch(e){prompt.textContent=e.message;reply.disabled=false;}};preview.prepend(f);}
 for(const heading of preview.querySelectorAll('h3'))if(heading.textContent==='Proposed actions'){heading.hidden=true;if(['UL','OL'].includes(heading.nextElementSibling?.tagName))heading.nextElementSibling.hidden=true;}
};
regionalReady.then(async()=>{const [view,key]=location.hash.slice(1).split('/');if(view==='concierge')openWorkspace(key||'agenda');try{const weather=await api('/weather/forecast');const day=weather.days?.[0];if(day){daySummary.dataset.weather=`${day.condition} · ${(day.recommendations||[]).slice(0,1).join('')}`;renderAgenda();}}catch{/* Weather is supplementary; existing weather settings remain available. */}});

// Appointments navigation and a separate rectangular launcher for other tools.
const appointmentsHeading=element('h2','Appointments');appointmentsHeading.id='appointments-navigation-heading';
primaryNav.setAttribute('aria-labelledby',appointmentsHeading.id);primaryNav.prepend(appointmentsHeading);
moreMenu.hidden=true;
const requestsTab=[...tabs.children].find(b=>b.dataset.tab==='attention');requestsTab.hidden=true;
const tomorrowButton=element('button','Tomorrow','secondary');tomorrowButton.type='button';tomorrowButton.dataset.tab='tomorrow';tomorrowButton.onclick=()=>openWorkspace('tomorrow');tabs.insertBefore(tomorrowButton,scheduleButton);
const toolsArea=element('section',undefined,'concierge-tools');toolsArea.setAttribute('aria-label','Family tools');
const toolGrid=element('div',undefined,'tool-grid');toolsArea.append(element('h2','Family tools'),toolGrid);document.querySelector('main').append(toolsArea);
// Small local line icons: no external font, library, or network request.
const toolIconPaths={
 'Ask Concierge':['M12 3l2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z','M20 2v4M18 4h4'],
 'Tasks':['M4 6l2 2 3-4M12 6h8M4 13l2 2 3-4M12 13h8M4 20h5M12 20h8'],
 'Requests':['M4 4h16v16H4Z','M4 13h5l1 3h4l1-3h5'],
 'Travel':['M5 10l2-6h10l2 6M4 10h16v8H4ZM7 18v3M17 18v3M7 14h2M15 14h2'],
 'Weather':['M8 4V2M3 6L1 4M13 6l2-2','M5 12a5 5 0 1 1 8-5','M6 20a4 4 0 1 1 1-8 6 6 0 0 1 11-1 4.5 4.5 0 1 1 1 9Z'],
 'Alerts':['M5 17h14l-2-3V9a5 5 0 0 0-10 0v5ZM10 21h4M12 2v2'],
 'Explore':['M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Z','M16 8l-2 6-6 2 2-6Z'],
 'History':['M3 10a9 9 0 1 1 1 8M3 3v7h7','M12 7v6l4 2'],
 'Settings':['M4 6h16M4 12h16M4 18h16','M8 3v6M16 9v6M10 15v6']
};
function toolTile(title,description,action){
 const b=element('button',undefined,'tool-tile');b.type='button';
 const icon=document.createElementNS('http://www.w3.org/2000/svg','svg');
 for(const [key,value]of Object.entries({viewBox:'0 0 24 24',width:'22',height:'22',fill:'none',stroke:'currentColor','stroke-width':'1.6','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true',focusable:'false',class:'tool-icon'}))icon.setAttribute(key,value);
 for(const d of toolIconPaths[title]||[]){const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d',d);icon.append(path);}
 const text=element('div',undefined,'tool-copy');text.append(element('strong',title),element('span',description));
 b.append(icon,text);b.onclick=action;toolGrid.append(b);return b;
}
toolTile('Ask Concierge','Organize a new request',()=>openWorkspace('compose'));
toolTile('Tasks','To-dos and progress',()=>{originalShowView('tasks');document.querySelector('h1').textContent='Family tasks';$('refresh').hidden=false;history.replaceState(null,'','#tasks');for(const b of tabs.children)b.setAttribute('aria-pressed','false');});
toolTile('Requests','Review and finish plans',()=>openWorkspace('attention'));
for(const [key,title,description]of [['departures','Travel','Routes and traffic'],['weather','Weather','Forecast and clothing advice'],['alerts','Alerts','Messages and reminders'],['events','Explore','Concerts and outings']])toolTile(title,description,()=>showView(key));
toolTile('History','Past activities and requests',()=>openWorkspace('history'));
toolTile('Settings','Family profiles and preferences',()=>openWorkspace('settings'));
const appointmentsOpenBase=openWorkspace;
openWorkspace=function(tab='agenda'){
 appointmentsOpenBase(tab==='tomorrow'?'agenda':tab==='compose'?'ask':tab);
 originalReview.hidden=tab==='compose';
 if(!['agenda','tomorrow','schedule'].includes(tab))for(const b of tabs.children)b.setAttribute('aria-pressed','false');
 todayTop.hidden=tab!=='compose';
 if(tab==='compose'){panes.ask.hidden=true;history.replaceState(null,'','#concierge/compose');document.querySelector('h1').textContent='Ask Concierge';}
 if(['agenda','tomorrow','schedule'].includes(tab)){
  document.querySelector('h1').textContent='Your family, organized';
  if(tab==='tomorrow'){range.value='tomorrow';layout.value='list';panes.agenda.querySelector('h2').textContent='Tomorrow';history.replaceState(null,'','#concierge/tomorrow');}
  for(const b of tabs.children)b.setAttribute('aria-pressed',String(b.dataset.tab===tab));
  renderAgenda();
 }
};
const appointmentsRenderBase=renderAgenda;
renderAgenda=function(){
 // Tasks have their own tile; this section presents only appointments.
 const tasks=state.tasks;
 try{state.tasks=[];appointmentsRenderBase();}finally{state.tasks=tasks;}
 unscheduled.hidden=true;
};
// Keep older task links useful after separating appointments from to-dos.
const toolShowBase=showView;
showView=function(view){if(view==='tasks'){originalShowView('tasks');document.querySelector('h1').textContent='Family tasks';return;}toolShowBase(view);};
regionalReady.then(()=>{const [view,key]=location.hash.slice(1).split('/');if(view==='concierge')openWorkspace(key||'agenda');});
const addTaskTileAction=element('button','Add task','secondary');addTaskTileAction.type='button';addTaskTileAction.onclick=()=>openActivity('new-task');$('tasks-view').querySelector('.board-top').append(addTaskTileAction);

// Direct appointment actions, without going through requests.
const appointmentActions=element('div',undefined,'appointment-actions');
const addAppointment=element('button','+ Add appointment');addAppointment.type='button';appointmentActions.append(addAppointment);panes.agenda.insertBefore(appointmentActions,panes.agenda.children[1]);
const appointmentFeedback=element('p',undefined,'appointment-feedback');appointmentFeedback.setAttribute('role','status');appointmentActions.after(appointmentFeedback);
addAppointment.onclick=async()=>{
 await openActivity('new-event');
 const selectedDay=range.value==='tomorrow'?addDays(dateKey(new Date()),1):dateKey(new Date());
 $('icloud-start').value=selectedDay+'T09:00';$('icloud-end').value=selectedDay+'T09:30';
 const choices=[...$('icloud-target').options].filter(o=>o.value);if(choices.length===1)$('icloud-target').value=choices[0].value;
 $('icloud-message').textContent='Date filled from this view. Choose the appointment’s actual start and end times.';
 $('icloud-title').focus();
};
const appointmentCardBase=agendaCard;
agendaCard=function(item){const row=appointmentCardBase(item);if(item.kind!=='task'){
 const edit=element('button',item.source==='icloud'?'Edit':'View details','secondary appointment-edit');edit.type='button';edit.setAttribute('aria-label',`${item.source==='icloud'?'Edit':'View'} ${item.title}`);
 edit.onclick=()=>item.source==='icloud'?editAppointmentDirect(item):openActivity('event',item);row.append(edit);
}return row;};
async function editAppointmentDirect(item){
 await openActivity('new-event');detailTitle.textContent='Edit appointment';
 $('icloud-event-form').querySelector('button[type=submit]').textContent='Save changes';
 $('icloud-title').value='';$('icloud-start').value='';$('icloud-end').value='';
 const loaded=await openIcloudEvent(item.id);
 if(loaded)$('icloud-title').focus();
}
const appointmentPanelBase=openActivity;
openActivity=async function(kind,item){
 await appointmentPanelBase(kind,item);
 if(kind==='new-event'){
  detailTitle.textContent='New appointment';calendarEditor.querySelector('summary').hidden=true;
  $('icloud-new').hidden=true;close.textContent='Cancel';
  $('icloud-event-form').querySelector('button[type=submit]').textContent='Add appointment';
  $('icloud-event-form').querySelector('button[type=submit]').disabled=false;
 }else{close.textContent='Close';}
};
window.appointmentSaved=message=>{dialog.close();appointmentFeedback.textContent=message;notice(message);};

// Approved appointments-first shell; retain the existing forms and API handlers.
const appMain=document.querySelector('main');
const shell=element('div',undefined,'concierge-shell');
const shellContent=element('div',undefined,'concierge-content');
for(const node of [...appMain.children])if(!node.matches('.heading, #notice'))shellContent.append(node);
shell.append(shellContent,dialog);appMain.append(shell);
const appointmentHeader=element('div',undefined,'appointment-header');
appointmentHeader.append(appointmentsHeading,appointmentActions);primaryNav.prepend(appointmentHeader);
const dayHeading=panes.agenda.querySelector('h2');
const dayToolbar=element('div',undefined,'appointment-day-toolbar');
dayToolbar.append(dayHeading,person.closest('label'),refreshAgenda);panes.agenda.prepend(dayToolbar);
refreshAgenda.textContent='Refresh';
const welcome=element('p','Your family’s day, in one place.','workspace-subtitle');document.querySelector('.heading>div').append(welcome);
const updateShell=()=>{const active=!panes.agenda.hidden&&!conciergeRoot.hidden;primaryNav.classList.toggle('appointments-active',active);appointmentActions.hidden=!active;};
new MutationObserver(updateShell).observe(conciergeRoot,{attributes:true,attributeFilter:['hidden'],subtree:true});updateShell();
// A modeless side panel keeps the selected appointment visible while editing.
const panelObserver=new MutationObserver(()=>shell.classList.toggle('editing',dialog.open));
panelObserver.observe(dialog,{attributes:true,attributeFilter:['open']});
dialog.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();dialog.close();}});
const cancelAppointment=element('button','Cancel','secondary');cancelAppointment.type='button';cancelAppointment.onclick=()=>dialog.close();
const saveAppointment=$('icloud-event-form').querySelector('button[type=submit]');
const editorActions=element('div',undefined,'appointment-editor-actions');saveAppointment.before(editorActions);editorActions.append(cancelAppointment,saveAppointment);
const repeatHelp=[...$('icloud-event-form').children].find(n=>n.tagName==='P'&&n.textContent.startsWith('Repeats start'));
if(repeatHelp)eventOptions.append(repeatHelp);
eventOptions.querySelector('summary').textContent='Repeat and notes';
calendarEditor.querySelector('p').textContent='Saved to your selected iCloud calendar. Times use this device’s timezone.';
const polishedRenderBase=renderAgenda;
renderAgenda=function(){polishedRenderBase();if(['today','tomorrow'].includes(range.value))dayHeading.textContent=new Intl.DateTimeFormat(regional.locale,{weekday:'long',month:'long',day:'numeric',timeZone:'UTC'}).format(new Date((range.value==='tomorrow'?addDays(dateKey(new Date()),1):dateKey(new Date()))+'T12:00:00Z'));};
regionalReady.then(()=>{renderAgenda();updateShell();});
