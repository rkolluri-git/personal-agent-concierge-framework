'use strict';
let regional = {locale: 'en-US', timezone: 'America/New_York', units: 'imperial'};
const regionalReady = fetch('/settings/regional').then(response => {
  if (response.status === 401) location.replace('/login');
  if (!response.ok) throw new Error('Could not load regional settings');
  return response.json();
}).then(value => {
  regional = value;
  new Intl.DateTimeFormat(regional.locale);
  $('regional-summary').textContent = `${regional.locale} · ${regional.timezone} · ${regional.units} · ${regional.messaging_provider || 'imessage'}`;
});
const $ = id => document.getElementById(id);
const state = {members: [], contacts: [], tasks: [], commutes: [], ready: false, calendarData: null};
const labels = {pending: 'To do', in_progress: 'In progress', completed: 'Completed'};
function notice(message = '', error = false) { $('notice').textContent = message; $('notice').className = error ? 'error' : ''; }
async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: {'Content-Type': 'application/json', 'X-Family-Request': 'dashboard'} });
  const data = await response.json().catch(() => null);
  if (response.status === 401) location.replace('/login');
  if (!response.ok) {
    const detail = data?.detail;
    throw new Error(typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map(e => e.msg).join('. ') : 'Could not save or load this change. Please try again.');
  }
  return data;
}
async function all(path) {
  const rows = [];
  for (let offset = 0; ; offset += 500) {
    const batch = await api(`${path}?limit=500&offset=${offset}`);
    rows.push(...batch);
    if (batch.length < 500) return rows;
  }
}
function element(tag, text, className) { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node; }
function renderMembers() {
  for (const [id, placeholder] of [['assignee', 'Unassigned'], ['filter-member', 'Everyone']]) {
    const select = $(id), selected = select.value;
    select.replaceChildren(new Option(placeholder, ''));
    for (const member of state.members) select.add(new Option(member.name, String(member.id)));
    select.value = [...select.options].some(o => o.value === selected) ? selected : '';
  }
  const contactByMember = new Map(state.contacts.map(contact => [contact.member_id, contact]));
  $('members').replaceChildren(...state.members.map(member => {
    const card = element('article', undefined, 'family-member-profile');
    card.dataset.memberId = member.id;
    card.append(element('h3', member.name));
    const roleLabel = element('label', 'Family role');
    const role = document.createElement('select');
    role.className = 'family-role';
    role.add(new Option('Parent', 'parent'));
    role.add(new Option('Child', 'child'));
    role.add(new Option('Adult', 'adult'));
    role.value = member.role || 'adult';
    roleLabel.append(role);
    const ageLabel = element('label', 'Age');
    const age = document.createElement('input');
    age.className = 'family-age';
    age.type = 'number'; age.min = '0'; age.max = '120'; age.placeholder = 'Not set';
    age.value = member.age === null ? '' : String(member.age);
    ageLabel.append(age);
    const saved = contactByMember.get(member.id);
    const contactLabel = element('label', 'Messaging phone or Apple Account email');
    contactLabel.className = 'family-contact-label';
    const contact = document.createElement('input');
    contact.className = 'family-contact'; contact.type = 'text'; contact.autocomplete = 'off';
    contact.placeholder = 'Phone number or email'; contact.value = saved?.imessage_handle || '';
    contactLabel.append(contact);
    const enabledLabel = element('label', undefined, 'contact-enabled family-contact-enabled-label');
    const enabled = document.createElement('input');
    enabled.className = 'family-contact-enabled'; enabled.type = 'checkbox'; enabled.checked = saved?.enabled ?? true;
    enabledLabel.append(enabled, element('span', 'Enable alerts and FA requests'));
    card.append(roleLabel, ageLabel, contactLabel, enabledLabel);
    return card;
  }));
  if (!state.members.length) $('members').append(element('p', 'Add your first family member below.', 'empty'));
}
function renderTasks() {
  window.renderAgenda?.();
  const selected = $('filter-member').value, status = $('filter-status').value;
  const tasks = state.tasks.filter(t => (!selected || String(t.assigned_to) === selected) && (!status || t.status === status));
  $('count').textContent = `${tasks.length} ${tasks.length === 1 ? 'task' : 'tasks'}`;
  $('tasks').replaceChildren();
  if (!tasks.length) { $('tasks').append(element('p', state.tasks.length ? 'No tasks match these filters.' : 'Nothing on the list yet. Add your first task.', 'empty')); return; }
  for (const task of tasks) {
    const card = element('article', undefined, 'task'), head = element('div', undefined, 'task-head');
    head.append(element('h3', task.title), element('span', labels[task.status], `badge ${task.status}`)); card.append(head);
    if (task.description) card.append(element('p', task.description));
    if (task.due_at) {
      const due = new Date(task.due_at);
      const dueLabel = `Due ${new Intl.DateTimeFormat(regional.locale, {dateStyle: 'medium', timeStyle: 'short', timeZone: regional.timezone}).format(due)}`;
      const dueNode = element('p', dueLabel, 'task-due');
      if (task.status !== 'completed' && due < new Date()) dueNode.classList.add('overdue');
      if (task.reminder_minutes_before !== null) dueNode.append(document.createTextNode(' · Message reminder scheduled'));
      card.append(dueNode);
    }
    if (task.repeat_interval === 'weekly') card.append(element('p', 'Repeats every week at this time', 'task-repeat-note'));
    const footer = element('div', undefined, 'task-footer'), actions = element('div', undefined, 'actions');
    footer.append(element('span', task.assigned_to_name || 'Unassigned', 'person'));
    const next = task.status === 'completed' ? [['pending', 'Reopen']] : task.status === 'pending' ? [['in_progress', 'Start'], ['completed', 'Complete']] : [['completed', 'Complete'], ['pending', 'Back to to do']];
    for (const [status, label] of next) {
      const button = element('button', label, 'secondary'); button.type = 'button'; button.setAttribute('aria-label', `${label}: ${task.title}`);
      button.addEventListener('click', async () => {
        actions.querySelectorAll('button').forEach(b => b.disabled = true);
        try {
          const updated = await api(`/tasks/${task.id}`, {method: 'PATCH', body: JSON.stringify({status})});
          state.tasks = state.tasks.map(t => t.id === updated.id ? updated : t); renderTasks();
          notice(status === 'completed' && updated.repeat_interval === 'weekly'
            ? `“${task.title}” is ready for its next weekly occurrence.`
            : `“${task.title}” is now ${labels[updated.status].toLowerCase()}.`);
        }
        catch (error) { notice(error.message, true); actions.querySelectorAll('button').forEach(b => b.disabled = false); }
      }); actions.append(button);
    }
    footer.append(actions); card.append(footer); $('tasks').append(card);
  }
}
async function load() {
  $('refresh').disabled = true;
  try { const [members, contacts, tasks] = await Promise.all([all('/family-members'), api('/alerts/contacts'), all('/tasks')]); state.members = members; state.contacts = contacts; state.tasks = tasks; state.ready = true; renderMembers(); renderTasks(); notice(); }
  catch (error) { notice(`Could not load your family’s tasks. ${error.message} Use Refresh to retry.`, true); }
  finally { $('refresh').disabled = false; document.querySelectorAll('form button').forEach(b => b.disabled = !state.ready); }
}
$('task-form').addEventListener('submit', async event => {
  event.preventDefault(); const title = $('title').value.trim(); if (!title) { notice('Please enter a task title.', true); $('title').focus(); return; }
  const button = event.submitter; button.disabled = true;
  try {
    const dueValue = $('task-due-at').value;
    const reminderValue = $('task-reminder').value;
    if ($('task-repeat').value === 'weekly' && !dueValue) {
      notice('Choose the first date and time for a weekly task.', true);
      $('task-due-at').focus(); button.disabled = false; return;
    }
    const task = await api('/tasks', {method: 'POST', body: JSON.stringify({
      title,
      description: $('description').value.trim() || null,
      assigned_to: $('assignee').value ? Number($('assignee').value) : null,
      due_at: dueValue ? new Date(dueValue).toISOString() : null,
      reminder_minutes_before: reminderValue === '' ? null : Number(reminderValue),
      repeat_interval: $('task-repeat').value
    })});
    state.tasks = [...state.tasks.filter(t => t.id !== task.id), task]; $('task-form').reset(); $('filter-member').value = ''; $('filter-status').value = ''; renderTasks(); notice('Task added.'); window.activityTaskSaved?.();
  } catch (error) { notice(error.message, true); }
  finally { button.disabled = false; }
});
$('family-profiles-form').addEventListener('submit', async event => {
  event.preventDefault();
  const button = event.submitter; button.disabled = true;
  const members = Array.from(document.querySelectorAll('.family-member-profile')).map(card => {
    const contact = card.querySelector('.family-contact').value.trim();
    return {
      member_id: Number(card.dataset.memberId),
      role: card.querySelector('.family-role').value,
      age: card.querySelector('.family-age').value === '' ? null : Number(card.querySelector('.family-age').value),
      imessage_handle: contact || null,
      alerts_enabled: card.querySelector('.family-contact-enabled').checked
    };
  });
  try {
    await api('/family-members/directory', {method: 'PUT', body: JSON.stringify({members})});
    await load();
    notice('All family profiles and contacts are saved securely.');
  } catch (error) { notice(error.message, true); }
  finally { button.disabled = false; }
});
$('member-form').addEventListener('submit', async event => {
  event.preventDefault(); const name = $('member-name').value.trim(); if (!name) { notice('Please enter a name.', true); $('member-name').focus(); return; }
  const button = event.submitter; button.disabled = true;
  try {
    const age = $('member-age').value;
    const contact = $('member-contact').value.trim();
    const member = await api('/family-members/with-contact', {method: 'POST', body: JSON.stringify({
      name,
      role: $('member-role').value,
      age: age === '' ? null : Number(age),
      imessage_handle: contact || null,
      alerts_enabled: true
    })});
    $('member-form').reset();
    await load();
    notice(`${member.name} added to the family${contact ? ' with an encrypted messaging contact' : ''}.`);
  }
  catch (error) { notice(error.message, true); }
  finally { button.disabled = false; }
});
$('refresh').addEventListener('click', load);
$('filter-member').addEventListener('change', renderTasks);
$('filter-status').addEventListener('change', renderTasks);
document.querySelectorAll('form button').forEach(b => b.disabled = true);
regionalReady.then(load).catch(error => notice(error.message, true));

