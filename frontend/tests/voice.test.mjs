import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/voice.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
});
const { createVoiceCapture, appendTranscript, recognitionError } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);

function fixture() {
  const instances = [];
  const states = [];
  const results = [];
  const errors = [];
  class Recognition {
    constructor() { instances.push(this); }
    start() { this.started = true; }
    stop() { this.stopped = true; }
    abort() { this.aborted = true; }
  }
  const capture = createVoiceCapture(Recognition, {
    status: (state) => states.push(state),
    result: (final, interim) => results.push({ final, interim }),
    error: (message) => errors.push(message),
  });
  return { capture, instances, states, results, errors };
}

const event = (text, final = true) => ({ results: [{ isFinal: final, 0: { transcript: text } }] });

test('microphone is untouched until an explicit start and listening waits for a browser event', () => {
  const f = fixture();
  assert.equal(f.instances.length, 0);
  f.capture.start();
  assert.equal(f.instances.length, 1);
  assert.equal(f.instances[0].lang, 'ru-RU');
  assert.deepEqual(f.states, ['starting']);
  f.instances[0].onstart();
  assert.equal(f.states.at(-1), 'listening');
});

test('abort blocks already queued callbacks, including results and errors after navigation', () => {
  const f = fixture();
  f.capture.start();
  const oldResult = f.instances[0].onresult;
  const oldError = f.instances[0].onerror;
  const oldStart = f.instances[0].onstart;
  f.capture.abort();
  oldResult(event('Поздний текст'));
  oldError({ error: 'network' });
  oldStart();
  assert.equal(f.instances[0].aborted, true);
  assert.equal(f.states.at(-1), 'idle');
  assert.deepEqual(f.results, []);
  assert.deepEqual(f.errors, []);
});

test('a previous run cannot replace a newer transcript', () => {
  const f = fixture();
  f.capture.start();
  const lateResult = f.instances[0].onresult;
  f.capture.start();
  f.instances[1].onresult(event('Актуальный ответ'));
  lateResult(event('Предыдущий ответ'));
  assert.deepEqual(f.results, [{ final: 'Актуальный ответ', interim: '' }]);
});

test('user stop accepts the final result but late events after end are ignored', () => {
  const f = fixture();
  f.capture.start();
  const recognition = f.instances[0];
  const lateResult = recognition.onresult;
  f.capture.stop();
  assert.equal(recognition.stopped, true);
  assert.equal(f.states.at(-1), 'processing');
  recognition.onresult(event('Финальный ответ'));
  recognition.onend();
  lateResult(event('Старый результат'));
  assert.deepEqual(f.results, [{ final: 'Финальный ответ', interim: '' }]);
  assert.equal(f.states.at(-1), 'idle');
});

test('interim speech is separate from the final transcript', () => {
  const f = fixture();
  f.capture.start();
  f.instances[0].onresult({ results: [
    { isFinal: true, 0: { transcript: 'Первый аргумент.' } },
    { isFinal: false, 0: { transcript: 'И ещё один' } },
  ] });
  assert.deepEqual(f.results, [{ final: 'Первый аргумент.', interim: 'И ещё один' }]);
});

test('permission and network errors return to text-safe idle state', () => {
  for (const code of ['not-allowed', 'network', 'audio-capture', 'no-speech']) {
    const f = fixture();
    f.capture.start();
    f.instances[0].onerror({ error: code });
    assert.equal(f.states.at(-1), 'idle');
    assert.equal(f.instances[0].aborted, true);
    assert.equal(f.errors[0], recognitionError(code));
    assert.match(f.errors[0], /письменно|напишите/);
  }
});

test('recognizer start failures never leave an active microphone state', () => {
  const states = [];
  const errors = [];
  class BrokenRecognition {
    start() { throw new Error('unsupported'); }
    abort() { this.aborted = true; }
  }
  const capture = createVoiceCapture(BrokenRecognition, { status: (state) => states.push(state), result: () => {}, error: (message) => errors.push(message) });
  capture.start();
  assert.deepEqual(states, ['starting', 'idle']);
  assert.equal(errors.length, 1);
});

test('adding speech preserves typed text and refuses overflow without silent data loss', () => {
  assert.equal(appendTranscript('Набранный ответ', 'Продиктованная часть'), 'Набранный ответ\nПродиктованная часть');
  assert.equal(appendTranscript('', ' Голосовой ответ '), 'Голосовой ответ');
  assert.equal(appendTranscript('а'.repeat(1999), 'б'), null);
  assert.equal(appendTranscript('а'.repeat(1998), 'б')?.length, 2000);
});
