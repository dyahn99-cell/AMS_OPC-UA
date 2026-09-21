/* Offline protocol checks only: worker source runs in a deny-by-default VM.
 * No real worker process, HTTP server, socket, device, installation or config read.
 */
'use strict';
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '..', 'worker.js'), 'utf8');
const script = new vm.Script(source, { filename: 'worker.js' });
const protocol = 'ams-worker-owner-v1';
const nodeBytes = Buffer.from('{"remotes":{"AMS01":{"read":{"flow":"ns=4;s=flow"}}}}\r\n');
const endpoint = 'opc.tcp://mock.invalid:4840';
const password = 'offline-secret-é';
const token = 'a'.repeat(64);
const instance = 'b'.repeat(32);

// Independently assemble the documented byte framing, not worker implementation.
function fingerprint(bytes, target = endpoint, secret = password) {
  const targetBytes = Buffer.from(target, 'utf8');
  const nodeLength = Buffer.alloc(8), endpointLength = Buffer.alloc(8);
  nodeLength.writeBigUInt64BE(BigInt(bytes.length));
  endpointLength.writeBigUInt64BE(BigInt(targetBytes.length));
  return crypto.createHash('sha256').update(Buffer.concat([
    Buffer.from(protocol + '\0'), nodeLength, bytes, endpointLength, targetBytes,
    crypto.createHash('sha256').update(secret, 'utf8').digest(),
  ])).digest('hex');
}
const expectedFingerprint = fingerprint(nodeBytes);
const authHeaders = {
  host: '127.0.0.1:7100',
  'x-ams-worker-token': token,
  'x-ams-worker-instance': instance,
  'x-ams-worker-fingerprint': expectedFingerprint,
};
let checks = 0;
function check(condition, message) { assert(condition, message); checks++; }

function fixture(options = {}) {
  const state = {
    httpCreates: 0, listenCalls: 0, opcuaLoads: 0, connects: 0, reads: [], writes: [],
    timers: new Map(), intervals: new Map(), exits: [], logs: [], fsReads: [], closes: 0,
  };
  let timerId = 0, now = 1000, listener, listenCallback;
  const serverEvents = {}, processEvents = {};
  const env = {
    WORKER_PORT: '7100', AMS_CONFIG_PATH: '/mock/config.json', AMS_NODES_PATH: '/mock/nodes.json',
    OPCUA_ENDPOINT: endpoint, AMS_PASSWORD: password,
    AMS_WORKER_OWNER_TOKEN: token, AMS_WORKER_INSTANCE_ID: instance,
    AMS_WORKER_FINGERPRINT: expectedFingerprint, ...options.env,
  };
  for (const key of options.missing || []) delete env[key];
  const good = { isGood: () => true, isNotGood: () => false, toString: () => 'Good' };
  const session = {
    read: async nodes => {
      state.reads.push(nodes);
      if (state.readError) throw new Error(state.readError);
      return nodes.map(() => ({
        statusCode: state.badStatus ? { isGood: () => false, toString: () => 'BadNoData' } : good,
        sourceTimestamp: state.sourceTimestamp === undefined ? '2026-09-01T00:00:00.000Z' : state.sourceTimestamp,
        value: { value: 4000 },
      }));
    },
    write: async value => { state.writes.push(value); return good; },
    close: async () => { state.closes++; },
  };
  const opcua = {
    OPCUAClient: { create: () => ({
      on: () => {}, connect: async () => { state.connects++; },
      createSession: async () => session, disconnect: async () => {},
    }) },
    MessageSecurityMode: { None: 'None' }, SecurityPolicy: { None: 'None' },
    DataType: { Boolean: 'Boolean', Byte: 'Byte' }, AttributeIds: { Value: 13 },
    Variant: class Variant { constructor(value) { Object.assign(this, value); } },
    VariantArrayType: { Array: 'Array' },
  };
  const server = {
    on: (event, callback) => { serverEvents[event] = callback; return server; },
    listen: (port, host, callback) => {
      assert.equal(port, 7100); assert.equal(host, '127.0.0.1');
      state.listenCalls++; listenCallback = callback; return server;
    },
    close: () => { state.closes++; },
  };
  const fakeFs = { readFileSync: (name, encoding) => {
    state.fsReads.push(name);
    let bytes;
    if (name === '/mock/config.json') bytes = Buffer.from(options.config ?? '{}');
    else if (name === '/mock/nodes.json') bytes = Buffer.from(options.nodes ?? nodeBytes);
    else throw new Error('unapproved mock file');
    return encoding ? bytes.toString(encoding) : bytes;
  } };
  const context = vm.createContext({
    require: name => {
      if (name === 'http') return { createServer: callback => { state.httpCreates++; listener = callback; return server; } };
      if (name === 'fs') return fakeFs;
      if (name === 'path') return path;
      if (name === 'crypto') return crypto;
      if (name === 'node-opcua') { state.opcuaLoads++; return opcua; }
      throw new Error('forbidden require: ' + name);
    },
    __dirname: '/mock', Buffer,
    process: { env, pid: 4242, on: (event, callback) => { processEvents[event] = callback; }, exit: code => { state.exits.push(code); } },
    console: { log: (...args) => state.logs.push(args.join(' ')) },
    Date: class FakeDate extends Date { constructor(...args) { super(...(args.length ? args : [now])); } static now() { return now; } },
    setTimeout: (callback, delay) => { const id = ++timerId; state.timers.set(id, { callback, delay }); return id; },
    clearTimeout: id => state.timers.delete(id),
    setInterval: (callback, delay) => { const id = ++timerId; state.intervals.set(id, { callback, delay }); return id; },
    clearInterval: id => state.intervals.delete(id),
  });
  let startupError;
  try { script.runInContext(context); } catch (error) { startupError = error; }
  return {
    state, context, startupError,
    listen: () => { assert(listenCallback); listenCallback(); },
    serverError: code => serverEvents.error({ code }),
    async installSession() {
      // Synthetic session only; do not exercise connect or boot timers here.
      context.mockSession = session;
      vm.runInContext('loadOpcua(); session = mockSession; connected = true;', context);
    },
    async runTimer(delay) {
      const entry = [...state.timers].find(([, timer]) => timer.delay === delay);
      assert(entry, 'expected fake timer ' + delay);
      state.timers.delete(entry[0]); now += delay;
      await entry[1].callback();
      for (let i = 0; i < 12; i++) await Promise.resolve();
    },
    async request(method, url, headers = authHeaders, body = {}) {
      const events = {}, responseHeaders = {};
      const req = {
        method, url, headers,
        rawHeaders: options.rawHeaders || Object.entries(headers).flatMap(([name, value]) => [name, value]),
        on: (event, callback) => { events[event] = callback; },
        destroy: () => {},
      };
      let text;
      const res = { statusCode: 200, setHeader: (name, value) => { responseHeaders[name] = value; }, end: value => { text = value; } };
      const pending = listener(req, res);
      if (events.data) {
        events.data(typeof body === 'string' ? body : JSON.stringify(body));
        events.end();
      }
      await pending;
      for (let i = 0; i < 12; i++) await Promise.resolve();
      return { status: res.statusCode, headers: responseHeaders, body: JSON.parse(text), text, bodyRead: !!events.data };
    },
  };
}