// Optional structured access for browsers that support WebMCP.
if (document.modelContext?.registerTool) {
  const lifecycle = new AbortController();
  window.addEventListener('pagehide', () => lifecycle.abort(), {once: true});
  try {
    Promise.resolve(document.modelContext.registerTool({
      name: 'read_family_tasks',
      title: 'Read family tasks',
      description: 'Read the saved family members and tasks. Does not change saved data.',
      inputSchema: {type: 'object', properties: {}, additionalProperties: false},
      annotations: {readOnlyHint: true, untrustedContentHint: true},
      async execute(input) {
        if (!input || typeof input !== 'object' || Array.isArray(input) || Object.keys(input).length) throw new Error('Expected an empty object.');
        const [members, tasks] = await Promise.all([all('/family-members'), all('/tasks')]);
        state.members = members; state.tasks = tasks; renderMembers(); renderTasks();
        return {members, tasks};
      }
    }, {signal: lifecycle.signal})).catch(() => {});
  } catch { /* The dashboard also works without browser tool support. */ }
}

let icloudEditId = null, icloudEtag = null, icloudRequestId = crypto.randomUUID();
async function loadIcloudCalendars() {
  const selected = $('icloud-target').value;
  const rows = await api('/calendar/icloud/calendars');
  $('icloud-target').replaceChildren(new Option('Choose a calendar', ''));
  for(const row of rows) $('icloud-target').add(new Option(row.label,row.key));
  $('icloud-target').value=selected;
}
function browserDate(value) {
  const d=new Date(value),pad=n=>String(n).padStart(2,'0');
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
async function openIcloudEvent(id) {
  const save=$('icloud-event-form').querySelector('button[type=submit]');save.disabled=true;save.textContent='Save changes';
  $('icloud-message').textContent='Loading appointment…';
  try {
    await loadIcloudCalendars();
    const e=await api(`/calendar/icloud/events/${id}`);
    icloudEditId=id;icloudEtag=e.etag;icloudRequestId=crypto.randomUUID();
    $('icloud-repeat').value='none';$('icloud-repeat').disabled=true;$('icloud-repeat-until').value='';$('icloud-repeat-until').disabled=true;
    $('icloud-target').value=e.calendar_key;$('icloud-target').disabled=true;
    $('icloud-title').value=e.title;$('icloud-start').value=browserDate(e.start);$('icloud-end').value=browserDate(e.end);
    $('icloud-location').value=e.location;$('icloud-description').value=e.description;
    $('icloud-editor').open=true;$('icloud-editor').scrollIntoView({behavior:'smooth'});$('icloud-message').textContent='Update the details, then choose Save changes.';save.disabled=false;return e;
  } catch(error) { $('icloud-message').textContent=error.message;save.disabled=true;return null; }
}
$('icloud-new').addEventListener('click',()=>{
  $('icloud-event-form').reset();$('icloud-target').disabled=false;$('icloud-repeat').disabled=false;$('icloud-repeat-until').disabled=true;icloudEditId=null;icloudEtag=null;icloudRequestId=crypto.randomUUID();$('icloud-message').textContent='New event. Choose its destination calendar.';
});
$('icloud-repeat').addEventListener('change',()=>{ $('icloud-repeat-until').disabled=$('icloud-repeat').value==='none'; if($('icloud-repeat-until').disabled) $('icloud-repeat-until').value=''; });
$('icloud-event-form').addEventListener('submit',async event=>{
  event.preventDefault();const button=event.target.querySelector('button');button.disabled=true;
  try {
    const body={calendar_key:$('icloud-target').value,title:$('icloud-title').value,start:new Date($('icloud-start').value).toISOString(),end:new Date($('icloud-end').value).toISOString(),location:$('icloud-location').value,description:$('icloud-description').value,request_id:icloudRequestId,etag:icloudEtag,repeat:$('icloud-repeat').value,repeat_until:$('icloud-repeat-until').value||null,timezone_name:Intl.DateTimeFormat().resolvedOptions().timeZone};
    await api(!icloudEditId && window.calendarRequestOrigin ? `/calendar/icloud/requests/${window.calendarRequestOrigin.id}/events/${window.calendarRequestOrigin.index}` : '/calendar/icloud/events'+(icloudEditId ? '/'+icloudEditId : ''),{method:icloudEditId?'PUT':'POST',body:JSON.stringify(body)});
    window.calendarRequestOrigin=null; window.loadAllRequests && loadConciergeInbox();
    const savedMessage=icloudEditId?'Appointment updated in iCloud.':'Appointment added to iCloud.';
    $('icloud-new').click();$('icloud-message').textContent=savedMessage;await loadCalendar();window.appointmentSaved?.(savedMessage);
  } catch(error) { $('icloud-message').textContent=error.message; } finally {button.disabled=false;}
});
$('load-archive').addEventListener('click',async()=>{
  try {const rows=await api('/calendar/archive');$('calendar-archive').replaceChildren(...(rows.length?rows.map(e=>element('p',`${e.start.slice(0,10)} · ${e.title} · ${e.calendar}`)):[element('p','No locally archived events yet.')]));}
  catch(error){$('calendar-archive').textContent=error.message;}
});
const sourceLabels = {google: 'Google Calendar', icloud: 'iCloud Calendar'};
let calendarLoaded = false;
function showView(view) {
  const headings = {events: 'What shall we go see?', tasks: 'What’s on our list?', calendar: 'What’s coming up?', departures: 'When should we leave?', weather: 'What should we wear?', concierge: 'What can I organize?', alerts: 'Who needs a reminder?'};
  for (const name of Object.keys(headings)) {
    $(name + '-view').hidden = name !== view;
    $('show-' + name).setAttribute('aria-pressed', String(name === view));
  }
  document.querySelector('h1').textContent = headings[view];
  $('refresh').hidden = view !== 'tasks';
  history.replaceState(null, '', view === 'tasks' ? location.pathname : '#' + view);
  if (view === 'calendar' && !calendarLoaded) loadCalendar();
  if (view === 'departures') loadDeparturePlanner();
  if (view === 'weather') loadWeather();
  if (view === 'concierge') loadConciergeInbox();
  if (view === 'alerts') loadAlerts();
  if (view === 'events') loadConcerts();
}
$('show-tasks').addEventListener('click', () => showView('tasks'));
$('show-calendar').addEventListener('click', () => showView('calendar'));
$('show-departures').addEventListener('click', () => showView('departures'));
$('show-weather').addEventListener('click', () => showView('weather'));
$('show-concierge').addEventListener('click', () => showView('concierge'));
$('show-alerts').addEventListener('click', () => showView('alerts'));
$('refresh-calendar').addEventListener('click', loadCalendar);
function formatEventTime(event, zone) {
  const dateFormat = {weekday: 'short', month: 'short', day: 'numeric'};
  if (event.all_day) {
    const start = new Date(event.start + 'T12:00:00Z'), last = new Date(event.end + 'T12:00:00Z');
    last.setUTCDate(last.getUTCDate() - 1); // Calendar all-day end dates are exclusive.
    const format = new Intl.DateTimeFormat(regional.locale, {...dateFormat, timeZone: 'UTC'});
    return `${format.format(start)}${last > start ? ' – ' + format.format(last) : ''} · All day`;
  }
  const start = new Date(event.start), end = new Date(event.end);
  const day = new Intl.DateTimeFormat(regional.locale, {...dateFormat, timeZone: zone});
  const clock = new Intl.DateTimeFormat(regional.locale, {hour: 'numeric', minute: '2-digit', timeZone: zone});
  return `${day.format(start)} · ${clock.format(start)} – ${day.format(start) === day.format(end) ? '' : day.format(end) + ' · '}${clock.format(end)}`;
}

function renderCalendarAssignments(data) {
  $('calendar-assignment-list').replaceChildren(...data.calendars.map(calendar => {
    const card = element('article', undefined, 'calendar-assignment-card');
    card.dataset.calendarKey = calendar.key;
    const heading = element('div', undefined, 'calendar-assignment-heading');
    heading.append(
      element('h4', calendar.name),
      element('span', sourceLabels[calendar.source] || calendar.source)
    );
    card.append(heading);
    const choices = element('div', undefined, 'calendar-member-choices');
    for (const member of data.members) {
      const label = element('label');
      const input = document.createElement('input');
      input.type = 'checkbox'; input.className = 'calendar-assignment-member';
      input.value = member.id; input.checked = calendar.member_ids.includes(member.id);
      label.append(input, element('span', member.name));
      choices.append(label);
    }
    if (!data.members.length) choices.append(element('p', 'Add family members before assigning calendars.', 'empty'));
    card.append(choices);
    return card;
  }));
  if (!data.calendars.length) {
    $('calendar-assignment-list').append(element('p', 'No connected calendars are available yet.', 'empty'));
  }
}

async function loadCalendar() {
  $('refresh-calendar').disabled = true;
  $('calendar-message').textContent = 'Checking your calendars…';
  try {
    const [eventsResult, assignmentsResult] = await Promise.allSettled([
      api('/calendar/events'), api('/calendar/assignments')
    ]);
    if (eventsResult.status === 'rejected') throw eventsResult.reason;
    const data = eventsResult.value; state.calendarData = data; calendarLoaded = true;
    if (assignmentsResult.status === 'fulfilled') {
      state.assignments = assignmentsResult.value;
      renderCalendarAssignments(assignmentsResult.value);
      $('calendar-assignment-status').textContent = '';
    } else {
      $('calendar-assignment-status').textContent = 'Calendar assignments could not be loaded. Refresh to try again.';
    }
    $('calendar-zone').textContent = `Times shown in ${data.timezone.replaceAll('_', ' ')}. Google is read-only; Open an appointment to edit its iCloud details.`;
    $('calendar-sources').replaceChildren(...data.sources.map(source => {
      const card = element('div', undefined, `calendar-source ${source.status}`);
      card.append(element('strong', sourceLabels[source.source]), element('p', source.message)); return card;
    }));
    await loadIcloudCalendars();
    renderConflicts(data);
    const conflicting = new Set((data.conflicts || []).flatMap(c => c.event_ids));
    $('calendar-events').replaceChildren(...data.events.map(event => {
      const row = element('article', undefined, 'calendar-event'), details = element('div');
      row.id = `calendar-event-${event.id}`;
      details.append(element('h3', event.title));
      if (conflicting.has(event.id)) { row.classList.add('has-conflict'); details.append(element('span', 'Possible conflict', 'conflict-badge')); }
      if (event.location) details.append(element('p', event.location));
      details.append(element('span', `${sourceLabels[event.source]} · ${event.calendar}`, 'calendar-source-label'));
      if(event.source === 'icloud' && !event.all_day) {
        const edit=element('button','Edit iCloud event','secondary'); edit.type='button';
        edit.addEventListener('click',()=>openIcloudEvent(event.id)); details.append(edit);
      }
      row.append(element('div', formatEventTime(event, data.timezone), 'calendar-time'), details); return row;
    }));
    const failures = data.sources.some(s => s.status === 'error'), connected = data.sources.some(s => s.status === 'connected');
    $('calendar-message').textContent = failures ? 'Some calendars could not be refreshed. Events below may be incomplete.' : !connected ? 'Connect Google and iCloud to see your upcoming events here.' : data.events.length ? `${data.events.length} upcoming ${data.events.length === 1 ? 'event' : 'events'}.` : 'No events in the next 14 days on your connected calendars.';
  } catch (error) {
    $('calendar-conflicts').hidden = true;
    $('calendar-message').textContent = 'Calendar refresh failed. Any events still shown are from the previous refresh. Please try again.';
  } finally { $('refresh-calendar').disabled = false; window.renderAgenda?.(); }
}
$('calendar-assignments-form').addEventListener('submit', async event => {
  event.preventDefault();
  const button = event.submitter; button.disabled = true;
  $('calendar-assignment-status').textContent = 'Saving calendar assignments…';
  const cards = Array.from(document.querySelectorAll('.calendar-assignment-card'));
  if (!cards.length) {
    $('calendar-assignment-status').textContent = 'Connect at least one calendar before saving assignments.';
    button.disabled = false;
    return;
  }
  const assignments = cards.map(card => ({
    calendar_key: card.dataset.calendarKey,
    member_ids: Array.from(card.querySelectorAll('.calendar-assignment-member:checked')).map(input => Number(input.value))
  }));
  try {
    const saved = await api('/calendar/assignments', {
      method: 'PUT', body: JSON.stringify({assignments})
    });
    renderCalendarAssignments(saved);
    $('calendar-assignment-status').textContent = 'Calendar assignments saved. Morning briefings will use these schedules.';
  } catch (error) {
    $('calendar-assignment-status').textContent = error.message;
  } finally { button.disabled = false; }
});
let concertData = {events: [], sources: []};
async function loadConcerts(refresh = false) {
  const button = $('refresh-events'); button.disabled = true;
  $('events-message').textContent = refresh ? 'Checking venue listings…' : 'Loading concerts…';
  try {
    concertData = await api('/events/concerts' + (refresh ? '/refresh' : ''), {method: refresh ? 'POST' : 'GET'});
    const prefs = concertData.preferences || {};
    $('event-artists').value = (prefs.artists || []).join(', ');
    $('event-genres').value = (prefs.genres || []).join(', ');
    $('event-budget').value = prefs.max_ticket_price ?? '';
    $('event-unknown-price').checked = prefs.include_unknown_prices !== false;
    $('event-all-ages').checked = Boolean(prefs.all_ages_only);
    $('event-prefs-enabled').checked = Boolean(prefs.enabled);
    const selected = $('events-month').value;
    $('events-month').replaceChildren(new Option('All months', ''));
    for (const month of [...new Set(concertData.events.map(e => e.start.slice(0, 7)))]) $('events-month').add(new Option(new Date(month + '-15T12:00:00').toLocaleDateString('en-US', {month: 'long'}), month));
    $('events-month').value = selected;
    $('events-sources').replaceChildren(...concertData.sources.map(source => element('p', `${source.name}: ${source.status === 'ok' ? 'Checked' : source.status === 'not_checked' ? 'Not checked yet' : 'Unavailable — any previous listings may be outdated'}${source.checked_at ? ' · ' + new Date(source.checked_at).toLocaleString() : ''}`, 'optional')));
    renderConcerts();
  } catch (error) { $('events-message').textContent = error.message; }
  finally { button.disabled = false; }
}
function renderConcerts() {
  const query = $('events-query').value.toLowerCase(), month = $('events-month').value;
  const rows = concertData.events.filter(e => (!$('event-match-prefs').checked || e.matches_preferences) && (!month || e.start.startsWith(month)) && (!$('events-saved').value || e.shortlisted) && `${e.title} ${e.genre} ${e.venue}`.toLowerCase().includes(query));
  $('events-message').textContent = `${rows.length} concerts shown. ` + (concertData.events.length ? 'Prices and age restrictions are shown only when provided by the venue.' : 'Use Refresh events to check the selected venues.');
  $('concert-list').replaceChildren(...rows.map(e => {
    const card = element('article', undefined, 'panel');
    card.append(element('h3', e.title), element('p', new Date(e.start).toLocaleString(regional.locale, {timeZone: regional.timezone, dateStyle: 'medium', ...(e.time_known ? {timeStyle: 'short'} : {})}) + ' · ' + e.venue), element('p', e.address, 'optional'));
    card.append(element('p', `${e.status} · ${e.genre} · Price: ${e.price || 'Not listed'} · Ages: ${e.age_restriction}`));
    if (e.stale) card.append(element('p', 'This source could not be refreshed. Check the listing before making plans.', 'error'));
    const link = element('a', 'View official listing'); link.href = e.url; link.target = '_blank'; link.rel = 'noopener noreferrer';
    const save = element('button', e.shortlisted ? 'Remove from shortlist' : 'Shortlist', 'secondary'); save.type = 'button';
    save.addEventListener('click', async () => {
      save.disabled = true;
      try { const result = await api(`/events/concerts/${e.id}/shortlist`, {method: 'PUT', body: JSON.stringify({shortlisted: !e.shortlisted})}); e.shortlisted = result.shortlisted; renderConcerts(); }
      catch (error) { $('events-message').textContent = error.message; save.disabled = false; }
    });
    card.append(link, document.createTextNode(' '), save); return card;
  }));
}
$('show-events').addEventListener('click', () => showView('events'));
$('refresh-events').addEventListener('click', () => loadConcerts(true));
$('event-preferences-form').addEventListener('submit', async event => {
  event.preventDefault(); const button = event.target.querySelector('button'); button.disabled = true;
  const split = id => $(id).value.split(',').map(s => s.trim()).filter(Boolean);
  try {
    await api('/events/preferences', {method: 'PUT', body: JSON.stringify({enabled: $('event-prefs-enabled').checked, artists: split('event-artists'), genres: split('event-genres'), max_ticket_price: $('event-budget').value === '' ? null : Number($('event-budget').value), include_unknown_prices: $('event-unknown-price').checked, all_ages_only: $('event-all-ages').checked})});
    await loadConcerts(); $('event-prefs-message').textContent = 'Preferences saved.';
  } catch (error) { $('event-prefs-message').textContent = error.message; }
  finally { button.disabled = false; }
});
for (const id of ['events-query', 'events-month', 'events-saved', 'event-match-prefs']) $(id).addEventListener('input', renderConcerts);
if (window.location.hash === '#events') showView('events');
if (window.location.hash === '#calendar') showView('calendar');
if (window.location.hash === '#departures') showView('departures');
if (window.location.hash === '#weather') showView('weather');
if (window.location.hash === '#concierge') showView('concierge');
if (window.location.hash === '#alerts') showView('alerts');

function weatherNumber(value, suffix = '') {
  return value === null || value === undefined ? 'Not available' : `${Math.round(value)}${suffix}`;
}
function renderWeather(data) {
  const temperatureUnit = data.units?.temperature || '°F';
  const current = data.current || {};
  $('weather-summary').textContent = `${data.location} · ${current.condition} · ${weatherNumber(current.temperature, temperatureUnit)} now, feels like ${weatherNumber(current.apparent_temperature, temperatureUnit)}.`;
  $('weather-days').replaceChildren(...data.days.map((day, index) => {
    const card = element('article', undefined, 'weather-day');
    const date = new Date(day.date + 'T12:00:00Z');
    const heading = index === 0 ? 'Today' : new Intl.DateTimeFormat(regional.locale, {weekday: 'long', month: 'short', day: 'numeric', timeZone: 'UTC'}).format(date);
    card.append(element('h3', heading));
    card.append(element('p', `${day.condition} · ${weatherNumber(day.temperature_min, '°')}–${weatherNumber(day.temperature_max, temperatureUnit)} · Rain ${weatherNumber(day.precipitation_probability, '%')} · UV ${weatherNumber(day.uv_index)}`, 'weather-facts'));
    const list = element('ul');
    day.recommendations.forEach(item => list.append(element('li', item)));
    card.append(list);
    return card;
  }));
}
function configureTemperatureInput(id, value, min, max) {
  const input = $(id), metric = regional.units === 'metric';
  const convert = number => metric ? (number - 32) * 5 / 9 : number;
  input.min = Math.ceil(convert(min)); input.max = Math.floor(convert(max));
  input.value = Math.max(Number(input.min), Math.min(Number(input.max), Math.round(convert(value))));
  input.parentElement.querySelector('.field-unit').textContent = `${metric ? '°C' : '°F'} feels-like temperature`;
}
function thresholdFahrenheit(id) {
  const value = Number($(id).value);
  return regional.units === 'metric' ? Math.round(value * 9 / 5 + 32) : value;
}
async function loadWeather() {
  await regionalReady;
  $('refresh-weather').disabled = true;
  $('weather-summary').textContent = 'Checking weather settings…';
  try {
    const settings = await api('/weather/settings');
    $('weather-location').value = settings.location_name || settings.suggested_location || '';
    $('weather-rain-threshold').value = settings.rain_probability_percent;
    configureTemperatureInput('weather-jacket-threshold', settings.jacket_below_fahrenheit, -50, 100);
    configureTemperatureInput('weather-light-threshold', settings.dress_light_above_fahrenheit, 40, 140);
    if (!settings.configured) {
      $('weather-days').replaceChildren();
      $('weather-summary').textContent = 'Confirm the suggested city or postal code, then save to see the forecast.';
      return;
    }
    $('weather-summary').textContent = 'Loading the family forecast…';
    renderWeather(await api('/weather/forecast'));
  } catch (error) {
    $('weather-summary').textContent = error.message;
  } finally { $('refresh-weather').disabled = false; }
}
$('refresh-weather').addEventListener('click', loadWeather);
$('weather-form').addEventListener('submit', async event => {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  $('weather-save-message').className = 'form-message';
  $('weather-save-message').textContent = 'Saving the location and checking the forecast…';
  try {
    await api('/weather/settings', {
      method: 'PUT',
      body: JSON.stringify({
        location: $('weather-location').value.trim(),
        rain_probability_percent: Number($('weather-rain-threshold').value),
        jacket_below_fahrenheit: thresholdFahrenheit('weather-jacket-threshold'),
        dress_light_above_fahrenheit: thresholdFahrenheit('weather-light-threshold')
      })
    });
    await loadWeather();
    $('weather-save-message').textContent = 'Weather preferences saved.';
  } catch (error) {
    $('weather-save-message').className = 'form-message error';
    $('weather-save-message').textContent = error.message;
  } finally { button.disabled = false; }
});

let activeConciergeInboxId = null;
let activeConciergeRequester = null;

function formatConciergeClock(value) {
  const [hour, minute] = value.split(':').map(Number);
  const date = new Date(Date.UTC(2000, 0, 1, hour, minute));
  return new Intl.DateTimeFormat(regional.locale, {
    hour: 'numeric', minute: '2-digit', timeZone: 'UTC'
  }).format(date);
}

function combineBackToBackEvents(events) {
  return events.reduce((combined, event) => {
    const previous = combined.at(-1);
    if (previous && previous.end_time === event.start_time) {
      previous.title = `${previous.title} + ${event.title}`;
      previous.end_time = event.end_time;
      previous.time_assumed = previous.time_assumed || event.time_assumed;
    } else {
      combined.push({...event});
    }
    return combined;
  }, []);
}

async function previewConcierge(driver = null, transportationMode = null, pickupBy = null, combineAdjacentEvents = false, savedPlan = null) {
  const button = $('concierge-form').querySelector('button[type="submit"]');
  button.disabled = true;
  $('concierge-status').textContent = 'Preparing a safe preview…';
  try {
    const plan = savedPlan || await api('/concierge/preview', {
      method: 'POST', body: JSON.stringify({
        text: $('concierge-text').value.trim(), driver,
        transportation_mode: transportationMode, pickup_by: pickupBy,
        combine_adjacent_events: combineAdjacentEvents,
        requester_name: activeConciergeRequester
      })
    });
    if (plan.request_type === 'schedule_query') {
      const wrapper = element('div'); wrapper.append(element('p', plan.reply_text));
      for (const e of plan.schedule_events || []) wrapper.append(element('p', `${e.all_day ? 'All day' : new Date(e.start).toLocaleString()} · ${e.title}`));
      $('concierge-preview').replaceChildren(wrapper);
      $('concierge-status').textContent = 'Calendar lookup only. No appointment created.'; return;
    }
    if (plan.request_type === 'acknowledgment') {
      $('concierge-preview').replaceChildren(element('p', plan.reply_text));
      $('concierge-status').textContent = 'Receipt test recognized. No task or appointment created.';
      return;
    }
    if (plan.request_type === 'events') {
      const results = element('div', undefined, 'concierge-plan');
      results.append(element('h3', 'Concert search results'), element('p', plan.reply_text));
      for (const concert of plan.event_results || []) {
        const card = element('article', undefined, 'panel');
        card.append(element('h4', concert.title), element('p', `${concert.start.slice(0, 10)} · ${concert.venue} · ${concert.genre} · ${concert.status}`));
        const link = element('a', 'View official listing'); link.href = concert.url; link.target = '_blank'; link.rel = 'noopener noreferrer'; card.append(link); results.append(card);
      }
      const open = element('button', 'Open Events to shortlist'); open.type = 'button'; open.addEventListener('click', () => showView('events')); results.append(open);
      $('concierge-preview').replaceChildren(results); $('concierge-status').textContent = 'Search complete. Nothing booked or sent.';
      return;
    }
    const wrapper = element('div', undefined, 'concierge-plan');
    const details = document.createElement('dl');
    const rows = [
      ['What', plan.title || 'Add a title'],
      ['Who', plan.primary_member || 'Choose a person'],
      ['When', [plan.date, plan.time].filter(Boolean).join(' · ') || 'Choose a time']
    ];
    rows.forEach(([term, value]) => { details.append(element('dt', term), element('dd', value)); });
    wrapper.append(details);
    if (plan.reply_text) wrapper.append(element('p', plan.reply_text, 'safe-preview'));
    let fieldEdits = null;
    if (activeConciergeInboxId !== null && (plan.calendar_events || []).length <= 1) {
      const editor = element('fieldset'); editor.append(element('legend', 'Edit plan details'));
      const inputs = {};
      for (const [key, label, type, value] of [
        ['title','Title','text',plan.title], ['date','Date','date',plan.date], ['time','Start time','time',plan.time],
        ['end_time','End time','time',plan.calendar_events?.[0]?.end_time]]) {
        const l=element('label',label), input=document.createElement('input'); input.type=type; input.value=value || ''; if(key==='title')input.maxLength=200; l.append(input); editor.append(l); inputs[key]=input;
      }
      const memberLabel=element('label','Assigned person'), member=document.createElement('select');
      const notifyLabel=element('label','Notify (select one or more)'), notify=document.createElement('select'); notify.multiple=true;
      for(const m of state.members) { member.add(new Option(m.name,m.name)); const o=new Option(m.name,m.name);o.selected=plan.notification_members.includes(m.name);notify.add(o); }
      member.value=plan.primary_member || '';memberLabel.append(member);notifyLabel.append(notify);editor.append(memberLabel,notifyLabel);
      const repeatLabel=element('label','Repeat'),repeat=document.createElement('select');repeat.add(new Option('Does not repeat','none'));repeat.add(new Option('Weekly','weekly'));repeat.value=plan.repeat_interval || 'none';repeatLabel.append(repeat);editor.append(repeatLabel);
      fieldEdits=()=>({...Object.fromEntries(Object.entries(inputs).map(([k,v])=>[k,v.value || null])),primary_member:member.value,notification_members:[...notify.selectedOptions].map(o=>o.value),repeat_interval:repeat.value});
      const more = element('details',undefined,'plan-more'); more.append(element('summary','Edit details and options'),editor); wrapper.append(more);
    }
    let combineEvents = null;
    if (Array.isArray(plan.calendar_events) && plan.calendar_events.length > 1) {
      const eventList = element('ol', undefined, 'concierge-event-list');
      const renderEventList = () => {
        const displayedEvents = combineEvents?.checked ? combineBackToBackEvents(plan.calendar_events) : plan.calendar_events;
        eventList.replaceChildren(...displayedEvents.map(event => {
          const assumption = event.time_assumed ? ' · PM inferred from the afternoon/evening schedule' : '';
          return element('li', `${event.title} · ${formatConciergeClock(event.start_time)}–${formatConciergeClock(event.end_time)}${assumption}`);
        }));
      };
      const hasAdjacentEvents = plan.calendar_events.some((event, index) => index > 0 && plan.calendar_events[index - 1].end_time === event.start_time);
      wrapper.append(element('h3', 'Calendar events'), eventList);
      if (hasAdjacentEvents) {
        const combineLabel = element('label', undefined, 'choice');
        combineEvents = document.createElement('input');
        combineEvents.type = 'checkbox';
        combineEvents.checked = Boolean(plan.combine_adjacent_events);
        combineEvents.addEventListener('change', renderEventList);
        combineLabel.append(combineEvents, element('span', 'Combine back-to-back events'));
        wrapper.append(combineLabel);
      }
      renderEventList();
    }
    if (plan.missing_fields.length) wrapper.append(element('p', 'Still needed: ' + plan.missing_fields.join(', ') + '.', 'review-warning'));
    const actions = element('ul');
    plan.proposed_actions.forEach(action => actions.append(element('li', action)));
    wrapper.append(element('h3', 'Proposed actions'), actions);
    let modeSelect = null;
    let driverSelect = null;
    let pickupSelect = null;
    if (plan.pickup_options.length && plan.transportation_mode) {
      const modeLabel = element('label', 'Transportation needed');
      modeSelect = document.createElement('select');
      modeSelect.append(
        new Option('Drop-off and pickup', 'dropoff_and_pickup'),
        new Option('Pickup only — already at school', 'pickup_only'),
        new Option('No transportation needed', 'none')
      );
      modeSelect.value = plan.transportation_mode;
      modeLabel.append(modeSelect);

      const driverLabel = element('label', 'Drop-off driver');
      driverSelect = document.createElement('select');
      driverSelect.append(new Option('Choose a parent', ''));
      plan.driver_options.forEach(name => driverSelect.append(new Option(name, name)));
      driverSelect.value = plan.driver || '';
      driverLabel.append(driverSelect);

      const pickupLabel = element('label', 'Pickup by');
      pickupSelect = document.createElement('select');
      pickupSelect.append(new Option('Choose pickup', ''));
      plan.pickup_options.forEach(name => pickupSelect.append(new Option(name, name)));
      pickupSelect.value = plan.pickup_by || '';
      pickupLabel.append(pickupSelect);
      const showRelevantTransportationFields = () => {
        driverLabel.hidden = modeSelect.value !== 'dropoff_and_pickup';
        pickupLabel.hidden = modeSelect.value === 'none';
      };
      modeSelect.addEventListener('change', showRelevantTransportationFields);
      wrapper.append(modeLabel, driverLabel, pickupLabel);
      showRelevantTransportationFields();
    }
    const safeMessage = element('p', activeConciergeInboxId !== null ? 'Draft saved. No task or calendar entry has been created by saving this draft.' : 'Review before adding.', 'safe-preview');
    wrapper.append(safeMessage);
    if (activeConciergeInboxId !== null) {
      const itemId=activeConciergeInboxId;
      let saveTimer, saveQueue=Promise.resolve(), revision=0;
      const draftStatus=element('p','Draft saved automatically.','optional');draftStatus.setAttribute('role','status');wrapper.append(draftStatus);
      const controls=()=>[...$('concierge-preview').querySelectorAll('button')];
      const queueSave=()=>{
        const version=++revision;
        controls().forEach(b=>b.disabled=true);
        draftStatus.textContent='Saving draft…';
        clearTimeout(saveTimer);
        saveTimer=setTimeout(()=>{
          const mode=modeSelect?modeSelect.value:plan.transportation_mode;
          const payload={text:$('concierge-text').value.trim(),keep_in_inbox:true,edits:fieldEdits?fieldEdits():null,
            driver:mode==='dropoff_and_pickup'?(driverSelect?.value||null):null,
            transportation_mode:mode,pickup_by:mode!=='none'?(pickupSelect?.value||null):null,
            combine_adjacent_events:combineEvents?combineEvents.checked:Boolean(plan.combine_adjacent_events)};
          saveQueue=saveQueue.catch(()=>{}).then(async()=>{
            try {const saved=await api(`/concierge/inbox/${itemId}/plan`,{method:'PUT',body:JSON.stringify(payload)});
              if(version!==revision)return;
              Object.assign(plan,saved.plan);
              draftStatus.textContent='Draft saved. '+(plan.missing_fields?.length?'Still needed: '+plan.missing_fields.join(', '):'Ready to add.');
              controls().forEach(b=>b.disabled=false);
            }catch(error){if(version===revision)draftStatus.textContent='Draft not saved: '+error.message+' Change a field to retry.';}
          });
        },650);
      };
      wrapper.addEventListener('input',queueSave);wrapper.addEventListener('change',queueSave);
    }
    if (plan.request_type === 'task') {
      const createButton = element('button', 'Create this task', 'concierge-action');
      createButton.type = 'button';
      createButton.addEventListener('click', async () => {
        if(plan.missing_fields?.length){$('concierge-status').textContent='Please complete: '+plan.missing_fields.join(', ');return;}
        createButton.disabled = true;
        try {
          let dueAt = null;
          if (plan.date && plan.time) {
            const localDue = new Date(`${plan.date}T${plan.time}:00`);
            if (!Number.isNaN(localDue.getTime())) dueAt = localDue.toISOString();
          }
          const task = await api(activeConciergeInboxId !== null ? `/concierge/inbox/${activeConciergeInboxId}/task` : '/tasks', {
            method: 'POST',
            body: JSON.stringify({
              title: plan.title,
              description: plan.transportation_mode === 'pickup_only'
                ? `Transportation: pickup only — ${plan.pickup_by}.`
                : plan.transportation_mode === 'dropoff_and_pickup'
                  ? `Transportation: drop-off by ${plan.driver}; pickup by ${plan.pickup_by}.`
                  : plan.transportation_mode === 'none' ? 'Transportation: none needed.' : null,
              assigned_to: plan.primary_member,
              due_at: dueAt,
              reminder_minutes_before: null,
              repeat_interval: plan.repeat_interval || 'none'
            })
          });
          state.tasks = [...state.tasks.filter(t => t.id !== task.id), task];
          renderTasks();
          createButton.textContent = 'Task created';
          safeMessage.textContent = `Saved as a task for ${task.assigned_to_name}. No notifications were sent.`;
          $('concierge-status').textContent = 'Task created successfully.';
          if (activeConciergeInboxId !== null) {
            try {
              await api(`/concierge/inbox/${activeConciergeInboxId}`, {
                method: 'PATCH', body: JSON.stringify({status: 'handled'})
              });
              activeConciergeInboxId = null;
              activeConciergeRequester = null;
              await loadConciergeInbox();
            } catch {
              $('concierge-status').textContent = 'Task created. The inbox request could not be marked handled; you can dismiss it below.';
            }
          }
        } catch (error) {
          createButton.disabled = false;
          $('concierge-status').textContent = error.message;
        }
      });
      wrapper.append(createButton);
    } else if (plan.request_type === 'calendar') {
      wrapper.append(element('p', 'Use Add to calendar below to review and save to iCloud.', 'optional'));
    }
    $('concierge-preview').replaceChildren(wrapper);
    $('concierge-status').textContent = 'Plan ready for your review.';
  } catch (error) {
    $('concierge-status').textContent = error.message;
  } finally { button.disabled = false; }
}

$('concierge-form').addEventListener('submit', async event => {
  event.preventDefault();
  activeConciergeInboxId = null;
  activeConciergeRequester = null;
  await previewConcierge();
});

function displayRequestType(value) {
  return value === 'needs_review' ? 'Needs clarification' : (value || 'Needs review');
}

function renderConciergeInbox(items) {
  $('concierge-inbox-list').replaceChildren(...items.map(item => {
    const card = element('article', undefined, 'concierge-inbox-item');
    const heading = element('div', undefined, 'concierge-inbox-item-heading');
    heading.append(
      element('h3', item.member_name),
      element('span', new Intl.DateTimeFormat(regional.locale, {dateStyle: 'medium', timeStyle: 'short', timeZone: regional.timezone}).format(new Date(item.received_at)))
    );
    const request = element('p', item.request_text, 'concierge-request-text');
    const plan = item.plan || {};
    const details = element('p', `${displayRequestType(plan.request_type)} · ${plan.title || 'Title needs review'}`, 'concierge-plan-summary');
    card.append(heading, request, details);
    if (Array.isArray(plan.missing_fields) && plan.missing_fields.length) {
      card.append(element('p', `Still needed: ${plan.missing_fields.join(', ')}.`, 'review-warning'));
    }
    if (plan.reply_text) card.append(element('p', plan.reply_text, 'safe-preview'));
    if (plan.dialog_state === 'awaiting_details') {
      const form = document.createElement('form');
      const label = element('label', `Answer for request #${item.id}`);
      const input = document.createElement('input');
      input.id = `concierge-reply-${item.id}`;
      label.htmlFor = input.id;
      input.required = true;
      input.maxLength = 2000;
      const submit = element('button', 'Send answer');
      submit.type = 'submit';
      let replyId = null;
      input.addEventListener('input', () => { replyId = null; });
      form.append(label, input, submit);
      form.addEventListener('submit', async event => {
        event.preventDefault();
        submit.disabled = true;
        input.disabled = true;
        replyId = replyId || crypto.randomUUID();
        try {
          await api(`/concierge/inbox/${item.id}/reply`, {
            method: 'POST', body: JSON.stringify({text: input.value.trim(), message_guid: replyId})
          });
          await loadConciergeInbox();
        } catch (error) {
          $('concierge-inbox-status').textContent = error.message;
          submit.disabled = false;
          input.disabled = false;
        }
      });
      card.append(form);
    }
    const actions = element('div', undefined, 'concierge-inbox-actions');
    const review = element('button', 'Open this plan', 'secondary');
    review.type = 'button';
    review.addEventListener('click', async () => {
      activeConciergeInboxId = item.id;
      activeConciergeRequester = item.member_name;
      $('concierge-text').value = item.request_text;
      await previewConcierge(
        plan.driver || null,
        plan.transportation_mode || null,
        plan.pickup_by || null,
        Boolean(plan.combine_adjacent_events),
        plan
      );
      $('concierge-form').scrollIntoView({behavior: 'smooth', block: 'start'});
    });
    const dismiss = element('button', 'Dismiss', 'secondary');
    dismiss.type = 'button';
    dismiss.addEventListener('click', async () => {
      review.disabled = true; dismiss.disabled = true;
      try {
        await api(`/concierge/inbox/${item.id}`, {
          method: 'PATCH', body: JSON.stringify({status: 'dismissed'})
        });
        if (activeConciergeInboxId === item.id) {
          activeConciergeInboxId = null;
          activeConciergeRequester = null;
        }
        await loadConciergeInbox();
      } catch (error) {
        review.disabled = false; dismiss.disabled = false;
        $('concierge-inbox-status').textContent = error.message;
      }
    });
    actions.append(review, dismiss);
    card.append(actions);
    return card;
  }));
  if (!items.length) {
    $('concierge-inbox-list').append(element('p', 'Nothing needs your attention.', 'empty'));
  }
}

async function loadConciergeInbox() {
  $('refresh-concierge-inbox').disabled = true;
  $('concierge-inbox-status').textContent = 'Checking for reviewed requests…';
  try {
    const items = await window.loadAllRequests('pending');
    renderConciergeInbox(items);
    $('concierge-inbox-status').textContent = items.length
      ? `${items.length} ${items.length === 1 ? 'request is' : 'requests are'} waiting for review.`
      : '';
  } catch (error) {
    $('concierge-inbox-status').textContent = 'Could not load incoming FA requests. Please refresh.';
  } finally { $('refresh-concierge-inbox').disabled = false; }
}

$('refresh-concierge-inbox').addEventListener('click', loadConciergeInbox);

function mapsDirectionLink(label, origin, destination) {
  const url = new URL('https://www.google.com/maps/dir/');
  url.searchParams.set('api', '1');
  url.searchParams.set('origin', origin);
  url.searchParams.set('destination', destination);
  url.searchParams.set('travelmode', 'driving');
  url.searchParams.set('dir_action', 'navigate');
  const link = element('a', label, 'map-link');
  link.href = url.toString();
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  return link;
}

const weekdayNames = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
let placesConfigured = false;

function setupAddressSuggestions(inputId, listId) {
  const input = $(inputId), list = $(listId);
  let timer;
  input.addEventListener('input', () => {
    clearTimeout(timer);
    list.replaceChildren();
    const query = input.value.trim();
    if (!placesConfigured || query.length < 3) return;
    timer = setTimeout(async () => {
      try {
        const result = await api(`/places/autocomplete?q=${encodeURIComponent(query)}`);
        if (input.value.trim() !== query) return;
        list.replaceChildren(...result.suggestions.map(item => {
          const option = document.createElement('option');
          option.value = item.address;
          return option;
        }));
      } catch (error) {
        list.replaceChildren();
      }
    }, 400);
  });
}

setupAddressSuggestions('home-address', 'home-address-suggestions');
setupAddressSuggestions('commute-address', 'commute-address-suggestions');

function resetCommuteForm() {
  $('commute-form').reset();
  $('commute-id').value = '';
  $('commute-kind').value = 'work';
  $('commute-time').value = '07:00';
  for (const input of document.querySelectorAll('[name="commute-weekday"]')) input.checked = Number(input.value) < 5;
  $('commute-enabled').checked = true;
  $('school-calendar-choice').hidden = true;
  $('save-commute').textContent = 'Add commute schedule';
  $('cancel-commute-edit').hidden = true;
}

function editCommute(schedule) {
  $('commute-id').value = schedule.id;
  $('commute-member').value = schedule.member_id;
  $('commute-kind').value = schedule.kind;
  $('commute-label').value = schedule.label;
  $('commute-address').value = schedule.destination_address;
  $('commute-time').value = schedule.send_time;
  for (const input of document.querySelectorAll('[name="commute-weekday"]')) input.checked = schedule.weekdays.includes(Number(input.value));
  $('commute-school-calendar').checked = schedule.use_school_calendar;
  $('commute-enabled').checked = schedule.enabled;
  $('school-calendar-choice').hidden = schedule.kind !== 'school';
  $('save-commute').textContent = 'Save commute schedule';
  $('cancel-commute-edit').hidden = false;
  $('commute-form').scrollIntoView({behavior: 'smooth', block: 'start'});
}

function renderCommutes(schedules, members, schoolCalendar) {
  state.commutes = schedules;
  const parentSelect = $('commute-member'), selected = parentSelect.value;
  parentSelect.replaceChildren(new Option('Choose a parent', ''));
  for (const member of members.filter(member => member.role === 'parent')) {
    parentSelect.add(new Option(member.name, String(member.id)));
  }
  if ([...parentSelect.options].some(option => option.value === selected)) parentSelect.value = selected;
  const calendarStatus = $('school-calendar-status');
  $('commute-school-calendar').disabled = schoolCalendar.status === 'disabled';
  if (schoolCalendar.status === 'disabled') {
    calendarStatus.textContent = 'School-day filtering is disabled for this installation.';
  } else if (schoolCalendar.status === 'ready') {
    const day = schoolCalendar.is_school_day ? 'a regular school day' : 'not a regular school day';
    calendarStatus.textContent = `Configured school calendar is available. Today is ${day}.`;
  } else {
    calendarStatus.textContent = 'The configured school calendar is unavailable. School traffic texts pause until a verified calendar is available.';
  }
  $('commute-schedule-list').replaceChildren(...schedules.map(schedule => {
    const card = element('article', undefined, 'commute-card');
    const heading = element('div', undefined, 'commute-card-heading');
    heading.append(element('h3', schedule.label), element('span', schedule.enabled ? 'Active' : 'Paused', `commute-state ${schedule.enabled ? 'active' : 'paused'}`));
    const days = schedule.weekdays.map(day => weekdayNames[day]).join(', ');
    card.append(heading, element('p', `${schedule.member_name} · ${schedule.kind === 'school' ? 'School' : 'Work'} · ${schedule.send_time} · ${days}`));
    card.append(element('p', schedule.destination_address, 'commute-address'));
    if (schedule.use_school_calendar) card.append(element('p', 'Skips excluded dates and non-school weekdays in the configured calendar.', 'optional'));
    const actions = element('div', undefined, 'actions');
    const edit = element('button', 'Edit', 'secondary'); edit.type = 'button'; edit.addEventListener('click', () => editCommute(schedule));
    const remove = element('button', 'Delete', 'secondary'); remove.type = 'button';
    remove.addEventListener('click', async () => {
      remove.disabled = true;
      try { await api(`/commutes/${schedule.id}`, {method: 'DELETE'}); await loadDeparturePlanner(); }
      catch (error) { $('commute-save-message').textContent = error.message; remove.disabled = false; }
    });
    actions.append(edit, remove); card.append(actions);
    return card;
  }));
  if (!schedules.length) $('commute-schedule-list').append(element('p', 'No automatic commute traffic texts configured yet.', 'empty'));
}

async function loadDeparturePlanner() {
  $('refresh-departures').disabled = true;
  $('departure-summary').textContent = 'Checking upcoming events…';
  try {
    const results = await Promise.all([
      api('/departure/settings'), api('/calendar/events'), api('/departure/trips'),
      all('/family-members'), api('/commutes'), api('/commutes/school-calendar'), api('/places/status'), api('/departure/traffic')
    ]);
    const settings = results[0], data = results[1];
    const tripPreferences = new Map(results[2].map(preference => [preference.event_id, preference.round_trip]));
    state.calendarData = data;
    $('home-address').value = settings.home_address;
    $('arrival-buffer').value = settings.arrival_buffer_minutes;
    $('parking-buffer').value = settings.parking_walk_minutes;
    placesConfigured = results[6].configured;
    $('places-status').textContent = placesConfigured
      ? 'Start typing to choose a Google address suggestion.'
      : 'Manual address entry is available. Add a Google Places key to enable suggestions.';
    if (placesConfigured && !$('places-attribution').src) $('places-attribution').src = $('places-attribution').dataset.src;
    $('places-attribution').hidden = !placesConfigured;
    renderCommutes(results[4], results[3], results[5]);
    const timed = data.events.filter(event => !event.all_day);
    $('departure-event-list').replaceChildren(...timed.map(event => {
      const row = element('article', undefined, 'departure-event'); row.dataset.eventId = event.id;
      const details = element('div');
      const route = element('p', '', 'trip-route');
      const updateRoute = roundTrip => {
        route.textContent = roundTrip
          ? 'Home → Appointment → Home · Return starts when the appointment ends.'
          : 'Home → Appointment · One way';
      };
      const roundTrip = tripPreferences.get(event.id) || false;
      updateRoute(roundTrip);
      details.append(element('h3', event.title), element('p', event.location || 'No location added'), route);
      const readiness = element(
        'span',
        event.departure_ready ? 'Ready to open in Google Maps' : 'Add a location in your calendar',
        'readiness ' + (event.departure_ready ? 'ready' : 'missing')
      );
      const controls = element('div', undefined, 'trip-controls');
      const choice = element('label', undefined, 'trip-choice');
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox'; checkbox.checked = roundTrip;
      const mapLinks = element('div', undefined, 'map-links');
      let returnLink;
      if (settings.configured && event.departure_ready) {
        const outboundLink = mapsDirectionLink('Open outbound route', settings.home_address, event.location);
        returnLink = mapsDirectionLink('Open return route', event.location, settings.home_address);
        returnLink.hidden = !roundTrip;
        mapLinks.append(outboundLink, returnLink);
      }
      checkbox.addEventListener('change', async () => {
        checkbox.disabled = true;
        try {
          await api('/departure/trips/' + event.id, {
            method: 'PUT', body: JSON.stringify({round_trip: checkbox.checked})
          });
          updateRoute(checkbox.checked);
          if (returnLink) returnLink.hidden = !checkbox.checked;
        } catch (error) {
          checkbox.checked = !checkbox.checked;
          $('departure-summary').textContent = 'Could not save the round-trip choice. Please try again.';
        } finally { checkbox.disabled = false; }
      });
      choice.append(checkbox, element('span', 'Return home after appointment'));
      const check = results[7].find(r => r.event_id === event.id);
      if (check) {
        controls.append(element('p', `Traffic alerts: ${check.disabled ? 'Off' : check.status}. Starts 2 hours before; reminder at least 45 minutes before.`, 'optional'));
        if (check.duration_seconds) controls.append(element('p', `Last estimate: ${Math.ceil(check.duration_seconds / 60)} minutes · ${new Date(check.last_checked).toLocaleString()}`));
        const label = element('label', 'Traffic reminder recipients');
        const select = document.createElement('select'); select.multiple = true;
        for (const member of results[3]) { const option = new Option(member.name, String(member.id)); option.selected = (check.recipient_ids || []).includes(member.id); select.add(option); }
        label.append(select); controls.append(label);
        const enabled = document.createElement('input'); enabled.type = 'checkbox'; enabled.checked = !check.disabled;
        const toggle = element('label', 'Get traffic alerts for this event '); toggle.append(enabled); controls.append(toggle);
        select.disabled = !enabled.checked; enabled.addEventListener('change', () => { select.disabled = !enabled.checked; });
        const save = element('button', 'Save traffic alert settings', 'secondary'); save.type = 'button';
        save.addEventListener('click', async () => {
          save.disabled = true;
          try { await api(`/departure/traffic/${event.id}/recipients`, {method:'PUT',body:JSON.stringify({member_ids:[...select.selectedOptions].map(o=>Number(o.value)),disabled:!enabled.checked})}); $('departure-summary').textContent='Traffic alert settings saved.'; }
          catch(error) { $('departure-summary').textContent=error.message; } finally { save.disabled=false; }
        }); controls.append(save);
        if (!check.recipient_ids) controls.append(element('p', 'Currently uses your calendar-alert recipient. Select names to change it.', 'optional'));
      }
      controls.append(readiness, choice, mapLinks);
      row.append(element('div', formatEventTime(event, data.timezone), 'calendar-time'), details, controls);
      return row;
    }));
    if (!timed.length) $('departure-event-list').append(element('p', 'No timed events in the next 14 days.', 'empty'));
    const setup = settings.configured ? 'Home is set.' : 'Add your home address.';
    const noun = timed.length === 1 ? 'event is' : 'events are';
    $('departure-summary').textContent = setup + ' ' + data.departure_ready_count + ' of ' + timed.length + ' timed ' + noun + ' ready for travel planning.';
  } catch (error) {
    $('departure-summary').textContent = 'Could not check departure readiness. Please refresh.';
  } finally { $('refresh-departures').disabled = false; }
}

$('refresh-departures').addEventListener('click', loadDeparturePlanner);
$('departure-form').addEventListener('submit', async event => {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  $('departure-save-message').className = 'form-message';
  $('departure-save-message').textContent = 'Saving…';
  try {
    await api('/departure/settings', {
      method: 'PUT',
      body: JSON.stringify({
        home_address: $('home-address').value.trim(),
        arrival_buffer_minutes: Number($('arrival-buffer').value),
        parking_walk_minutes: Number($('parking-buffer').value)
      })
    });
    $('departure-save-message').textContent = 'Saved privately in Family Agent.';
    await loadDeparturePlanner();
  } catch (error) {
    $('departure-save-message').textContent = error.message;
    $('departure-save-message').className = 'form-message error';
  } finally { button.disabled = false; }
});

$('commute-kind').addEventListener('change', () => {
  const school = $('commute-kind').value === 'school';
  $('school-calendar-choice').hidden = !school;
  if (school) $('commute-school-calendar').checked = true;
  else $('commute-school-calendar').checked = false;
});
$('cancel-commute-edit').addEventListener('click', resetCommuteForm);
$('commute-form').addEventListener('submit', async event => {
  event.preventDefault();
  const button = event.submitter;
  if (button.id === 'cancel-commute-edit') return;
  const weekdays = Array.from(document.querySelectorAll('[name="commute-weekday"]:checked')).map(input => Number(input.value));
  if (!weekdays.length) {
    $('commute-save-message').textContent = 'Choose at least one day.';
    return;
  }
  button.disabled = true;
  const id = $('commute-id').value;
  try {
    await api(id ? `/commutes/${id}` : '/commutes', {
      method: id ? 'PUT' : 'POST',
      body: JSON.stringify({
        member_id: Number($('commute-member').value), label: $('commute-label').value.trim(),
        kind: $('commute-kind').value, destination_address: $('commute-address').value.trim(),
        send_time: $('commute-time').value, weekdays,
        use_school_calendar: $('commute-kind').value === 'school' && $('commute-school-calendar').checked,
        enabled: $('commute-enabled').checked
      })
    });
    resetCommuteForm();
    await loadDeparturePlanner();
    $('commute-save-message').textContent = 'Commute traffic schedule saved securely.';
  } catch (error) {
    $('commute-save-message').textContent = error.message;
  } finally { button.disabled = false; }
});

function localDateTimeValue(date) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}

