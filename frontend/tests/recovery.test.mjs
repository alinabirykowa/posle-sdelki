import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

// Use the installed compiler, so these tests also work with Node 20.19 rather
// than relying on newer Node releases' native TypeScript support.
async function loadSource(name) {
  const source = await readFile(new URL(`../src/${name}.ts`, import.meta.url), 'utf8');
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  });
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
}
const { createPendingActions, recoveredMessage, reconcilePendingActions } = await loadSource('recovery');
const { api, errorMessage } = await loadSource('api');

function storage() {
  const data = new Map();
  return {
    getItem: (key) => data.get(key) ?? null,
    setItem: (key, value) => data.set(key, value),
    removeItem: (key) => data.delete(key),
  };
}
let counter = 0;
const uuid = () => `request-${++counter}`;

test('a lost response and reload preserve the request identity', () => {
  const saved = storage();
  const firstPage = createPendingActions(() => saved, uuid);
  const sent = firstPage.get('proposal:one', 'prioritize_swap');
  assert.deepEqual(firstPage.get('proposal:one', 'prioritize_swap'), sent);
  const reloadedPage = createPendingActions(() => saved, uuid);
  assert.deepEqual(reloadedPage.get('proposal:one', 'prioritize_swap'), sent);
  reloadedPage.clear('proposal:one', sent.id);
  assert.notEqual(reloadedPage.get('proposal:one', 'prioritize_swap').id, sent.id);
});

test('different actions and conversations never inherit another request ID', () => {
  const actions = createPendingActions(storage, uuid);
  const initial = actions.get('proposal:one', 'paid_change');
  const changed = actions.get('proposal:one', 'prioritize_swap');
  const second = actions.get('proposal:two', 'prioritize_swap');
  assert.notEqual(changed.id, initial.id);
  assert.notEqual(second.id, changed.id);
  actions.clear('proposal:one', initial.id); // A late response must not erase a newer action.
  assert.equal(actions.read('proposal:one').id, changed.id);
});

test('blocked storage keeps retries stable while the page remains open', () => {
  const actions = createPendingActions(() => { throw new Error('blocked'); }, uuid);
  const pending = actions.get('retry:one', 'retry');
  assert.equal(actions.get('retry:one', 'retry').id, pending.id);
  actions.clear('retry:one', pending.id);
  assert.notEqual(actions.get('retry:one', 'retry').id, pending.id);
});

test('failed storage removal does not revive an acknowledged action in memory', () => {
  const saved = storage();
  const actions = createPendingActions(() => saved, uuid);
  const pending = actions.get('retry:one', 'retry');
  saved.removeItem = () => { throw new Error('blocked'); };
  actions.clear('retry:one', pending.id);
  assert.equal(actions.read('retry:one'), null);
});

test('legacy message identifiers recover and corrupt values are ignored', () => {
  const saved = storage();
  saved.setItem('legacy', JSON.stringify({ text: 'Что важно?', id: 'old-id' }));
  saved.setItem('broken', '{');
  const actions = createPendingActions(() => saved, uuid);
  assert.deepEqual(actions.read('legacy'), { payload: 'Что важно?', id: 'old-id' });
  assert.equal(actions.read('broken'), null);
});

test('recovery needs an exact server acknowledgement, not identical words', () => {
  const pending = { id: 'one', payload: 'Спасибо' };
  const message = { role: 'user', text: 'Спасибо', client_message_id: 'one' };
  assert.equal(recoveredMessage([message], pending), true);
  assert.equal(recoveredMessage([{ ...message, client_message_id: 'other' }], pending), false);
  assert.equal(recoveredMessage([{ ...message, role: 'assistant' }], pending), false);
  assert.equal(recoveredMessage([{ ...message, text: 'Иной текст' }], pending), false);
  assert.equal(recoveredMessage([message], null), false);
});

