/** Reassemble large telemetry messages without changing their original payload. */
export function createActivityReceiver(onEvent, onError = () => {}) {
  const pending = new Map();
  return {
    reset() { pending.clear(); },
    receive(event) {
      if (event?.type !== 'activity-chunk') { onEvent(event); return; }
      const now = Date.now();
      for (const [key, item] of pending) {
        if (now - item.created > 60000) {
          pending.delete(key);
          onError('An activity update was incomplete. The saved graph is still available in the atlas.');
        }
      }
      if (!Number.isInteger(event.total) || event.total < 1 || event.total > 2048 ||
          !Number.isInteger(event.index) || event.index < 0 || event.index >= event.total ||
          typeof event.data !== 'string' || event.data.length > 12000 || typeof event.transfer_id !== 'string') {
        onError('Received an invalid activity update.'); return;
      }
      let item = pending.get(event.transfer_id);
      if (!item) {
        if (pending.size >= 16) {
          pending.delete(pending.keys().next().value);
          onError('Some activity updates were incomplete. Refresh the atlas for the saved graph.');
        }
        item = {created: now, total:event.total, parts:new Map()};
        pending.set(event.transfer_id,item);
      }
      if (item.total !== event.total) { pending.delete(event.transfer_id); return; }
      item.parts.set(event.index,event.data);
      if (item.parts.size === item.total) {
        pending.delete(event.transfer_id);
        try { onEvent(JSON.parse(Array.from({length:item.total}, (_, i) => item.parts.get(i)).join(''))); }
        catch { onError('Could not read an activity update. Refresh the atlas for saved knowledge.'); }
      }
    },
  };
}