function renderMorningBriefing(config) {
  $('morning-briefing-enabled').checked = config.enabled;
  $('morning-briefing-time').value = config.send_time;
  $('morning-briefing-recipients').replaceChildren(...config.recipients.map(recipient => {
    const card = element('section', undefined, 'briefing-recipient');
    card.dataset.memberId = recipient.member_id;
    card.dataset.calendarKeys = JSON.stringify(recipient.calendar_keys);
    card.append(element('h4', recipient.member_name));
    const options = element('div', undefined, 'briefing-options');
    const enabledLabel = element('label');
    const enabled = document.createElement('input');
    enabled.type = 'checkbox'; enabled.className = 'briefing-member-enabled'; enabled.checked = recipient.enabled;
    enabledLabel.append(enabled, element('span', 'Send a briefing'));
    const familyLabel = element('label');
    const family = document.createElement('input');
    family.type = 'checkbox'; family.className = 'briefing-family-view'; family.checked = recipient.include_family_schedule;
    familyLabel.append(family, element('span', 'Include all family activities'));
    options.append(enabledLabel, familyLabel); card.append(options);
    card.append(element('p', recipient.contact_ready ? 'messaging contact is ready.' : 'Add this person’s messaging contact before briefings can be delivered.', 'contact-note'));
    const assignedNames = config.calendars
      .filter(calendar => recipient.calendar_keys.includes(calendar.key))
      .map(calendar => calendar.name);
    card.append(element(
      'p',
      assignedNames.length ? `Assigned calendars: ${assignedNames.join(', ')}` : 'No individual calendars assigned yet. Use the Calendar tab.',
      'contact-note'
    ));
    return card;
  }));
  $('morning-briefing-status').textContent = config.configured
    ? (config.enabled ? `Briefings are scheduled for ${config.send_time} each morning.` : 'Morning briefings are paused.')
    : 'Choose recipients and calendars, then save to activate morning briefings.';
}