test('API sends action IDs and exposes no raw network error to the user', async (t) => {
  const sent = [];
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    sent.push({ url, body: JSON.parse(init.body) });
    return new Response(JSON.stringify({ id: 'one' }), { status: 200 });
  });
  await api.propose('one', 'prioritize_swap', 'offer-id');
  await api.retry('one', 'retry-id');
  assert.deepEqual(sent.map((r) => r.body), [
    { option_id: 'prioritize_swap', client_action_id: 'offer-id' },
    { client_action_id: 'retry-id' },
  ]);
  assert.match(errorMessage(new TypeError('Failed to fetch')), /Не удалось связаться/);
  assert.doesNotMatch(errorMessage(new TypeError('Failed to fetch')), /Failed to fetch/);
  assert.match(errorMessage(new DOMException('timeout', 'TimeoutError')), /Сервер не успел/);
});

test('a later successful message acknowledges an earlier proposal with a lost reply', () => {
  const saved = storage();
  const actions = createPendingActions(() => saved, uuid);
  const lostProposal = actions.get('pending-proposal:one', 'prioritize_swap');
  const question = actions.get('pending-message:one', 'Что важно?');
  const freshMessages = [
    { role: 'user', kind: 'proposal', text: 'Предложение', client_action_id: lostProposal.id },
    { role: 'user', text: 'Что важно?', client_message_id: question.id },
  ];
  assert.deepEqual(reconcilePendingActions('one', freshMessages, actions), { message: 'Что важно?', proposal: true });
  assert.notEqual(actions.get('pending-proposal:one', 'prioritize_swap').id, lostProposal.id);
  assert.equal(actions.read('pending-message:one'), null);
  assert.equal(saved.getItem('pending-message:one'), null);
});

test('a successful HTTP response with no JSON is not treated as saved state', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response('gateway text', { status: 200 }));
  await assert.rejects(api.session('one'), /неполный ответ/);
});

const { readPendingCatalogStart, getPendingCatalogStart, clearPendingCatalogStart } = await loadSource('recovery');

test('catalogue recovery keeps the original case, revision and mode after reload and publication changes', () => {
  const saved = storage();
  const actions = createPendingActions(() => saved, uuid);
  const sent = getPendingCatalogStart('account-a', 'case-one', 3, 'live', actions);
  const reloaded = createPendingActions(() => saved, uuid);
  assert.deepEqual(readPendingCatalogStart('account-a', reloaded), sent);
  assert.deepEqual(getPendingCatalogStart('account-a', 'case-one', 8, 'demo', reloaded), sent);
  assert.deepEqual(getPendingCatalogStart('account-a', 'case-two', 1, 'demo', reloaded), sent);
  clearPendingCatalogStart(sent, reloaded);
  const deliberateNewStart = getPendingCatalogStart('account-a', 'case-one', 8, 'demo', reloaded);
  assert.notEqual(deliberateNewStart.id, sent.id);
  assert.equal(deliberateNewStart.revision, 8);
  assert.equal(deliberateNewStart.mode, 'demo');
});

test('catalogue recovery cannot cross accounts and late acknowledgement cannot remove a newer start', () => {
  const saved = storage();
  const actions = createPendingActions(() => saved, uuid);
  const first = getPendingCatalogStart('account-a', 'case-one', 3, 'live', actions);
  assert.equal(readPendingCatalogStart('account-b', actions), null);
  const anotherAccount = getPendingCatalogStart('account-b', 'case-one', 3, 'live', actions);
  assert.notEqual(anotherAccount.id, first.id);
  clearPendingCatalogStart(first, actions);
  const second = getPendingCatalogStart('account-a', 'case-one', 4, 'demo', actions);
  clearPendingCatalogStart(first, actions);
  assert.deepEqual(readPendingCatalogStart('account-a', actions), second);
  assert.deepEqual(readPendingCatalogStart('account-b', actions), anotherAccount);
});

