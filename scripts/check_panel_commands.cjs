const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(path.join(__dirname, '../dashboard.html'), 'utf8');
for (const match of source.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)) {
  if (match[1].trim()) new vm.Script(match[1]);
}
const start = source.indexOf('// Serialize panel commands');
const end = source.indexOf('async function setModeCommand(', start);
assert(start > 0 && end > start);
const context = {
  Date, deviceConnected: true,
  document: { querySelectorAll: () => [] },
  setTimeout: fn => { context.timeout = fn; return 1; },
  clearTimeout() {}, toast() {},
};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
const row = offset => ({ timestamp: new Date(Date.now() + offset).toISOString() });
(async () => {
  let release, calls = 0;
  const request = context.runPanelCommand(() => {
    calls++;
    return new Promise(resolve => { release = resolve; });
  });
  await context.runPanelCommand(() => calls++);
  assert.equal(calls, 1, 'Repeated clicks must not send another command');
  assert.equal(context.acceptPanelTelemetry(row(10000)), false);
  release(); await request;
  assert.equal(context.acceptPanelTelemetry(row(-1000)), false);
  assert.equal(context.panelCommandBusy(), true);
  assert.equal(context.acceptPanelTelemetry(row(1000)), true);
  assert.equal(context.panelCommandBusy(), false);
  await context.runPanelCommand(async () => {});
  context.timeout();
  assert.equal(context.panelCommandBusy(), false);
  assert.equal(context.acceptPanelTelemetry(row(-1000)), false);
  context.resetPanelCommand();
  assert.equal(context.acceptPanelTelemetry({}), true);
  let finish;
  const old = context.runPanelCommand(() => new Promise(r => { finish = r; }));
  context.resetPanelCommand(); finish(); await old;
  assert.equal(context.panelCommandBusy(), false, 'Old response must not lock the new selection');
  await assert.rejects(context.runPanelCommand(async () => { throw Error('network'); }));
  context.timeout();
  assert.equal(context.panelCommandBusy(), false);
  console.log('PASS: panel command ordering, stale telemetry, timeout, selection changes, exceptions, JS syntax');
})().catch(error => { console.error(error); process.exitCode = 1; });