function renderBriefingLedger(ledger) {
  const statusLabels = {
    scheduled: 'Scheduled', waiting_for_mac: 'Waiting for Mac/service',
    waiting_for_calendar: 'Waiting for calendar', waiting_for_weather: 'Waiting for weather',
    pending: 'Queued', queued: 'Sending', retrying: 'Retrying', sent: 'Sent',
    failed: 'Failed', uncertain: 'Delivery uncertain', missed: 'Missed', disabled: 'Disabled', no_contact: 'No contact',
    not_recorded: 'Not recorded'
  };
  $('briefing-ledger-days').replaceChildren(...ledger.days.map(day => {
    const card = element('section', undefined, 'ledger-day');
    const heading = element('div', undefined, 'ledger-day-header');
    const date = new Date(`${day.date}T12:00:00`).toLocaleDateString(regional.locale, {
      weekday: 'short', month: 'short', day: 'numeric'
    });
    heading.append(element('span', date), element('strong', day.summary.replaceAll('_', ' ')));
    const deliveries = element('div', undefined, 'ledger-deliveries');
    for (const delivery of day.deliveries) {
      const text = `${delivery.member_name}: ${statusLabels[delivery.status] || delivery.status}`;
      deliveries.append(element('span', text, `ledger-delivery ${delivery.status}`));
    }
    if (!day.deliveries.length) deliveries.append(element('span', 'No recipients configured', 'optional'));
    card.append(heading, deliveries);
    return card;
  }));
}