test('invalid persisted catalogue attempts are not sent to the server', () => {
  for (const payload of ['{', JSON.stringify({ case_id: '', revision: 1, mode: 'demo' }), JSON.stringify({ case_id: 'one', revision: -1, mode: 'live' }), JSON.stringify({ case_id: 'one', revision: 2, mode: 'unknown' })]) {
    const saved = storage();
    saved.setItem('pending-catalog-start:account-a', JSON.stringify({ id: 'bad', payload }));
    assert.equal(readPendingCatalogStart('account-a', createPendingActions(() => saved, uuid)), null);
  }
});

const { readPendingTrainingStart, getPendingTrainingStart, clearPendingTrainingStart } = await loadSource('recovery');
const trainingConfig = {
  industry: 'it', topic: 'scope', difficulty: 'hard', tone: 'collaborative',
  client_role: 'project_lead', goal: 'deadline', duration_minutes: 10,
  format: 'text', response_seconds: 0,
};

test('training lost-response recovery preserves the original payload until an explicit new start', () => {
  const saved = storage();
  const firstPage = createPendingActions(() => saved, uuid);
  const pending = getPendingTrainingStart('account-a', trainingConfig, 'live', firstPage);
  assert.equal(pending.key, 'pending-training-start:account-a');
  const reloaded = createPendingActions(() => saved, uuid);
  assert.deepEqual(readPendingTrainingStart('account-a', reloaded), pending);
  const differentForm = { ...trainingConfig, topic: 'discount', goal: 'cashflow', duration_minutes: 5 };
  assert.deepEqual(getPendingTrainingStart('account-a', differentForm, 'demo', reloaded), pending);
  // The old conversation may already have been completed through the cabinet.
  // Explicitly starting again retires its recovery ID, even for identical input.
  clearPendingTrainingStart(pending, reloaded);
  assert.equal(readPendingTrainingStart('account-a', reloaded), null);
  const newStart = getPendingTrainingStart('account-a', trainingConfig, 'live', reloaded);
  assert.notEqual(newStart.id, pending.id);
  assert.deepEqual(newStart.configuration, trainingConfig);
  assert.equal(newStart.mode, 'live');
});

test('training starts are isolated by identity and never adopt the legacy global request', () => {
  const saved = storage();
  const actions = createPendingActions(() => saved, uuid);
  actions.get('pending-training-start', JSON.stringify({ configuration: trainingConfig, mode: 'live' }));
  assert.equal(readPendingTrainingStart('account-a', actions), null);
  assert.equal(readPendingTrainingStart('guest', actions), null);
  const first = getPendingTrainingStart('account-a', trainingConfig, 'demo', actions);
  const other = getPendingTrainingStart('account-b', trainingConfig, 'demo', actions);
  const guest = getPendingTrainingStart('guest', trainingConfig, 'demo', actions);
  assert.equal(new Set([first.id, other.id, guest.id]).size, 3);
  const reloaded = createPendingActions(() => saved, uuid);
  assert.deepEqual(readPendingTrainingStart('account-a', reloaded), first);
  assert.deepEqual(readPendingTrainingStart('account-b', reloaded), other);
  assert.deepEqual(readPendingTrainingStart('guest', reloaded), guest);
});

test('late acknowledgement of an old training start cannot clear a newer intent', () => {
  const saved = storage();
  const actions = createPendingActions(() => saved, uuid);
  const old = getPendingTrainingStart('account-a', trainingConfig, 'demo', actions);
  clearPendingTrainingStart(old, actions);
  const fresh = getPendingTrainingStart('account-a', trainingConfig, 'demo', actions);
  clearPendingTrainingStart(old, actions);
  assert.deepEqual(readPendingTrainingStart('account-a', actions), fresh);
  assert.deepEqual(readPendingTrainingStart('account-a', createPendingActions(() => saved, uuid)), fresh);
});