async function main() {
  for (const field of ['AMS_WORKER_OWNER_TOKEN', 'AMS_WORKER_INSTANCE_ID', 'AMS_WORKER_FINGERPRINT']) {
    for (const settings of [{ missing: [field] }, { env: { [field]: 'bad' } }]) {
      const f = fixture(settings);
      check(!!f.startupError, 'missing/malformed ownership must abort');
      check(f.state.httpCreates === 0 && f.state.opcuaLoads === 0 && f.state.fsReads.length === 0, 'abort before inputs/listen/connect');
    }
  }
  for (const settings of [
    { nodes: Buffer.concat([nodeBytes, Buffer.from(' ')]) },
    { env: { OPCUA_ENDPOINT: endpoint + '/other' } },
    { env: { AMS_PASSWORD: password + 'changed' } },
    { nodes: 'not-json' }, { config: '{bad' }, { env: { WORKER_PORT: '7100garbage' } },
  ]) {
    const f = fixture(settings);
    check(!!f.startupError && f.state.httpCreates === 0 && f.state.opcuaLoads === 0, 'effective input mismatch must abort before server');
  }
  const configFallback = fixture({
    missing: ['OPCUA_ENDPOINT', 'AMS_PASSWORD'],
    config: JSON.stringify({ opcua_endpoint: endpoint, ams_password: password }),
  });
  check(!configFallback.startupError, 'fingerprint uses resolved config inputs');
  const emptyPassword = fixture({ env: { AMS_PASSWORD: '', AMS_WORKER_FINGERPRINT: fingerprint(nodeBytes, endpoint, '') } });
  check(!emptyPassword.startupError, 'explicit empty password is not silently replaced');

  const bindFailure = fixture();
  check(!bindFailure.startupError && bindFailure.state.listenCalls === 1, 'server listen requested');
  check(bindFailure.state.opcuaLoads === 0 && bindFailure.state.timers.size === 0, 'no boot connect/timer until listen succeeds');
  bindFailure.serverError('EADDRINUSE');
  await bindFailure.runTimer(10);
  check(bindFailure.state.opcuaLoads === 0 && bindFailure.state.connects === 0 && bindFailure.state.exits[0] === 1, 'occupied port exits without device connection');
  bindFailure.listen();
  check(bindFailure.state.timers.size === 0, 'listen callback after error cannot arm connection');

  const f = fixture();
  check(!f.startupError, 'valid owned worker initializes in VM');
  f.listen();
  const timerCount = f.state.timers.size;
  for (let i = 0; i < 3; i++) {
    const status = await f.request('GET', '/status');
    check(status.status === 200 && !status.bodyRead, 'owned status accepted without body');
    check(status.body.worker_protocol === protocol && status.body.worker_instance_id === instance
      && status.body.worker_fingerprint === expectedFingerprint && status.body.pid === 4242, 'owned status identifies loaded worker');
    check(!status.text.includes(token) && !status.text.includes(password), 'status never exposes ownership token or password');
  }
  check(f.state.opcuaLoads === 0 && f.state.connects === 0 && f.state.timers.size === timerCount, 'status remains passive');
  const attacks = [
    {}, { ...authHeaders, 'x-ams-worker-token': 'c'.repeat(64) },
    { ...authHeaders, 'x-ams-worker-instance': 'c'.repeat(32) },
    { ...authHeaders, 'x-ams-worker-fingerprint': 'c'.repeat(64) },
    { ...authHeaders, 'x-ams-worker-token': undefined },
    { ...authHeaders, 'x-ams-worker-instance': undefined },
    { ...authHeaders, 'x-ams-worker-fingerprint': undefined },
    { ...authHeaders, 'x-ams-worker-token': [token] },
    { ...authHeaders, host: 'evil.invalid:7100' },
    { ...authHeaders, host: 'localhost:7100' },
    { ...authHeaders, host: '127.0.0.1:8000' },
    { ...authHeaders, origin: 'http://127.0.0.1:8000' },
    { ...authHeaders, origin: 'null' }, { ...authHeaders, origin: '' },
  ];
  for (const [method, route] of [
    ['GET', '/status'], ['GET', '/data'], ['GET', '/data/AMS01'], ['POST', '/read'],
    ['POST', '/write'], ['POST', '/write-byte'], ['POST', '/write-bytes'], ['POST', '/shutdown'],
    ['OPTIONS', '/write'], ['GET', '/unknown'],
  ]) for (const headers of attacks) {
    const result = await f.request(method, route, headers, 'not-json');
    check(result.status === 403 && !result.bodyRead, 'guard precedes body/routes: ' + route);
    check(result.headers['Connection'] === 'close' && !('Access-Control-Allow-Origin' in result.headers), 'no keepalive or CORS for rejection');
  }
  check(f.state.opcuaLoads === 0 && f.state.reads.length === 0 && f.state.writes.length === 0
    && f.state.timers.size === timerCount && f.state.exits.length === 0, 'rejected requests have no device/shutdown side effects');
  for (const header of ['Host', 'X-AMS-Worker-Token', 'X-AMS-Worker-Instance', 'X-AMS-Worker-Fingerprint']) {
    const duplicate = fixture({ rawHeaders: [...Object.entries(authHeaders).flat(), header, authHeaders[header.toLowerCase()]] });
    duplicate.listen();
    const result = await duplicate.request('POST', '/write', authHeaders, 'bad-json');
    check(result.status === 403 && !result.bodyRead && duplicate.state.opcuaLoads === 0, 'duplicate identity header rejected');
  }
  for (const route of ['/status?token=' + token, 'http://127.0.0.1:7100/data', '//evil.invalid/data']) {
    const response = await f.request('GET', route);
    // A double-slash is harmless unknown origin-form route, never URL authority.
    check([400, 404].includes(response.status) && f.state.opcuaLoads === 0, 'no absolute URL or query credentials');
  }

  for (const value of ['true', 'false', 1, 0, null, {}, []]) {
    const result = await f.request('POST', '/write', authHeaders, { nodeId: 'ns=4;s=valve', value });
    check(result.status === 400, 'strict Boolean required');
  }
  for (const value of ['0x10', '10garbage', '10', true, null, {}, [], -1, 256, 1.5]) {
    check((await f.request('POST', '/write-byte', authHeaders, { nodeId: 'ns=4;s=byte', value })).status === 400, 'strict numeric byte required');
    check((await f.request('POST', '/write-bytes', authHeaders, { nodeId: 'ns=4;s=bytes', bytes: [value] })).status === 400, 'strict numeric array byte required');
  }
  for (const bytes of [[], Array(17).fill(0)]) {
    check((await f.request('POST', '/write-bytes', authHeaders, { nodeId: 'ns=4;s=bytes', bytes })).status === 400, 'array bounds');
  }
  for (const body of ['null', '[]', '{bad', '{"nodeId":4,"value":true}']) {
    check((await f.request('POST', '/write', authHeaders, body)).status === 400, 'malformed body/nodeId rejected');
  }
  check(f.state.opcuaLoads === 0, 'invalid input cannot connect');
  const diagnostic = await f.request('POST', '/read', authHeaders, { nodeId: 'ns=4;s=flow' });
  check(diagnostic.body.error === 'not_connected' && f.state.opcuaLoads === 0, 'diagnostic read does not initiate a connection');

  await f.installSession();
  for (const [route, body, expectedType, expectedValue] of [
    ['/write', { nodeId: 'ns=4;s=valve', value: false }, 'Boolean', false],
    ['/write-byte', { nodeId: 'ns=4;s=byte', value: 255 }, 'Byte', 255],
    ['/write-bytes', { nodeId: 'ns=4;s=bytes', bytes: [0, 255] }, 'Byte', [0, 255]],
  ]) {
    const response = await f.request('POST', route, authHeaders, body);
    check(response.status === 200 && response.body.ok, 'valid owned write accepted');
    const written = f.state.writes.at(-1).value.value;
    assert.equal(written.dataType, expectedType);
    assert.deepEqual(JSON.parse(JSON.stringify(written.value)), expectedValue); checks++;
  }
  check((await f.request('POST', '/read', authHeaders, { nodeId: 'ns=4;s=flow' })).body.value === 4000, 'owned diagnostic read uses fake session');
  const data = await f.request('GET', '/data');
  check(data.body.remotes.AMS01.values.flow === 4000, 'telemetry payload preserved');
  check((await f.request('GET', '/data/AMS01')).body.values.flow === 4000, 'owned remote data route preserved');
  check(f.state.connects === 0, 'session checks did not initiate device connect');

  // Exercise both cache writers with only a synthetic session and fake clock.
  for (const reader of ['readAllRemotes', 'readAllRemotesSequential']) {
    const telemetry = fixture();
    await telemetry.installSession();
    const poll = async () => {
      await vm.runInContext(reader + '()', telemetry.context);
      return JSON.parse(vm.runInContext('JSON.stringify(readCache.AMS01)', telemetry.context));
    };
    const initial = await poll();
    check(initial.source_timestamps.flow === '2026-09-01T00:00:00.000Z', reader + ' preserves source timestamp');
    check(initial.connected && !initial.stale && typeof initial.sample_id === 'string', reader + ' identifies fresh sample');
    telemetry.state.readError = 'synthetic read failure';
    const failed = await poll();
    check(!failed.connected && failed.stale && failed.last_error === 'synthetic read failure', reader + ' marks retained failure unavailable');
    check(failed.sample_id === initial.sample_id && failed.read_at === initial.read_at
      && failed.connection_generation === initial.connection_generation, reader + ' retains measurement identity on failure');
    check(failed.values.flow === 4000 && failed.source_timestamps.flow === initial.source_timestamps.flow,
      reader + ' retains values and source time without freshening them');
    telemetry.state.readError = null;
    telemetry.state.badStatus = true;
    telemetry.state.sourceTimestamp = null;
    const bad = await poll();
    check(!bad.connected && bad.stale && bad.sample_id === initial.sample_id && bad.read_at === initial.read_at,
      reader + ' all-bad read cannot mint new identity');
    check(bad.node_status.flow === 'BadNoData' && bad.source_timestamps.flow === null,
      reader + ' failure carries current per-node diagnostic/source metadata');
    telemetry.state.badStatus = false;
    telemetry.state.sourceTimestamp = 'not-a-date';
    const recovered = await poll();
    check(recovered.connected && !recovered.stale && recovered.sample_id !== initial.sample_id,
      reader + ' successful new read gets new identity');
    check(recovered.source_timestamps.flow === null, reader + ' malformed source time is not receive time');
    check(telemetry.state.connects === 0 && telemetry.state.writes.length === 0,
      reader + ' cache tests never connect or write');
  }

  const startup = fixture(); startup.listen(); await startup.runTimer(5000);
  check(startup.state.opcuaLoads === 1 && startup.state.connects === 1, 'startup timer connects only after successful fake listen');
  const shutdownResult = await f.request('POST', '/shutdown');
  check(shutdownResult.status === 200 && shutdownResult.body.shutting_down, 'owned shutdown accepted');
  await f.runTimer(10);
  check(f.state.exits[0] === 0 && f.state.closes >= 1 && f.state.timers.size === 0, 'shutdown clears boot/reconnect timers and closes fake resources');
  check(!f.state.logs.join('\n').includes(token), 'token absent from logs');
  console.log(JSON.stringify({ checks_passed: checks, transport: 'VM fake http/fs/process/clock/session only', fingerprint_vector: expectedFingerprint }));
}
main().catch(error => { console.error(error); process.exitCode = 1; });