function renderSelfHealing(report) {
  const panel = $('self-healing-status');
  panel.replaceChildren();
  if (report.status === 'never_run') {
    panel.append(element('p', 'The first weekly validation will run Sunday after 7:00 AM.', 'optional'));
    return;
  }
  const labels = {healthy: 'All checks passed', repaired: 'Safe repairs completed', attention_needed: 'Needs attention'};
  const card = element('article', undefined, `self-healing-card ${report.status}`);
  const heading = element('div', undefined, 'self-healing-header');
  const checked = new Date(report.checked_at).toLocaleString(regional.locale, {
    weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'
  });
  heading.append(element('strong', labels[report.status] || report.status), element('span', checked));
  card.append(heading);
  const addList = (title, values, className) => {
    if (!values?.length) return;
    card.append(element('h4', title));
    const list = element('ul', undefined, className);
    for (const value of values) list.append(element('li', value));
    card.append(list);
  };
  addList('Checked', report.checks, 'self-healing-checks');
  addList('Fixed automatically', report.actions, 'self-healing-actions');
  addList('Review needed', report.issues, 'self-healing-issues');
  panel.append(card);
}

function weekendDateRange(data) {
  const options = {month: 'short', day: 'numeric'};
  const start = new Date(`${data.weekend_start}T12:00:00`);
  const end = new Date(`${data.weekend_end}T12:00:00`);
  return `${start.toLocaleDateString(regional.locale, options)}–${end.toLocaleDateString(regional.locale, options)}`;
}

