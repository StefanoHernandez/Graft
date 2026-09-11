import assert from "node:assert/strict";
import test from "node:test";

import { citationLabel, resolveConfig } from "../src/config.js";

function script(dataset: Record<string, string>, src = "https://graft.example.test/widget/graft.js") {
  return { src, dataset } as unknown as HTMLScriptElement;
}

test("the backend comes from the script's own origin", () => {
  const config = resolveConfig(script({ graftBot: "wk_abc" }));
  assert.deepEqual(config, {
    backend: "https://graft.example.test",
    botKey: "wk_abc",
    title: "Ask about the docs",
  });
});

test("a path on the script URL does not leak into the backend", () => {
  const config = resolveConfig(
    script({ graftBot: "wk_abc" }, "https://graft.example.test/static/v2/graft.js"),
  );
  assert.equal(config?.backend, "https://graft.example.test");
});

test("an explicit backend wins and loses its trailing slash", () => {
  const config = resolveConfig(script({ graftBot: "wk_abc", graftBackend: "https://api.test/" }));
  assert.equal(config?.backend, "https://api.test");
});

test("a custom title is honoured", () => {
  assert.equal(resolveConfig(script({ graftBot: "k", graftTitle: "Aiuto" }))?.title, "Aiuto");
});

test("without a bot key there is no widget", () => {
  assert.equal(resolveConfig(script({})), null);
  assert.equal(resolveConfig(script({ graftBot: "   " })), null);
});

test("without a script element there is no widget", () => {
  assert.equal(resolveConfig(null), null);
});

test("a source is labelled with what a reader can look up", () => {
  assert.equal(
    citationLabel({ id: "S1", filename: "manual.pdf", page: 2, heading: null, excerpt: "" }),
    "manual.pdf · page 2",
  );
  assert.equal(
    citationLabel({ id: "S2", filename: "guide.md", page: null, heading: "Setup", excerpt: "" }),
    "guide.md · Setup",
  );
  assert.equal(
    citationLabel({ id: "S3", filename: "notes.txt", page: null, heading: null, excerpt: "" }),
    "notes.txt",
  );
});
