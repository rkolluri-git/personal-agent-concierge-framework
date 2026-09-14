import { readFile } from 'node:fs/promises';

export default async function handler(event) {
  if (event.type !== 'message' || event.action !== 'received') return;
  const context = event.context || {};
  if (context.channelId !== 'whatsapp' || !/^\s*FA(?:\s*[:,-]\s*|\s+)\S/i.test(context.content || '')) return;
  try {
    const config = JSON.parse(await readFile(process.env.FAMILY_MESSAGING_CONFIG, 'utf8'));
    if (config.provider !== 'openclaw' || context.accountId !== config.openclaw_account) return;
    // Reject group/conversation identities; do not derive identity from message text.
    if (String(context.conversationId || '').includes('@g.us')) return;
    const sender = context.metadata?.senderE164 || context.from;
    if (!/^\+[1-9][0-9]{7,14}$/.test(sender || '') || !config.opted_in_recipients?.includes(sender)) return;
    if (!context.messageId || context.content.length > 2000 || typeof config.bridge_token !== 'string' || config.bridge_token.length < 32) return;
    const response = await fetch('http://127.0.0.1:8001/webhooks/openclaw', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', Authorization: `Bearer ${config.bridge_token}`},
      body: JSON.stringify({account_id: context.accountId, sender, message_id: context.messageId, text: context.content}),
      signal: AbortSignal.timeout(10000),
    });
    if (!response.ok) throw new Error('Relay rejected');
  } catch {
    console.error('Family Agent relay unavailable. Check local gateway and private configuration; no message details logged.');
  }
}