function renderWeekendSchedule(data) {
  const preview = $('weekend-schedule-preview');
  const count = data.recipients.length;
  $('weekend-schedule-summary').textContent = `${weekendDateRange(data)} · ${data.event_count} ${data.event_count === 1 ? 'event' : 'events'} · ${count} ${count === 1 ? 'recipient' : 'recipients'}`;
  $('weekend-schedule-messages').replaceChildren(...data.recipients.map(recipient => {
    const card = element('article', undefined, 'weekend-message');
    card.append(element('h4', recipient.member_name), element('p', recipient.message));
    return card;
  }));
  const send = $('send-weekend-schedule');
  send.disabled = !data.calendar_refresh_complete || !count;
  preview.hidden = false;
  const notes = [];
  if (!data.calendar_connected) notes.push('Connect at least one calendar before sending a weekend schedule.');
  else if (!data.calendar_refresh_complete) notes.push('A calendar could not refresh. Resolve it and preview again before sending.');
  if (data.unavailable_members.length) notes.push(`No enabled messaging contact: ${data.unavailable_members.join(', ')}.`);
  if (!count) notes.push('Add and enable at least one family messaging contact.');
  $('weekend-schedule-status').textContent = notes.join(' ');
}

$('preview-weekend-schedule').addEventListener('click', async event => {
  const button = event.currentTarget;
  button.disabled = true;
  $('weekend-schedule-status').textContent = 'Refreshing calendars and preparing next weekend…';
  $('weekend-schedule-preview').hidden = true;
  try {
    renderWeekendSchedule(await api('/alerts/weekend/preview'));
  } catch (error) {
    $('weekend-schedule-status').textContent = error.message;
  } finally { button.disabled = false; }
});

