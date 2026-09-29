import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(
  new URL("../src/training.ts", import.meta.url),
  "utf8",
);
const { outputText } = ts.transpileModule(source, {
  compilerOptions: {
    target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.ESNext,
  },
});
const { sameTrainingContext, trainingSummary } = await import(
  `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`
);

async function loadSource(name) {
  const source = await readFile(
    new URL(`../src/${name}.ts`, import.meta.url),
    "utf8",
  );
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.ESNext,
    },
  });
  return import(
    `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`
  );
}
const { api } = await loadSource("api");
const { createPendingActions } = await loadSource("recovery");

const legacy = {
  scenario: { id: "scope" },
  priority: "deadline",
  difficulty: "standard",
  mode: "demo",
  mentor_state: { mode: "guided", tracked_from_start: true, used: false, counts: { hint: 0, example: 0, review: 0 } },
};
const config = {
  industry: "it",
  topic: "scope",
  difficulty: "standard",
  tone: "reserved",
  client_role: "project_lead",
  goal: "deadline",
  duration_minutes: 10,
  format: "text",
  response_seconds: 0,
};
const configured = {
  ...legacy,
  training_config: config,
  context_key: "saved-context-one",
};

test("preset attempts with complete assistance tracking compare using original settings", () => {
  assert.equal(sameTrainingContext(legacy, { ...legacy, id: "retry" }), true);
  assert.equal(
    sameTrainingContext(legacy, {
      ...legacy,
      training_config: null,
      context_key: null,
    }),
    true,
  );
  for (const changed of [
    { scenario: { id: "discount" } },
    { priority: "full_scope" },
    { difficulty: "hard" },
    { mode: "live" },
  ]) {
    assert.equal(sameTrainingContext(legacy, { ...legacy, ...changed }), false);
  }
});

test("assistance history must be known and equivalent before comparison", () => {
  const old = { ...configured, mentor_state: undefined };
  assert.equal(sameTrainingContext(old, old), false);
  assert.equal(sameTrainingContext(old, configured), false);
  const withHelp = { ...configured, mentor_state: { ...configured.mentor_state, used: true, counts: { hint: 1, example: 0, review: 0 } } };
  assert.equal(sameTrainingContext(configured, withHelp), false);
  assert.equal(sameTrainingContext(withHelp, { ...withHelp, id: "another" }), true);
  assert.equal(sameTrainingContext(withHelp, { ...withHelp, mentor_state: { ...withHelp.mentor_state, mode: "independent" } }), false);
  assert.equal(sameTrainingContext(configured, { ...configured, scenario: { ...configured.scenario, practice_model: "conversation" } }), false);
  assert.equal(sameTrainingContext(configured, { ...configured, mentor_state: { ...configured.mentor_state, counts: { hint: 1, example: 0, review: 0 } } }), false);
});

test("extra turns and planned turn budgets must match before comparison", () => {
  assert.equal(sameTrainingContext(configured, { ...configured, extra_turns: 0 }), true);
  assert.equal(sameTrainingContext(configured, { ...configured, extra_turns: 4 }), false);
  assert.equal(sameTrainingContext({ ...configured, extra_turns: 4 }, { ...configured, extra_turns: 4 }), true);
  assert.equal(sameTrainingContext({ ...configured, max_turns: 8 }, { ...configured, max_turns: 12 }), false);
});

test("generated replies and analyzer-only sessions are not treated as the same practice", () => {
  const oldLive = { ...configured, mode: "live" };
  const generated = { ...oldLive, reply_mode: "generated" };
  assert.equal(sameTrainingContext(oldLive, { ...oldLive, reply_mode: "rules" }), true);
  assert.equal(sameTrainingContext(oldLive, generated), false);
  assert.equal(sameTrainingContext(generated, { ...generated, id: "retry" }), true);
});

test("configured retries with the same saved context remain comparable", () => {
  assert.equal(
    sameTrainingContext(configured, { ...configured, id: "retry", turns: 2 }),
    true,
  );
  assert.equal(
    sameTrainingContext(configured, { ...configured, mode: "live" }),
    false,
  );
});

