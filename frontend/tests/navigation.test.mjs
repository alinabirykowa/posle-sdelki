import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/navigation.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } });
const { progressRoute, sessionDestination } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

test("completion and history open the same saved report in the personal cabinet", () => {
  const session = { id: "conversation-123", status: "completed" };
  const route = sessionDestination(session);
  assert.equal(route, "/progress/conversation-123");
  assert.deepEqual(progressRoute(route), { active: true, reviewId: session.id });
});

test("active conversations remain in the room and cannot be mistaken for reports", () => {
  const route = sessionDestination({ id: "current", status: "active" });
  assert.equal(route, "/session/current");
  assert.deepEqual(progressRoute(route), { active: false });
});

test("cabinet overview and malformed review routes are distinct", () => {
  assert.deepEqual(progressRoute("/progress"), { active: true });
  for (const route of ["/progress-other", "/progress/", "/progress/a/b", "/progress/%invalid", "/progress/a?x=1"])
    assert.deepEqual(progressRoute(route), { active: false });
});