test('all nine training fields, numeric literals and compatible goals are validated on recovery', () => {
  const invalid = [
    '{', 'null', '[]', 'true', JSON.stringify({ configuration: null, mode: 'demo' }),
    JSON.stringify({ configuration: trainingConfig, mode: 'unknown' }),
    JSON.stringify({ configuration: trainingConfig, mode: 'demo', unrelated: true }),
    JSON.stringify({ configuration: { ...trainingConfig, unrelated: true }, mode: 'demo' }),
    JSON.stringify({ configuration: { ...trainingConfig, topic: 'scope', goal: 'budget' }, mode: 'demo' }),
    JSON.stringify({ configuration: { ...trainingConfig, topic: 'discount', goal: 'deadline' }, mode: 'demo' }),
    ...Object.keys(trainingConfig).flatMap((field) => {
      const missing = { ...trainingConfig };
      delete missing[field];
      return [
        JSON.stringify({ configuration: missing, mode: 'demo' }),
        JSON.stringify({ configuration: { ...trainingConfig, [field]: 'invalid' }, mode: 'demo' }),
        JSON.stringify({ configuration: { ...trainingConfig, [field]: null }, mode: 'demo' }),
      ];
    }),
    ...[true, '10', 0, 7, 10.5].map((value) => JSON.stringify({ configuration: { ...trainingConfig, duration_minutes: value }, mode: 'demo' })),
    ...[false, '0', '45', 60, 45.5].map((value) => JSON.stringify({ configuration: { ...trainingConfig, response_seconds: value }, mode: 'demo' })),
  ];
  for (const payload of invalid) {
    const saved = storage();
    saved.setItem('pending-training-start:account-a', JSON.stringify({ id: 'invalid-saved', payload }));
    const actions = createPendingActions(() => saved, uuid);
    assert.equal(readPendingTrainingStart('account-a', actions), null, payload);
    const fresh = getPendingTrainingStart('account-a', trainingConfig, 'demo', actions);
    assert.notEqual(fresh.id, 'invalid-saved');
    assert.deepEqual(fresh.configuration, trainingConfig);
    assert.deepEqual(readPendingTrainingStart('account-a', actions), fresh);
  }
});

test('supported training alternatives recover without losing enum settings', () => {
  for (const config of [
    trainingConfig,
    { ...trainingConfig, industry: 'digital', difficulty: 'standard', tone: 'reserved', client_role: 'business_owner', goal: 'full_scope', duration_minutes: 15, format: 'voice', response_seconds: 45 },
    { ...trainingConfig, industry: 'consulting', topic: 'discount', tone: 'pressing', client_role: 'procurement', goal: 'budget', duration_minutes: 5 },
    { ...trainingConfig, topic: 'discount', goal: 'cashflow' },
  ]) {
    const saved = storage();
    const sent = getPendingTrainingStart('account-a', config, 'live', createPendingActions(() => saved, uuid));
    assert.deepEqual(readPendingTrainingStart('account-a', createPendingActions(() => saved, uuid)), sent);
  }
});

test('invalid saved training IDs cannot survive as a new request identity', () => {
  for (const id of ['', '   ', 'x'.repeat(101), null, 27]) {
    const saved = storage();
    saved.setItem('pending-training-start:account-a', JSON.stringify({ id, payload: JSON.stringify({ configuration: trainingConfig, mode: 'demo' }) }));
    const actions = createPendingActions(() => saved, uuid);
    assert.equal(readPendingTrainingStart('account-a', actions), null);
    const newRequest = getPendingTrainingStart('account-a', trainingConfig, 'demo', actions);
    assert.notEqual(newRequest.id, id);
    assert.deepEqual(readPendingTrainingStart('account-a', actions), newRequest);
  }
});

test('training recovery does not retain mutable form references and tolerates blocked storage', () => {
  const actions = createPendingActions(() => { throw new Error('storage blocked'); }, uuid);
  const form = { ...trainingConfig };
  const sent = getPendingTrainingStart('account-a', form, 'demo', actions);
  form.tone = 'pressing';
  assert.deepEqual(readPendingTrainingStart('account-a', actions), sent);
  assert.equal(sent.configuration.tone, trainingConfig.tone);
  clearPendingTrainingStart(sent, actions);
  assert.notEqual(getPendingTrainingStart('account-a', form, 'demo', actions).id, sent.id);
});