test("different generated business contexts cannot be compared despite matching base settings", () => {
  for (const changed of [
    { industry: "consulting" },
    { tone: "pressing" },
    { client_role: "business_owner" },
    { duration_minutes: 5 },
    { format: "voice", response_seconds: 45 },
  ]) {
    const other = {
      ...configured,
      training_config: { ...config, ...changed },
      context_key: `different-context-${JSON.stringify(changed)}`,
    };
    assert.equal(sameTrainingContext(configured, other), false);
    assert.equal(sameTrainingContext(other, configured), false);
  }
});

test("a configured session never compares with an old preset or a missing context key", () => {
  assert.equal(sameTrainingContext(configured, legacy), false);
  assert.equal(sameTrainingContext(legacy, configured), false);
  const missingKey = { ...configured, context_key: undefined };
  assert.equal(sameTrainingContext(configured, missingKey), false);
  assert.equal(sameTrainingContext(missingKey, missingKey), false);
  assert.equal(sameTrainingContext(missingKey, legacy), false);
  assert.equal(
    sameTrainingContext({ ...configured, training_config: undefined }, legacy),
    false,
  );
});

test("summaries describe the saved format and duration, without inventing metadata for old sessions", () => {
  assert.equal(trainingSummary(legacy), "");
  assert.equal(
    trainingSummary(configured),
    "IT-услуги · Переписка · 10 мин · Сдержанный клиент",
  );
  assert.equal(
    trainingSummary({
      ...configured,
      training_config: {
        ...config,
        industry: "consulting",
        tone: "pressing",
        format: "voice",
        duration_minutes: 5,
      },
    }),
    "Консалтинг · Голос · 5 мин · Клиент давит",
  );
});

test("a lost configured-start response can be retried after reload with the same complete API payload", async (t) => {
  const stored = new Map();
  const storage = {
    getItem: (key) => stored.get(key) ?? null,
    setItem: (key, value) => stored.set(key, value),
    removeItem: (key) => stored.delete(key),
  };
  let nextId = 0;
  const newId = () => `training-action-${++nextId}`;
  const pendingKey = "pending-training-start";
  const payload = JSON.stringify({ configuration: config, mode: "live" });
  const sent = [];
  t.mock.method(globalThis, "fetch", async (url, init) => {
    const body = JSON.parse(init.body);
    sent.push({ url, body, method: init.method });
    // The server has already accepted the action, but its response is lost.
    if (sent.length === 1) throw new TypeError("Failed to fetch");
    return new Response(JSON.stringify({ id: "same-saved-session" }));
  });

  const initialPage = createPendingActions(() => storage, newId);
  const first = initialPage.get(pendingKey, payload);
  await assert.rejects(api.trainingStart(config, "live", first.id));

  const reloadedPage = createPendingActions(() => storage, newId);
  const recovered = reloadedPage.get(pendingKey, payload);
  const session = await api.trainingStart(config, "live", recovered.id);
  assert.equal(session.id, "same-saved-session");
  assert.deepEqual(sent[0], {
    url: "/api/training/start",
    method: "POST",
    body: { configuration: config, mode: "live", client_action_id: first.id },
  });
  assert.deepEqual(sent[1], sent[0]);

  const differentConfig = reloadedPage.get(
    pendingKey,
    JSON.stringify({
      configuration: { ...config, duration_minutes: 5 },
      mode: "live",
    }),
  );
  const differentMode = reloadedPage.get(
    pendingKey,
    JSON.stringify({ configuration: config, mode: "demo" }),
  );
  assert.notEqual(differentConfig.id, recovered.id);
  assert.notEqual(differentMode.id, differentConfig.id);
  assert.notEqual(differentMode.id, recovered.id);
  // A delayed acknowledgement from the old request must not clear the new one.
  reloadedPage.clear(pendingKey, recovered.id);
  assert.equal(reloadedPage.read(pendingKey).id, differentMode.id);
});

test("a route practice start sends its saved focus stage", async (t) => {
  let body;
  t.mock.method(globalThis, "fetch", async (_url, init) => {
    body = JSON.parse(init.body);
    return new Response(JSON.stringify({ id: "route-session" }));
  });
  await api.trainingStart(config, "demo", "route-start", "explain");
  assert.deepEqual(body, {
    configuration: config,
    mode: "demo",
    client_action_id: "route-start",
    route_stage: "explain",
  });
});
