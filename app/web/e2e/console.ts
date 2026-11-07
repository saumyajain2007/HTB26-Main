import { expect, test as base } from "@playwright/test";

/*
 * Every end-to-end test also watches the browser console: an error logged by the app, a library
 * or WebGL fails the test, as does an uncaught exception. A test that provokes an error on
 * purpose (a 404 the page then explains) lists it in `expectedConsoleErrors`.
 */
export const test = base.extend<{ expectedConsoleErrors: RegExp[]; consoleErrors: string[] }>({
  expectedConsoleErrors: [[], { option: true }],
  consoleErrors: [
    async ({ page, expectedConsoleErrors }, use) => {
      const errors: string[] = [];
      page.on("console", (message) => {
        if (message.type() !== "error") return;
        const text = message.text();
        if (!expectedConsoleErrors.some((expected) => expected.test(text))) errors.push(text);
      });
      page.on("pageerror", (error) => {
        errors.push(`Uncaught: ${error.message}`);
      });
      await use(errors);
      expect(errors, "errors in the browser console").toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };
