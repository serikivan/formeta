import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  define: {
    "process.env.NODE_ENV": JSON.stringify("production"),
  },
  build: {
    emptyOutDir: false,
    outDir: "frontend/assets",
    cssCodeSplit: false,
    lib: {
      entry: "frontend/react/visualization-entry.jsx",
      name: "ProjectionVisualizationBundle",
      formats: ["iife"],
      fileName: () => "visualization-react.js",
    },
    rollupOptions: {
      output: {
        assetFileNames: (assetInfo) => {
          if (assetInfo.name?.endsWith(".css")) return "visualization-react.css";
          return "visualization-[name][extname]";
        },
      },
    },
  },
});
