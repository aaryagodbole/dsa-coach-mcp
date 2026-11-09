import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

// MCP Apps hosts sandbox the view and load nothing else, so the build is one HTML file,
// written where the Python package serves it from.
export default defineConfig({
  plugins: [react(), viteSingleFile()],
  build: {
    rollupOptions: { input: "dashboard.html" },
    outDir: "../src/dsa_coach_mcp/ui",
    emptyOutDir: false,
  },
});
