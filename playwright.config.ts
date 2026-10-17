import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/browser",
  testMatch: "*.spec.ts",
  workers: 1,
  timeout: 60000,
  outputDir: ".pytest_tmp/browser-results",
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:18765", browserName: "chromium", headless: true },
  webServer: {
    command: "pixi run python scripts/serve_composition_demo.py",
    url: "http://127.0.0.1:18765/health",
    reuseExistingServer: false,
    timeout: 90000
  }
});
