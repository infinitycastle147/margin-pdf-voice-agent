import test from 'node:test';
import assert from 'node:assert/strict';
import { createActivityReceiver } from './activity-stream.js';

test('reassembles out-of-order chunks and preserves full Unicode output', () => {
  const event={type:'agent-activity',id:'a',output:'Evidence: café → renewable energy. '.repeat(800)};
  const payload=JSON.stringify(event),parts=[];
  for(let i=0;i<payload.length;i+=12000)parts.push(payload.slice(i,i+12000));
  const results=[],receiver=createActivityReceiver(e=>results.push(e));
  for(let i=parts.length-1;i>=0;i--)receiver.receive({type:'activity-chunk',transfer_id:'transfer',index:i,total:parts.length,data:parts[i]});
  assert.deepEqual(results,[event]);
});
test('keeps running and completed events separate even with the same activity id', () => {
  const results=[],receiver=createActivityReceiver(e=>results.push(e));
  for(const status of ['running','completed'])receiver.receive({type:'activity-chunk',transfer_id:status,index:0,total:1,data:JSON.stringify({id:'same',status})});
  assert.deepEqual(results.map(r=>r.status),['running','completed']);
});
test('rejects malformed chunk counts and never invents a complete event', () => {
  const results=[],errors=[],receiver=createActivityReceiver(e=>results.push(e),e=>errors.push(e));
  receiver.receive({type:'activity-chunk',transfer_id:'invalid',index:0,total:1e9,data:'{}'});
  receiver.receive({type:'activity-chunk',transfer_id:'partial',index:0,total:2,data:'{}'});
  assert.equal(results.length,0);assert.equal(errors.length,1);
});
test('reset removes fragments from a previous voice session', () => {
  const results=[],receiver=createActivityReceiver(e=>results.push(e));
  receiver.receive({type:'activity-chunk',transfer_id:'t',index:0,total:2,data:'{"a":'});
  receiver.reset();
  receiver.receive({type:'activity-chunk',transfer_id:'t',index:1,total:2,data:'1}'});
  assert.equal(results.length,0);
});
