import assert from 'node:assert/strict';
import {mkdtemp, writeFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import handler from '../integrations/openclaw/family-agent/handler.js';
const dir = await mkdtemp(join(tmpdir(), 'family-agent-hook-'));
try {
  const config = {provider:'openclaw',openclaw_account:'family',bridge_token:'a'.repeat(40),opted_in_recipients:['+15555550101']};
  process.env.FAMILY_MESSAGING_CONFIG = join(dir, 'config.json');
  await writeFile(process.env.FAMILY_MESSAGING_CONFIG, JSON.stringify(config));
  const calls = [];
  globalThis.fetch = async (...args) => {calls.push(args); return {ok:true};};
  const event = {type:'message',action:'received',context:{channelId:'whatsapp',accountId:'family',from:'+15555550101',content:'FA bring milk',messageId:'id1'}};
  await handler(event);
  assert.equal(calls.length,1);
  assert.equal(JSON.parse(calls[0][1].body).sender, '+15555550101');
  for (const override of [{accountId:'personal'},{from:'+15555550999'},{content:'Personal message'},{messageId:null},{conversationId:'123@g.us'}]) {
    await handler({...event,context:{...event.context,...override}});
  }
  assert.equal(calls.length,1);
  console.log('OpenClaw hook filtering passed (6 scenarios; no messages sent).');
} finally { await rm(dir, {recursive:true, force:true}); }