$('send-weekend-schedule').addEventListener('click', async event => {
  const button = event.currentTarget;
  button.disabled = true;
  $('weekend-schedule-status').textContent = 'Queueing the reviewed schedule for delivery…';
  try {
    const result = await api('/alerts/weekend/send', {method: 'POST'});
    await loadAlerts();
    $('weekend-schedule-status').textContent = `${result.created} personalized weekend ${result.created === 1 ? 'message is' : 'messages are'} queued for immediate delivery.`;
  } catch (error) {
    $('weekend-schedule-status').textContent = error.message;
    button.disabled = false;
  }
});

async function loadAlerts() {
  $('refresh-alerts').disabled = true;
  $('alert-message-status').textContent = 'Loading alerts…';
  try {
    const results = await Promise.all([
      all('/family-members'), api('/alerts/contacts'), api('/alerts'), api('/alerts/calendar-rule'),
      api('/alerts/morning'), api('/alerts/morning/ledger'), api('/health/self-healing')
    ]);
    const members = results[0], contacts = results[1], alerts = results[2], rule = results[3], morning = results[4], ledger = results[5], healing = results[6];
    state.members = members; state.contacts = contacts;
    renderMembers();
    renderMorningBriefing(morning);
    renderBriefingLedger(ledger);
    renderSelfHealing(healing);
    const contactByMember = new Map(contacts.map(contact => [contact.member_id, contact]));
    for (const id of ['alert-member', 'calendar-alert-member']) {
      const select = $(id), selected = select.value;
      select.replaceChildren(new Option('Choose a family member', ''));
      for (const member of members) select.add(new Option(member.name, String(member.id)));
      const preferred = id === 'calendar-alert-member' && rule.member_id ? String(rule.member_id) : selected;
      select.value = Array.from(select.options).some(option => option.value === preferred) ? preferred : '';
    }
    if (!rule.configured && contacts.length) $('calendar-alert-member').value = String(contacts[0].member_id);
    $('calendar-alert-enabled').checked = rule.enabled;
    $('leave-reminder-minutes').value = rule.leave_reminder_minutes;
    $('appointment-reminder-minutes').value = rule.appointment_reminder_minutes;
    $('calendar-alert-rule-status').textContent = rule.configured
      ? (rule.enabled ? 'Automatic calendar reminders are active.' : 'Automatic calendar reminders are paused.')
      : 'Choose a recipient and save to activate automatic reminders.';

    $('alert-contacts').replaceChildren(...members.map(member => {
      const saved = contactByMember.get(member.id);
      const card = element('section', undefined, 'alert-contact');
      card.dataset.memberId = member.id;
      card.append(element('h3', member.name));
      const handleLabel = element('label', 'Messaging phone or Apple Account email');
      const input = document.createElement('input');
      input.className = 'alert-contact-handle'; input.type = 'text'; input.autocomplete = 'off';
      input.placeholder = 'Phone number or email';
      input.value = saved?.imessage_handle || '';
      handleLabel.append(input);
      const enabledLabel = element('label', undefined, 'contact-enabled');
      const enabled = document.createElement('input');
      enabled.className = 'alert-contact-enabled'; enabled.type = 'checkbox'; enabled.checked = saved?.enabled ?? true;
      enabledLabel.append(enabled, element('span', 'Enable alerts and FA requests'));
      card.append(handleLabel, enabledLabel);
      return card;
    }));
    if (!members.length) $('alert-contacts').append(element('p', 'Add a family member before configuring alerts.', 'empty'));

    $('alert-list').replaceChildren(...alerts.map(alert => {
      const row = element('article', undefined, 'alert-row');
      const when = new Intl.DateTimeFormat(regional.locale, {
        dateStyle: 'medium', timeStyle: 'short'
      }).format(new Date(alert.scheduled_for));
      const details = element('div');
      details.append(element('strong', alert.member_name), element('p', alert.message));
      row.append(details, element('span', when), element('span', alert.status, 'alert-status ' + alert.status));
      return row;
    }));
    if (!alerts.length) $('alert-list').append(element('p', 'No alerts scheduled yet.', 'empty'));
    if (!$('alert-time').value) $('alert-time').value = localDateTimeValue(new Date(Date.now() + 5 * 60000));
    $('alert-message-status').textContent = '';
  } catch (error) {
    $('alert-message-status').textContent = 'Could not load alerts. Please refresh.';
  } finally { $('refresh-alerts').disabled = false; }
}

$('alert-contacts-form').addEventListener('submit', async event => {
  event.preventDefault();
  const button = event.submitter; button.disabled = true;
  const contacts = Array.from(document.querySelectorAll('.alert-contact')).map(card => {
    const handle = card.querySelector('.alert-contact-handle').value.trim();
    return {
      member_id: Number(card.dataset.memberId),
      imessage_handle: handle || null,
      enabled: card.querySelector('.alert-contact-enabled').checked
    };
  });
  try {
    await api('/alerts/contacts', {method: 'PUT', body: JSON.stringify({contacts})});
    await loadAlerts();
    $('alert-message-status').textContent = 'All messaging contacts are saved securely.';
  } catch (error) {
    $('alert-message-status').textContent = error.message;
  } finally { button.disabled = false; }
});

$('calendar-alert-rule-form').addEventListener('submit', async event => {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  try {
    await api('/alerts/calendar-rule', {
      method: 'PUT',
      body: JSON.stringify({
        member_id: Number($('calendar-alert-member').value),
        enabled: $('calendar-alert-enabled').checked,
        appointment_reminder_minutes: Number($('appointment-reminder-minutes').value),
        leave_reminder_minutes: Number($('leave-reminder-minutes').value)
      })
    });
    await loadAlerts();
    $('calendar-alert-rule-status').textContent = $('calendar-alert-enabled').checked
      ? 'Automatic calendar reminders are active.'
      : 'Automatic calendar reminders are paused.';
  } catch (error) {
    $('calendar-alert-rule-status').textContent = error.message;
  } finally { button.disabled = false; }
});

$('morning-briefing-form').addEventListener('submit', async event => {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  $('morning-briefing-status').textContent = 'Saving morning briefings…';
  const recipients = Array.from(document.querySelectorAll('.briefing-recipient')).map(card => ({
    member_id: Number(card.dataset.memberId),
    enabled: card.querySelector('.briefing-member-enabled').checked,
    include_family_schedule: card.querySelector('.briefing-family-view').checked,
    calendar_keys: JSON.parse(card.dataset.calendarKeys || '[]')
  }));
  try {
    const saved = await api('/alerts/morning', {
      method: 'PUT',
      body: JSON.stringify({
        enabled: $('morning-briefing-enabled').checked,
        send_time: $('morning-briefing-time').value,
        recipients
      })
    });
    renderMorningBriefing(saved);
  } catch (error) {
    $('morning-briefing-status').textContent = error.message;
  } finally { button.disabled = false; }
});

$('refresh-alerts').addEventListener('click', loadAlerts);
$('alert-form').addEventListener('submit', async event => {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  try {
    await api('/alerts', {
      method: 'POST',
      body: JSON.stringify({
        member_id: Number($('alert-member').value),
        message: $('alert-message').value.trim(),
        scheduled_for: new Date($('alert-time').value).toISOString()
      })
    });
    $('alert-form').reset();
    $('alert-time').value = localDateTimeValue(new Date(Date.now() + 5 * 60000));
    await loadAlerts();
    $('alert-message-status').textContent = 'Alert scheduled. It will remain queued until the iMessage bridge runs.';
  } catch (error) {
    $('alert-message-status').textContent = error.message;
  } finally { button.disabled = false; }
});

function renderConflicts(data) {
  const panel = $('calendar-conflicts');
  const conflicts = data.conflicts || [];
  panel.replaceChildren(); panel.hidden = false;
  panel.classList.toggle('has-overlaps', conflicts.length > 0);
  const heading = element('h3', conflicts.length ? `${conflicts.length} possible ${conflicts.length === 1 ? 'conflict' : 'conflicts'}` : data.conflict_check_complete ? 'No timed overlaps found' : 'Overlap check is incomplete');
  heading.id = 'conflicts-heading'; panel.append(heading);
  panel.append(element('p', 'Checks timed events marked busy across the selected calendars. All-day events are excluded. Events for different people may overlap without a clash.'));
  if (!data.conflict_check_complete) panel.append(element('p', 'Only successfully loaded calendars were checked. Connect or refresh the remaining sources for a complete check.'));
  const byId = new Map(data.events.map(event => [event.id, event]));
  const list = element('ul');
  for (const conflict of conflicts) {
    const item = element('li');
    conflict.event_ids.forEach((id, index) => {
      const event = byId.get(id); if (!event) return;
      if (index) item.append(document.createTextNode(' overlaps with '));
      const link = element('a', `${event.title} (${sourceLabels[event.source]} · ${event.calendar})`);
      link.href = `#calendar-event-${id}`; item.append(link);
    });
    item.append(element('p', `${formatEventTime({...conflict, all_day: false}, data.timezone)} · ${conflict.minutes} minutes together`));
    list.append(item);
  }
  if (conflicts.length) panel.append(list);
}

$('sign-out').addEventListener('click', async () => { await api('/auth/logout', {method:'POST'}); location.replace('/login'); });
